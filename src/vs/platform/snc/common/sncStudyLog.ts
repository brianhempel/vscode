/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { createDecorator } from '../../instantiation/common/instantiation.js';

/**
 * Sculpt-n-Code study logging: an append-only JSON-lines record of how a
 * participant used the system, written to disk for later analysis. See
 * `Study Logging.md` at the repo root for the event catalog.
 *
 * Two halves:
 *  - `ISNCStudyLogWriter` lives in the main process (the renderer cannot write
 *    files), reached over the `sncStudyLog` IPC channel. It owns the session id
 *    (one per app launch) and appends batches of lines to one file per session.
 *  - The renderer-side service (workbench/contrib/snc) buffers events and
 *    flushes them to the writer about once a second and on shutdown.
 *
 * Product code never talks to the service directly: it calls `studyLog.log(...)`,
 * a module-level sink that the workbench service installs itself into. That
 * keeps the call sites to one line, works from code that is not
 * dependency-injected (VisualizationWidget), and can never throw.
 */

export const SNC_STUDY_LOG_CHANNEL = 'sncStudyLog';

export const ISNCStudyLogWriter = createDecorator<ISNCStudyLogWriter>('sncStudyLogWriter');

export interface ISNCStudyLogSessionInfo {
	/** Random id minted once per app launch; also the log file's basename. */
	sessionId: string;
	/** Where the file goes when `clickacode.studyLogging.directory` is unset. */
	defaultDirectory: string;
	/** ISO timestamp of when the main process started. */
	startedAt: string;
}

export interface ISNCStudyLogWriter {
	getSessionInfo(): Promise<ISNCStudyLogSessionInfo>;
	/**
	 * Append already-serialized JSON lines (no trailing newline) to the session's
	 * file under `directory` (or the default directory when undefined). Writes
	 * for one session are serialized, so lines land in the order they are sent.
	 * Resolves to the absolute path of the file written.
	 */
	append(directory: string | undefined, lines: string[]): Promise<string>;
}

/** One record in the log file. */
export interface ISNCStudyLogEvent {
	/** Wall clock, ISO 8601. */
	t: string;
	/** Monotonic milliseconds since the window loaded (`performance.now()`). */
	ms: number;
	/** Per-window sequence number, for ordering and gap detection. */
	seq: number;
	session: string;
	window: number;
	type: string;
	/** URI of the file the event concerns, when there is one. */
	file?: string;
	payload?: unknown;
}

export interface ISNCStudyLogSink {
	log(type: string, payload?: unknown, file?: string): void;
}

/** The maximum number of events held before a sink is installed. */
const PRE_INSTALL_BUFFER_LIMIT = 5000;

let installedSink: ISNCStudyLogSink | undefined;
let preInstallBuffer: { type: string; payload?: unknown; file?: string }[] = [];

/**
 * The origin SNC assigns to an edit it is itself making to a text model, so
 * the model-change listener can tell SNC's edits from the user's typing.
 * `pushEditOperations` fires `onDidChangeContent` synchronously, which is what
 * makes a simple "set, run, clear" bracket sufficient.
 */
let currentEditOrigin: string | undefined;

/**
 * The single entry point product code uses. Every method swallows its own
 * errors: logging must never break the thing it is observing.
 */
export const studyLog = {
	log(type: string, payload?: unknown, file?: string): void {
		try {
			if (installedSink) {
				installedSink.log(type, payload, file);
			} else if (preInstallBuffer.length < PRE_INSTALL_BUFFER_LIMIT) {
				preInstallBuffer.push({ type, payload, file });
			}
		} catch {
			// never throw into product code
		}
	},

	/**
	 * Run `fn` with `origin` recorded as the reason for any model edits it makes
	 * (e.g. `'NewCode'`, `'ChangeSelectedText'`). Nested brackets keep the
	 * outermost origin.
	 */
	withEditOrigin<T>(origin: string, fn: () => T): T {
		const previous = currentEditOrigin;
		if (previous === undefined) {
			currentEditOrigin = origin;
		}
		try {
			return fn();
		} finally {
			currentEditOrigin = previous;
		}
	},

	/** The origin of the SNC edit in progress, or undefined when the user is typing. */
	currentEditOrigin(): string | undefined {
		return currentEditOrigin;
	},
};

/** Called once by the workbench service; drains whatever was logged before it existed. */
export function installStudyLogSink(sink: ISNCStudyLogSink): void {
	installedSink = sink;
	const buffered = preInstallBuffer;
	preInstallBuffer = [];
	for (const e of buffered) {
		try {
			sink.log(e.type, e.payload, e.file);
		} catch {
			// ignore
		}
	}
}

export function uninstallStudyLogSink(sink: ISNCStudyLogSink): void {
	if (installedSink === sink) {
		installedSink = undefined;
	}
}

/**
 * Coalesces a stream of high-frequency events (mouse moves, cursor moves,
 * scrolls) into far fewer log records.
 *
 * Rule: a `note(key, payload)` is logged immediately when `key` differs from
 * the previous note's key, or when at least `minIntervalMs` have passed since
 * the last logged record. Notes that are suppressed are counted; the count of
 * suppressed notes since the last record is attached to the next record as
 * `coalesced`, and the most recent suppressed note is emitted as a trailing
 * record after `trailingMs` of silence so the final position is never lost.
 */
export class StudyLogCoalescer {
	private lastKey: string | undefined;
	private lastLoggedMs = -Infinity;
	private suppressed = 0;
	private pending: { payload: unknown; file?: string } | undefined;
	private trailingTimer: ReturnType<typeof setTimeout> | undefined;

	constructor(
		private readonly type: string,
		private readonly minIntervalMs: number,
		private readonly trailingMs: number = minIntervalMs,
	) { }

	note(key: string, payload: unknown, file?: string): void {
		try {
			const now = Date.now();
			const keyChanged = key !== this.lastKey;
			this.lastKey = key;
			if (keyChanged || now - this.lastLoggedMs >= this.minIntervalMs) {
				this.emit(payload, file, now);
			} else {
				this.suppressed++;
				this.pending = { payload, file };
				this.armTrailing();
			}
		} catch {
			// ignore
		}
	}

	/** Emit whatever is pending right away (e.g. before a related discrete event). */
	flush(): void {
		try {
			if (this.trailingTimer !== undefined) {
				clearTimeout(this.trailingTimer);
				this.trailingTimer = undefined;
			}
			if (this.pending) {
				const { payload, file } = this.pending;
				this.emit(payload, file, Date.now());
			}
		} catch {
			// ignore
		}
	}

	private armTrailing(): void {
		if (this.trailingTimer !== undefined) {
			clearTimeout(this.trailingTimer);
		}
		this.trailingTimer = setTimeout(() => {
			this.trailingTimer = undefined;
			this.flush();
		}, this.trailingMs);
	}

	private emit(payload: unknown, file: string | undefined, now: number): void {
		const record = (typeof payload === 'object' && payload !== null)
			? { ...(payload as object), coalesced: this.suppressed }
			: { value: payload, coalesced: this.suppressed };
		this.suppressed = 0;
		this.pending = undefined;
		this.lastLoggedMs = now;
		studyLog.log(this.type, record, file);
	}
}

/**
 * Best-effort name of the visualizer that produced a chunk of HTML, from the
 * `*-visualizer` class on its container (`string-visualizer`,
 * `list-visualizer`, ...). Undefined when there is no such class.
 */
export function visualizerTypeOf(html: string): string | undefined {
	try {
		const m = /class="([^"]*)"/.exec(html.slice(0, 2000));
		if (!m) { return undefined; }
		const cls = m[1].split(/\s+/).find(c => c.endsWith('-visualizer') || c.endsWith('_visualizer'));
		if (cls) { return cls; }
		const m2 = /class="[^"]*\b([a-z_-]*visualizer)\b[^"]*"/.exec(html.slice(0, 4000));
		return m2 ? m2[1] : undefined;
	} catch {
		return undefined;
	}
}

/** Trim long strings for the log; the full text lives in the file snapshots. */
export function truncateForLog(text: string, max = 2000): { text: string; length: number; truncated: boolean } {
	return text.length > max
		? { text: text.slice(0, max), length: text.length, truncated: true }
		: { text, length: text.length, truncated: false };
}
