/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/sncConsole.css';
import * as dom from '../../../../base/browser/dom.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { DisposableStore } from '../../../../base/common/lifecycle.js';
import { Schemas } from '../../../../base/common/network.js';
import { localize, localize2 } from '../../../../nls.js';
import { ICodeEditor, IViewZone } from '../../../../editor/browser/editorBrowser.js';
import { CodeEditorWidget } from '../../../../editor/browser/widget/codeEditor/codeEditorWidget.js';
import { EditorOption, IEditorOptions } from '../../../../editor/common/config/editorOptions.js';
import { Position } from '../../../../editor/common/core/position.js';
import { Range } from '../../../../editor/common/core/range.js';
import { IModelDeltaDecoration } from '../../../../editor/common/model.js';
import { IEditorDecorationsCollection } from '../../../../editor/common/editorCommon.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { IContextKeyService, RawContextKey } from '../../../../platform/contextkey/common/contextkey.js';
import { IContextMenuService } from '../../../../platform/contextview/browser/contextView.js';
import { IHoverService } from '../../../../platform/hover/browser/hover.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { IKeybindingService } from '../../../../platform/keybinding/common/keybinding.js';
import { IOpenerService } from '../../../../platform/opener/common/opener.js';
import { registerIcon } from '../../../../platform/theme/common/iconRegistry.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { IViewPaneOptions, ViewPane } from '../../../browser/parts/views/viewPane.js';
import { IViewDescriptorService } from '../../../common/views.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { EOF_MARKER, IConsoleChunk, ISNCConsoleService, eofMarkerLine } from '../common/sncConsole.js';

export const SNC_CONSOLE_VIEW_ID = 'workbench.panel.sncConsole';

/** True while focus is inside the console's editor, so Ctrl-D can be rebound there. */
export const CONTEXT_IN_SNC_CONSOLE = new RawContextKey<boolean>('inSNCConsole', false);

export const sncConsoleViewIcon = registerIcon('snc-console-view-icon', Codicon.terminal,
	localize('sncConsoleViewIcon', 'View icon of the Sculpt-n-Code console.'));

export const SNC_CONSOLE_TITLE = localize2('sncConsole', "Console");

/** Zones are keyed by the line they hang under; 0 means "above line 1". */
interface IOutputZone {
	id: string;
	zone: IViewZone;
	node: HTMLElement;
	/** What the zone currently renders, so an unchanged zone is left alone. */
	key: string;
}

/**
 * The program's console: the stdin document as an ordinary editable text
 * editor, with the run's stdout/stderr rendered in view zones between its
 * lines. Structurally this is a second Sculpt-n-Code editor — editing a line
 * reruns the program and the zones update, exactly as editing source does.
 */
export class SNCConsoleViewPane extends ViewPane {

	private editor!: CodeEditorWidget;
	private editorContainer!: HTMLElement;
	private decorations!: IEditorDecorationsCollection;

	/** Source file the console is currently bound to. */
	private filePath: string = '';
	private readonly modelBinding = this._register(new DisposableStore());

	private zones = new Map<number, IOutputZone>();

	constructor(
		options: IViewPaneOptions,
		@IKeybindingService keybindingService: IKeybindingService,
		@IContextMenuService contextMenuService: IContextMenuService,
		@IConfigurationService configurationService: IConfigurationService,
		@IContextKeyService contextKeyService: IContextKeyService,
		@IViewDescriptorService viewDescriptorService: IViewDescriptorService,
		@IInstantiationService instantiationService: IInstantiationService,
		@IOpenerService openerService: IOpenerService,
		@IThemeService themeService: IThemeService,
		@IHoverService hoverService: IHoverService,
		@IEditorService private readonly editorService: IEditorService,
		@ISNCConsoleService private readonly consoleService: ISNCConsoleService,
	) {
		super(options, keybindingService, contextMenuService, configurationService, contextKeyService,
			viewDescriptorService, instantiationService, openerService, themeService, hoverService);

		this._register(this.editorService.onDidActiveEditorChange(() => this.bindToActiveFile()));
		this._register(this.consoleService.onDidChangeTranscript(filePath => {
			if (filePath === this.filePath) {
				this.renderTranscript();
			}
		}));
	}

	protected override renderBody(container: HTMLElement): void {
		super.renderBody(container);
		container.classList.add('snc-console');
		this.editorContainer = dom.append(container, dom.$('.snc-console-editor'));

		this.editor = this._register(this.instantiationService.createInstance(
			CodeEditorWidget,
			this.editorContainer,
			this.editorOptions(),
			// No contributions: this is a plain input surface, and the code
			// editor's usual machinery (suggest, format, folding) has nothing to
			// offer a terminal transcript.
			{ isSimpleWidget: true, contributions: [] }
		));
		this.decorations = this.editor.createDecorationsCollection();

		this._register(dom.addDisposableListener(this.editorContainer, dom.EventType.CLICK, e => {
			if ((e.target as HTMLElement).classList?.contains('snc-console-hint')) {
				this.insertEofMarker();
			}
		}));

		const inConsole = CONTEXT_IN_SNC_CONSOLE.bindTo(this.editor.contextKeyService);
		this._register(this.editor.onDidFocusEditorText(() => inConsole.set(true)));
		this._register(this.editor.onDidBlurEditorText(() => inConsole.set(false)));

		this.bindToActiveFile();
	}

	private editorOptions(): IEditorOptions {
		return {
			// A terminal session, not code: no gutter furniture, and long output
			// wraps rather than running off the side.
			lineNumbers: 'off',
			glyphMargin: false,
			folding: false,
			minimap: { enabled: false },
			wordWrap: 'on',
			lineDecorationsWidth: 0,
			lineNumbersMinChars: 0,
			renderLineHighlight: 'none',
			scrollBeyondLastLine: false,
			overviewRulerLanes: 0,
			hideCursorInOverviewRuler: true,
			scrollbar: { alwaysConsumeMouseWheel: false },
			automaticLayout: false,
			fontFamily: 'var(--monaco-monospace-font)',
		};
	}

	protected override layoutBody(height: number, width: number): void {
		super.layoutBody(height, width);
		this.editorContainer.style.height = `${height}px`;
		this.editor?.layout({ height, width });
	}

	override focus(): void {
		super.focus();
		this.editor?.focus();
	}

	// -- binding -------------------------------------------------------------

	/** Which Python file the console follows: whichever one is in front. */
	private activeFilePath(): string {
		const resource = this.editorService.activeEditor?.resource;
		return resource?.scheme === Schemas.file && resource.path.endsWith('.py') ? resource.fsPath : '';
	}

	private async bindToActiveFile(): Promise<void> {
		if (!this.editor) {
			return;
		}
		const filePath = this.activeFilePath();
		// An unsaved buffer, or a non-Python tab: keep showing the last file's
		// session rather than blanking out as the user glances at another tab.
		if (!filePath || filePath === this.filePath) {
			return;
		}

		this.filePath = filePath;
		this.modelBinding.clear();
		const model = await this.consoleService.stdinModel(filePath);
		if (this.filePath !== filePath || this._store.isDisposed) {
			return; // The user moved on while we were loading.
		}
		this.editor.setModel(model);
		this.modelBinding.add(model.onDidChangeContent(() => this.renderDecorations()));
		this.renderTranscript();
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
		const model = this.editor?.getModel();
		if (!model || !this.filePath) {
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
		const cursorLine = this.editor.getPosition()?.lineNumber ?? 1;
		const cursorOffsetInViewport = this.editor.getTopForLineNumber(cursorLine) - this.editor.getScrollTop();

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

		const restored = this.editor.getTopForLineNumber(cursorLine) - cursorOffsetInViewport;
		this.editor.setScrollTop(Math.max(0, restored));

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
			// Clicks are caught by one delegated listener on the container: zones
			// are rebuilt on every rerun, and a listener per zone would pile up.
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
		dom.scheduleAtNextAnimationFrame(dom.getWindow(this.editorContainer), () => {
			if (this._store.isDisposed || !this.editor?.getModel()) {
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
		const model = this.editor?.getModel();
		if (!model || !this.filePath) {
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

	// -- actions -------------------------------------------------------------

	/** Ctrl-D: end the stream here. */
	insertEofMarker(): void {
		const model = this.editor?.getModel();
		if (!model) {
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
		if (this.filePath) {
			this.consoleService.clear(this.filePath);
		}
	}

	get consoleEditor(): ICodeEditor | undefined {
		return this.editor;
	}
}
