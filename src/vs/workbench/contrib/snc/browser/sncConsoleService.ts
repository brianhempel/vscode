/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { VSBuffer } from '../../../../base/common/buffer.js';
import { Emitter, Event } from '../../../../base/common/event.js';
import { Disposable, IDisposable } from '../../../../base/common/lifecycle.js';
import { basename, dirname, joinPath } from '../../../../base/common/resources.js';
import { URI } from '../../../../base/common/uri.js';
import { ITextModel } from '../../../../editor/common/model.js';
import { IModelService } from '../../../../editor/common/services/model.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { InstantiationType, registerSingleton } from '../../../../platform/instantiation/common/extensions.js';
import { IProcessResult } from '../../../../platform/snc/common/snc.js';
import {
	EMPTY_TRANSCRIPT, IConsoleChunk, IConsoleTranscript, ISNCConsoleService,
	SNC_STDIN_DIR_NAME, splitAtEofMarker, stdinModelUri
} from '../common/sncConsole.js';

/**
 * How long a run may go without finishing before its output starts appearing
 * live. Under this, the transcript swaps in atomically at the end — which is
 * every ordinary run, and is what keeps the console from flickering while the
 * user types in either editor. Over it (a slow loop) liveness wins.
 */
const LIVE_OUTPUT_DELAY_MS = 150;

/** Coalescing window for live chunks, matching the one `item` messages use. */
const LIVE_FIRE_THROTTLE_MS = 16;

/** Quiet period before the stdin document is written back to disk. */
const SAVE_DELAY_MS = 400;

interface IFileConsole {
	/** Synchronous mirror of the model's text, so a run never waits on disk. */
	stdinText: string;
	loading?: Promise<ITextModel>;
	model?: ITextModel;
	modelListener?: IDisposable;

	/** What the console displays. */
	committed: IConsoleTranscript;
	/** Output from the run in flight. */
	pending: IConsoleChunk[];
	/** The in-flight run is slow enough that its output is being shown as it arrives. */
	live: boolean;
	liveTimer?: any;
	liveFireTimer?: any;
	saveTimer?: any;

	/** The console has been offered for this file once; don't nag after that. */
	opened: boolean;
}

export class SNCConsoleService extends Disposable implements ISNCConsoleService {

	declare readonly _serviceBrand: undefined;

	private readonly _onDidChangeStdin = this._register(new Emitter<string>());
	readonly onDidChangeStdin: Event<string> = this._onDidChangeStdin.event;

	private readonly _onDidChangeTranscript = this._register(new Emitter<string>());
	readonly onDidChangeTranscript: Event<string> = this._onDidChangeTranscript.event;

	private readonly _onDidRequestOpen = this._register(new Emitter<{ filePath: string; focus: boolean }>());
	readonly onDidRequestOpen: Event<{ filePath: string; focus: boolean }> = this._onDidRequestOpen.event;

	private readonly consoles = new Map<string, IFileConsole>();

	constructor(
		@IModelService private readonly modelService: IModelService,
		@IFileService private readonly fileService: IFileService,
	) {
		super();
	}

	private stateFor(filePath: string): IFileConsole {
		let state = this.consoles.get(filePath);
		if (!state) {
			state = { stdinText: '', committed: EMPTY_TRANSCRIPT, pending: [], live: false, opened: false };
			this.consoles.set(filePath, state);
		}
		return state;
	}

	// -- stdin ---------------------------------------------------------------

	stdinFor(filePath: string): { stdin: string; stdinEof: boolean } {
		const state = this.stateFor(filePath);
		if (!state.model && !state.loading) {
			// First run for this file. It goes out with empty stdin, and the
			// load below reruns it with the restored session a moment later.
			this.stdinModel(filePath);
		}
		return splitAtEofMarker(state.stdinText);
	}

	stdinModel(filePath: string): Promise<ITextModel> {
		const state = this.stateFor(filePath);
		if (state.model) {
			return Promise.resolve(state.model);
		}
		if (!state.loading) {
			state.loading = this.loadStdinModel(filePath, state);
		}
		return state.loading;
	}

	private async loadStdinModel(filePath: string, state: IFileConsole): Promise<ITextModel> {
		let text = '';
		try {
			text = (await this.fileService.readFile(this.stdinFileUri(filePath))).value.toString();
		} catch {
			// No session recorded for this file yet.
		}

		const uri = stdinModelUri(filePath);
		const model = this.modelService.getModel(uri) ?? this.modelService.createModel(text, null, uri);
		state.model = model;
		state.stdinText = model.getValue();
		state.modelListener = model.onDidChangeContent(() => {
			state.stdinText = model.getValue();
			this.scheduleSave(filePath, state);
			this._onDidChangeStdin.fire(filePath);
		});

		if (state.stdinText) {
			// The run that kicked this load off went out with empty stdin.
			this._onDidChangeStdin.fire(filePath);
		}
		return model;
	}

	async clear(filePath: string): Promise<void> {
		const model = await this.stdinModel(filePath);
		// Goes through the model rather than the disk so it's one undoable edit
		// and the rerun happens on the same path as any other stdin change.
		model.setValue('');
	}

	// -- persistence ---------------------------------------------------------

	/**
	 * Where a file's stdin document lives: `.snc_stdin/<name>.txt` beside the
	 * source, mirroring how `.snc_url_cache` sits beside it. Unlike that cache
	 * this is the user's own input, so it is meant to be committed.
	 */
	private stdinFileUri(filePath: string): URI {
		const source = URI.file(filePath);
		return joinPath(dirname(source), SNC_STDIN_DIR_NAME, `${basename(source)}.txt`);
	}

	private scheduleSave(filePath: string, state: IFileConsole): void {
		clearTimeout(state.saveTimer);
		state.saveTimer = setTimeout(() => this.save(filePath, state), SAVE_DELAY_MS);
	}

	private async save(filePath: string, state: IFileConsole): Promise<void> {
		const uri = this.stdinFileUri(filePath);
		try {
			if (!state.stdinText) {
				// An empty document is no session at all; leaving the file
				// behind would put an empty artifact in the user's repo.
				await this.fileService.del(uri).catch(() => { });
				return;
			}
			await this.fileService.createFolder(dirname(uri)).catch(() => { });
			await this.fileService.writeFile(uri, VSBuffer.fromString(state.stdinText));
		} catch (err) {
			// Losing the recorded session is not worth interrupting the user
			// mid-keystroke; the in-memory document is still correct.
			console.error('SNC: failed to save stdin document', err);
		}
	}

	// -- transcript ----------------------------------------------------------

	runStarted(filePath: string): void {
		const state = this.stateFor(filePath);
		state.pending = [];
		state.live = false;
		clearTimeout(state.liveTimer);
		state.liveTimer = setTimeout(() => {
			state.live = true;
			this.fireTranscript(filePath, state);
		}, LIVE_OUTPUT_DELAY_MS);
	}

	appendOutput(filePath: string, chunk: IConsoleChunk): void {
		const state = this.stateFor(filePath);
		state.pending.push(chunk);
		if (state.live && !state.liveFireTimer) {
			state.liveFireTimer = setTimeout(() => {
				state.liveFireTimer = undefined;
				this.fireTranscript(filePath, state);
			}, LIVE_FIRE_THROTTLE_MS);
		}
	}

	runAbandoned(filePath: string): void {
		const state = this.stateFor(filePath);
		this.stopLiveTimers(state);
		const wasLive = state.live;
		state.live = false;
		state.pending = [];
		if (wasLive) {
			// The display had switched to this run's output; put the last
			// completed one back rather than leaving it half-drawn.
			this.fireTranscript(filePath, state);
		}
	}

	runFinished(filePath: string, result: IProcessResult | undefined): void {
		const state = this.stateFor(filePath);
		this.stopLiveTimers(state);
		state.live = false;
		state.committed = {
			chunks: state.pending,
			stdinConsumed: result?.stdinConsumed ?? 0,
			awaitingKind: result?.awaitingInput ? (result.awaitingKind ?? 'line') : undefined,
		};
		state.pending = [];
		this.fireTranscript(filePath, state);

		if (!state.opened && (state.committed.chunks.length > 0 || state.committed.awaitingKind)) {
			state.opened = true;
			// Only ever once per file: every keystroke reruns, and a program
			// parked on `input()` would otherwise steal focus continuously.
			this._onDidRequestOpen.fire({ filePath, focus: !!state.committed.awaitingKind });
		}
	}

	transcriptFor(filePath: string): IConsoleTranscript {
		const state = this.stateFor(filePath);
		if (state.live) {
			// Mid-run: show what has arrived, but nothing that is only known
			// once the run ends.
			return { chunks: state.pending, stdinConsumed: state.committed.stdinConsumed, awaitingKind: undefined };
		}
		return state.committed;
	}

	private stopLiveTimers(state: IFileConsole): void {
		clearTimeout(state.liveTimer);
		clearTimeout(state.liveFireTimer);
		state.liveTimer = state.liveFireTimer = undefined;
	}

	private fireTranscript(filePath: string, _state: IFileConsole): void {
		this._onDidChangeTranscript.fire(filePath);
	}

	override dispose(): void {
		for (const state of this.consoles.values()) {
			clearTimeout(state.liveTimer);
			clearTimeout(state.liveFireTimer);
			clearTimeout(state.saveTimer);
			state.modelListener?.dispose();
		}
		this.consoles.clear();
		super.dispose();
	}
}

registerSingleton(ISNCConsoleService, SNCConsoleService, InstantiationType.Delayed);
