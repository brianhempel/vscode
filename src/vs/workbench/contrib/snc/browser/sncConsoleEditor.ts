/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/sncConsole.css';
import * as dom from '../../../../base/browser/dom.js';
import { Disposable, DisposableStore } from '../../../../base/common/lifecycle.js';
import { localize } from '../../../../nls.js';
import { ICodeEditor, IViewZone } from '../../../../editor/browser/editorBrowser.js';
import { EditorOption } from '../../../../editor/common/config/editorOptions.js';
import { Position } from '../../../../editor/common/core/position.js';
import { Range } from '../../../../editor/common/core/range.js';
import { IEditorContribution, IEditorDecorationsCollection } from '../../../../editor/common/editorCommon.js';
import { IModelDeltaDecoration } from '../../../../editor/common/model.js';
import { IContextKey, IContextKeyService, RawContextKey } from '../../../../platform/contextkey/common/contextkey.js';
import { EOF_MARKER, IConsoleChunk, ISNCConsoleService, eofMarkerLine, sourceFileForStdinUri } from '../common/sncConsole.js';

/**
 * True while the editor in focus is a stdin document, so Ctrl-D can mean
 * end-of-input there without disturbing it anywhere else.
 */
export const CONTEXT_IN_SNC_CONSOLE = new RawContextKey<boolean>('inSNCConsole', false);

/** Zones are keyed by the line they hang under; 0 means "above line 1". */
interface IOutputZone {
	id: string;
	zone: IViewZone;
	node: HTMLElement;
	/** What the zone currently renders, so an unchanged zone is left alone. */
	key: string;
}

/**
 * The program's console, as a contribution on the stdin document's ordinary
 * editor: the run's stdout/stderr rendered in view zones between the lines the
 * program read. Structurally this is a second Sculpt-n-Code editor — editing a
 * line reruns the program and the zones update, exactly as editing source does.
 *
 * It is registered against every editor and does nothing in almost all of them;
 * `sourceFileForStdinUri` is what tells a console apart from any other file.
 */
export class SNCConsoleEditorContribution extends Disposable implements IEditorContribution {

	static readonly ID = 'editor.contrib.sncConsole';

	/** Source file whose transcript this editor shows, empty if it isn't a console. */
	private filePath: string = '';
	private readonly modelBinding = this._register(new DisposableStore());
	private readonly inConsole: IContextKey<boolean>;

	private decorations: IEditorDecorationsCollection;
	private zones = new Map<number, IOutputZone>();

	constructor(
		private readonly editor: ICodeEditor,
		@IContextKeyService contextKeyService: IContextKeyService,
		@ISNCConsoleService private readonly consoleService: ISNCConsoleService,
	) {
		super();
		this.inConsole = CONTEXT_IN_SNC_CONSOLE.bindTo(contextKeyService);
		this.decorations = this.editor.createDecorationsCollection();

		this._register(this.editor.onDidChangeModel(() => this.bindToModel()));
		this._register(this.consoleService.onDidChangeTranscript(filePath => {
			if (filePath === this.filePath) {
				this.renderTranscript();
			}
		}));
		this.bindToModel();
	}

	/** The console this editor is showing, if the caller wants to act on it. */
	static get(editor: ICodeEditor): SNCConsoleEditorContribution | null {
		return editor.getContribution<SNCConsoleEditorContribution>(SNCConsoleEditorContribution.ID);
	}

	get isConsole(): boolean {
		return !!this.filePath;
	}

	private bindToModel(): void {
		this.modelBinding.clear();
		this.clearZones();
		this.decorations.clear();

		const model = this.editor.getModel();
		this.filePath = (model && sourceFileForStdinUri(model.uri)) || '';
		this.inConsole.set(this.isConsole);
		if (!this.isConsole || !model) {
			return;
		}

		this.modelBinding.add(model.onDidChangeContent(() => this.renderDecorations()));
		// Zones added while the editor is still swapping its view over to the new
		// model are attached to the view being torn down: the node lands in the
		// DOM and is never positioned. Render once that has settled instead.
		this.modelBinding.add(this.editor.onDidLayoutChange(() => this.relayoutZones()));

		// Clicks are caught by one delegated listener rather than one per zone:
		// zones are rebuilt on every rerun and per-zone listeners would pile up.
		const domNode = this.editor.getDomNode();
		if (domNode) {
			this.modelBinding.add(dom.addDisposableListener(domNode, dom.EventType.CLICK, e => {
				if ((e.target as HTMLElement).classList?.contains('snc-console-hint')) {
					this.insertEofMarker();
				}
			}));
		}

		this.scheduleRender();
	}

	/**
	 * Draw on a later turn than the event that asked for it. `onDidChangeModel`
	 * fires while the editor is mid-swap between views, and a zone added at that
	 * moment belongs to the view being discarded — it ends up in the DOM but
	 * unpositioned, which looks exactly like output that never arrived.
	 */
	private scheduleRender(): void {
		const domNode = this.editor.getDomNode();
		if (!domNode) {
			return;
		}
		this.modelBinding.add(dom.scheduleAtNextAnimationFrame(dom.getWindow(domNode), () => {
			if (!this._store.isDisposed) {
				this.renderTranscript();
			}
		}));
	}

	// -- rendering -----------------------------------------------------------

	/**
	 * Line a chunk hangs under: the number of newlines in the stdin the program
	 * had consumed when it wrote the chunk. Offset 0 puts it above line 1.
	 */
	private lineForOffset(text: string, offset: number): number {
		let lines = 0;
		for (let i = 0; i < offset && i < text.length; i++) {
			if (text.charCodeAt(i) === 10 /* \n */) {
				lines++;
			}
		}
		return lines;
	}

	private renderTranscript(): void {
		const model = this.editor.getModel();
		if (!model || !this.isConsole) {
			return;
		}
		const transcript = this.consoleService.transcriptFor(this.filePath);
		const text = model.getValue();

		// Group the run's chunks by the line they belong under, keeping order.
		const byLine = new Map<number, IConsoleChunk[]>();
		for (const chunk of transcript.chunks) {
			const line = this.lineForOffset(text, chunk.stdinOffset);
			const group = byLine.get(line);
			if (group) {
				group.push(chunk);
			} else {
				byLine.set(line, [chunk]);
			}
		}

		// `sys.stdin.read()` and `for line in sys.stdin:` can't finish until the
		// stream ends, and nothing else in the UI would tell the user that. The
		// hint appears exactly when it's needed, at the point execution stopped.
		const hintLine = transcript.awaitingKind === 'eof'
			? this.lineForOffset(text, transcript.stdinConsumed)
			: undefined;
		if (hintLine !== undefined && !byLine.has(hintLine)) {
			byLine.set(hintLine, []);
		}

		// Anchor on the cursor's position in the viewport: zone heights above it
		// change on every rerun, and without this the line being typed on jumps.
		//
		// Only once the user has actually scrolled, though. At the top there is
		// no position to preserve, and anchoring there is actively wrong: the
		// first zone usually goes *above* line 1, so holding line 1 still would
		// scroll that zone straight off the top of the viewport.
		const scrollTop = this.editor.getScrollTop();
		const cursorLine = this.editor.getPosition()?.lineNumber ?? 1;
		const cursorOffsetInViewport = this.editor.getTopForLineNumber(cursorLine) - scrollTop;

		this.editor.changeViewZones(accessor => {
			for (const [line, zone] of this.zones) {
				if (!byLine.has(line)) {
					accessor.removeZone(zone.id);
					this.zones.delete(line);
				}
			}
			for (const [line, chunks] of byLine) {
				const hint = line === hintLine;
				const key = `${hint ? 'eof-hint ' : ''}${chunks.map(c => `${c.stream}:${c.text}`).join(' ')}`;
				const existing = this.zones.get(line);
				if (existing) {
					if (existing.key !== key) {
						// Updated in place rather than torn down and rebuilt, so
						// a rerun that only changes text doesn't flash.
						this.fillZoneNode(existing.node, chunks, hint);
						existing.key = key;
						existing.zone.heightInPx = this.measure(chunks, hint);
						accessor.layoutZone(existing.id);
					}
					continue;
				}
				const node = dom.$('.snc-console-output');
				this.fillZoneNode(node, chunks, hint);
				const zone: IViewZone = {
					afterLineNumber: line,
					domNode: node,
					heightInPx: this.measure(chunks, hint),
					suppressMouseDown: false,
				};
				this.zones.set(line, { id: accessor.addZone(zone), zone, node, key });
			}
		});

		if (scrollTop > 0) {
			const restored = this.editor.getTopForLineNumber(cursorLine) - cursorOffsetInViewport;
			this.editor.setScrollTop(Math.max(0, restored));
		}

		this.renderDecorations();
		this.measureZonesAfterLayout();
	}

	private fillZoneNode(node: HTMLElement, chunks: readonly IConsoleChunk[], eofHint: boolean): void {
		dom.clearNode(node);
		for (const chunk of chunks) {
			const span = dom.$(chunk.stream === 'stderr' ? 'span.snc-console-stderr' : 'span.snc-console-stdout');
			span.textContent = chunk.text;
			node.appendChild(span);
		}
		if (eofHint) {
			const hint = dom.$('a.snc-console-hint');
			hint.textContent = localize('sncConsoleEofHint', "Reading until end of input — click or press Ctrl+D to end it");
			node.appendChild(hint);
		}
	}

	/** Exact whenever nothing wraps; `measureZonesAfterLayout` fixes it up when it does. */
	private measure(chunks: readonly IConsoleChunk[], eofHint: boolean): number {
		const lineHeight = this.editor.getOption(EditorOption.lineHeight);
		const text = chunks.map(c => c.text).join('');
		const newlines = text.split('\n').length - (text.endsWith('\n') ? 1 : 0);
		return (Math.max(chunks.length ? 1 : 0, newlines) + (eofHint ? 1 : 0)) * lineHeight;
	}

	/**
	 * Correct zone heights once the DOM has laid out. Word-wrapped output is
	 * taller than its newline count suggests, and only the browser knows by
	 * how much.
	 */
	private measureZonesAfterLayout(): void {
		const domNode = this.editor.getDomNode();
		if (!domNode) {
			return;
		}
		dom.scheduleAtNextAnimationFrame(dom.getWindow(domNode), () => {
			if (this._store.isDisposed || !this.editor.getModel()) {
				return;
			}
			// One pass only. The node's height doesn't depend on the zone's, so
			// there is nothing for a second pass to discover -- and it would loop.
			this.editor.changeViewZones(accessor => {
				for (const zone of this.zones.values()) {
					const measured = zone.node.scrollHeight;
					if (measured > 0 && measured !== zone.zone.heightInPx) {
						zone.zone.heightInPx = measured;
						accessor.layoutZone(zone.id);
					}
				}
			});
		});
	}

	/**
	 * Dim what the program never read, and mark the end-of-stream line so it
	 * reads as a marker rather than as input.
	 */
	private renderDecorations(): void {
		const model = this.editor.getModel();
		if (!model || !this.isConsole) {
			return;
		}
		const text = model.getValue();
		const transcript = this.consoleService.transcriptFor(this.filePath);
		const decorations: IModelDeltaDecoration[] = [];

		const consumedLine = this.lineForOffset(text, transcript.stdinConsumed);
		for (let line = consumedLine + 1; line <= model.getLineCount(); line++) {
			decorations.push({
				range: new Range(line, 1, line, model.getLineMaxColumn(line)),
				options: { description: 'snc-console-unread', inlineClassName: 'snc-console-unread' }
			});
		}

		const marker = eofMarkerLine(text);
		if (marker !== undefined && marker <= model.getLineCount()) {
			decorations.push({
				range: new Range(marker, 1, marker, model.getLineMaxColumn(marker)),
				options: { description: 'snc-console-eof', inlineClassName: 'snc-console-eof' }
			});
		}

		this.decorations.set(decorations);
	}

	/**
	 * Re-assert every zone's height. A zone whose height was never applied — one
	 * added against a view that was about to be replaced — is indistinguishable
	 * from a correct one until the editor lays out again, so take that chance.
	 */
	private relayoutZones(): void {
		if (this.zones.size === 0) {
			return;
		}
		this.editor.changeViewZones(accessor => {
			for (const zone of this.zones.values()) {
				accessor.layoutZone(zone.id);
			}
		});
		this.measureZonesAfterLayout();
	}

	private clearZones(): void {
		if (this.zones.size === 0) {
			return;
		}
		this.editor.changeViewZones(accessor => {
			for (const zone of this.zones.values()) {
				accessor.removeZone(zone.id);
			}
		});
		this.zones.clear();
	}

	// -- actions -------------------------------------------------------------

	/** Ctrl-D: end the stream here. */
	insertEofMarker(): void {
		const model = this.editor.getModel();
		if (!model || !this.isConsole) {
			return;
		}
		const position = this.editor.getPosition() ?? new Position(model.getLineCount(), 1);
		const atLineStart = position.column === 1;
		const text = `${atLineStart ? '' : '\n'}${EOF_MARKER}\n`;
		this.editor.executeEdits('snc-console-eof', [{
			range: Range.fromPositions(position),
			text,
			forceMoveMarkers: true
		}]);
		this.editor.focus();
	}

	/** Throw the session away and start over from the program's first prompt. */
	clearSession(): void {
		if (this.isConsole) {
			this.consoleService.clear(this.filePath);
		}
	}

	override dispose(): void {
		// No `clearZones` here: the zones belong to an editor that is going away
		// with them, and reaching into it mid-teardown is what breaks.
		this.zones.clear();
		super.dispose();
	}
}
