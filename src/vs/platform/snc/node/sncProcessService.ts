import { spawn, ChildProcess } from 'node:child_process';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Disposable } from '../../../base/common/lifecycle.js';
import { Promises } from '../../../base/node/pfs.js';
import { IProcessOptions, IProcessResult, ISNCProcessService, IVisualizationItem, SNCCommand, SNCStreamMessage, SNCTimingData, ILoopReport, UiEvent } from '../common/snc.js';
import { Emitter } from '../../../base/common/event.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

/**
 * A pool worker process. Each worker starts in --pool-worker mode, loads
 * visualizers, and reaches checkpoint 1. It can optionally be advanced to
 * checkpoint 2 by sending an init_imports message. Each worker handles
 * exactly one run then exits.
 */
interface PoolWorker {
	child: ChildProcess;
	buffer: string;
	checkpoint: 1 | 2;
	ready: boolean;
	workingDirectory: string;
	/** For checkpoint 2 workers: the code whose imports are pre-loaded */
	code?: string;
}

/**
 * State for an active run
 */
interface RunState {
	runId: string;
	buffer: string;
	stderr: string;
	timeoutId?: ReturnType<typeof setTimeout>;
	ended: boolean;
	tSpawn: number;
	tStdinEnd?: number;
	tStdoutFirst?: number;
	tFirstItem?: number;
	tEnd?: number;
}

/**
 * Checkpoint 1 workers are the fallback for runs a warmed worker can't cover.
 * Sized to absorb a burst: a run only ends up here once checkpoint 2 is empty,
 * and a burst of runs (each killing the one before it) can empty it, so this
 * pool is what stands between a burst and a run waiting on a cold spawn.
 */
const CP1_POOL_SIZE = 5;
const CP2_POOL_SIZE = 10;

/**
 * The leading imports of a program, as a key for matching it to a warmed worker.
 *
 * A checkpoint 2 worker has executed exactly these statements into its globals,
 * so two programs sharing a key can share a worker — which is what lets a warmed
 * worker survive an ordinary keystroke, since editing the body leaves the key
 * alone. Mirrors `_leading_import_stmts` in python_runner.py: contiguous
 * `import`/`from` statements from the top of the file, plus a module docstring
 * if there is one. Comments and blank lines among the imports are skipped —
 * nothing they change is executed.
 *
 * This is a line scanner, not a Python parser, so it can disagree with the
 * runner on exotic input. That only ever costs a warmed worker: the worker
 * re-checks with a real AST and executes the imports itself when they don't
 * match, so a wrong answer here makes a run slow, never wrong.
 */
export function importPrefixOf(code: string): string {
	const lines = code.split('\n');
	const prefix: string[] = [];
	let i = 0;
	let seenStatement = false;

	while (i < lines.length) {
		const trimmed = lines[i].trim();

		// Not statements: they can sit among the imports without changing what runs.
		if (trimmed === '' || trimmed.startsWith('#')) { i++; continue; }

		// Only the very first statement can be the module docstring, and the
		// runner executes it in the import half — so it belongs to the key.
		if (!seenStatement && (trimmed.startsWith('"') || trimmed.startsWith('\''))) {
			const end = endOfStringLiteral(lines, i);
			if (end === -1) { break; }
			for (let j = i; j <= end; j++) { prefix.push(lines[j].trimEnd()); }
			i = end + 1;
			seenStatement = true;
			continue;
		}

		if (!/^(import|from)\s/.test(trimmed)) { break; }

		// An import can span lines, via parentheses or a trailing backslash. It
		// can't contain a string literal, so a `#` is always the start of a
		// comment and a paren is always real punctuation.
		const parts: string[] = [];
		let depth = 0;
		while (i < lines.length) {
			const text = lines[i].split('#')[0].trimEnd();
			for (const ch of text) {
				if (ch === '(') { depth++; } else if (ch === ')') { depth--; }
			}
			const continued = depth > 0 || text.endsWith('\\');
			parts.push(text.endsWith('\\') ? text.slice(0, -1) : text);
			i++;
			if (!continued) { break; }
		}
		// Reformatting an import — a comment on the end, a reindented
		// continuation line — doesn't change what it binds.
		prefix.push(parts.join(' ').replace(/\s+/g, ' ').trim());
		seenStatement = true;
	}

	return prefix.join('\n');
}

/**
 * Index of the line where a string literal starting at `start` ends, or -1 if
 * it is never closed.
 */
function endOfStringLiteral(lines: string[], start: number): number {
	const text = lines[start].trim();
	const triple = ['"""', '\'\'\''].find(q => text.startsWith(q));
	if (!triple) {
		return start; // a single-line 'str' or "str"
	}
	// A triple-quoted string may also close on the line that opens it.
	if (text.length >= 6 && text.slice(3).includes(triple)) { return start; }
	for (let j = start + 1; j < lines.length; j++) {
		if (lines[j].includes(triple)) { return j; }
	}
	return -1;
}

/**
 * Directory the Python runner caches network reads in, beside the file being
 * edited. Must match `CACHE_DIR_NAME` in `url_cache.py`.
 */
const URL_CACHE_DIR_NAME = '.snc_url_cache';

export class SNCProcessService extends Disposable implements ISNCProcessService {

	private checkpoint1Pool: PoolWorker[] = [];
	private checkpoint2Pool: PoolWorker[] = [];

	/** The code checkpoint 2 workers are warmed with (the newest we've seen) */
	private checkpoint2Code: string = '';

	/**
	 * The leading imports of `checkpoint2Code`. This, not the whole file, is what
	 * a warmed worker has actually executed, so it is what has to match for one
	 * to be reusable — a body edit leaves the pool intact.
	 */
	private checkpoint2ImportPrefix: string = '';

	/** The working directory for the current pool */
	private poolWorkingDirectory: string = '';

	/** The currently executing worker (killed on the next run) */
	private activeWorker: PoolWorker | null = null;

	/**
	 * Python executable used to spawn workers. Defaults to `python3`; the
	 * renderer resolves the user's preferred interpreter via the Python
	 * extension's `python.interpreterPath` command and updates this via
	 * `setPythonExecutable`.
	 */
	private pythonExecutable: string = 'python3';

	/** Active runs */
	private readonly runs = new Map<string, RunState>();

	/**
	 * Callbacks waiting for any pool worker to become ready.
	 * Resolved by processWorkerBuffer when a checkpoint_ready message arrives.
	 * Rejected by handleSpawnFailure when the python executable can't be launched.
	 */
	private readonly workerWaiters: Array<{
		resolve: (worker: PoolWorker) => void;
		reject: (err: Error) => void;
	}> = [];

	/**
	 * Set when the python executable fails to launch (e.g. ENOENT). While set,
	 * we stop refilling pools and fail new runs fast with a user-visible
	 * error. Cleared by `setPythonExecutable` when the user changes
	 * configuration so we'll retry with the new value.
	 */
	private pythonSpawnError: string | null = null;

	/**
	 * Network read caches emptied during this app session, by directory. This
	 * service is created once per app session, so the presence of a key means
	 * the cache has already been dealt with since the last reload.
	 */
	private readonly clearedUrlCaches = new Map<string, Promise<void>>();

	private _disposed = false;

	constructor() {
		super();
	}

	private readonly _onStream = this._register(new Emitter<SNCStreamMessage>());
	public readonly onStream = this._onStream.event;

	private get runnerPath(): string {
		return path.join(__dirname, 'python_runner.py');
	}

	// -------------------------------------------------------------------
	// Pool management
	// -------------------------------------------------------------------

	/**
	 * Spawn a single pool worker process at checkpoint 1.
	 */
	private spawnWorker(workingDirectory: string): PoolWorker | null {
		try {
			// PYTHONHASHSEED pins string hashing, which sets the iteration order
			// of sets. Every rerun is a fresh process, so without it a
			// `set(words)` reshuffles on each keystroke — the same instability
			// python_runner's reseed() fixes for random numbers, but it can only
			// be set at interpreter start, not from inside the runner.
			const child = spawn(this.pythonExecutable, [this.runnerPath, '--pool-worker', workingDirectory], {
				env: { ...process.env, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8', PYTHONHASHSEED: '1234567' }
			});

			const worker: PoolWorker = {
				child,
				buffer: '',
				checkpoint: 1,
				ready: false,
				workingDirectory,
			};

			child.stdout?.on('data', (data: Buffer) => {
				worker.buffer += data.toString();
				this.processWorkerBuffer(worker);
			});

			child.stderr?.on('data', (_data: Buffer) => {
				// Silently ignore stderr from pool workers
			});

			child.on('error', (err: Error) => {
				this.removeWorkerFromPool(worker);
				this.handleSpawnFailure(err);
			});

			child.on('close', () => {
				this.removeWorkerFromPool(worker);
			});

			return worker;
		} catch (err) {
			this.handleSpawnFailure(err instanceof Error ? err : new Error(String(err)));
			return null;
		}
	}

	/**
	 * Called when a worker process fails to launch (e.g. python executable
	 * doesn't exist). Marks the executable as broken so we stop filling pools,
	 * tears down anything in flight, and notifies all active runs and
	 * waiters so the user sees a real error instead of a hang.
	 */
	private handleSpawnFailure(err: Error): void {
		if (this.pythonSpawnError) {
			// Already in failed state — additional spawn errors from sibling
			// workers in the same broken pool are expected. Don't re-notify.
			return;
		}

		const code = (err as NodeJS.ErrnoException).code;
		const message = code === 'ENOENT'
			? `Clickacode: failed to launch Python ('${this.pythonExecutable}'). Configure your interpreter via the Python extension or 'python.defaultInterpreterPath'.`
			: `Clickacode: failed to launch Python ('${this.pythonExecutable}'): ${err.message}`;

		this.pythonSpawnError = message;
		this.drainAllPools();

		while (this.workerWaiters.length > 0) {
			try { this.workerWaiters.shift()!.reject(new Error(message)); } catch { /* ignore */ }
		}

		for (const [runId, state] of this.runs) {
			if (state.timeoutId) {
				clearTimeout(state.timeoutId);
			}
			this._onStream.fire({ runId, type: 'error', error: message });
		}
		this.runs.clear();
		this.activeWorker = null;
	}

	/**
	 * Ensure the pools are filled to their target sizes.
	 *
	 * `includeCheckpoint2` is false while a run is being dispatched: spawning ten
	 * workers there would undo the deferral in `invalidateCheckpoint2Pool`. They
	 * are spawned when the run ends instead.
	 */
	private ensurePoolFilled(workingDirectory: string, includeCheckpoint2: boolean = true): void {
		if (this._disposed) { return; }
		// While the python executable is known to be broken, don't keep
		// retrying — that would just spin a spawn-error storm. The flag is
		// cleared by setPythonExecutable when the user changes config.
		if (this.pythonSpawnError) { return; }

		// If working directory changed, drain everything and restart
		if (this.poolWorkingDirectory && this.poolWorkingDirectory !== workingDirectory) {
			this.drainAllPools();
		}
		this.poolWorkingDirectory = workingDirectory;

		// Fill checkpoint 1 pool
		while (this.checkpoint1Pool.length < CP1_POOL_SIZE) {
			const worker = this.spawnWorker(workingDirectory);
			if (!worker) { break; }
			this.checkpoint1Pool.push(worker);
		}

		// Fill checkpoint 2 pool (only if we have code to warm with)
		if (includeCheckpoint2 && this.checkpoint2Code) {
			while (this.checkpoint2Pool.length < CP2_POOL_SIZE) {
				const worker = this.spawnWorker(workingDirectory);
				if (!worker) { break; }
				// The worker starts at checkpoint 1. Once it's ready,
				// processWorkerBuffer will advance it to checkpoint 2
				// (because it's in the checkpoint2Pool).
				worker.code = this.checkpoint2Code;
				this.checkpoint2Pool.push(worker);
			}
		}
	}

	/**
	 * Send init_imports to advance a checkpoint-1-ready worker to checkpoint 2.
	 */
	private warmToCheckpoint2(worker: PoolWorker, code: string): void {
		try {
			const msg = JSON.stringify({ type: 'init_imports', code }) + '\n';
			worker.child.stdin?.write(msg);
			worker.code = code;
			worker.ready = false; // will become ready again when checkpoint_ready(2) arrives
		} catch {
			this.removeWorkerFromPool(worker);
		}
	}

	/**
	 * Kill all checkpoint 2 workers, whose pre-executed imports are no longer the
	 * ones the user's program wants, and adopt the new code to warm with.
	 *
	 * Replacements are NOT spawned here — they are spawned once the current run
	 * completes (in handleRunMessage). Otherwise typing out `import pandas` one
	 * character at a time would spawn and kill ten processes per keystroke.
	 */
	private invalidateCheckpoint2Pool(newCode: string, newImportPrefix: string): void {
		for (const worker of this.checkpoint2Pool) {
			try { worker.child.kill(); } catch { /* ignore */ }
		}
		this.checkpoint2Pool = [];
		this.checkpoint2Code = newCode;
		this.checkpoint2ImportPrefix = newImportPrefix;
	}

	/**
	 * Take a ready worker for a program with the given leading imports. If no
	 * worker is ready, returns a Promise that resolves when one becomes available.
	 */
	private takeReadyWorker(importPrefix: string): PoolWorker | Promise<PoolWorker> {
		// Prefer a checkpoint 2 worker whose warmed imports are this program's
		if (importPrefix === this.checkpoint2ImportPrefix) {
			const idx = this.checkpoint2Pool.findIndex(w => w.ready);
			if (idx !== -1) {
				return this.checkpoint2Pool.splice(idx, 1)[0];
			}
		}

		// Fall back to a checkpoint 1 worker
		const idx = this.checkpoint1Pool.findIndex(w => w.ready);
		if (idx !== -1) {
			return this.checkpoint1Pool.splice(idx, 1)[0];
		}

		// No workers ready — wait for the next one to reach its checkpoint
		return new Promise<PoolWorker>((resolve, reject) => {
			this.workerWaiters.push({ resolve, reject });
		});
	}

	/**
	 * Drop every run still queued for a worker.
	 *
	 * Each waiter is a run the editor has already moved past — a newer run is
	 * starting, and the service only ever shows the newest. Serving them in turn
	 * makes a burst of N events cost N worker acquisitions, which is how a
	 * mousemove flood turns into seconds of queueing. Their promises reject, and
	 * `startProgram` returns quietly on that path.
	 */
	private abandonQueuedRuns(): void {
		while (this.workerWaiters.length > 0) {
			try { this.workerWaiters.shift()!.reject(new Error('superseded by a newer run')); } catch { /* ignore */ }
		}
	}

	/**
	 * Remove a worker from whichever pool it belongs to.
	 */
	private removeWorkerFromPool(worker: PoolWorker): void {
		let idx = this.checkpoint1Pool.indexOf(worker);
		if (idx !== -1) {
			this.checkpoint1Pool.splice(idx, 1);
			return;
		}
		idx = this.checkpoint2Pool.indexOf(worker);
		if (idx !== -1) {
			this.checkpoint2Pool.splice(idx, 1);
		}
	}

	/**
	 * Kill all workers in both pools.
	 */
	private drainAllPools(): void {
		for (const worker of [...this.checkpoint1Pool, ...this.checkpoint2Pool]) {
			try { worker.child.kill(); } catch { /* ignore */ }
		}
		this.checkpoint1Pool = [];
		this.checkpoint2Pool = [];
	}

	// -------------------------------------------------------------------
	// Worker stdout processing
	// -------------------------------------------------------------------

	/**
	 * Process buffered NDJSON output from a pool worker.
	 */
	private processWorkerBuffer(worker: PoolWorker): void {
		let idx: number;
		while ((idx = worker.buffer.indexOf('\n')) !== -1) {
			const line = worker.buffer.slice(0, idx).trim();
			worker.buffer = worker.buffer.slice(idx + 1);
			if (!line) { continue; }

			try {
				const msg = JSON.parse(line);

				if (msg.type === 'checkpoint_ready') {
					if (msg.checkpoint === 1) {
						// Advance it to checkpoint 2 if that's what it's for --
						// but not while a run has nothing to run on. A waiting
						// run outranks warming for some future one: queueing it
						// behind someone else's imports is how a keystroke ends
						// up waiting seconds for a worker that was ready.
						if (this.checkpoint2Pool.includes(worker) && worker.code && this.workerWaiters.length === 0) {
							this.warmToCheckpoint2(worker, worker.code);
						} else {
							worker.ready = true;
							worker.checkpoint = 1;
							this.resolveNextWaiter(worker);
						}
					} else if (msg.checkpoint === 2) {
						worker.ready = true;
						worker.checkpoint = 2;
						this.resolveNextWaiter(worker);
					}
				} else if (msg.type === 'warning' && msg.warning) {
					const runId = msg.run_id;
					if (runId) {
						this._onStream.fire({ runId, type: 'warning', warning: msg.warning });
					} else {
						console.warn('[SNC] Visualizer load warning (no active run):', msg.warning);
					}
				} else if (msg.type === 'item' || msg.type === 'command' || msg.type === 'loop' || msg.type === 'end' || msg.type === 'output') {
					const runId = msg.run_id || (msg.item && msg.item.runId);
					if (runId) {
						this.handleRunMessage(runId, msg);
					}
				}
			} catch {
				// Ignore non-JSON lines
			}
		}
	}

	/**
	 * If anyone is waiting for a ready worker, resolve the first waiter.
	 * Only resolves if the worker is still in a pool (not already taken).
	 */
	private resolveNextWaiter(worker: PoolWorker): void {
		if (this.workerWaiters.length === 0) { return; }

		// Remove the worker from its pool before handing it to the waiter
		const inCP1 = this.checkpoint1Pool.indexOf(worker);
		const inCP2 = this.checkpoint2Pool.indexOf(worker);
		if (inCP1 === -1 && inCP2 === -1) { return; }

		if (inCP1 !== -1) { this.checkpoint1Pool.splice(inCP1, 1); }
		if (inCP2 !== -1) { this.checkpoint2Pool.splice(inCP2, 1); }

		this.workerWaiters.shift()!.resolve(worker);

		// Replenish the pool after handing out a worker
		if (this.poolWorkingDirectory) {
			this.ensurePoolFilled(this.poolWorkingDirectory);
		}
	}

	// -------------------------------------------------------------------
	// Run handling
	// -------------------------------------------------------------------

	/**
	 * Handle a message (item/command/output/end) for a specific run.
	 */
	private handleRunMessage(runId: string, msg: any): void {
		const state = this.runs.get(runId);
		if (!state) { return; }

		if (msg.type === 'item' && msg.item) {
			if (!state.tFirstItem) {
				state.tFirstItem = Date.now();
			}
			this._onStream.fire({
				runId,
				type: 'item',
				item: { ...msg.item, runId } as IVisualizationItem
			});
		} else if (msg.type === 'command' && msg.command) {
			this._onStream.fire({
				runId,
				type: 'command',
				command: msg.command as SNCCommand
			});
		} else if (msg.type === 'loop' && msg.loop) {
			this._onStream.fire({
				runId,
				type: 'loop',
				loop: msg.loop as ILoopReport
			});
		} else if (msg.type === 'output') {
			this._onStream.fire({
				runId,
				type: 'output',
				stream: msg.stream === 'stderr' ? 'stderr' : 'stdout',
				text: String(msg.text ?? ''),
				stdinOffset: typeof msg.stdin_offset === 'number' ? msg.stdin_offset : 0
			});
		} else if (msg.type === 'end') {
			state.ended = true;
			state.tEnd = Date.now();
			if (state.timeoutId) {
				clearTimeout(state.timeoutId);
			}
			const timing: SNCTimingData = {
				spawnTimeMs: state.tSpawn,
				spawnToStdinEndMs: typeof state.tStdinEnd === 'number' ? state.tStdinEnd - state.tSpawn : undefined,
				spawnToStdoutFirstMs: typeof state.tStdoutFirst === 'number' ? state.tStdoutFirst - state.tSpawn : undefined,
				spawnToFirstItemMs: typeof state.tFirstItem === 'number' ? state.tFirstItem - state.tSpawn : undefined,
				spawnToEndMs: typeof state.tEnd === 'number' ? state.tEnd - state.tSpawn : undefined,
			};
			this._onStream.fire({
				runId,
				type: 'end',
				result: msg.result as IProcessResult,
				timing
			});
			this.runs.delete(runId);
			this.activeWorker = null;

			// Lazily refill pools after a run completes (not during rapid edits).
			// This is where CP2 workers get spawned after code settles.
			if (this.poolWorkingDirectory && !this._disposed) {
				this.ensurePoolFilled(this.poolWorkingDirectory);
			}
		}
	}

	/**
	 * Empty the runner's network read cache, once per cache directory per app
	 * session. The cache exists to keep reruns cheap while the user edits, not
	 * to outlive the window: reloading the app is how the user asks for fresh
	 * data. Clearing it here rather than in the runner matters because every
	 * rerun is a brand-new worker process, which would leave nothing cached.
	 */
	private clearUrlCacheOnce(options: IProcessOptions): Promise<void> {
		// Mirrors `cache_dir_for` in url_cache.py: beside the file being edited,
		// falling back to the working directory the worker runs in.
		const directory = options.filePath ? path.dirname(options.filePath) : options.workingDirectory;
		const cacheDir = directory ? path.join(directory, URL_CACHE_DIR_NAME) : '';

		// A relative or oddly shaped path could name any directory at all, so
		// only ever delete something that is unmistakably a cache directory.
		if (!path.isAbsolute(cacheDir) || path.basename(cacheDir) !== URL_CACHE_DIR_NAME) {
			return Promise.resolve();
		}

		let cleared = this.clearedUrlCaches.get(cacheDir);
		if (!cleared) {
			// A cache we can't delete is not a reason to fail the user's run.
			cleared = Promises.rm(cacheDir).catch(() => { });
			this.clearedUrlCaches.set(cacheDir, cleared);
		}
		return cleared;
	}

	// -------------------------------------------------------------------
	// Public API
	// -------------------------------------------------------------------

	/**
	 * Start a program using the process pool.
	 */
	async startProgram(content: string, options: IProcessOptions, runId: string): Promise<void> {
		const tSpawn = Date.now();

		const state: RunState = {
			runId,
			buffer: '',
			stderr: '',
			ended: false,
			tSpawn
		};
		this.runs.set(runId, state);

		this._onStream.fire({
			runId,
			type: 'spawn',
			timing: { spawnTimeMs: tSpawn }
		});

		// If we already know the python executable is broken, fail fast
		// instead of trying to spawn (and re-notifying about it). The
		// renderer's notification is already up.
		if (this.pythonSpawnError) {
			this._onStream.fire({ runId, type: 'error', error: this.pythonSpawnError });
			this.runs.delete(runId);
			return;
		}

		if (options?.timeout) {
			state.timeoutId = setTimeout(() => {
				if (!state.ended) {
					this._onStream.fire({
						runId,
						type: 'error',
						error: `Process execution timed out after ${options.timeout}ms`
					});
				}
				this.runs.delete(runId);
			}, options.timeout);
		}

		// Kill the currently active worker (stale run).
		// models_and_events carries all UI state forward so nothing is lost.
		if (this.activeWorker) {
			try { this.activeWorker.child.kill(); } catch { /* ignore */ }
			this.activeWorker = null;
		}

		// Runs still queued for a worker are superseded by this one exactly as the
		// active run just was, and their output would be discarded on arrival. Let
		// them go instead of handing each one a worker in turn: under a flood of
		// events the queue is the lag. Only the newest run is worth running.
		this.abandonQueuedRuns();

		// Ensure pool is seeded for this working directory. Checkpoint 2 is left
		// to the end of the run: warming it with code we may be about to
		// invalidate two lines below would just burn processes.
		this.ensurePoolFilled(options.workingDirectory, false);

		// A warmed worker has executed this program's imports and nothing else, so
		// only an edit that reaches the imports invalidates the pool. A body edit
		// — nearly every keystroke — keeps it, and just freshens the code new
		// workers warm on so they can skip compiling the body too.
		const importPrefix = importPrefixOf(content);
		const invalidated = importPrefix !== this.checkpoint2ImportPrefix;
		if (invalidated) {
			this.invalidateCheckpoint2Pool(content, importPrefix);
		} else {
			this.checkpoint2Code = content;
		}

		// Drop a cache left over from before this app session started, before any
		// worker can read through it.
		await this.clearUrlCacheOnce(options);

		// Take a ready worker (or wait for one). The waiter promise rejects
		// if the python executable can't be launched; in that case
		// handleSpawnFailure has already fired the user-facing error stream
		// message and cleaned up `this.runs`, so we just return.
		let worker: PoolWorker;
		try {
			const workerOrPromise = this.takeReadyWorker(importPrefix);
			worker = workerOrPromise instanceof Promise ? await workerOrPromise : workerOrPromise;
		} catch {
			// Either the python executable is broken — handleSpawnFailure has
			// already told the user and cleaned up — or a newer run superseded
			// this one, which needs no announcement. Just don't leak the run.
			if (state.timeoutId) { clearTimeout(state.timeoutId); }
			this.runs.delete(runId);
			return;
		}

		// Send the run command
		try {
			const cmd = JSON.stringify({
				type: 'run',
				run_id: runId,
				code: content,
				file_path: options.filePath ?? null,
				models_and_events: options.modelsAndEventsJson || '',
				focused_line: options.focusedLine ?? null,
				loop_selections: options.loopSelections ?? {},
				read_only: options.readOnly ?? false,
				stdin: options.stdin ?? '',
				// Default false so a read past the end starves — which is what
				// opens the console — rather than seeing a spurious EOF.
				stdin_eof: options.stdinEof ?? false
			}) + '\n';
			worker.child.stdin?.write(cmd);
			state.tStdinEnd = Date.now();
			this.activeWorker = worker;
		} catch (_err) {
			this._onStream.fire({ runId, type: 'error', error: 'Failed to write to worker stdin' });
			this.runs.delete(runId);
		}

		// Replenish. Checkpoint 2 is skipped only when we just invalidated it: that
		// is the rapid-import-editing case, where respawning ten workers we are
		// about to kill again is pure churn. Every other run must top it up here —
		// a burst of runs never reaches `run end` (each kills the one before it),
		// so leaving the refill to run-end alone lets the pool drain to empty and
		// dumps the whole burst onto checkpoint 1.
		this.ensurePoolFilled(options.workingDirectory, !invalidated);
	}

	async setPythonExecutable(executable: string): Promise<void> {
		const next = executable && executable.length > 0 ? executable : 'python3';
		if (next === this.pythonExecutable) {
			return;
		}
		this.pythonExecutable = next;

		// Reset the broken-state flag so we'll retry with the new value;
		// if it's still broken, handleSpawnFailure will notify again.
		this.pythonSpawnError = null;

		// Pre-warmed workers were spawned with the old interpreter — drop them
		// and refill. The active worker (if any) is allowed to finish; it'll
		// be killed by the next run as today.
		this.drainAllPools();
		if (this.poolWorkingDirectory && !this._disposed) {
			this.ensurePoolFilled(this.poolWorkingDirectory);
		}
	}

	async sendEvents(events: UiEvent[]): Promise<void> {
		const worker = this.activeWorker;
		if (!worker || events.length === 0) { return; }
		try {
			worker.child.stdin?.write(JSON.stringify({ type: 'events', events }) + '\n');
		} catch {
			// The run is on its way out. The editor keeps them queued and the
			// next run will carry them, so there is nothing to report.
		}
	}

	async cancel(runId: string): Promise<void> {
		const state = this.runs.get(runId);
		if (!state) { return; }
		if (state.timeoutId) {
			clearTimeout(state.timeoutId);
		}
		// Kill the active worker if it's handling this run
		if (this.activeWorker) {
			try { this.activeWorker.child.kill(); } catch { /* ignore */ }
			this.activeWorker = null;
		}
		this.runs.delete(runId);
	}

	override dispose(): void {
		this._disposed = true;
		if (this.activeWorker) {
			try { this.activeWorker.child.kill(); } catch { /* ignore */ }
			this.activeWorker = null;
		}
		this.drainAllPools();
		this.workerWaiters.length = 0;
		super.dispose();
	}
}
