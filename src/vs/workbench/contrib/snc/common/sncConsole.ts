/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Event } from '../../../../base/common/event.js';
import { URI } from '../../../../base/common/uri.js';
import { ITextModel } from '../../../../editor/common/model.js';
import { createDecorator } from '../../../../platform/instantiation/common/instantiation.js';
import { IProcessResult } from '../../../../platform/snc/common/snc.js';

/**
 * The user program's console: an editable stdin document with the program's
 * output rendered between its lines.
 *
 * Sculpt-n-Code reruns the whole file several times a second in a fresh worker,
 * so there is nobody for a live terminal to talk to. Instead the stdin the user
 * typed is a *document* the editor owns and ships in with every run, and the
 * output is recomputed from scratch each time and shown as view zones between
 * the stdin lines. Editing a stdin line reruns the program exactly the way
 * editing a source line does.
 */

/** Scheme of the stdin document's model. */
export const SNC_STDIN_SCHEME = 'snc-stdin';

/** Directory the stdin documents persist into, beside the file being edited. */
export const SNC_STDIN_DIR_NAME = '.snc_stdin';

/**
 * A line of exactly this ends the stream. It lives in the document rather than
 * in a sidecar or a toolbar toggle so that it is editable, undoable and
 * diffable like the rest of the input — and so that it is *positional*: text
 * below it is simply never read.
 *
 * The cost is that a program can't be fed the literal line `<EOF>`. There is no
 * escape hatch; for a teaching tool that trade is worth it.
 */
export const EOF_MARKER = '<EOF>';

export interface IConsoleChunk {
	readonly stream: 'stdout' | 'stderr';
	readonly text: string;
	/** Characters of the stdin document consumed when this was written. */
	readonly stdinOffset: number;
}

export interface IConsoleTranscript {
	readonly chunks: readonly IConsoleChunk[];
	/** How far into the stdin document the program got. */
	readonly stdinConsumed: number;
	/** Set when the run stopped waiting for input the document doesn't have. */
	readonly awaitingKind: 'line' | 'eof' | undefined;
}

export const EMPTY_TRANSCRIPT: IConsoleTranscript = { chunks: [], stdinConsumed: 0, awaitingKind: undefined };

/** The model URI for a source file's stdin document. */
export function stdinModelUri(filePath: string): URI {
	return URI.file(filePath).with({ scheme: SNC_STDIN_SCHEME });
}

/**
 * Split a stdin document at its end-of-stream marker.
 *
 * This is the only place the `<EOF>` convention is interpreted: Python's
 * contract stays the dumb one, "here is the text, here is whether it ends".
 * Because only text *above* the marker is ever sent, every offset the runner
 * reports back maps one-to-one onto a position in the document.
 */
export function splitAtEofMarker(text: string): { stdin: string; stdinEof: boolean } {
	const lines = text.split('\n');
	const marker = lines.findIndex(line => line.trim() === EOF_MARKER);
	if (marker < 0) {
		return { stdin: text, stdinEof: false };
	}
	// Each line above the marker keeps the newline that terminated it.
	return { stdin: marker === 0 ? '' : lines.slice(0, marker).join('\n') + '\n', stdinEof: true };
}

/** 1-indexed line holding the end-of-stream marker, if the document has one. */
export function eofMarkerLine(text: string): number | undefined {
	const marker = text.split('\n').findIndex(line => line.trim() === EOF_MARKER);
	return marker < 0 ? undefined : marker + 1;
}

export const ISNCConsoleService = createDecorator<ISNCConsoleService>('sncConsoleService');

export interface ISNCConsoleService {
	readonly _serviceBrand: undefined;

	/** The stdin document for this file changed; its program should rerun. */
	readonly onDidChangeStdin: Event<string>;

	/** The transcript to display for this file changed. */
	readonly onDidChangeTranscript: Event<string>;

	/** This file's console has something to show. `focus` when it wants typing. */
	readonly onDidRequestOpen: Event<{ filePath: string; focus: boolean }>;

	/**
	 * What to send as the program's stdin, read from a synchronous cache so a
	 * run never waits on disk. A file whose document hasn't loaded yet reads as
	 * empty, and loading it fires `onDidChangeStdin` to rerun with the real text.
	 */
	stdinFor(filePath: string): { stdin: string; stdinEof: boolean };

	/** A run is starting; drop the output collected for the previous one. */
	runStarted(filePath: string): void;

	/** Record a chunk of program output for the in-flight run. */
	appendOutput(filePath: string, chunk: IConsoleChunk): void;

	/** The in-flight run ended; publish what it produced. */
	runFinished(filePath: string, result: IProcessResult | undefined): void;

	/**
	 * The in-flight run produced nothing worth showing (it never started, or
	 * the source doesn't parse). Drops its output but leaves the last good
	 * transcript up, the way the source editor keeps its widgets stable while
	 * the user is mid-edit.
	 */
	runAbandoned(filePath: string): void;

	/** What the console should currently display for this file. */
	transcriptFor(filePath: string): IConsoleTranscript;

	/** The editable stdin document, created (and loaded from disk) on demand. */
	stdinModel(filePath: string): Promise<ITextModel>;

	/** Throw away the stored input and start the session over. */
	clear(filePath: string): Promise<void>;
}
