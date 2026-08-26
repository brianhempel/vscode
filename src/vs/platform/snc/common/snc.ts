/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { createDecorator } from '../../../platform/instantiation/common/instantiation.js';
import { Event } from '../../../base/common/event.js';

export interface IVisualizationItem {
	line: number;
	visIndex: number; // within line
	runId: string;
	execution_step: number;
	html: string;
	model?: unknown;
	unhandledEvents?: UiEvent[];
	last_line_in_containing_loop?: number;
}

export type UiEvent = { line: number; visIndex: number, pythonEventStr: string, eventJSON: any };

export interface IProcessResult {
	stdout: string; // Always empty from a run: program output streams as `output` messages
	stderr: string; // As above, except on the syntax-error path, which reports the error here
	exitCode: number;
	syntaxError?: boolean;
	/**
	 * The run stopped on a read past the end of the recorded stdin. Not a
	 * failure: the program is waiting for the user to type, so `exitCode` is 0
	 * and no error item was logged.
	 */
	awaitingInput?: boolean;
	/** `'line'` if more typing satisfies the read, `'eof'` if only ending the stream will. */
	awaitingKind?: 'line' | 'eof';
	/** Characters of the stdin document the program consumed. */
	stdinConsumed?: number;
}

export interface IProcessOptions {
	timeout?: number; // Optional timeout in milliseconds
	workingDirectory: string; // Required working directory for code execution
	filePath?: string; // Path of the file being run; sites the .snc_url_cache dir beside it
	modelsAndEventsJson?: string; // visualizers state, and events to apply
	focusedLine?: number; // 1-indexed line whose top-level visualizer should render full-size; others render with small=True
	stdin?: string; // The console document, replayed through the program's stdin
	stdinEof?: boolean; // Whether the document ends the stream; false makes a read past its end starve rather than see EOF
}

/**
 * Mime type an snc-py-exps drag carries alongside `text/plain`, holding
 * `{ expr, imports }` as JSON. `text/plain` stays the expression on its own, so
 * dropping anywhere else still works; this is what lets a drop into a Python
 * editor bring the imports the expression needs with it.
 */
export const SNC_PY_EXP_MIME = 'application/vnd.snc.py-exp';

export interface NewCodeEdit {
	type: 'insert';
	afterLine: number; // 1-indexed; 0 means insert before line 1
	text: string;
	// How many of the inserted lines are the statement's header. A visualizer
	// links only its header; the body below belongs to the user. Absent on
	// incidental edits (e.g. an auto-added import).
	headerLines?: number;
	// How many lines of the inserted text come BEFORE the statement -- a
	// `#%click` config comment the new line opens with. The statement (what
	// gets linked, and whose name is offered for renaming) starts below them.
	leadingLines?: number;
}

export type SNCCommand =
	// `imports` is what the visualizer that generated this code says it needs to
	// run. Whether the file already has them, and where a missing one goes, is
	// the editor's to decide — see pythonImports.ts.
	| { type: 'NewCode'; triggerLine: number; triggerVisIndex: number; edits: NewCodeEdit[]; imports?: string[] }
	| { type: 'CopyToClipboard'; text: string }
	// Rewrite the `#%click` comment that holds the trigger line's visualizer
	// config (its columns, fields, ...). `comment` is the whole comment text
	// without indentation; null removes it. The editor finds the existing
	// comment by the rule the runner reads it with -- the nearest one above
	// with only blank lines and comments between -- and replaces it, or
	// inserts a new line above the trigger line.
	| { type: 'SetConfigComment'; comment: string | null; triggerLine: number; triggerVisIndex: number }
	// The backend supplies expression intent; the editor's linked range remains
	// authoritative for the concrete assignment target. On semantic action
	// changes, suggested_var_name requests a safe editor-side rename.
	// triggerLine/triggerVisIndex identify the visualizer that emitted this
	// update, so the editor can find that visualizer's own linked range instead
	// of a single global one (avoids cross-talk between multiple linked lines).
	| {
		type: 'ChangeSelectedText';
		expression: string;
		suggested_var_name?: string | null;
		triggerLine: number;
		triggerVisIndex: number;
	}
	// Rewrite the expression a visualizer's OWN line is showing, in place —
	// what the list visualizer's Sort does. Unlike ChangeSelectedText, which
	// edits a line the visualizer wrote and tracks by decoration, this replaces
	// an exact range of the user's own source. A range rather than a line, so a
	// `return xs` or `if xs:` can never have its keyword eaten and a multi-line
	// expression needs no special case.
	//
	// Columns are 0-based UTF-8 byte offsets, as Python's parser reports them;
	// the editor converts to its own 1-based columns, being the side that knows
	// the encoding of the document it is editing.
	| {
		type: 'ChangeSourceExpr';
		expression: string;
		start_line: number;
		start_col: number;
		end_line: number;
		end_col: number;
		triggerLine: number;
		triggerVisIndex: number;
	};

/**
 * Timing data for visualizer performance measurement.
 * All times are in milliseconds and relative to spawn time unless otherwise noted.
 */
export interface SNCTimingData {
	/** Backend timestamp (Date.now()) when spawn was called */
	spawnTimeMs: number;
	/** Time from spawn to stdin end (code sent) */
	spawnToStdinEndMs?: number;
	/** Time from spawn to first byte on stdout */
	spawnToStdoutFirstMs?: number;
	/** Time from spawn to first visualization item parsed */
	spawnToFirstItemMs?: number;
	/** Time from spawn to run completion */
	spawnToEndMs?: number;
}

export type SNCStreamMessage =
	| { runId: string; type: 'item'; item: IVisualizationItem }
	| { runId: string; type: 'command'; command: SNCCommand }
	| { runId: string; type: 'end'; result: IProcessResult; timing?: SNCTimingData }
	| { runId: string; type: 'spawn'; timing: SNCTimingData }
	| { runId: string; type: 'error'; error: string }
	| { runId: string; type: 'warning'; warning: string }
	/**
	 * A chunk of the program's stdout/stderr. `stdinOffset` is how much of the
	 * stdin document had been consumed when it was written, which is what
	 * places the chunk between the right two lines of the console.
	 */
	| { runId: string; type: 'output'; stream: 'stdout' | 'stderr'; text: string; stdinOffset: number };

export const ISNCProcessService = createDecorator<ISNCProcessService>('sncProcessService');

export interface ISNCProcessService {
	/**
	 * Streaming API: event that delivers incremental visualization items and completion.
	 * Listen via `channel.listen('onStream')` on the renderer side.
	 */
	readonly onStream: Event<SNCStreamMessage>;

	/**
	 * Start a streaming run. Use `runId` to correlate `onStream` messages.
	 * Returns when the child process is successfully spawned and stdin sent.
	 */
	startProgram(content: string, options: IProcessOptions, runId: string): Promise<void>;

	/**
	 * Cancel a streaming run by runId. No-op if already finished or not found.
	 */
	cancel(runId: string): Promise<void>;

	/**
	 * Set the Python executable to use for spawning workers. The renderer
	 * resolves this from the Python extension via `python.interpreterPath`
	 * (or falls back to `'python3'`) and forwards it here. If the value
	 * differs from the current one, both pools are drained and refilled
	 * with the new interpreter.
	 */
	setPythonExecutable(executable: string): Promise<void>;
}
