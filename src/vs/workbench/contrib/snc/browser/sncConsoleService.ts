/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { VSBuffer } from '../../../../base/common/buffer.js';
import { Emitter, Event } from '../../../../base/common/event.js';
import { Disposable, IDisposable, IReference } from '../../../../base/common/lifecycle.js';
import { dirname } from '../../../../base/common/resources.js';
import { URI } from '../../../../base/common/uri.js';
import { IResolvedTextEditorModel, ITextModelService } from '../../../../editor/common/services/resolverService.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { InstantiationType, registerSingleton } from '../../../../platform/instantiation/common/extensions.js';
import { IProcessResult } from '../../../../platform/snc/common/snc.js';
import { ITextFileService } from '../../../services/textfile/common/textfiles.js';
import {
	EMPTY_TRANSCRIPT, IConsoleChunk, IConsoleTranscript, ISNCConsoleService, splitAtEofMarker, stdinFileUri
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
	loading?: Promise<void>;
	modelRef?: IReference<IResolvedTextEditorModel>;
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
		@ITextModelService private readonly textModelService: ITextModelService,
		@ITextFileService private readonly textFileService: ITextFileService,
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
		if (!state.modelRef && !state.loading) {
			// First run for this file. It goes out with empty stdin, and if a
			// session was recorded the load below reruns it a moment later.
			this.loadStdinIfPresent(filePath);
		}
		return splitAtEofMarker(state.stdinText);
	}

	/**
	 * Adopt an existing stdin document without creating one. A program that
	 * never touches stdin must not leave a file behind, so the document only
	 * comes into existence through `ensureStdinFile`.
	 */
	async loadStdinIfPresent(filePath: string): Promise<void> {
		const state = this.stateFor(filePath);
		if (state.modelRef || state.loading) {
			return state.loading;
		}
		state.loading = (async () => {
			if (await this.fileService.exists(stdinFileUri(filePath))) {
				await this.track(filePath, state);
			}
		})();
		return state.loading;
	}

	async ensureStdinFile(filePath: string): Promise<URI> {
		const uri = stdinFileUri(filePath);
		const state = this.stateFor(filePath);
		await state.loading?.catch(() => { });
		if (!state.modelRef) {
			if (!(await this.fileService.exists(uri))) {
				// A text model can only be resolved for a resource that exists,
				// and the tab has to have a file behind it to be saveable.
				await this.fileService.createFolder(dirname(uri));
				await this.fileService.writeFile(uri, VSBuffer.fromString(''));
			}
			await this.track(filePath, state);
		}
		return uri;
	}

	/**
	 * Hold a reference to the stdin document's model so it stays loaded whether
	 * or not a tab is showing it, and rerun the program whenever it changes.
	 */
	private async track(filePath: string, state: IFileConsole): Promise<void> {
		const ref = await this.textModelService.createModelReference(stdinFileUri(filePath));
		if (state.modelRef || this._store.isDisposed) {
			ref.dispose(); // Raced with another caller, or we're going away.
			return;
		}
		state.modelRef = ref;
		const model = ref.object.textEditorModel;
		const stale = state.stdinText !== model.getValue();
		state.stdinText = model.getValue();
		state.modelListener = model.onDidChangeContent(() => {
			state.stdinText = model.getValue();
			this.scheduleSave(filePath, state);
			this._onDidChangeStdin.fire(filePath);
		});
		if (stale) {
			// The run that kicked this load off went out without the recording.
			this._onDidChangeStdin.fire(filePath);
		}
	}

	async clear(filePath: string): Promise<void> {
		await this.ensureStdinFile(filePath);
		// Goes through the model rather than the disk so it's one undoable edit
		// and the rerun happens on the same path as any other stdin change.
		// An edit, not setValue: that flushes the document's whole undo stack.
		const model = this.stateFor(filePath).modelRef?.object.textEditorModel;
		if (!model) {
			return;
		}
		model.pushStackElement();
		model.pushEditOperations(null, [{ range: model.getFullModelRange(), text: '' }], () => null);
		model.pushStackElement();
	}

	// -- persistence ---------------------------------------------------------

	private scheduleSave(filePath: string, state: IFileConsole): void {
		clearTimeout(state.saveTimer);
		state.saveTimer = setTimeout(() => this.save(filePath, state), SAVE_DELAY_MS);
	}

	private async save(filePath: string, state: IFileConsole): Promise<void> {
		if (!state.modelRef) {
			return;
		}
		try {
			// Saved for the user rather than left dirty: typing here is a program
			// input, not an edit they are expected to commit deliberately.
			await this.textFileService.save(stdinFileUri(filePath));
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
			this.fireTranscript(filePath);
		}, LIVE_OUTPUT_DELAY_MS);
	}

	appendOutput(filePath: string, chunk: IConsoleChunk): void {
		const state = this.stateFor(filePath);
		state.pending.push(chunk);
		if (state.live && !state.liveFireTimer) {
			state.liveFireTimer = setTimeout(() => {
				state.liveFireTimer = undefined;
				this.fireTranscript(filePath);
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
			this.fireTranscript(filePath);
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
		this.fireTranscript(filePath);

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

	private fireTranscript(filePath: string): void {
		this._onDidChangeTranscript.fire(filePath);
	}

	override dispose(): void {
		for (const state of this.consoles.values()) {
			clearTimeout(state.liveTimer);
			clearTimeout(state.liveFireTimer);
			clearTimeout(state.saveTimer);
			state.modelListener?.dispose();
			state.modelRef?.dispose();
		}
		this.consoles.clear();
		super.dispose();
	}
}

registerSingleton(ISNCConsoleService, SNCConsoleService, InstantiationType.Delayed);
