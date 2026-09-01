import { registerEditorContribution, EditorContributionInstantiation, EditorAction, registerEditorAction, ServicesAccessor } from '../../../browser/editorExtensions.js';
import { Disposable, DisposableStore, IDisposable } from '../../../../base/common/lifecycle.js';
import { IEditorContribution, ScrollType } from '../../../common/editorCommon.js';
import { ICodeEditor, IViewZone, IOverlayWidget, IOverlayWidgetPosition, IOverlayWidgetPositionCoordinates, OverlayWidgetPositionPreference, IEditorMouseEvent, MouseTargetType } from '../../../browser/editorBrowser.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { localize } from '../../../../nls.js';
import { IHoverService } from '../../../../platform/hover/browser/hover.js';
import { HoverStyle } from '../../../../base/browser/ui/hover/hover.js';
import { IStorageService, StorageScope, StorageTarget } from '../../../../platform/storage/common/storage.js';
import { Position } from '../../../common/core/position.js';
import { Range } from '../../../common/core/range.js';
import { Selection, SelectionDirection } from '../../../common/core/selection.js';
import { EditorOption } from '../../../common/config/editorOptions.js';
import { IModelContentChangedEvent } from '../../../common/textModelEvents.js';
import { IModelDeltaDecoration, ITextModel, TrackedRangeStickiness } from '../../../common/model.js';
import { ILoopReport, IProcessOptions, IVisualizationItem, LoopPath, NewCodeEdit, SNCCommand, SNCStreamMessage, SNCTimingData, SNC_PY_EXP_MIME, SNC_READ_ONLY_VISUALIZERS_SETTING, UiEvent, UiEventSpec } from '../../../../platform/snc/common/snc.js';
import { IPythonImportInsertion, pythonImportInsertion } from '../../../../platform/snc/common/pythonImports.js';
import { IMainProcessService } from '../../../../platform/ipc/common/mainProcessService.js';
import { IWorkspaceContextService } from '../../../../platform/workspace/common/workspace.js';
import { createTrustedTypesPolicy } from '../../../../base/browser/trustedTypes.js';
import { FileAccess, Schemas } from '../../../../base/common/network.js';
import { IHostService } from '../../../../workbench/services/host/browser/host.js';
import { IEditorService } from '../../../../workbench/services/editor/common/editorService.js';
import { IClipboardService } from '../../../../platform/clipboard/common/clipboardService.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { INotificationService, INotificationHandle, Severity } from '../../../../platform/notification/common/notification.js';
import { ISNCConsoleService } from '../../../../workbench/contrib/snc/common/sncConsole.js';
import * as dom from '../../../../base/browser/dom.js';
import { studyLog, StudyLogCoalescer, truncateForLog, visualizerTypeOf } from '../../../../platform/snc/common/sncStudyLog.js';
import './snc.css';

// 'sncVisualization' is a trusted name defined in src/vs/code/electron-browser/workbench/workbench(-dev).html
const ttPolicy = createTrustedTypesPolicy('sncVisualization', { createHTML: value => value });

/**
 * Normalize an Amadine (AMDN) SVG export so it can be styled from CSS.
 *
 * Amadine bakes color into inline `style="fill:#000000;..."` attributes, which
 * CSS cannot override (short of `!important`). Mirroring the Python icon loader
 * in visualizer_utils.py, this drops the XML prolog/comments and rewrites each
 * `style="k:v;..."` into discrete presentation attributes (`k="v" ...`), which
 * CSS rules *can* override — so `fill: currentColor` in snc.css wins.
 */
function cleanAmadineSvg(raw: string): string {
	return raw
		.replace(/<\?xml[^>]*\?>/g, '')
		.replace(/<!--[\s\S]*?-->/g, '')
		.replace(/\bstyle="([^"]*)"/g, (_match, decls: string) =>
			decls
				.split(';')
				.map(decl => decl.trim())
				.filter(decl => decl.includes(':'))
				.map(decl => {
					const idx = decl.indexOf(':');
					return `${decl.slice(0, idx).trim()}="${decl.slice(idx + 1).trim()}"`;
				})
				.join(' ')
		)
		.trim();
}

// The link-chain icon is loaded from two_chain_links.svg on disk (copied to
// out/ by the build; see the resource glob in build/gulpfile.vscode.js for
// production packaging). It's fetched once, cleaned so CSS controls its `fill`,
// and cached. `chainSvgMarkup` is populated asynchronously; setLinkChain fills
// any icon created before the load resolves.
const CHAIN_SVG_URI = FileAccess.asBrowserUri('vs/editor/contrib/snc/browser/two_chain_links.svg');
let chainSvgMarkup: string | null = null;
let chainSvgLoad: Promise<string> | null = null;
function loadChainSvg(): Promise<string> {
	if (!chainSvgLoad) {
		chainSvgLoad = fetch(CHAIN_SVG_URI.toString(true))
			.then(response => response.text())
			.then(raw => (chainSvgMarkup = cleanAmadineSvg(raw)))
			.catch(() => (chainSvgMarkup = ''));
	}
	return chainSvgLoad;
}
// Warm the cache at module load so the icon is ready by first render.
loadChainSvg();


/**
 * A dropdown panel reparented out of the widget so it can be a fixed overlay.
 */
interface IHoistedDropdown {
	readonly panel: HTMLElement;
	/** The `.snc-dropdown-trigger` the panel was nested in. */
	readonly trigger: HTMLElement;
	/** The box the panel is placed against; see `resolveMeasureTarget`. */
	readonly measureTarget: HTMLElement;
	readonly align: string;
	/** Scroll containers whose movement invalidates the panel's position. */
	readonly scrollers: HTMLElement[];
	/**
	 * An ancestor that already hides itself when the trigger scrolls out of
	 * view (a hoisted segment-label anchor). When set, the panel follows its
	 * visibility instead of running its own scrollport test.
	 */
	readonly visibilityHost: HTMLElement | null;
}

/**
 * Widget that displays visualization data for a specific line of code.
 */
/**
 * A compact, log-friendly description of the DOM element a pointer event
 * landed on: tag, a few classes, and the SNC attributes that give it meaning
 * (its action expression, the py-exps it offers, its Python event strings).
 */
function describeEventTarget(node: Node | null, root: Element): unknown {
	try {
		const el = node instanceof Element ? node : node?.parentElement;
		if (!el) { return undefined; }
		const attrs: Record<string, string> = {};
		for (const name of ['data-action-expr', 'snc-py-exps', 'snc-idx', 'snc-mouse-down', 'snc-resize-col', 'snc-mouse-up', 'snc-mouse-move', 'snc-notify-mouse-is-up', 'snc-hover-moves', 'snc-key-down', 'snc-input', 'snc-idx-start', 'snc-unfocused-clickable', 'snc-add-at-cursor', 'data-tooltip', 'title']) {
			const v = el.getAttribute(name);
			if (v !== null) { attrs[name] = v.length > 300 ? v.slice(0, 300) + '…' : v; }
		}
		const actionEl = el.closest('[data-action-expr]');
		const pyExpEl = el.closest('[snc-py-exps]');
		let depth = 0;
		for (let n: Element | null = el; n && n !== root; n = n.parentElement) { depth++; }
		return {
			tag: el.tagName.toLowerCase(),
			classes: typeof el.className === 'string' ? el.className.split(/\s+/).filter(Boolean).slice(0, 6) : [],
			text: (el.textContent ?? '').slice(0, 60),
			depth,
			attrs,
			actionExpr: actionEl && actionEl !== el ? actionEl.getAttribute('data-action-expr')?.slice(0, 300) : undefined,
			pyExps: pyExpEl && pyExpEl !== el ? pyExpEl.getAttribute('snc-py-exps')?.slice(0, 300) : undefined,
		};
	} catch {
		return undefined;
	}
}

class VisualizationWidget extends Disposable implements IOverlayWidget {
	private static readonly BLOCK_LAYOUT_THRESHOLD_PX = 150;
	private static readonly MIN_AVAILABLE_WIDTH_PX = 200;
	private readonly editor: ICodeEditor;
	private readonly domNode: HTMLElement;
	private position: Position | null = null;
	private lastOnscreenPixelPosition: IOverlayWidgetPositionCoordinates | null = null;
	/** Room left at the end of the line for a loop slider ahead of this widget. */
	leftInset = 0;
	private readonly visIndex: number;
	private readonly lineNumber: number;
	private readonly onPointerEvent: (pythonEventStr: string, ev: MouseEvent, overrideRect?: DOMRect) => void;
	private readonly onKeyboardEvent: (pythonEventStr: string, ev: KeyboardEvent) => void;
	private readonly onInputEvent: (pythonEventStr: string, value: string) => void;
	// Invoked when the user clicks the "+" button in an expression tooltip to
	// assign that expression to a new variable on the line below.
	private readonly onInsertNewVar: (expression: string, imports?: readonly string[]) => void;
	// Returns true when this widget's line is currently the focused line and
	// thus rendered full-size. When false, the widget is in small mode and
	// the first mousedown is intercepted as an "expand" request instead of
	// being dispatched as a Python event.
	private readonly isFocused: () => boolean;
	// Whether visualizers are read-only (clickacode.readOnlyVisualizers). Python
	// already renders without the code-writing affordances; this is the
	// widget's own refusal, for anything that slips through -- a drag, an
	// action tooltip, a "+", the link chain -- and for the attributes it strips
	// off the HTML it is handed (see updateContent).
	private readonly isReadOnly: () => boolean;
	private readonly onExpandRequest: () => void;
	// Invoked when the user clicks the link-chain icon in the widget's lower-left
	// corner (unlink when currently linked, relink otherwise).
	private readonly onLinkChainClick: () => void;
	// Persistent chain-icon chrome (lower-left). Recreated content in
	// updateContent wipes domNode.innerHTML, so this is re-appended each render.
	private linkChainEl: HTMLElement | null = null;
	private moveThrottleTimer: any = null;
	private readonly moveThrottleDelay = 16;
	// Where the pointer last was with a button held. A modifier pressed or
	// released while the pointer is stationary produces no mousemove of its
	// own, so the window key listeners below replay this position as a
	// synthetic move carrying the new modifier state (Python re-resolves the
	// selection type live from the modifiers on dragged moves).
	private lastDragPointer: { x: number; y: number; buttons: number } | null = null;
	private lastRenderedHtml: string | null = null;
	private focusRestoreVersion = 0;
	// Values the user has typed into an snc-input box that Python hasn't
	// echoed back yet, oldest first, keyed by the box's snc-input attribute
	// (stable across renders, unlike the element). Typing is local and
	// instant; Python's answer is a whole program run later. A render whose
	// value= is one of these *older* values is Python catching up, not
	// Python changing its mind, and must not overwrite what's in the DOM --
	// see keepNewerTypedValue.
	private pendingTypedValues: { key: string; values: string[] } | null = null;
	// Dropdown panels reparented to the editor container so they escape the
	// widget's overflow. More than one can be open at once (e.g. a column's ▾
	// menu alongside the column-name input's suggestion list).
	private hoistedDropdowns: IHoistedDropdown[] = [];
	private hoistedDropdownListeners: IDisposable[] = [];
	// Segment-label anchors reparented to the widget root (out of the
	// scrollable .string-visualizer that would otherwise clip them). Each entry
	// remembers the scroll container and the anchor's char position (relative to
	// the widget) captured at the scroll offset `baseScrollLeft/Top`, so the
	// label can be re-glued to its character / hidden as the container scrolls.
	private hoistedSegmentLabels: {
		anchor: HTMLElement;
		scroller: HTMLElement;
		baseLeft: number;
		baseTop: number;
		baseScrollLeft: number;
		baseScrollTop: number;
		// What decides whether the anchor has scrolled away, when the anchor's own
		// position doesn't. A segment label sits on its character, so it answers
		// for itself; a hoisted toolbar hangs BELOW the thing it belongs to, off
		// the bottom of the scroller by design, so the visualizer it was lifted out
		// of answers instead. Left unset, the anchor answers.
		clipTarget?: HTMLElement;
	}[] = [];
	private hoistedSegmentLabelListeners: IDisposable[] = [];
	private useBlockLayout = false;
	private readonly clipboardService: IClipboardService;
	private pyExpTooltip: HTMLElement | null = null;
	private pyExpTooltipBridge: HTMLElement | null = null;
	private pyExpTooltipTimer: any = null;
	private pyExpTooltipHideTimer: any = null;
	private pyExpCurrentTarget: Element | null = null;
	private pyExpTooltipDragInProgress = false;
	private lastMouseDownTarget: Node | null = null;
	// A press on a draggable handle in a non-focused visualizer, held rather
	// than acted on: acting pins focus, and the re-render that follows would
	// take the handle out from under the drag that was about to start. Read on
	// mouseup, where a press that never became a drag is the click it was.
	private unfocusedDragPress: MouseEvent | null = null;
	private actionTooltip: HTMLElement | null = null;
	private actionTooltipBridge: HTMLElement | null = null;
	private actionTooltipTimer: any = null;
	private actionTooltipHideTimer: any = null;
	private actionTooltipTarget: Element | null = null;
	private simpleTooltip: HTMLElement | null = null;
	private simpleTooltipTimer: any = null;
	private simpleTooltipHideTimer: any = null;
	private simpleTooltipTarget: Element | null = null;
	private hoverMenu: HTMLElement | null = null;
	private hoverMenuTrigger: Element | null = null;
	private hoverMenuHideTimer: any = null;
	private hoverMenuListeners: IDisposable[] = [];
	private hoistedHover: HTMLElement | null = null;
	private hoistedHoverHost: Element | null = null;
	private hoistedHoverHideTimer: any = null;
	private hoistedHoverListeners: IDisposable[] = [];
	private hoistedHoverDragging = false;
	private hoveredPickRegionId: string | null = null;
	private hoveredPickRegionSlices: HTMLElement[] = [];

	// How long the pointer must rest on an [snc-dwell] element before its event
	// is sent. Long enough that crossing a menu on the way somewhere else opens
	// nothing, short enough to feel like the menu is following the pointer.
	private static readonly DWELL_MS = 150;

	// How long the mouse must rest on a snc-py-exps handle before its expression
	// tooltip appears.
	private static readonly PY_EXP_TOOLTIP_SHOW_DELAY_MS = 100;

	// How long the mouse must rest on an action button or a data-tooltip element
	// before its tooltip appears.
	private static readonly TOOLTIP_SHOW_DELAY_MS = 300;

	// How far a dropdown panel hangs off its trigger - the same distance a
	// tooltip sits off the thing it belongs to. The gap itself is the panel's
	// margin-top in CSS; this copy is for the flip above a trigger, which has
	// to undo that margin before it can put the gap on the other side.
	private static readonly MENU_GAP = 4;

	private dwellTimer: any = null;
	private dwellTarget: Element | null = null;
	constructor(editor: ICodeEditor, lineNumber: number, visIndex: number, onPointerEvent: (pythonEventStr: string, ev: MouseEvent, overrideRect?: DOMRect) => void, onKeyboardEvent: (pythonEventStr: string, ev: KeyboardEvent) => void, onInputEvent: (pythonEventStr: string, value: string) => void, isFocused: () => boolean, isReadOnly: () => boolean, onExpandRequest: () => void, onInsertNewVar: (expression: string, imports?: readonly string[]) => void, onLinkChainClick: () => void, clipboardService: IClipboardService) {
		super();
		this.editor = editor;
		this.position = new Position(lineNumber, 1);
		this.visIndex = visIndex;
		this.lineNumber = lineNumber;
		this.onPointerEvent = onPointerEvent;
		this.onKeyboardEvent = onKeyboardEvent;
		this.onInputEvent = onInputEvent;
		this.onInsertNewVar = onInsertNewVar;
		this.isFocused = isFocused;
		this.isReadOnly = isReadOnly;
		this.onExpandRequest = onExpandRequest;
		this.onLinkChainClick = onLinkChainClick;
		this.clipboardService = clipboardService;

		// Create the widget DOM node. The line number rides along as a class so a
		// visualizer can be picked out by the line it belongs to (`.snc-line-7`),
		// which is the only handle a UI test has on which visualizer is which -
		// nothing in the HTML the visualizer renders says where it came from. A
		// widget is only ever reused for the line it was made for (a line whose
		// item count changes is rebuilt), so this stays true without maintenance.
		this.domNode = document.createElement('div');
		this.domNode.className = `snc-visualization-widget snc-line-${lineNumber}`;

		// Add custom mouse wheel event handling to actually scroll
		this._register(dom.addDisposableListener(this.domNode, 'wheel', (e: WheelEvent) => {
			let remainingDeltaY = e.deltaY;
			let remainingDeltaX = e.deltaX;
			let consumedAny = false;

			for (const node of e.composedPath()) {
				if (!dom.isHTMLElement(node)) {
					continue;
				}
				if (node !== this.domNode && !this.domNode.contains(node)) {
					continue;
				}

				const oldScrollTop = node.scrollTop;
				const oldScrollLeft = node.scrollLeft;

				if (remainingDeltaY !== 0) {
					node.scrollTop += remainingDeltaY;
					const consumedDeltaY = node.scrollTop - oldScrollTop;
					if (consumedDeltaY !== 0) {
						remainingDeltaY -= consumedDeltaY;
						consumedAny = true;
					}
				}

				if (remainingDeltaX !== 0) {
					node.scrollLeft += remainingDeltaX;
					const consumedDeltaX = node.scrollLeft - oldScrollLeft;
					if (consumedDeltaX !== 0) {
						remainingDeltaX -= consumedDeltaX;
						consumedAny = true;
					}
				}

				if (remainingDeltaY === 0 && remainingDeltaX === 0) {
					break;
				}
			}

			if (consumedAny) {
				e.preventDefault();
				e.stopPropagation();
			}
		}));


		this._register(dom.addDisposableListener(this.domNode, 'mousedown', (ev: MouseEvent) => {
			// A new gesture: seal the previous one's edits into their own undo
			// stop. SNC writes code via raw pushEditOperations, which coalesces
			// into the open undo stack element until a boundary is pushed --
			// without one here, every dragged segment merges into a single
			// Cmd-Z. At-mousedown rather than at-mouseup so a final edit
			// arriving async from Python still lands inside its own gesture.
			this.editor.getModel()?.pushStackElement();
			this.lastMouseDownTarget = ev.target as Node;
			this.lastDragPointer = { x: ev.clientX, y: ev.clientY, buttons: ev.buttons };
			studyLog.log('widget.mousedown', { line: this.lineNumber, visIndex: this.visIndex, focused: this.isFocused(), button: ev.button, detail: ev.detail, x: ev.clientX, y: ev.clientY, altKey: ev.altKey, ctrlKey: ev.ctrlKey, metaKey: ev.metaKey, shiftKey: ev.shiftKey, target: describeEventTarget(ev.target as Node, this.domNode) }, this.editor.getModel()?.uri.toString());
			// A new press, so any held one is spent -- its own mouseup landed
			// somewhere the widget never saw.
			this.unfocusedDragPress = null;
			// Small-mode click-to-expand: intercept the first mousedown so the
			// click pins focus to this line instead of dispatching a Python
			// event. We swallow the event because the small DOM is structurally
			// different from full (e.g. z_object_visualizer's _visualize_small),
			// so the event's target won't exist after the re-run.
			if (!this.isFocused()) {
				// Some controls opt out of click-to-focus so they work in the
				// non-focused (small) preview - e.g. the string visualizer's
				// expand/collapse toggle. Elements marked snc-unfocused-clickable
				// dispatch their Python event directly instead of pinning focus.
				const targetNode = ev.target as Node | null;
				const targetEl = targetNode instanceof Element ? targetNode : (targetNode?.parentElement ?? null);
				if (targetEl && targetEl.closest('[snc-unfocused-clickable]')) {
					// A handle that is dragged as well as clicked (the tiny-len
					// counts on the expand bar) needs the press left alone:
					// preventDefault cancels the browser's drag before it can
					// begin, and dispatching now would pin focus and re-render
					// the handle away mid-press. Its event waits for the mouseup
					// that says no drag happened. A click-only control (the
					// expand toggle, draggable="false") still acts on the press
					// and swallows it.
					if (this.startsDrag(targetEl)) {
						this.unfocusedDragPress = ev;
						return;
					}
					ev.preventDefault();
					ev.stopPropagation();
					this.dispatch_mouse_python_event('snc-mouse-down', ev, true);
					return;
				}
				ev.preventDefault();
				ev.stopPropagation();
				this.onExpandRequest();
				return;
			}
			if (this.handleAddAtCursor(ev)) { return; }
			this.dispatch_mouse_python_event('snc-mouse-down', ev);
		}));
		this._register(dom.addDisposableListener(this.domNode, 'mousemove', (ev: MouseEvent) => {
			if (ev.buttons !== 0) {
				this.lastDragPointer = { x: ev.clientX, y: ev.clientY, buttons: ev.buttons };
			}
			if (this.moveThrottleTimer) { return; }
			this.moveThrottleTimer = setTimeout(() => { this.moveThrottleTimer = null; }, this.moveThrottleDelay);
			this.dispatch_mouse_python_event('snc-mouse-move', ev);
		}));
		this._register(dom.addDisposableListener(this.domNode, 'mouseup', (ev: MouseEvent) => {
			// The press came up where a drag would have taken it away instead
			// (see mousedown), so it was a click after all: send what the press
			// would have sent, from where the press was.
			const press = this.unfocusedDragPress;
			this.unfocusedDragPress = null;
			if (press) {
				this.dispatch_mouse_python_event('snc-mouse-down', press, true);
				return;
			}
			this.dispatch_mouse_python_event('snc-mouse-up', ev);
		}));
		this._register(dom.addDisposableListener(this.domNode, 'mouseout', (ev: MouseEvent) => {
			this.dispatch_mouse_python_event('snc-mouse-out', ev);
		}));
		this._register(dom.addDisposableListener(this.domNode, 'mouseleave', (ev: MouseEvent) => {
			this.dispatch_mouse_python_event('snc-mouse-out', ev);
		}));
		this._register(dom.addDisposableListener(this.domNode, 'keydown', (ev: KeyboardEvent) => {
			// For input/textarea elements, only dispatch certain keys to Python.
			// Other keys should still type normally, but must not bubble to VS Code.
			const target = ev.target as HTMLElement;
			if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA')) {
				const isAllowedKey = ev.key === 'Enter' || ev.key === 'Escape' || ev.key === 'ArrowUp' || ev.key === 'ArrowDown' || ev.key === 'Tab';
				const isMetaCombo = ev.metaKey && (ev.key === 'Backspace' || ev.key === 'r');
				if (!isAllowedKey && !isMetaCombo) {
					ev.stopPropagation();
					return;
				}
			}
			this.dispatch_keyboard_event('snc-key-down', ev);
		}));
		// A modifier pressed or released mid-drag with the pointer stationary
		// produces no mousemove, yet Python resolves the selection type live
		// from the modifiers riding on dragged moves. Replay the last drag
		// position as a synthetic move carrying the new modifier state, so the
		// switch is heard without waiting for the pointer to move. On window,
		// not the widget: mid-drag, keyboard focus can sit anywhere.
		const onModifierChangeDuringDrag = (ev: KeyboardEvent) => {
			if (ev.key !== 'Shift' && ev.key !== 'Alt' && ev.key !== 'Control') { return; }
			if (!this.isFocused() || !this.lastDragPointer) { return; }
			// Present on a visualizer's container only while it believes a
			// drag is in progress.
			if (!this.domNode.querySelector('[snc-notify-mouse-is-up]')) { return; }
			const { x, y, buttons } = this.lastDragPointer;
			const under = this.domNode.ownerDocument.elementFromPoint(x, y);
			// Re-resolved rather than remembered: every Python run rebuilds the
			// DOM, so the element the last real move hit may be gone by now.
			if (!under || !this.domNode.contains(under)) { return; }
			// The throttle exists to thin identical moves; this one IS the
			// change worth sending.
			if (this.moveThrottleTimer) { clearTimeout(this.moveThrottleTimer); this.moveThrottleTimer = null; }
			under.dispatchEvent(new MouseEvent('mousemove', {
				bubbles: true,
				clientX: x,
				clientY: y,
				buttons,
				altKey: ev.altKey, ctrlKey: ev.ctrlKey, metaKey: ev.metaKey, shiftKey: ev.shiftKey,
			}));
		};
		const targetWindow = dom.getWindow(this.editor.getContainerDomNode());
		this._register(dom.addDisposableListener(targetWindow, 'keydown', onModifierChangeDuringDrag, true));
		this._register(dom.addDisposableListener(targetWindow, 'keyup', onModifierChangeDuringDrag, true));
		this._register(dom.addDisposableListener(this.domNode, 'input', (ev: Event) => {
			this.dispatch_input_event('snc-input', ev);
		}));

		for (const d of this.pyExpListeners(this.domNode, this.domNode)) {
			this._register(d);
		}

		// Allow snc-input elements to accept snc-py-exps drops
		this._register(dom.addDisposableListener(this.domNode, 'dragover', (ev: DragEvent) => {
			if (this.isReadOnly()) { return; }
			const input = this.findAncestorWithAttr(ev.target as Node, 'snc-input');
			if (input) {
				ev.preventDefault();
				input.classList.add('snc-drop-target');
				const inputEl = input as HTMLInputElement;
				inputEl.focus();
				const pos = this.getInputCharIndexAtPoint(inputEl, ev.clientX);
				inputEl.setSelectionRange(pos, pos);
			}
		}));
		this._register(dom.addDisposableListener(this.domNode, 'drop', (ev: DragEvent) => {
			if (this.isReadOnly()) { return; }
			const input = this.findAncestorWithAttr(ev.target as Node, 'snc-input');
			if (input && ev.dataTransfer) {
				ev.preventDefault();
				ev.stopPropagation();
				const text = ev.dataTransfer.getData('text/plain');
				const inputEl = input as HTMLInputElement;
				const pos = inputEl.selectionStart ?? inputEl.value.length;
				studyLog.log('widget.drop', { line: this.lineNumber, visIndex: this.visIndex, text, insertAt: pos, previousValue: inputEl.value, target: describeEventTarget(input, this.domNode) }, this.editor.getModel()?.uri.toString());
				inputEl.value = inputEl.value.slice(0, pos) + text + inputEl.value.slice(pos);
				inputEl.selectionStart = inputEl.selectionEnd = pos + text.length;
				input.classList.remove('snc-drop-target');
				inputEl.dispatchEvent(new Event('input', { bubbles: true }));
			}
		}));

		// Tooltip on hover for action buttons with data-action-expr
		this._register(dom.addDisposableListener(this.domNode, 'mouseover', (ev: MouseEvent) => {
			const btn = this.isReadOnly() ? null : this.findAncestorWithAttr(ev.target as Node, 'data-action-expr');
			if (btn && btn.getAttribute('data-action-expr')) {
				clearTimeout(this.actionTooltipHideTimer);
				if (btn !== this.actionTooltipTarget) {
					this.hideActionTooltip();
					this.actionTooltipTarget = btn;
					this.actionTooltipTimer = setTimeout(() => {
						this.showActionTooltip(btn);
					}, VisualizationWidget.TOOLTIP_SHOW_DELAY_MS);
				}
			} else if (this.actionTooltipTarget) {
				this.scheduleActionTooltipHide();
			}
		}));
		this._register(dom.addDisposableListener(this.domNode, 'mouseout', (ev: MouseEvent) => {
			const relatedTarget = ev.relatedTarget as Node | null;
			if (relatedTarget && (this.actionTooltip?.contains(relatedTarget)
				|| this.actionTooltipBridge?.contains(relatedTarget))) {
				return;
			}
			if (relatedTarget && this.findAncestorWithAttr(relatedTarget, 'data-action-expr')) {
				return;
			}
			if (this.actionTooltipTarget) {
				this.actionTooltipTarget = null;
			}
			this.scheduleActionTooltipHide();
		}));

		for (const d of this.simpleTooltipListeners(this.domNode, this.domNode)) {
			this._register(d);
		}

		for (const d of this.dwellListeners(this.domNode, this.domNode,
			(raw, el) => this.wrapWithChildKeys(raw, el.parentElement, this.domNode))) {
			this._register(d);
		}

		// Hover-to-open dropdown menus (data-hover-menu panels inside .snc-dropdown-trigger)
		this._register(dom.addDisposableListener(this.domNode, 'mouseover', (ev: MouseEvent) => {
			const trigger = this.findAncestorWithClass(ev.target as Node, 'snc-dropdown-trigger');
			if (trigger && !trigger.classList.contains('dimmed')) {
				clearTimeout(this.hoverMenuHideTimer);
				if (trigger !== this.hoverMenuTrigger) {
					this.hideHoverMenu();
					this.hoverMenuTrigger = trigger;
					this.showHoverMenu(trigger);
				}
			}
		}));
		this._register(dom.addDisposableListener(this.domNode, 'mouseout', (ev: MouseEvent) => {
			if (!this.hoverMenuTrigger) { return; }
			const relatedTarget = ev.relatedTarget as Node | null;
			if (relatedTarget && this.hoverMenu && this.hoverMenu.contains(relatedTarget)) { return; }
			if (relatedTarget && this.findAncestorWithClass(relatedTarget, 'snc-dropdown-trigger') === this.hoverMenuTrigger) { return; }
			this.scheduleHoverMenuHide();
		}));

		// Controls that live just outside their own cell (a table row's drag
		// handle, over the left edge of the table) and so are clipped away by
		// the scrollport they sit in. One is lifted out at a time, for as long
		// as its host is hovered - see showHoistedHover.
		this._register(dom.addDisposableListener(this.domNode, 'mouseover', (ev: MouseEvent) => {
			const host = this.findAncestorWithAttr(ev.target as Node, 'snc-hoist-host');
			if (!host) { return; }
			clearTimeout(this.hoistedHoverHideTimer);
			if (host !== this.hoistedHoverHost) {
				this.hideHoistedHover();
				this.hoistedHoverHost = host;
				this.showHoistedHover(host as HTMLElement);
			}
		}));
		this._register(dom.addDisposableListener(this.domNode, 'mouseout', (ev: MouseEvent) => {
			if (!this.hoistedHoverHost) { return; }
			const relatedTarget = ev.relatedTarget as Node | null;
			// The lifted control is outside the host, so moving onto it leaves
			// the host: that is the one departure that must not put it away.
			if (relatedTarget && this.hoistedHover?.contains(relatedTarget)) { return; }
			if (relatedTarget && this.findAncestorWithAttr(relatedTarget, 'snc-hoist-host') === this.hoistedHoverHost) { return; }
			this.scheduleHoistedHoverHide();
		}));

		// Group hover for the pick tool's regions. A region spans every row of
		// its band in one column, drawn as one overlay slice per cell (see
		// _render_pick_region in table_visualizer.py), so CSS :hover lights
		// only the slice under the mouse. Mirror the hover onto every slice of
		// the region so the whole click target darkens together.
		this._register(dom.addDisposableListener(this.domNode, 'mouseover', (ev: MouseEvent) => {
			this.setHoveredPickRegion(this.findAncestorWithAttr(ev.target as Node, 'data-pick-region'));
		}));
		this._register(dom.addDisposableListener(this.domNode, 'mouseout', (ev: MouseEvent) => {
			const relatedTarget = ev.relatedTarget as Node | null;
			if (relatedTarget && this.findAncestorWithAttr(relatedTarget, 'data-pick-region')) { return; }
			this.setHoveredPickRegion(null);
		}));

		// Add the widget to the editor
		this.editor.addOverlayWidget(this);
	}

	/**
	 * Move the pick tool's group-hover highlight to *region*'s slices (or
	 * clear it for null). The class does the styling that :hover cannot: it
	 * marks every cell-slice of the hovered region, not just the one under
	 * the mouse.
	 */
	private setHoveredPickRegion(region: Element | null): void {
		const regionId = region?.getAttribute('data-pick-region') ?? null;
		// "Same region" is not enough to skip the work: a re-render (e.g. the
		// click that toggles the region) replaces the marked elements while
		// the pointer sits still, so the class must go back on.
		if (regionId === this.hoveredPickRegionId
			&& (!region || region.classList.contains('hovered'))) { return; }
		for (const slice of this.hoveredPickRegionSlices) {
			slice.classList.remove('hovered');
		}
		this.hoveredPickRegionId = regionId;
		this.hoveredPickRegionSlices = [];
		if (!region || regionId === null) { return; }
		// Scoped to this table: a nested visualizer never draws regions, but
		// two tables in one widget could reuse a region id.
		const table = region.closest('.list-visualizer') ?? this.domNode;
		for (const slice of table.querySelectorAll(`[data-pick-region="${CSS.escape(regionId)}"]`)) {
			slice.classList.add('hovered');
			this.hoveredPickRegionSlices.push(slice as HTMLElement);
		}
	}

	/**
	 * Hover tooltip, highlight and drag for snc-py-exps handles.
	 *
	 * Only activates over the draggable border/padding of the handle, not over
	 * inner content (marked draggable="false"), so a nested visualizer's own
	 * handles keep their hovers.
	 *
	 * Like simpleTooltipListeners, the widget root gets these once at
	 * construction and each hoisted dropdown panel gets its own set: a hoisted
	 * panel no longer sits under the root, so nothing from there reaches the
	 * handles inside it (the column ▾ menu's tally headers, for instance).
	 */
	private pyExpListeners(root: HTMLElement, stopAt: Element): IDisposable[] {
		return [
			dom.addDisposableListener(root, 'dragstart', (ev: DragEvent) => {
				// The press did become a drag, so it is not a click waiting on
				// a mouseup -- which won't come, dragend coming instead.
				this.unfocusedDragPress = null;
				const pyExpEl = this.findAncestorWithAttr(ev.target as Node, 'snc-py-exps', stopAt);
				if (pyExpEl && this.isReadOnly()) {
					// Nothing leaves a read-only visualizer as code.
					ev.preventDefault();
					return;
				}
				if (pyExpEl && ev.dataTransfer) {
					if (this.lastMouseDownTarget) {
						let el: Element | null = this.lastMouseDownTarget instanceof Element
							? this.lastMouseDownTarget
							: this.lastMouseDownTarget.parentElement;
						while (el && el !== pyExpEl) {
							if (el.getAttribute('draggable') === 'false') {
								ev.preventDefault();
								return;
							}
							el = el.parentElement;
						}
					}

					// The first is the primary: what a handle offering several
					// hands over when it is dragged as a whole, the rest being
					// the tooltip's to offer.
					const primary = pyExpsOf(pyExpEl, 'snc-py-exps')[0];
					if (!primary) { return; }
					const expression = primary.expr;
					setPyExpDragData(ev.dataTransfer, expression, primary.imports);
					studyLog.log('widget.dragStart', { line: this.lineNumber, visIndex: this.visIndex, expr: expression, imports: primary.imports, alternatives: pyExpsOf(pyExpEl, 'snc-py-exps').length, target: describeEventTarget(pyExpEl, this.domNode) }, this.editor.getModel()?.uri.toString());
					this.hidePyExpTooltip();

					const dragGhost = document.createElement('div');
					dragGhost.textContent = expression;
					dragGhost.className = 'snc-py-exp-drag-ghost';
					document.body.appendChild(dragGhost);
					ev.dataTransfer.setDragImage(dragGhost, 0, 0);
					setTimeout(() => dragGhost.remove(), 0);
				}
			}),
			dom.addDisposableListener(root, 'mouseover', (ev: MouseEvent) => {
				const pyExpEl = this.isReadOnly() ? null : this.findAncestorWithAttr(ev.target as Node, 'snc-py-exps', stopAt);
				const inDraggableZone = pyExpEl ? this.isInDraggableZone(ev.target as Node, pyExpEl) : false;

				if (inDraggableZone) {
					clearTimeout(this.pyExpTooltipHideTimer);
					if (pyExpEl !== this.pyExpCurrentTarget) {
						if (this.pyExpCurrentTarget) {
							this.pyExpCurrentTarget.classList.remove('snc-py-exp-drag-hover');
						}
						this.pyExpCurrentTarget = pyExpEl!;
						pyExpEl!.classList.add('snc-py-exp-drag-hover');
						clearTimeout(this.pyExpTooltipTimer);
						this.pyExpTooltipTimer = setTimeout(() => {
							this.showPyExpTooltip(pyExpEl!);
						}, VisualizationWidget.PY_EXP_TOOLTIP_SHOW_DELAY_MS);
					}
				} else if (this.pyExpCurrentTarget) {
					this.pyExpCurrentTarget.classList.remove('snc-py-exp-drag-hover');
					this.pyExpCurrentTarget = null;
					this.schedulePyExpTooltipHide();
				}
			}),
			dom.addDisposableListener(root, 'mouseout', (ev: MouseEvent) => {
				const relatedTarget = ev.relatedTarget as Node | null;
				// Don't hide if moving into the tooltip itself, or onto the
				// underlay covering the gap on the way to it.
				if (relatedTarget && (this.pyExpTooltip?.contains(relatedTarget)
					|| this.pyExpTooltipBridge?.contains(relatedTarget))) {
					return;
				}
				// Don't clean up if moving within the same snc-py-exps (mouseover will handle it)
				if (relatedTarget && this.findAncestorWithAttr(relatedTarget, 'snc-py-exps', stopAt)) {
					return;
				}
				if (this.pyExpCurrentTarget) {
					this.pyExpCurrentTarget.classList.remove('snc-py-exp-drag-hover');
					this.pyExpCurrentTarget = null;
				}
				this.schedulePyExpTooltipHide();
			}),
		];
	}

	/**
	 * Simple tooltip on hover for elements with data-tooltip="<text>" (lighter
	 * weight than the action/py-exp tooltips: just text, no copy button, no
	 * draggable expression).
	 *
	 * The widget root gets these once at construction. A hoisted dropdown panel
	 * needs its own set: it no longer sits under the root, so nothing from there
	 * reaches it.
	 */
	private simpleTooltipListeners(root: HTMLElement, stopAt: Element): IDisposable[] {
		return [
			dom.addDisposableListener(root, 'mouseover', (ev: MouseEvent) => {
				const target = this.findAncestorWithAttr(ev.target as Node, 'data-tooltip', stopAt);
				if (target && target.getAttribute('data-tooltip')) {
					clearTimeout(this.simpleTooltipHideTimer);
					if (target !== this.simpleTooltipTarget) {
						this.hideSimpleTooltip();
						this.simpleTooltipTarget = target;
						this.simpleTooltipTimer = setTimeout(() => {
							this.showSimpleTooltip(target);
						}, VisualizationWidget.TOOLTIP_SHOW_DELAY_MS);
					}
				} else if (this.simpleTooltipTarget) {
					this.scheduleSimpleTooltipHide();
				}
			}),
			dom.addDisposableListener(root, 'mouseout', (ev: MouseEvent) => {
				const relatedTarget = ev.relatedTarget as Node | null;
				if (relatedTarget && this.findAncestorWithAttr(relatedTarget, 'data-tooltip', stopAt)) {
					return;
				}
				if (this.simpleTooltipTarget) {
					this.simpleTooltipTarget = null;
				}
				this.scheduleSimpleTooltipHide();
			}),
		];
	}

	/**
	 * Send an element's `snc-dwell` event once the pointer has rested on it.
	 *
	 * What dwelling means is the renderer's to say — the column ▾ menu uses it
	 * to open the submenu a row names, and to put away the open one over a row
	 * that names none — so this only decides when a rest has happened. Python
	 * renders the attribute solely where dwelling would change something, so
	 * every event sent here is one worth the re-run it costs.
	 *
	 * Moving within the same dwell element does not restart the wait: a rest is
	 * the pointer staying on a thing, not staying perfectly still on it.
	 */
	private dwellListeners(root: HTMLElement, stopAt: Element,
		wrapEvent: (raw: string, el: Element) => string): IDisposable[] {
		const cancel = () => {
			clearTimeout(this.dwellTimer);
			this.dwellTimer = null;
			this.dwellTarget = null;
		};
		return [
			dom.addDisposableListener(root, 'mouseover', (ev: MouseEvent) => {
				const target = this.findAncestorWithAttr(ev.target as Node, 'snc-dwell', stopAt);
				if (target === this.dwellTarget) {
					return;
				}
				cancel();
				if (!target) {
					return;
				}
				this.dwellTarget = target;
				this.dwellTimer = setTimeout(() => {
					// The render this armed against is gone if the pointer has
					// since moved on, and its event would be describing a menu
					// that no longer exists.
					if (this.dwellTarget !== target) {
						return;
					}
					cancel();
					this.onPointerEvent(
						wrapEvent(target.getAttribute('snc-dwell') ?? '', target), ev);
				}, VisualizationWidget.DWELL_MS);
			}),
			dom.addDisposableListener(root, 'mouseleave', cancel),
		];
	}

	/**
	 * Walk up from a node to find the nearest ancestor (or itself) with the given attribute.
	 */
	private findAncestorWithAttr(node: Node | null, attr: string, stopAt: Element = this.domNode): Element | null {
		let el: Element | null = node?.nodeType === Node.ELEMENT_NODE ? (node as Element) : (node?.parentElement ?? null);
		while (el && el !== stopAt) {
			if (el.hasAttribute(attr)) {
				return el;
			}
			el = el.parentElement;
		}
		return null;
	}

	private findAncestorWithClass(node: Node | null, className: string): Element | null {
		let el: Element | null = node?.nodeType === Node.ELEMENT_NODE ? (node as Element) : (node?.parentElement ?? null);
		while (el && el !== this.domNode) {
			if (el.classList.contains(className)) {
				return el;
			}
			el = el.parentElement;
		}
		return null;
	}

	/**
	 * Find the character index in an input element closest to a given clientX.
	 */
	private getInputCharIndexAtPoint(inputEl: HTMLInputElement, clientX: number): number {
		const rect = inputEl.getBoundingClientRect();
		const style = getComputedStyle(inputEl);
		const paddingLeft = parseFloat(style.paddingLeft) || 0;
		const x = clientX - rect.left - paddingLeft + inputEl.scrollLeft;

		const canvas = document.createElement('canvas');
		const ctx = canvas.getContext('2d')!;
		ctx.font = style.font;

		const text = inputEl.value;
		for (let i = 0; i <= text.length; i++) {
			const w = ctx.measureText(text.substring(0, i)).width;
			if (w >= x) {
				if (i > 0) {
					const pw = ctx.measureText(text.substring(0, i - 1)).width;
					return (x - pw < w - x) ? i - 1 : i;
				}
				return 0;
			}
		}
		return text.length;
	}

	/**
	 * Build a "+" button for an expression tooltip. Clicking it inserts the
	 * expression as new code on the line below (via onInsertNewVar) and
	 * dismisses the tooltip. An assignable expression is wrapped in a
	 * `<name> = <expr>` assignment; a whole statement (e.g. a visualizer-generated
	 * `for`/`if` snippet) is inserted verbatim without an assignment.
	 */
	private createNewVarButton(expression: string, imports: string[], hideTooltip: () => void): HTMLButtonElement {
		const newVarBtn = document.createElement('button');
		newVarBtn.className = 'snc-copy-btn snc-new-var-btn';
		newVarBtn.textContent = '+';
		newVarBtn.title = isAssignableExpression(expression)
			? 'Assign to a new variable'
			: 'Insert as new code';
		newVarBtn.addEventListener('mousedown', (e) => {
			e.preventDefault();
			e.stopPropagation();
			hideTooltip();
			this.onInsertNewVar(expression, imports);
		});
		return newVarBtn;
	}

	/**
	 * One expression's row in a tooltip: copy it, insert it as new code, or drag
	 * it out. A handle offering several gets one row each, stacked in the order
	 * the visualizer listed them.
	 *
	 * `onDragStart`/`onDragEnd` are how the py-exp tooltip keeps itself alive
	 * across a drag that starts inside it; the action tooltip has nothing to do
	 * there and passes nothing.
	 */
	private pyExpRow(exp: IPyExp, hideTooltip: () => void,
		onDragStart?: () => void, onDragEnd?: () => void): HTMLElement {
		const row = document.createElement('div');
		row.className = 'snc-py-exp-row';

		const copyBtn = document.createElement('button');
		copyBtn.className = 'snc-copy-btn';
		copyBtn.textContent = '\u{29C9}';
		copyBtn.title = 'Copy to clipboard';
		copyBtn.addEventListener('mousedown', (e) => {
			e.preventDefault();
			e.stopPropagation();
			this.clipboardService.writeText(exp.expr);
			studyLog.log('widget.copyExpr', { line: this.lineNumber, visIndex: this.visIndex, expr: exp.expr, imports: exp.imports }, this.editor.getModel()?.uri.toString());
			copyBtn.textContent = '\u2713';
			setTimeout(() => { copyBtn.textContent = '\u{29C9}'; }, 1000);
		});
		row.appendChild(copyBtn);

		row.appendChild(this.createNewVarButton(exp.expr, exp.imports, hideTooltip));

		// What the expression reads as, when the visualizer said: two readings
		// of one thing are often two different values, and the code alone
		// doesn't always say which is which.
		if (exp.label) {
			const labelSpan = document.createElement('span');
			labelSpan.className = 'snc-py-exp-row-label';
			labelSpan.textContent = exp.label;
			row.appendChild(labelSpan);
		}

		const exprSpan = document.createElement('span');
		exprSpan.className = 'snc-py-exp-row-expr';
		exprSpan.textContent = exp.expr;
		exprSpan.draggable = true;
		exprSpan.style.cursor = 'grab';
		exprSpan.addEventListener('dragstart', (e) => {
			if (e.dataTransfer) {
				onDragStart?.();
				setPyExpDragData(e.dataTransfer, exp.expr, exp.imports);

				const dragGhost = document.createElement('div');
				dragGhost.textContent = exp.expr;
				dragGhost.className = 'snc-py-exp-drag-ghost';
				document.body.appendChild(dragGhost);
				e.dataTransfer.setDragImage(dragGhost, 0, 0);
				setTimeout(() => dragGhost.remove(), 0);
			}
		});
		if (onDragEnd) {
			exprSpan.addEventListener('dragend', onDragEnd);
		}
		row.appendChild(exprSpan);
		return row;
	}

	/**
	 * Lay a transparent underlay over the gap between a tooltip and the element
	 * it belongs to, so that reaching for the tooltip reaches nothing else.
	 *
	 * Those few px are over the visualizer, and a mousemove sampled there lands
	 * on whatever is underneath -- a string visualizer character, say, which
	 * reports the hover to Python, re-renders the widget, and takes the tooltip
	 * away mid-reach. Nothing under the gap has anything to offer while the
	 * tooltip is up, so the underlay takes the pointer instead, and counts as
	 * being on the tooltip for the purpose of keeping it up.
	 *
	 * Returns null when the two overlap, there being no gap to cover.
	 */
	private tooltipBridge(tooltip: HTMLElement, target: DOMRect,
		keepAlive: () => void, letGo: () => void): HTMLElement | null {
		const tip = tooltip.getBoundingClientRect();
		// A px into each of the pair it spans, so rounding leaves no seam.
		const OVERLAP = 1;
		// The pointer's path between the two is rarely the straight line
		// between their nearest edges, so the underlay is a little wider than
		// the pair it spans.
		const SLACK = 3;
		const [xMin, xMax] = [Math.min(tip.left, target.left) - SLACK, Math.max(tip.right, target.right) + SLACK];
		const [yMin, yMax] = [Math.min(tip.top, target.top) - SLACK, Math.max(tip.bottom, target.bottom) + SLACK];
		let box: { left: number; top: number; width: number; height: number };
		if (tip.bottom <= target.top) {
			box = { left: xMin, top: tip.bottom - OVERLAP, width: xMax - xMin, height: target.top - tip.bottom + 2 * OVERLAP };
		} else if (tip.top >= target.bottom) {
			box = { left: xMin, top: target.bottom - OVERLAP, width: xMax - xMin, height: tip.top - target.bottom + 2 * OVERLAP };
		} else if (tip.right <= target.left) {
			box = { left: tip.right - OVERLAP, top: yMin, width: target.left - tip.right + 2 * OVERLAP, height: yMax - yMin };
		} else if (tip.left >= target.right) {
			box = { left: target.right - OVERLAP, top: yMin, width: tip.left - target.right + 2 * OVERLAP, height: yMax - yMin };
		} else {
			return null;
		}

		const bridge = document.createElement('div');
		bridge.className = 'snc-tooltip-bridge';
		bridge.style.left = `${box.left}px`;
		bridge.style.top = `${box.top}px`;
		bridge.style.width = `${box.width}px`;
		bridge.style.height = `${box.height}px`;
		bridge.addEventListener('mouseenter', keepAlive);
		bridge.addEventListener('mouseleave', letGo);
		this.editor.getContainerDomNode().appendChild(bridge);
		return bridge;
	}

	/**
	 * Show a tooltip with the handle's Python expressions, a row each, near the
	 * given element.
	 */
	private showPyExpTooltip(target: Element): void {
		// Remove any existing tooltip DOM without clearing highlight/tracking state
		if (this.pyExpTooltip) {
			this.pyExpTooltip.remove();
			this.pyExpTooltip = null;
		}
		if (this.pyExpTooltipBridge) {
			this.pyExpTooltipBridge.remove();
			this.pyExpTooltipBridge = null;
		}

		const exps = pyExpsOf(target, 'snc-py-exps');
		if (!exps.length) { return; }
		studyLog.log('widget.tooltip', { kind: 'pyExp', line: this.lineNumber, visIndex: this.visIndex, exprs: exps.map(e => e.expr), target: describeEventTarget(target, this.domNode) }, this.editor.getModel()?.uri.toString());

		const rect = target.getBoundingClientRect();
		const tooltip = document.createElement('div');
		tooltip.className = 'snc-tooltip snc-py-exp-tooltip';

		for (const exp of exps) {
			tooltip.appendChild(this.pyExpRow(exp, () => this.hidePyExpTooltip(),
				() => {
					this.pyExpTooltipDragInProgress = true;
					clearTimeout(this.pyExpTooltipHideTimer);
					// A drag hit-tests whatever is under the pointer for a drop
					// target, and the underlay is not one: leaving it up would
					// refuse a drop landing in the strip it covers.
					if (this.pyExpTooltipBridge) {
						this.pyExpTooltipBridge.remove();
						this.pyExpTooltipBridge = null;
					}
				},
				() => {
					this.pyExpTooltipDragInProgress = false;
					this.hidePyExpTooltip();
				}));
		}

		// Keep tooltip alive while hovering it (or the underlay bridging the
		// gap to it); also keep hover menu alive
		const keepAlive = () => {
			clearTimeout(this.pyExpTooltipHideTimer);
			clearTimeout(this.hoverMenuHideTimer);
		};
		const letGo = () => {
			this.schedulePyExpTooltipHide();
			if (this.hoverMenu) {
				this.scheduleHoverMenuHide();
			}
		};
		tooltip.addEventListener('mouseenter', keepAlive);
		tooltip.addEventListener('mouseleave', letGo);

		// A handle wrapping the whole visualizer has no free space above it: the
		// widget's top edge is against the line of code it belongs to, so a
		// tooltip there covers either that code or the visualizer above it. Put
		// it beside the widget, where nothing else is drawn.
		const wrapsWholeWidget = target.parentElement === this.domNode;
		const align = target.getAttribute('snc-py-exp-align')
			?? (wrapsWholeWidget ? 'right' : null);

		// Measured rather than assumed a line tall: a handle offering several
		// expressions is as tall as it has rows, and a guess would sit the
		// tooltip on top of the thing it belongs to.
		tooltip.style.visibility = 'hidden';
		this.editor.getContainerDomNode().appendChild(tooltip);
		const tooltipRect = tooltip.getBoundingClientRect();

		if (align === 'right') {
			// Position to the right of the target, vertically centered
			let left = rect.right + 4;
			if (left + tooltipRect.width > window.innerWidth) {
				left = rect.left - tooltipRect.width - 4;
			}
			tooltip.style.left = `${left}px`;
			tooltip.style.top = `${rect.top + (rect.height - tooltipRect.height) / 2}px`;
		} else {
			// Position above the target element, or below it when there's no room
			const above = rect.top - tooltipRect.height - 4;
			tooltip.style.left = `${rect.left}px`;
			tooltip.style.top = `${above < 0 ? rect.bottom + 4 : above}px`;
		}
		tooltip.style.visibility = '';

		this.pyExpTooltip = tooltip;
		this.pyExpTooltipBridge = this.tooltipBridge(tooltip, rect, keepAlive, letGo);
	}

	/**
	 * Schedule hiding the tooltip after a short delay.
	 */
	private schedulePyExpTooltipHide(): void {
		clearTimeout(this.pyExpTooltipTimer);
		clearTimeout(this.pyExpTooltipHideTimer);
		this.pyExpTooltipHideTimer = setTimeout(() => {
			if (this.pyExpTooltipDragInProgress) {
				return;
			}
			this.hidePyExpTooltip();
		}, 200);
	}

	/**
	 * Immediately hide and remove the tooltip, and clear the draggable-zone highlight.
	 */
	private hidePyExpTooltip(): void {
		clearTimeout(this.pyExpTooltipTimer);
		clearTimeout(this.pyExpTooltipHideTimer);
		this.pyExpTooltipDragInProgress = false;
		if (this.pyExpCurrentTarget) {
			this.pyExpCurrentTarget.classList.remove('snc-py-exp-drag-hover');
			this.pyExpCurrentTarget = null;
		}
		if (this.pyExpTooltip) {
			this.pyExpTooltip.remove();
			this.pyExpTooltip = null;
		}
		if (this.pyExpTooltipBridge) {
			this.pyExpTooltipBridge.remove();
			this.pyExpTooltipBridge = null;
		}
	}

	private showActionTooltip(target: Element): void {
		this.hideActionTooltip();

		const exps = pyExpsOf(target, 'data-action-expr');
		if (!exps.length) { return; }
		studyLog.log('widget.tooltip', { kind: 'action', line: this.lineNumber, visIndex: this.visIndex, exprs: exps.map(e => e.expr), target: describeEventTarget(target, this.domNode) }, this.editor.getModel()?.uri.toString());

		const rect = target.getBoundingClientRect();
		const tooltip = document.createElement('div');
		tooltip.className = 'snc-tooltip snc-action-tooltip';

		for (const exp of exps) {
			tooltip.appendChild(this.pyExpRow(exp, () => this.hideActionTooltip()));
		}

		const keepAlive = () => {
			clearTimeout(this.actionTooltipHideTimer);
		};
		const letGo = () => {
			this.scheduleActionTooltipHide();
		};
		tooltip.addEventListener('mouseenter', keepAlive);
		tooltip.addEventListener('mouseleave', letGo);

		tooltip.style.visibility = 'hidden';
		this.editor.getContainerDomNode().appendChild(tooltip);
		const tooltipRect = tooltip.getBoundingClientRect();
		const above = rect.top - tooltipRect.height - 4;
		tooltip.style.left = `${rect.left}px`;
		tooltip.style.top = `${above < 0 ? rect.bottom + 4 : above}px`;
		tooltip.style.visibility = '';

		this.actionTooltip = tooltip;
		this.actionTooltipBridge = this.tooltipBridge(tooltip, rect, keepAlive, letGo);
	}

	private scheduleActionTooltipHide(): void {
		clearTimeout(this.actionTooltipTimer);
		clearTimeout(this.actionTooltipHideTimer);
		this.actionTooltipHideTimer = setTimeout(() => {
			this.hideActionTooltip();
		}, 200);
	}

	private hideActionTooltip(): void {
		clearTimeout(this.actionTooltipTimer);
		clearTimeout(this.actionTooltipHideTimer);
		this.actionTooltipTarget = null;
		if (this.actionTooltip) {
			this.actionTooltip.remove();
			this.actionTooltip = null;
		}
		if (this.actionTooltipBridge) {
			this.actionTooltipBridge.remove();
			this.actionTooltipBridge = null;
		}
	}

	private showSimpleTooltip(target: Element): void {
		this.hideSimpleTooltip();

		const text = target.getAttribute('data-tooltip');
		if (!text) { return; }

		const rect = target.getBoundingClientRect();
		const tooltip = document.createElement('div');
		tooltip.className = 'snc-tooltip snc-simple-tooltip';
		tooltip.textContent = text;

		// Same placement convention as snc-py-exps tooltips:
		//   data-tooltip-align="right"  -> render to the right of the target,
		//                                  vertically centered (with a fallback
		//                                  to the left if it would overflow)
		//   data-tooltip-align="bottom" -> render below the target (with a
		//                                  fallback to above if it overflows).
		//   default                     -> render above the target (with a
		//                                  fallback to below if it overflows).
		const align = target.getAttribute('data-tooltip-align');
		const win = dom.getWindow(this.editor.getContainerDomNode());
		const viewportWidth = win.innerWidth;

		if (align === 'right') {
			tooltip.style.visibility = 'hidden';
			this.editor.getContainerDomNode().appendChild(tooltip);
			const tooltipRect = tooltip.getBoundingClientRect();
			let left = rect.right + 4;
			if (left + tooltipRect.width > viewportWidth) {
				left = rect.left - tooltipRect.width - 4;
			}
			tooltip.style.left = `${left}px`;
			tooltip.style.top = `${rect.top + (rect.height - tooltipRect.height) / 2}px`;
			tooltip.style.visibility = '';
		} else if (align === 'bottom') {
			tooltip.style.left = `${rect.left}px`;
			tooltip.style.top = `${rect.bottom + 4}px`;
			this.editor.getContainerDomNode().appendChild(tooltip);
			const tooltipRect = tooltip.getBoundingClientRect();
			if (tooltipRect.bottom > win.innerHeight) {
				tooltip.style.top = `${Math.max(0, rect.top - tooltipRect.height - 4)}px`;
			}
			if (tooltipRect.right > viewportWidth) {
				tooltip.style.left = `${Math.max(0, rect.right - tooltipRect.width)}px`;
			}
		} else {
			// Measured, not guessed at a line tall, so this sits the same 4px
			// off its target as the py-exp and action tooltips do.
			tooltip.style.visibility = 'hidden';
			this.editor.getContainerDomNode().appendChild(tooltip);
			const tooltipRect = tooltip.getBoundingClientRect();
			const above = rect.top - tooltipRect.height - 4;
			tooltip.style.left = `${rect.left}px`;
			tooltip.style.top = `${above < 0 ? rect.bottom + 4 : above}px`;
			if (rect.left + tooltipRect.width > viewportWidth) {
				tooltip.style.left = `${Math.max(0, rect.right - tooltipRect.width)}px`;
			}
			tooltip.style.visibility = '';
		}

		this.simpleTooltip = tooltip;
	}

	private scheduleSimpleTooltipHide(): void {
		clearTimeout(this.simpleTooltipTimer);
		clearTimeout(this.simpleTooltipHideTimer);
		this.simpleTooltipHideTimer = setTimeout(() => {
			this.hideSimpleTooltip();
		}, 100);
	}

	private hideSimpleTooltip(): void {
		clearTimeout(this.simpleTooltipTimer);
		clearTimeout(this.simpleTooltipHideTimer);
		this.simpleTooltipTarget = null;
		if (this.simpleTooltip) {
			this.simpleTooltip.remove();
			this.simpleTooltip = null;
		}
	}

	private showHoverMenu(trigger: Element): void {
		const panel = trigger.querySelector('.snc-dropdown-panel[data-hover-menu]') as HTMLElement;
		if (!panel) { return; }
		studyLog.log('widget.hoverMenu', { line: this.lineNumber, visIndex: this.visIndex, trigger: describeEventTarget(trigger, this.domNode), items: panel.textContent?.slice(0, 200) }, this.editor.getModel()?.uri.toString());

		const triggerRect = trigger.getBoundingClientRect();
		const align = panel.getAttribute('snc-dropdown-align') || 'left';

		// Capture child-key chain before hoisting (clone loses nested ancestors).
		// Same pattern as hoistDropdownPanel / hoistSegmentLabels.
		const childKeyChain: string[] = [];
		let ancestor: Element | null = trigger.parentElement;
		while (ancestor && ancestor !== this.domNode) {
			const ck = ancestor.getAttribute('snc-child-key');
			if (ck) { childKeyChain.push(ck); }
			// A nested visualizer's toolbar is itself hoisted to the widget
			// root, so a trigger in one has no `snc-child-key` ancestors left
			// to walk - they went with the toolbar, which carries what it
			// found as a chain (hoistNestedToolbars). Without this a menu in a
			// table cell's action bar sent its clicks to the TABLE, which has
			// no such event, and the row did nothing at all.
			const inherited = ancestor.getAttribute('snc-child-key-chain');
			if (inherited) { childKeyChain.push(...JSON.parse(inherited) as string[]); }
			ancestor = ancestor.parentElement;
		}

		const clone = panel.cloneNode(true) as HTMLElement;
		clone.classList.add('snc-hover-menu');
		clone.style.display = '';
		clone.removeAttribute('data-hover-menu');
		if (childKeyChain.length > 0) {
			clone.setAttribute('snc-child-key-chain', JSON.stringify(childKeyChain));
		}

		if (align === 'right') {
			clone.style.right = `${window.innerWidth - triggerRect.right}px`;
		} else {
			clone.style.left = `${triggerRect.left}px`;
		}
		// Flush with the trigger's bottom edge; the panel's own margin-top is the
		// gap, so a hover menu hangs off its trigger by the same 4px a hoisted
		// click menu does.
		clone.style.top = `${triggerRect.bottom}px`;

		// Wire up event listeners on the hoisted panel. Walk only within the
		// clone, then re-apply the stashed ChildEvent envelope so nested
		// visualizers (e.g. string tool select inside a list cell) still route.
		const wrapEvent = (raw: string, attrEl: Element): string => {
			let wrapped = this.wrapWithChildKeys(raw, attrEl.parentElement, clone);
			const chainStr = clone.getAttribute('snc-child-key-chain');
			if (chainStr) {
				for (const ck of JSON.parse(chainStr) as string[]) {
					wrapped = `ChildEvent(${ck}, ${JSON.stringify(wrapped)})`;
				}
			}
			return wrapped;
		};

		this.hoverMenuListeners.push(
			dom.addDisposableListener(clone, 'mousedown', (ev: MouseEvent) => {
				const node = ev.target as Node;
				let el: Element | null = node.nodeType === Node.ELEMENT_NODE ? (node as Element) : (node.parentElement);
				while (el && el !== clone.parentElement) {
					if (el.hasAttribute('snc-mouse-down')) {
						const raw = el.getAttribute('snc-mouse-down') ?? '';
						this.onPointerEvent(wrapEvent(raw, el), ev);
						break;
					}
					el = el.parentElement;
				}
			})
		);

		clone.addEventListener('mouseenter', () => {
			clearTimeout(this.hoverMenuHideTimer);
		});
		clone.addEventListener('mouseleave', () => {
			this.scheduleHoverMenuHide();
		});

		clone.addEventListener('mouseover', (ev: MouseEvent) => {
			const pyExpEl = this.findAncestorWithAttr(ev.target as Node, 'snc-py-exps');
			if (pyExpEl) {
				clearTimeout(this.pyExpTooltipHideTimer);
				if (pyExpEl !== this.pyExpCurrentTarget) {
					this.pyExpCurrentTarget = pyExpEl;
					clearTimeout(this.pyExpTooltipTimer);
					this.pyExpTooltipTimer = setTimeout(() => {
						this.showPyExpTooltip(pyExpEl);
					}, VisualizationWidget.PY_EXP_TOOLTIP_SHOW_DELAY_MS);
				}
			} else if (this.pyExpCurrentTarget) {
				this.pyExpCurrentTarget = null;
				this.schedulePyExpTooltipHide();
			}
		});
		clone.addEventListener('mouseout', (ev: MouseEvent) => {
			const relatedTarget = ev.relatedTarget as Node | null;
			if (relatedTarget && (this.pyExpTooltip?.contains(relatedTarget)
				|| this.pyExpTooltipBridge?.contains(relatedTarget))) {
				return;
			}
			if (relatedTarget && this.findAncestorWithAttr(relatedTarget, 'snc-py-exps')) {
				return;
			}
			if (this.pyExpCurrentTarget) {
				this.pyExpCurrentTarget = null;
			}
			this.schedulePyExpTooltipHide();
		});

		this.editor.getContainerDomNode().appendChild(clone);
		this.hoverMenu = clone;
	}

	/**
	 * Lift the control marked `snc-hover-hoist` inside *host* out of the
	 * scrollport that clips it, for as long as the pointer is on the host.
	 *
	 * A table row's drag handle sits just outside the left edge of its
	 * row-number cell -- which is the left edge of the table, inside
	 * `.list-table-scroll`, whose overflow cuts it away entirely. Hoisting it
	 * on hover is the trade the hover menus make: one element at a time, only
	 * while it is wanted, rather than every row's handle hoisted at render and
	 * repositioned on every scroll.
	 *
	 * A clone rather than the element itself, like showHoverMenu: the next
	 * render replaces the widget's markup wholesale, and a control that had
	 * been moved out would be left in the editor container with nothing behind
	 * it to answer for.
	 *
	 * The copy is laid over the box the original occupies, so where it lands is
	 * decided by the stylesheet that placed the original and by nothing here.
	 * That is why the original is only made invisible rather than taken out of
	 * the flow: it stays the authority on where its copy belongs, and moving it
	 * in CSS moves the copy with it.
	 */
	private showHoistedHover(host: HTMLElement): void {
		const source = host.querySelector(':scope > [snc-hover-hoist]') as HTMLElement | null;
		if (!source) { return; }
		// Nowhere to lay a copy over. A control taken out of the flow entirely
		// has no box to read, and one placed at the origin would be a copy in
		// the corner of the editor rather than beside the row it came from.
		const sourceRect = source.getBoundingClientRect();
		if (sourceRect.width === 0 && sourceRect.height === 0) { return; }

		// A host scrolled out of one of its own scrollports is clipped away in
		// the widget, so nothing should be lifted out on its behalf.
		const hostRect = host.getBoundingClientRect();
		const container = this.editor.getContainerDomNode();
		const scrollers: HTMLElement[] = [];
		let ancestor: HTMLElement | null = host.parentElement;
		while (ancestor && ancestor !== this.domNode.parentElement && ancestor !== container) {
			if (VisualizationWidget.isScrollableElement(ancestor)) { scrollers.push(ancestor); }
			ancestor = ancestor.parentElement;
		}
		for (const scroller of scrollers) {
			const port = scroller.getBoundingClientRect();
			if (port.width === 0 || port.height === 0) { continue; }
			if (hostRect.right <= port.left || hostRect.left >= port.right
				|| hostRect.bottom <= port.top || hostRect.top >= port.bottom) {
				return;
			}
		}

		const clone = source.cloneNode(true) as HTMLElement;
		clone.removeAttribute('snc-hover-hoist');
		clone.classList.add('snc-hoisted-hover');
		// Over the box the original occupies, exactly. The rect is where the
		// stylesheet put the original's border box, margins and offsets and
		// all -- so the copy takes none of those with it, or it would be
		// offset a second time by the same rules that produced this rect.
		clone.style.position = 'fixed';
		clone.style.zIndex = '10000';
		clone.style.margin = '0';
		clone.style.left = `${sourceRect.left}px`;
		clone.style.top = `${sourceRect.top}px`;
		clone.style.right = 'auto';
		clone.style.bottom = 'auto';
		// Sized from the rect too, rather than left to shrink to fit again out
		// here: the box is what was measured, so it is the box that is copied.
		clone.style.boxSizing = 'border-box';
		clone.style.width = `${sourceRect.width}px`;
		clone.style.height = `${sourceRect.height}px`;
		clone.style.visibility = 'visible';
		container.appendChild(clone);

		this.hoistedHoverListeners.push(
			// The root's own mousedown never sees the clone, and dragstart
			// reads this to tell a drag from a click that slipped.
			dom.addDisposableListener(clone, 'mousedown', (ev: MouseEvent) => {
				this.lastMouseDownTarget = ev.target as Node;
			}),
			dom.addDisposableListener(clone, 'mouseleave', () => this.scheduleHoistedHoverHide()),
			dom.addDisposableListener(clone, 'mouseenter', () => clearTimeout(this.hoistedHoverHideTimer)),
			// A drag leaves the control the moment it starts, which is the one
			// departure that must not take the control away underneath it.
			dom.addDisposableListener(clone, 'dragstart', () => { this.hoistedHoverDragging = true; }),
			dom.addDisposableListener(clone, 'dragend', () => {
				this.hoistedHoverDragging = false;
				this.hideHoistedHover();
			}),
			...this.pyExpListeners(clone, container),
			...this.simpleTooltipListeners(clone, container),
		);
		// Scrolling moves the host out from under it, and there is no reason to
		// chase a control the pointer is about to leave anyway.
		for (const scroller of scrollers) {
			this.hoistedHoverListeners.push(
				dom.addDisposableListener(scroller, 'scroll', () => this.hideHoistedHover()));
		}

		this.hoistedHover = clone;
	}

	private scheduleHoistedHoverHide(): void {
		clearTimeout(this.hoistedHoverHideTimer);
		if (this.hoistedHoverDragging) { return; }
		this.hoistedHoverHideTimer = setTimeout(() => {
			this.hideHoistedHover();
		}, 100);
	}

	private hideHoistedHover(): void {
		clearTimeout(this.hoistedHoverHideTimer);
		this.hoistedHoverDragging = false;
		this.hoistedHoverHost = null;
		for (const d of this.hoistedHoverListeners) {
			d.dispose();
		}
		this.hoistedHoverListeners = [];
		if (this.hoistedHover) {
			this.hoistedHover.remove();
			this.hoistedHover = null;
		}
	}

	private scheduleHoverMenuHide(): void {
		clearTimeout(this.hoverMenuHideTimer);
		this.hoverMenuHideTimer = setTimeout(() => {
			this.hideHoverMenu();
		}, 150);
	}

	private hideHoverMenu(): void {
		clearTimeout(this.hoverMenuHideTimer);
		this.hoverMenuTrigger = null;
		for (const d of this.hoverMenuListeners) {
			d.dispose();
		}
		this.hoverMenuListeners = [];
		if (this.hoverMenu) {
			this.hoverMenu.remove();
			this.hoverMenu = null;
		}
		this.hidePyExpTooltip();
	}

	/**
	 * Whether a press on *target* would begin a native drag: the nearest
	 * element between it and the widget root that says either way says yes.
	 *
	 * The browser's own rule, asked before the press is swallowed -- a handle
	 * marked draggable="true" (py_exp_attrs writes it) drags, and anything
	 * inside it marked draggable="false" doesn't, which is how a control that
	 * only wants clicks opts out.
	 */
	private startsDrag(target: Element): boolean {
		let el: Element | null = target;
		while (el && el !== this.domNode) {
			const draggable = el.getAttribute('draggable');
			if (draggable === 'true') { return true; }
			if (draggable === 'false') { return false; }
			el = el.parentElement;
		}
		return false;
	}

	/**
	 * Check if target is in the draggable zone of an snc-py-exps element
	 * (i.e., not inside a descendant marked draggable="false").
	 */
	private isInDraggableZone(target: Node, pyExpEl: Element): boolean {
		let el: Element | null = target instanceof Element ? target : target.parentElement;
		while (el && el !== pyExpEl) {
			if (el.getAttribute('draggable') === 'false') {
				return false;
			}
			el = el.parentElement;
		}
		return true;
	}

	private wrapWithChildKeys(pythonEventStr: string, from: Element | null, stop: Element | null): string {
		let el = from;
		while (el && el !== stop) {
			const childKey = el.getAttribute('snc-child-key');
			if (childKey) {
				pythonEventStr = `ChildEvent(${childKey}, ${JSON.stringify(pythonEventStr)})`;
			}
			// Elements hoisted out of their original DOM ancestry (e.g. segment
			// labels reparented to the widget root) carry their lost child-key
			// chain here so events still resolve to the right nested model.
			const chainStr = el.getAttribute('snc-child-key-chain');
			if (chainStr) {
				for (const ck of JSON.parse(chainStr) as string[]) {
					pythonEventStr = `ChildEvent(${ck}, ${JSON.stringify(pythonEventStr)})`;
				}
			}
			el = el.parentElement;
		}
		return pythonEventStr;
	}

	private dispatch_mouse_python_event(attr_name: string, ev: MouseEvent, forceDispatch = false): void {
		// Only the focused visualizer receives events. A non-focused widget's
		// first mousedown pins focus (handled in the mousedown listener); all
		// other mouse events (move/up/out) on a non-focused widget must not be
		// dispatched — hovering a non-focused auto-linked line would otherwise
		// re-run its linked action and rewrite the linked line.
		// forceDispatch is set for snc-unfocused-clickable controls (e.g. the
		// expand/collapse toggle) that intentionally act without pinning focus.
		if (!this.isFocused() && !forceDispatch) { return; }
		if (!ev.target) { return; }

		let node = ev.target as Node;
		let el: Element | null = node.nodeType === Node.ELEMENT_NODE ? (node as Element) : (node.parentElement);
		const startEl = el;

		// A visualizer rendered small is a non-focused preview, and Python drops
		// every event on a non-focused child except the mousedown that pins focus
		// (route_child_event). Mouse moves over one can therefore only ever cost a
		// full program re-run, so they never leave the front-end. Down/up still
		// dispatch, since that mousedown is how the preview gets focused.
		if (attr_name === 'snc-mouse-move' && el?.closest('.visualizer-container.small')) {
			return;
		}

		// Present on a visualizer's container only while it believes a drag is
		// in progress. It means two things here: moves over plain chars and
		// grouped text are wanted (a drag has to track wherever the pointer
		// goes), and a mouseup no listener hears should be reported once (the
		// notify fallback at the bottom). Idle, match chars still hear moves
		// through their explicit snc-mouse-move; everything else stays silent,
		// since each move costs a full program run.
		const dragTrackingEl = startEl?.closest('[snc-notify-mouse-is-up]') ?? null;

		// Where the pointer sits, resolved to the nearest indexed char element
		// (snc-idx / snc-idx-start) up front, so the walk below can give it
		// the same nearest-element precedence as an explicit listener. The
		// pixel seams between char spans (and the empty area beside a line)
		// hit-test to a plain container, but the caret still snaps to the
		// nearest char -- and handled only as a post-walk fallback, a click
		// on those pixels inside a table bubbled past the string to the list
		// visualizer's DeselectChildren mousedown and unfocused the child
		// instead of placing the cursor.
		const caretRange = document.caretRangeFromPoint(ev.clientX, ev.clientY);
		let caretNode: Node | null = caretRange?.startContainer ?? null;
		if (caretNode && caretNode.nodeType !== Node.TEXT_NODE && caretNode.childNodes.length > 0) {
			// A hit on the seam between spans can resolve to the parent with
			// an offset between its children; take the child at the seam.
			caretNode = caretNode.childNodes[Math.min(caretRange!.startOffset, caretNode.childNodes.length - 1)];
		}
		let caretIdxEl: Element | null = null;
		let g: Element | null = !caretNode ? null
			: caretNode.nodeType === Node.ELEMENT_NODE ? caretNode as Element
			: caretNode.parentElement;
		while (g && g !== this.domNode) {
			if (g.hasAttribute('snc-idx-start') || g.hasAttribute('snc-idx')) {
				caretIdxEl = g;
				break;
			}
			g = g.parentElement;
		}
		const dispatchGroupedTextEvent = (groupEl: Element): boolean => {
			// Moves over grouped text are drag-only, like the snc-idx shorthand
			// -- except a grouped match interior (snc-hover-moves) hears idle
			// hovers too: hovering a match is how its labels appear.
			if (attr_name === 'snc-mouse-move' && !dragTrackingEl && !groupEl.hasAttribute('snc-hover-moves')) {
				return false;
			}
			const textNode = groupEl.firstChild;
			if (!textNode || textNode.nodeType !== Node.TEXT_NODE) {
				return false;
			}
			const textLen = textNode.textContent?.length ?? 1;
			// The caret carries the char offset only when it actually resolved
			// into this group's text; a seam hit beside the group means its
			// first char.
			const offset = caretRange && caretRange.startContainer === textNode
				? Math.min(caretRange.startOffset, textLen - 1)
				: 0;
			const charIndex = parseInt(groupEl.getAttribute('snc-idx-start') ?? '0') + offset;
			let pythonEventStr: string = {
				'snc-mouse-move': `MouseMove(${charIndex})`,
				'snc-mouse-down': `MouseDown(${charIndex})`,
				'snc-mouse-up': `MouseUp(${charIndex})`,
			}[attr_name] ?? '';
			// The group covers move/down/up only: nothing to say for a mouseout.
			if (pythonEventStr === '') {
				return false;
			}
			pythonEventStr = this.wrapWithChildKeys(pythonEventStr, groupEl.parentElement, this.domNode);
			// Build a per-character rect for accurate offsetY/elementHeight
			const charRange = document.createRange();
			charRange.setStart(textNode, offset);
			charRange.setEnd(textNode, Math.min(offset + 1, textLen));
			this.onPointerEvent(pythonEventStr, ev, charRange.getBoundingClientRect());
			return true;
		};

		// A pointer event that lands inside the same visualizer as the caret's
		// nearest char -- on the pixel seam between two spans, or in the empty
		// area past the end of a line -- belongs to that char. Start the walk
		// there; everything from the real target on up still gets its turn.
		if (caretIdxEl && startEl && startEl.contains(caretIdxEl)
			&& startEl.closest('.visualizer-container') === caretIdxEl.closest('.visualizer-container')) {
			el = caretIdxEl;
		}

		// A click inside a focused visualizer that no listener claims stops at
		// the visualizer's edge instead of bubbling out: whatever an enclosing
		// visualizer would make of it (the list visualizer's DeselectChildren,
		// say), it is not a click on THAT visualizer. Small previews keep
		// bubbling -- the mousedown that pins their focus is handled outside
		// them.
		const mousedownBoundaryEl = attr_name === 'snc-mouse-down'
			? startEl?.closest('.visualizer-container:not(.small)') ?? null
			: null;

		while (el && el != this.domNode) {
			if (el.hasAttribute(attr_name) || el.hasAttribute(`snc-idx`)) {
				let pythonEventStr: string;
				if (el.hasAttribute(attr_name)) {
					pythonEventStr = el.getAttribute(attr_name) ?? '';
				} else if (attr_name === 'snc-mouse-move' && !dragTrackingEl) {
					// The shorthand's move expansion is drag-only; outside a
					// drag a move over a plain char has nothing to say.
					pythonEventStr = '';
				} else {
					// snc-idx="5" is shorthand for snc-mouse-move="MouseMove(5)" snc-mouse-down="MouseDown(5)" snc-mouse-up="MouseUp(5)"
					pythonEventStr = {
						'snc-mouse-move': `MouseMove(${el.getAttribute(`snc-idx`)})`,
						'snc-mouse-down': `MouseDown(${el.getAttribute(`snc-idx`)})`,
						'snc-mouse-up': `MouseUp(${el.getAttribute(`snc-idx`)})`,
					}[attr_name] ?? '';
				}

				if (attr_name === 'snc-resize-col') {
					pythonEventStr = pythonEventStr.replace("width=0", `width=${(ev as any).resizeWidth}`);
				}

				// The shorthand covers move/down/up only. A mouseout over it is
				// nothing the visualizer asked to hear about -- and it fires at
				// every element boundary the pointer crosses. Sent anyway (as an
				// empty event string) it was a no-op in Python that still cost a
				// full run, superseding the run for the event before it: a
				// mouseup's run killed just after its item retired the mouseup
				// from the queue, and with it the line of code the visualizer
				// was about to write. So: no event, keep looking upward.
				if (pythonEventStr === '') {
					el = el.parentElement;
					continue;
				}
				pythonEventStr = this.wrapWithChildKeys(pythonEventStr, el.parentElement, this.domNode);
				this.onPointerEvent(pythonEventStr, ev);
				return;
			} else if (el.hasAttribute('snc-idx-start')) {
				// The grouped text under the pointer beats any listener above
				// it, exactly as an explicit listener here would. A gated move
				// keeps walking: an ancestor row may be mid-drag and tracking
				// moves of its own.
				if (dispatchGroupedTextEvent(el)) {
					return;
				}
			}
			if (el === mousedownBoundaryEl) {
				return;
			}
			el = el.parentElement;
		}

		// Fallback: the grouped text under the pointer was not on the target's
		// ancestor chain (the caret snapped into text the target does not
		// contain) and nothing nearer claimed the event.
		if (caretIdxEl && caretIdxEl.hasAttribute('snc-idx-start') && dispatchGroupedTextEvent(caretIdxEl)) {
			return;
		}

		// The mouse is up (a release, or a move showing no buttons) and no
		// listener above heard it, but the visualizer believes a drag is in
		// progress: tell it once so the drag can finalize. The attribute comes
		// off the DOM here, so a burst of no-button moves costs one run, not
		// one per move; the next render decides whether to ask again.
		if (attr_name === 'snc-mouse-up' || (attr_name === 'snc-mouse-move' && ev.buttons === 0)) {
			if (dragTrackingEl) {
				const notifyStr = dragTrackingEl.getAttribute('snc-notify-mouse-is-up') ?? '';
				dragTrackingEl.removeAttribute('snc-notify-mouse-is-up');
				if (notifyStr !== '') {
					this.onPointerEvent(this.wrapWithChildKeys(notifyStr, dragTrackingEl.parentElement, this.domNode), ev);
				}
			}
		}
	}

	private dispatch_keyboard_event(attr_name: string, ev: KeyboardEvent): void {
		if (!this.isFocused()) { return; }
		if (!ev.target) { return; }

		let node = ev.target as Node;
		let el: Element | null = node.nodeType === Node.ELEMENT_NODE ? (node as Element) : (node.parentElement);

		// Walk up to find element with the keyboard event handler attribute
		while (el) {
			if (el.hasAttribute(attr_name)) {
				let pythonEventStr: string = el.getAttribute(attr_name) ?? '';
				pythonEventStr = this.wrapWithChildKeys(pythonEventStr, el.parentElement, this.domNode);
				this.onKeyboardEvent(pythonEventStr, ev);
				return;
			}
			if (el === this.domNode) { break; }
			el = el.parentElement;
		}

		// Also check the domNode itself (container level handler)
		if (this.domNode.hasAttribute(attr_name)) {
			const pythonEventStr: string = this.domNode.getAttribute(attr_name) ?? '';
			this.onKeyboardEvent(pythonEventStr, ev);
		}
	}

	/** Remember a value just sent to Python from an snc-input box. */
	private noteTypedValue(inputEl: Element, value: string): void {
		const key = inputEl.getAttribute('snc-input') ?? '';
		if (this.pendingTypedValues && this.pendingTypedValues.key === key) {
			this.pendingTypedValues.values.push(value);
		} else {
			// Typing moved to another box: whatever the old one had in flight
			// will be echoed into an unfocused box, which is harmless.
			this.pendingTypedValues = { key, values: [value] };
		}
	}

	/**
	 * Reconcile a freshly rendered snc-input box with what the user has typed
	 * into its predecessor since. `domValue` is the predecessor's value at the
	 * moment of the render; `el` is the new element (its value is what Python
	 * rendered).
	 *
	 * Invariant: while typed values are still in flight, the DOM is the source
	 * of truth for the focused box. Every input event carries the box's whole
	 * value, so the values we've sent form a history, oldest first:
	 *   - Python rendered the newest one: it has caught up; nothing in flight.
	 *   - Python rendered an older one (an event still queued, or a run
	 *     cancelled mid-stream): stale. Put the DOM value back; the newer
	 *     event is still on its way and Python will catch up.
	 *   - Python rendered something we never sent: it deliberately changed the
	 *     box (cleared it on Escape, normalized it, ...). Take Python's value
	 *     and forget the history, so the change isn't fought.
	 * Returns true when the DOM value was kept (so the caller restores the
	 * selection as it was, not clamped to the stale value).
	 */
	private keepNewerTypedValue(el: HTMLInputElement | HTMLTextAreaElement, domValue: string): boolean {
		const pending = this.pendingTypedValues;
		const key = el.getAttribute('snc-input');
		if (!pending || key === null || pending.key !== key) {
			return false;
		}
		const rendered = el.value;
		const newest = pending.values[pending.values.length - 1];
		if (rendered === newest) {
			this.pendingTypedValues = null;
			return false;
		}
		const staleIndex = pending.values.indexOf(rendered);
		if (staleIndex < 0) {
			this.pendingTypedValues = null;
			return false;
		}
		// Values up to and including the echoed one are acknowledged.
		pending.values.splice(0, staleIndex + 1);
		if (el.value !== domValue) {
			el.value = domValue;
		}
		return true;
	}

	private dispatch_input_event(attr_name: string, ev: Event): void {
		if (!this.isFocused()) { return; }
		const target = ev.target as HTMLElement;
		if (!target) { return; }

		let el: Element | null = target;
		while (el && el !== this.domNode) {
			if (el.hasAttribute(attr_name)) {
				let pythonEventStr: string = el.getAttribute(attr_name) ?? '';
				pythonEventStr = this.wrapWithChildKeys(pythonEventStr, el.parentElement, this.domNode);
				const value = (target as HTMLInputElement).value ?? '';
				this.noteTypedValue(el, value);
				this.onInputEvent(pythonEventStr, value);
				return;
			}
			el = el.parentElement;
		}
	}

	/**
	 * Handle click on an element with snc-add-at-cursor.
	 * Reads snc-add-target (a CSS selector) to find the target input,
	 * inserts the snc-add-at-cursor value at the cursor position,
	 * then fires an input event so the Python model updates.
	 * Returns true if the event was handled.
	 */
	private handleAddAtCursor(ev: MouseEvent): boolean {
		if (!ev.target || this.isReadOnly()) { return false; }
		let el: Element | null = (ev.target as Node).nodeType === Node.ELEMENT_NODE
			? (ev.target as Element)
			: (ev.target as Node).parentElement;

		while (el && el !== this.domNode) {
			const textToInsert = el.getAttribute('snc-add-at-cursor');
			if (textToInsert !== null) {
				const targetSelector = el.getAttribute('snc-add-target');
				if (!targetSelector) { return false; }
				const targetInput = this.domNode.querySelector(targetSelector) as HTMLInputElement | null;
				if (targetInput) {
					const start = targetInput.selectionStart ?? targetInput.value.length;
					const end = targetInput.selectionEnd ?? start;
					const before = targetInput.value.slice(0, start);
					const after = targetInput.value.slice(end);
					targetInput.value = before + textToInsert + after;
					const newCursor = start + textToInsert.length;
					targetInput.setSelectionRange(newCursor, newCursor);
					targetInput.dispatchEvent(new Event('input', { bubbles: true }));
					targetInput.focus();
				}
				ev.preventDefault();
				ev.stopPropagation();
				return true;
			}
			el = el.parentElement;
		}
		return false;
	}

	getId(): string {
		return `editor.contrib.visualizationOverlayWidget-${this.lineNumber}-${this.visIndex}`;
	}

	getVisIndex(): number {
		return this.visIndex;
	}

	getDomNode(): HTMLElement {
		return this.domNode;
	}

	getPosition(): IOverlayWidgetPosition | null {
		if (!this.position) {
			return null;
		}

		// Calculate absolute position coordinates
		const lineNumber = this.position.lineNumber;
		const model = this.editor.getModel();

		if (!model) {
			return null;
		}

		try {
			// Get the line content to find the end column
			const lineContent = model.getLineContent(lineNumber);
			const endColumn = lineContent.length + 1;
			const lineHeight = this.editor.getOption(EditorOption.lineHeight);
			const firstNonWhitespaceColumn = model.getLineFirstNonWhitespaceColumn(lineNumber);
			const indentationColumn = firstNonWhitespaceColumn > 0 ? firstNonWhitespaceColumn : 1;
			const targetColumn = this.useBlockLayout ? indentationColumn : endColumn;

			// Use the editor's coordinate conversion methods
			const position = { lineNumber, column: targetColumn };
			const pixelPosition = this.editor.getScrolledVisiblePosition(position);

			if (!pixelPosition) {
				// Line is not visible
				return null;
			}

			// Align first line of text with 1px border; block layout starts on the next
			// visual line to render below the code line.
			pixelPosition.top += this.useBlockLayout ? lineHeight : -1;

			// 8px of padding for visualizers on the same line
			pixelPosition.left += this.useBlockLayout ? 0 : 8 + this.leftInset;

			// Cap the widget width so that it scrolls if too large
			const layoutInfo = this.editor.getLayoutInfo();
			const available = layoutInfo.contentLeft + layoutInfo.contentWidth - pixelPosition.left - 8;
			this.domNode.style.maxWidth = `${Math.max(VisualizationWidget.MIN_AVAILABLE_WIDTH_PX, available)}px`;

			if (pixelPosition.top < 0 && this.lastOnscreenPixelPosition) {
				// x coordinate is not reliable when lines are offscreen, use last known coordinate
				return {
					preference: {
						top: pixelPosition.top,
						left: this.lastOnscreenPixelPosition.left
					}
				};
			} else {
				this.lastOnscreenPixelPosition = pixelPosition;
				return { preference: pixelPosition };
			}
		} catch (error) {
			return null;
		}
	}

	/**
	 * Update the widget's HTML content
	 */
	private static readonly FOCUSABLE_SELECTOR = '[tabindex], input, textarea, select';
	private static readonly SCROLLABLE_OVERFLOW = /^(auto|scroll|overlay|hidden)$/;
	private static isScrollableElement(el: HTMLElement): boolean {
		if (el.scrollTop === 0 && el.scrollLeft === 0
			&& el.scrollHeight <= el.clientHeight
			&& el.scrollWidth <= el.clientWidth) {
			return false;
		}
		// visible overflow is not a scroller
		const style = dom.getWindow(el).getComputedStyle(el);
		return VisualizationWidget.SCROLLABLE_OVERFLOW.test(style.overflowY)
			|| VisualizationWidget.SCROLLABLE_OVERFLOW.test(style.overflowX);
	}

	updateContent(html: string): boolean {
		// Avoid tearing down/rebuilding DOM when content did not change.
		if (this.lastRenderedHtml === html) {
			return false;
		}

		// Dismiss any active tooltips/menus since the DOM is being replaced
		this.hidePyExpTooltip();
		this.hideActionTooltip();
		this.hideSimpleTooltip();
		this.hideHoverMenu();
		this.hideHoistedHover();

		// Any pending focus restoration from an older render should be ignored.
		const currentFocusRestoreVersion = ++this.focusRestoreVersion;

		// Save focus state BEFORE cleaning up the hoisted dropdown (removing it
		// from the DOM would cause the browser to lose focus on any input inside it).
		const activeElement = document.activeElement;
		let focusedIndex = -1;
		// An input that names itself is found again by that name rather than by
		// its place in the list. The list is shared between the widget and the
		// hoisted panels, so an input the render adds or drops anywhere ahead of
		// the focused one shifts it -- which is exactly what a box whose typing
		// adds a cell to the table does to itself.
		let savedFocusKey: string | null = null;
		let savedSelectionStart: number | null = null;
		let savedSelectionEnd: number | null = null;
		let savedValue: string | null = null;
		const savedWidgetScrollTop = this.domNode.scrollTop;
		const savedWidgetScrollLeft = this.domNode.scrollLeft;
		const oldScrollableElements = Array.from(this.domNode.querySelectorAll('*'))
			.filter(dom.isHTMLElement)
			.filter(VisualizationWidget.isScrollableElement);
		const savedScrollOffsets = oldScrollableElements.map((el) => ({
			top: el.scrollTop,
			left: el.scrollLeft
		}));

		// Build the combined list of focusable elements across widget + hoisted dropdowns
		const widgetFocusable = Array.from(this.domNode.querySelectorAll(VisualizationWidget.FOCUSABLE_SELECTOR));
		const allOldFocusable = [...widgetFocusable, ...this.hoistedFocusable()];

		// Track whether an [autofocus] element existed in the OLD render. If
		// one is in the NEW render but wasn't in the old one, it's "newly
		// appearing" - we want to focus it even when an input was previously
		// focused (e.g. user clicked a label trigger to open an edit popup
		// while the search box still held focus).
		const hadAutoFocusEl = !!(this.domNode.querySelector('[autofocus]')
			|| this.queryHoistedDropdowns('[autofocus]'));

		if (activeElement && (this.domNode.contains(activeElement) || this.hoistedDropdownsContain(activeElement))) {
			for (let i = 0; i < allOldFocusable.length; i++) {
				if (allOldFocusable[i] === activeElement) {
					focusedIndex = i;
					break;
				}
			}
			savedFocusKey = activeElement.getAttribute('snc-focus-key');
			// Save cursor position for input/textarea elements
			if (activeElement instanceof HTMLInputElement || activeElement instanceof HTMLTextAreaElement) {
				savedSelectionStart = activeElement.selectionStart;
				savedSelectionEnd = activeElement.selectionEnd;
				savedValue = activeElement.value;
			}
		} else {
			// Nothing focused in here: no typing can be in flight that matters.
			this.pendingTypedValues = null;
		}

		// Now safe to clean up the old hoisted dropdowns
		this.cleanupHoistedDropdowns();
		this.cleanupHoistedSegmentLabels();

		const trustedHtml = ttPolicy?.createHTML(html) ?? html;
		this.domNode.innerHTML = trustedHtml as string;
		this.lastRenderedHtml = html;
		if (this.isReadOnly()) {
			this.stripCodeAffordances(this.domNode);
		}

		// Replacing innerHTML detached the persistent chain-icon chrome; put it
		// back so its state survives content re-renders.
		if (this.linkChainEl) {
			this.domNode.appendChild(this.linkChainEl);
		}

		// Hoist any dropdown panels outside the overflow container
		this.hoistDropdownPanels();
		// Hoist segment labels out of the scrollable string container so they
		// aren't clipped by its overflow.
		this.hoistSegmentLabels();
		this.hoistNestedToolbars();
		this.setupResizableColumns();
		this.updateLayoutMode();

		// Scroll any element marked for scroll-into-view (e.g. selected autocomplete item)
		const scrollTarget = (this.queryHoistedDropdowns('[snc-scroll-into-view]')
			?? this.domNode.querySelector('[snc-scroll-into-view]')
		) as HTMLElement | null;
		if (scrollTarget) {
			scrollTarget.scrollIntoView({ block: 'nearest' });
		}

		// Restore scroll synchronously: replacing innerHTML reset every scrollable
		// container to 0, and mouse events hit-test the DOM as it stands when they
		// fire. Deferring the restore a frame (as focus restoration below does) let
		// a drag's mousemove land on the string before it was scrolled back,
		// reading the char index under the pointer from the wrong end of the
		// string and yanking the selection backward.
		const shouldRestoreScroll = savedWidgetScrollTop !== 0
			|| savedWidgetScrollLeft !== 0
			|| savedScrollOffsets.some((offset) => offset.top !== 0 || offset.left !== 0);
		if (shouldRestoreScroll) {
			this.domNode.scrollTop = savedWidgetScrollTop;
			this.domNode.scrollLeft = savedWidgetScrollLeft;
			const newScrollableElements = Array.from(this.domNode.querySelectorAll('*'))
				.filter(dom.isHTMLElement)
				.filter(VisualizationWidget.isScrollableElement);
			const restoreCount = Math.min(savedScrollOffsets.length, newScrollableElements.length);
			for (let i = 0; i < restoreCount; i++) {
				newScrollableElements[i].scrollTop = savedScrollOffsets[i].top;
				newScrollableElements[i].scrollLeft = savedScrollOffsets[i].left;
			}
		}
		// [autofocus] elements may live inside a hoisted dropdown panel
		// (which is taken out of this.domNode so it can be position:fixed).
		// Look in both places.
		const autoFocusEl = (this.domNode.querySelector('[autofocus]')
			|| this.queryHoistedDropdowns('[autofocus]')
		) as HTMLElement | null;
		const hasScrollToMatch = this.domNode.querySelector('[snc-scroll-to-match]') !== null;

		// Find the box that will get focus back (same lookup as in the rAF
		// below) and reconcile its value right away, synchronously: the focus
		// restore is a frame away and the user may type into the box before
		// then, so the value it holds must already be the newer one.
		const keySelector = savedFocusKey ? `[snc-focus-key="${CSS.escape(savedFocusKey)}"]` : null;
		const findFocusTarget = (): HTMLElement | null => {
			const keyed = keySelector
				? (this.domNode.querySelector(keySelector) || this.queryHoistedDropdowns(keySelector))
				: null;
			const widgetFocusable = Array.from(this.domNode.querySelectorAll(VisualizationWidget.FOCUSABLE_SELECTOR));
			const allFocusable = [...widgetFocusable, ...this.hoistedFocusable()];
			return (keyed ?? (focusedIndex < allFocusable.length ? allFocusable[focusedIndex] : null)) as HTMLElement | null;
		};
		if (focusedIndex >= 0 && savedValue !== null) {
			const target = findFocusTarget();
			if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement) {
				this.keepNewerTypedValue(target, savedValue);
			}
		}

		if (focusedIndex >= 0 || autoFocusEl || hasScrollToMatch) {
			// Defer to next frame so layout/DOM updates settle, and ensure only the
			// latest update in a burst is allowed to restore focus. Scroll was
			// restored synchronously above, so focus restoration with
			// preventScroll does not fight with scroll offsets.
			dom.getWindow(this.domNode).requestAnimationFrame(() => {
				if (currentFocusRestoreVersion !== this.focusRestoreVersion) {
					return;
				}

				// Scroll to first search match (after scroll restoration so we can
				// check whether it's already visible at the restored position)
				const matchTarget = this.domNode.querySelector('[snc-scroll-to-match]') as HTMLElement | null;
				if (matchTarget) {
					this.scrollToFirstMatch(matchTarget);
				}

				// Autofocus: focus the [autofocus] element when it's newly appearing.
				// Two cases honor autofocus:
				//   1. No input was previously focused (savedSelectionStart === null) -
				//      e.g. focus was on the outer div, so autofocus the new input.
				//   2. An autofocus element appeared in this render but did NOT exist
				//      in the previous one - the user just opened a popup expecting it
				//      to take focus, so override the saved input cursor restoration.
				// Otherwise (autofocus el is the SAME one persisting across renders, e.g.
				// the user is typing into it), preserve the cursor via focusedIndex below.
				const autoFocusIsNew = !!autoFocusEl && !hadAutoFocusEl;
				if (autoFocusEl && (savedSelectionStart === null || autoFocusIsNew)) {
					autoFocusEl.focus({ preventScroll: true });
					if (autoFocusEl instanceof HTMLInputElement) {
						// Select all text if requested (e.g. editing an existing field)
						if (autoFocusEl.hasAttribute('snc-select-all')) {
							autoFocusEl.select();
						} else {
							// Or drop the cursor at a given offset, for a value the
							// visualizer pre-filled around it (e.g. inside the `[]`
							// a column search's `in` hands the user).
							const cursorPos = autoFocusEl.getAttribute('snc-cursor-pos');
							if (cursorPos !== null) {
								const pos = Math.min(Number(cursorPos), autoFocusEl.value.length);
								autoFocusEl.setSelectionRange(pos, pos);
							}
						}
					}
				} else if (focusedIndex >= 0) {
					// The element that named itself, wherever it has ended up;
					// failing that, the same nth focusable element.
					// Look in both the widget and any hoisted dropdowns
					const el = findFocusTarget();
					if (el) {
						const wasFocused = document.activeElement === el;
						el.focus({ preventScroll: true });
						// Restore cursor position for input/textarea elements.
						// Not if the user already has this box: they may have typed
						// into it since the render (its value was reconciled above),
						// and their caret is newer than the saved one.
						if (!wasFocused && savedSelectionStart !== null && (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement)) {
							el.selectionStart = savedSelectionStart;
							el.selectionEnd = savedSelectionEnd;
						}
					}
				}
			});
		}
		return true;
	}

	private scrollToFirstMatch(matchTarget: HTMLElement): void {
		// Overflowing is not the same as scrolling. The string visualizer puts
		// a plain <div> inside its scroll box (to restore white-space:pre out
		// of the flex context), and that div reports the full content height
		// against a clamped client height -- so an overflow-only test stops on
		// it and then sets scrollTop on something that cannot scroll. Ask for
		// an element that actually scrolls.
		let container: HTMLElement | null = matchTarget.parentElement;
		while (container && container !== this.domNode) {
			if (VisualizationWidget.isScrollableElement(container)) {
				break;
			}
			container = container.parentElement;
		}
		if (!container || container === this.domNode) {
			return;
		}

		const targetRect = matchTarget.getBoundingClientRect();
		const containerRect = container.getBoundingClientRect();

		// Pinned table headers (position: sticky) visually cover the top of
		// the scroll container, so a row aligned to containerRect.top can
		// still end up hidden underneath the header. The whole <thead> is what
		// pins -- sub-column rows included -- so it is the group's height that
		// has to be cleared, not the first row's.
		const headerEl = container.querySelector('thead') as HTMLElement | null;
		const headerHeight = headerEl && dom.getWindow(headerEl).getComputedStyle(headerEl).position === 'sticky'
			? headerEl.getBoundingClientRect().height
			: 0;
		const visibleTop = containerRect.top + headerHeight;

		// Vertical: if not fully visible, align to top of container (below any pinned header)
		if (targetRect.top < visibleTop || targetRect.bottom > containerRect.bottom) {
			container.scrollTop += targetRect.top - visibleTop - 2;
		}

		// Horizontal: if not fully visible
		if (targetRect.left < containerRect.left || targetRect.right > containerRect.right) {
			// First try scrolling all the way left
			container.scrollLeft = 0;
			const newRect = matchTarget.getBoundingClientRect();
			if (newRect.left < containerRect.left || newRect.right > containerRect.right) {
				container.scrollLeft = newRect.left - containerRect.left - 2;
			}
		}
	}

	usesBlockLayout(): boolean {
		return this.useBlockLayout;
	}

	private updateLayoutMode(): void {
		const rect = this.domNode.getBoundingClientRect();
		this.useBlockLayout = rect.width > VisualizationWidget.BLOCK_LAYOUT_THRESHOLD_PX || rect.height > VisualizationWidget.BLOCK_LAYOUT_THRESHOLD_PX;
		this.domNode.classList.toggle('snc-visualization-widget-block-layout', this.useBlockLayout);
	}

	/** Every currently hoisted panel's focusable descendants, in panel order. */
	private hoistedFocusable(): Element[] {
		return this.hoistedDropdowns.flatMap((entry) =>
			Array.from(entry.panel.querySelectorAll(VisualizationWidget.FOCUSABLE_SELECTOR)));
	}

	/** First match for `selector` across the hoisted panels, or null. */
	private queryHoistedDropdowns(selector: string): Element | null {
		for (const entry of this.hoistedDropdowns) {
			const found = entry.panel.querySelector(selector);
			if (found) { return found; }
		}
		return null;
	}

	private hoistedDropdownsContain(node: Node): boolean {
		return this.hoistedDropdowns.some((entry) => entry.panel.contains(node));
	}

	/**
	 * Hoist every state-driven dropdown panel out of this widget's overflow
	 * container and position each as a fixed overlay in the editor container.
	 * Hover menus are excluded - they are cloned out separately by showHoverMenu.
	 */
	private hoistDropdownPanels(): void {
		const panels = Array.from(this.domNode.querySelectorAll('.snc-dropdown-panel:not([data-hover-menu])'))
			.filter(dom.isHTMLElement);

		for (const panel of panels) {
			const trigger = panel.closest('.snc-dropdown-trigger') as HTMLElement;
			if (!trigger) { continue; }
			this.hoistDropdownPanel(panel, trigger);
		}

		if (this.hoistedDropdowns.length === 0) { return; }

		// A hoisted panel is position:fixed but its trigger is not: scrolling any
		// container between them (e.g. .list-table-scroll under a column's ▾ menu,
		// which scrolls horizontally) slides the trigger out from under it.
		const scrollers = new Set(this.hoistedDropdowns.flatMap((entry) => entry.scrollers));
		for (const scroller of scrollers) {
			this.hoistedDropdownListeners.push(
				dom.addDisposableListener(scroller, 'scroll', () => this.repositionHoistedDropdowns())
			);
		}
		this.hoistedDropdownListeners.push(
			this.editor.onDidScrollChange(() => this.repositionHoistedDropdowns())
		);

		// A click away from every open panel puts the menu that says so away —
		// the third way out of a column ▾ menu, alongside the ▾ itself and
		// Escape, and the one that needs no aiming. `snc-dismiss` carries the
		// event, so the front end needs to know neither which panel is a menu
		// nor what closing one entails.
		//
		// "Outside" means outside them all: a submenu is a hoisted panel of its
		// own, so clicking in Sort or Compute is not clicking away from the menu
		// that opened them. Triggers are exempt too — they already toggle, and
		// dismissing as well would be closing it twice.
		const dismissable = this.hoistedDropdowns.filter(
			(entry) => entry.panel.hasAttribute('snc-dismiss'));
		if (dismissable.length > 0) {
			this.hoistedDropdownListeners.push(
				dom.addDisposableListener(this.domNode.ownerDocument, 'mousedown', (ev: MouseEvent) => {
					const node = ev.target as Node | null;
					if (!node) { return; }
					for (const entry of this.hoistedDropdowns) {
						if (entry.panel.contains(node) || entry.trigger.contains(node)) { return; }
					}
					for (const entry of dismissable) {
						this.onPointerEvent(
							this.wrapHoistedPanelEvent(
								entry.panel.getAttribute('snc-dismiss') ?? '', entry.panel),
							ev);
					}
				}, true)
			);
		}
	}

	/**
	 * Bring an event written on a hoisted panel itself back into the child-key
	 * scope the panel was rendered in. The chain its lost ancestors carried is
	 * saved on the panel at hoist time; an attribute on the panel has no
	 * ancestors left inside it to walk.
	 */
	private wrapHoistedPanelEvent(raw: string, panel: HTMLElement): string {
		let wrapped = raw;
		const chainStr = panel.getAttribute('snc-child-key-chain');
		if (chainStr) {
			for (const ck of JSON.parse(chainStr) as string[]) {
				wrapped = `ChildEvent(${ck}, ${JSON.stringify(wrapped)})`;
			}
		}
		return wrapped;
	}

	/**
	 * Reparent one panel to the editor container, preserving the child-key chain
	 * its lost ancestors carried, and wire up the events that no longer bubble
	 * to this widget.
	 */
	private hoistDropdownPanel(panel: HTMLElement, trigger: HTMLElement): void {
		const align = panel.getAttribute('snc-dropdown-align') || 'left';

		// Capture child-key chain before removing from DOM (ancestors will be lost).
		// A panel nested inside an already-hoisted one (a chip menu on a column
		// search row) has no `snc-child-key` ancestors left to walk - they went
		// with the outer panel, which carries what it found as a chain - so
		// inherit that instead of starting over with an empty one.
		const childKeyChain: string[] = [];
		let ancestor = panel.parentElement;
		while (ancestor && ancestor !== this.domNode) {
			const ck = ancestor.getAttribute('snc-child-key');
			if (ck) { childKeyChain.push(ck); }
			const inherited = ancestor.getAttribute('snc-child-key-chain');
			if (inherited) { childKeyChain.push(...JSON.parse(inherited) as string[]); }
			ancestor = ancestor.parentElement;
		}
		if (childKeyChain.length > 0) {
			panel.setAttribute('snc-child-key-chain', JSON.stringify(childKeyChain));
		}

		// Collect the scroll containers between trigger and widget root before the
		// panel leaves the DOM; they drive repositionHoistedDropdowns. A nested
		// panel's trigger sits in an already-hoisted panel, so the walk stops at
		// the editor container rather than passing through the widget root.
		const scrollers: HTMLElement[] = [];
		const container = this.editor.getContainerDomNode();
		let scrollAncestor: HTMLElement | null = trigger.parentElement;
		while (scrollAncestor
			&& scrollAncestor !== this.domNode.parentElement
			&& scrollAncestor !== container) {
			if (VisualizationWidget.isScrollableElement(scrollAncestor)) {
				scrollers.push(scrollAncestor);
			}
			scrollAncestor = scrollAncestor.parentElement;
		}
		const visibilityHost = trigger.closest('.segment-label-anchor') as HTMLElement | null;

		// Remove from the widget DOM
		panel.remove();

		// Measured after the panel leaves so it can't be mistaken for the
		// visible control.
		const measureTarget = VisualizationWidget.resolveMeasureTarget(trigger);

		panel.style.position = 'fixed';
		panel.style.zIndex = '10000';

		// Append to the editor's container so it escapes widget overflow
		container.appendChild(panel);
		const entry: IHoistedDropdown = { panel, trigger, measureTarget, align, scrollers, visibilityHost };
		this.hoistedDropdowns.push(entry);
		this.positionHoistedDropdown(entry);

		// Apply saved child-key chain from before hoisting
		const wrapHoistedEvent = (raw: string, attrEl: Element): string => {
			let wrapped = this.wrapWithChildKeys(raw, attrEl.parentElement, panel);
			const chainStr = panel.getAttribute('snc-child-key-chain');
			if (chainStr) {
				for (const ck of JSON.parse(chainStr) as string[]) {
					wrapped = `ChildEvent(${ck}, ${JSON.stringify(wrapped)})`;
				}
			}
			return wrapped;
		};

		// Wire up event listeners on the hoisted panel
		// (since it's outside this.domNode, normal event bubbling won't reach our listeners)
		this.hoistedDropdownListeners.push(
			dom.addDisposableListener(panel, 'mousedown', (ev: MouseEvent) => {
				if (!ev.target) { return; }
				const node = ev.target as Node;
				let el: Element | null = node.nodeType === Node.ELEMENT_NODE ? (node as Element) : (node.parentElement);
				while (el && el !== panel.parentElement) {
					if (el.hasAttribute('snc-mouse-down')) {
						const pythonEventStr = wrapHoistedEvent(el.getAttribute('snc-mouse-down') ?? '', el);
						this.onPointerEvent(pythonEventStr, ev);
						// Innermost handler wins; walking on would double-fire when
						// a panel row nests snc-mouse-down inside another (matches
						// the hover-menu walker).
						break;
					}
					el = el.parentElement;
				}
			})
		);
		this.hoistedDropdownListeners.push(
			dom.addDisposableListener(panel, 'keydown', (ev: KeyboardEvent) => {
				const target = ev.target as HTMLElement;
				if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA')) {
					const isAllowedKey = ev.key === 'Enter' || ev.key === 'Escape';
					const isMetaCombo = ev.metaKey && (ev.key === 'Backspace' || ev.key === 'r');
					if (!isAllowedKey && !isMetaCombo) {
						ev.stopPropagation();
						return;
					}
				}
				// Walk up within the hoisted panel for snc-key-down
				let el: Element | null = target;
				while (el && el !== panel.parentElement) {
					if (el.hasAttribute('snc-key-down')) {
						const pythonEventStr = wrapHoistedEvent(el.getAttribute('snc-key-down') ?? '', el);
						this.onKeyboardEvent(pythonEventStr, ev);
						return;
					}
					el = el.parentElement;
				}
				// Fall back to the widget DOM (the snc-key-down handler is on
				// the visualizer's wrapper div inside this.domNode, not in the panel)
				const keyHandler = this.domNode.querySelector('[snc-key-down]');
				if (keyHandler) {
					let pythonEventStr: string = keyHandler.getAttribute('snc-key-down') ?? '';
					pythonEventStr = this.wrapWithChildKeys(pythonEventStr, keyHandler.parentElement, this.domNode);
					this.onKeyboardEvent(pythonEventStr, ev);
				}
			})
		);
		this.hoistedDropdownListeners.push(...this.simpleTooltipListeners(panel, container));
		// Handles inside the panel (the column ▾ menu's tally headers) are out of
		// the widget root's reach now, so they need their own set too.
		this.hoistedDropdownListeners.push(...this.pyExpListeners(panel, container));
		// The column ▾ menu is one of these, and its rows are what dwelling on
		// opens and closes — so this is the set that actually does the work.
		this.hoistedDropdownListeners.push(
			...this.dwellListeners(panel, container, wrapHoistedEvent));
		this.hoistedDropdownListeners.push(
			dom.addDisposableListener(panel, 'input', (ev: Event) => {
				const target = ev.target as HTMLElement;
				if (!target) { return; }
				let el: Element | null = target;
				while (el && el !== panel.parentElement) {
					if (el.hasAttribute('snc-input')) {
						const pythonEventStr = wrapHoistedEvent(el.getAttribute('snc-input') ?? '', el);
						const value = (target as HTMLInputElement).value ?? '';
						this.noteTypedValue(el, value);
						this.onInputEvent(pythonEventStr, value);
						return;
					}
					el = el.parentElement;
				}
			})
		);
	}

	/**
	 * The box a hoisted panel should be placed against.
	 *
	 * Usually the trigger itself, but a trigger whose only in-flow content was
	 * the panel has a degenerate box: the segment-label trigger is an
	 * inline-flex holding nothing but an absolutely positioned `.segment-label`,
	 * so it measures 0x0 at its anchor's inline origin rather than where the
	 * label paints. Fall back to the first child that occupies space.
	 */
	private static resolveMeasureTarget(trigger: HTMLElement): HTMLElement {
		const rect = trigger.getBoundingClientRect();
		if (rect.width > 0 || rect.height > 0) { return trigger; }
		for (const child of Array.from(trigger.children).filter(dom.isHTMLElement)) {
			const childRect = child.getBoundingClientRect();
			if (childRect.width > 0 || childRect.height > 0) { return child; }
		}
		return trigger;
	}

	/**
	 * Place one hoisted panel under (or above) its trigger, clamped into the
	 * viewport. A panel's position follows whatever it hangs off - for a column
	 * menu that is wherever that column happens to sit - so it can't be assumed
	 * to fit in the direction its `snc-dropdown-align` asks for.
	 */
	private positionHoistedDropdown(entry: IHoistedDropdown): void {
		const { panel, measureTarget, align, scrollers, visibilityHost } = entry;

		// A trigger scrolled out of one of its scrollports is clipped away in the
		// widget, so its menu should go too rather than float over unrelated
		// content. A zero-area port clips nothing, so it constrains nothing.
		const triggerRect = measureTarget.getBoundingClientRect();
		const clippedAway = visibilityHost
			? visibilityHost.style.visibility === 'hidden'
			: scrollers.some((scroller) => {
				const port = scroller.getBoundingClientRect();
				if (port.width === 0 || port.height === 0) { return false; }
				return triggerRect.right <= port.left
					|| triggerRect.left >= port.right
					|| triggerRect.bottom <= port.top
					|| triggerRect.top >= port.bottom;
			});
		panel.style.visibility = clippedAway ? 'hidden' : '';

		const targetWindow = dom.getWindow(this.editor.getContainerDomNode());
		const viewportWidth = targetWindow.innerWidth;
		const viewportHeight = targetWindow.innerHeight;

		// Lay out at the requested alignment first, then measure: the panel sizes
		// itself to its content, so its width isn't known before it is placed.
		// 'flyout' hangs the panel's top-left off the trigger's top-right rather
		// than dropping it below - it reads as belonging to the control it came
		// from instead of to the row beneath it.
		const isFlyout = align === 'flyout';
		panel.style.top = `${isFlyout ? triggerRect.top : triggerRect.bottom}px`;
		if (isFlyout) {
			panel.style.left = `${triggerRect.right}px`;
			panel.style.right = '';
		} else if (align === 'right') {
			panel.style.left = '';
			panel.style.right = `${viewportWidth - triggerRect.right}px`;
		} else {
			panel.style.left = `${triggerRect.left}px`;
			panel.style.right = '';
		}

		const panelRect = panel.getBoundingClientRect();
		if (panelRect.right > viewportWidth) {
			// A flyout mirrors to the trigger's other side, keeping the tops
			// aligned; the drop-down alignments just slide back into view.
			const mirroredLeft = triggerRect.left - panelRect.width;
			const fallbackLeft = Math.max(0, viewportWidth - panelRect.width);
			panel.style.right = '';
			panel.style.left = `${isFlyout && mirroredLeft >= 0 ? mirroredLeft : fallbackLeft}px`;
		} else if (panelRect.left < 0) {
			panel.style.right = '';
			panel.style.left = '0px';
		}
		if (panelRect.bottom > viewportHeight) {
			// A flyout slides up to fit - flipping it across the trigger would
			// leave it pointing at nothing. A drop-down flips above its trigger,
			// unless there's even less room up there.
			//
			// Flipping crosses the trigger, so the panel's margin-top - the gap,
			// pushing it down and away when it hangs below - now pushes it up and
			// INTO the trigger: back that out, then leave the same gap above.
			const flippedTop = triggerRect.top - panelRect.height
				- 2 * VisualizationWidget.MENU_GAP;
			const slidTop = Math.max(0, viewportHeight - panelRect.height);
			panel.style.top = `${!isFlyout && flippedTop >= 0 ? flippedTop : slidTop}px`;
		}
	}

	private repositionHoistedDropdowns(): void {
		for (const entry of this.hoistedDropdowns) {
			this.positionHoistedDropdown(entry);
		}
	}

	/**
	 * Remove all hoisted dropdown panels and dispose their event listeners.
	 */
	private cleanupHoistedDropdowns(): void {
		for (const entry of this.hoistedDropdowns) {
			entry.panel.remove();
		}
		this.hoistedDropdowns = [];
		for (const d of this.hoistedDropdownListeners) {
			d.dispose();
		}
		this.hoistedDropdownListeners = [];
	}

	/**
	 * Reparent each segment-label anchor out of its scrollable
	 * `.string-visualizer` (whose `overflow` would clip the absolutely
	 * positioned label) onto the widget root. The anchor is zero-width; we set
	 * its left/top so it lands exactly where it sat inline, and the inner
	 * `.segment-label` keeps its original relative offsets so the visuals are
	 * unchanged - just no longer clipped.
	 *
	 * The anchor stays a descendant of `this.domNode`, so the existing
	 * mousedown delegation continues to resolve `snc-mouse-down`; we stash any
	 * `snc-child-key` ancestors as `snc-child-key-chain` so nested-model events
	 * still resolve after the move.
	 */
	private hoistSegmentLabels(): void {
		const anchors = Array.from(this.domNode.querySelectorAll('.segment-label-anchor'))
			.filter(dom.isHTMLElement)
			// Skip anything already at the widget root (defensive; shouldn't happen).
			.filter((a) => a.parentElement !== this.domNode);
		if (anchors.length === 0) { return; }

		const widgetRect = this.domNode.getBoundingClientRect();
		const scrollers = new Set<HTMLElement>();

		for (const anchor of anchors) {
			const scroller = anchor.closest('.string-visualizer') as HTMLElement | null;
			if (!scroller) { continue; }

			// Capture position + child-key chain BEFORE detaching (ancestors are
			// lost once removed from the DOM).
			const anchorRect = anchor.getBoundingClientRect();
			const childKeyChain: string[] = [];
			let ancestor = anchor.parentElement;
			while (ancestor && ancestor !== this.domNode) {
				const ck = ancestor.getAttribute('snc-child-key');
				if (ck) { childKeyChain.push(ck); }
				ancestor = ancestor.parentElement;
			}
			if (childKeyChain.length > 0) {
				anchor.setAttribute('snc-child-key-chain', JSON.stringify(childKeyChain));
			}

			const baseLeft = anchorRect.left - widgetRect.left;
			const baseTop = anchorRect.top - widgetRect.top;

			anchor.remove();
			anchor.style.left = `${baseLeft}px`;
			anchor.style.top = `${baseTop}px`;
			this.domNode.appendChild(anchor);

			this.hoistedSegmentLabels.push({
				anchor,
				scroller,
				baseLeft,
				baseTop,
				baseScrollLeft: scroller.scrollLeft,
				baseScrollTop: scroller.scrollTop,
			});
			scrollers.add(scroller);
		}

		// Keep labels glued to their characters as the string scrolls, and hide
		// any that scroll outside their container's visible box.
		this.repositionHoistedSegmentLabels();
		for (const scroller of scrollers) {
			this.hoistedSegmentLabelListeners.push(
				dom.addDisposableListener(scroller, 'scroll', () => this.repositionHoistedSegmentLabels())
			);
		}
	}

	private setupResizableColumns(): void {
		const resiable_col_handles = Array.from(this.domNode.querySelectorAll<HTMLElement>('.col-resize-handle')).filter(dom.isHTMLElement);

		for (const handle of resiable_col_handles) {
			const col = handle.closest<HTMLElement>('.col-header');
			const table = col?.closest<HTMLElement>('.list-table-scroll');
			if (!col || !table) { continue; }

			const col_attr = col.dataset['col']!;
			const cells = Array.from(table.querySelectorAll<HTMLElement>('td[data-col="' + CSS.escape(col_attr) + '"]'));

			let currWidth = 0;
			let mouseX = 0;

			const beginResizing = (e: PointerEvent) => {
				currWidth = col!.offsetWidth - 10; // Subtract the padding
				handle.onpointermove = resize;

				mouseX = e.clientX;

			  handle.setPointerCapture(e.pointerId);
			}

			const stopResizing = (e: PointerEvent) => {
				handle.onpointermove = null;
				handle.releasePointerCapture(e.pointerId);

				// const event: UiEventSpec = {
				// 	line: link.line,
				// 	visIndex: link.visIndex,
				// 	pythonEventStr: 'lambda e: Unlink()',
				// 	eventJSON: { type: 'unlink' },
				// };

				const augmented_e = { ...e, resizeWidth: currWidth, target: handle };
				this.dispatch_mouse_python_event('snc-resize-col', augmented_e);

				mouseX = 0;
				currWidth = 0;
			};

			const resize = (e: PointerEvent) => {
				const dx = e.clientX - mouseX;
				currWidth += dx;
				mouseX = e.clientX;

				[...cells, col!].forEach(cell => {
					cell.style.maxWidth = `${currWidth}px`;
					cell.style.minWidth = `${currWidth}px`;
					cell.style.overflow = 'hidden';
				});
			};


			this._register(dom.addDisposableListener(handle, 'pointerdown', beginResizing));
			this._register(dom.addDisposableListener(handle, 'pointerup', stopResizing));
		}
	}

	private hoistNestedToolbars(): void {
		const anchors = Array.from(this.domNode.querySelectorAll('.visualizer-container .visualizer-container > .toolbar-anchor'))
			.filter(dom.isHTMLElement)
			// Skip anything already at the widget root (defensive; shouldn't happen).
			.filter((a) => a.parentElement !== this.domNode);
		if (anchors.length === 0) { return; }

		const widgetRect = this.domNode.getBoundingClientRect();
		const scrollers = new Set<HTMLElement>();

		for (const anchor of anchors) {
			const scroller = anchor.closest('.snc-base-visualizer') as HTMLElement | null;
			if (!scroller) { continue; }

			// Capture position + child-key chain BEFORE detaching (ancestors are
			// lost once removed from the DOM).
			const anchorRect = anchor.getBoundingClientRect();
			const childKeyChain: string[] = [];
			let ancestor = anchor.parentElement;
			while (ancestor && ancestor !== this.domNode) {
				const ck = ancestor.getAttribute('snc-child-key');
				if (ck) { childKeyChain.push(ck); }
				ancestor = ancestor.parentElement;
			}
			if (childKeyChain.length > 0) {
				anchor.setAttribute('snc-child-key-chain', JSON.stringify(childKeyChain));
			}

			const baseLeft = anchorRect.left - widgetRect.left;
			const baseTop = anchorRect.top - widgetRect.top - 10;

			// The toolbar hangs below its visualizer, and for the last row of a
			// list that is below the scroller's bottom edge -- so the toolbar can't
			// answer for itself whether it has scrolled out of view. The container
			// it came out of stays in flow and does.
			const clipTarget = anchor.parentElement ?? undefined;

			anchor.remove();
			anchor.style.left = `${baseLeft}px`;
			anchor.style.top = `${baseTop}px`;
			anchor.classList.add('toolbar-anchor-hoisted');
			this.domNode.appendChild(anchor);

			this.hoistedSegmentLabels.push({
				anchor,
				scroller,
				baseLeft,
				baseTop,
				baseScrollLeft: scroller.scrollLeft,
				baseScrollTop: scroller.scrollTop,
				clipTarget,
			});
			scrollers.add(scroller);
		}



		// Keep labels glued to their characters as the string scrolls, and hide
		// any that scroll outside their container's visible box.
		this.repositionHoistedSegmentLabels();
		for (const scroller of scrollers) {
			this.hoistedSegmentLabelListeners.push(
				dom.addDisposableListener(scroller, 'scroll', () => this.repositionHoistedSegmentLabels())
			);
		}
	}

	/**
	 * Recompute hoisted segment-label positions from their scroll container and
	 * hide any that have scrolled out of the container's visible area.
	 */
	private repositionHoistedSegmentLabels(): void {
		if (this.hoistedSegmentLabels.length === 0) { return; }
		const widgetRect = this.domNode.getBoundingClientRect();
		for (const entry of this.hoistedSegmentLabels) {
			const { anchor, scroller, baseLeft, baseTop, baseScrollLeft, baseScrollTop, clipTarget } = entry;
			// Re-glue to the character: shift the anchor by the scroll delta since
			// it was hoisted (content scrolls left/up => label follows).
			const left = baseLeft - (scroller.scrollLeft - baseScrollLeft);
			const top = baseTop - (scroller.scrollTop - baseScrollTop);
			anchor.style.left = `${left}px`;
			anchor.style.top = `${top}px`;

			// Hide when the character has scrolled outside the scroller's visible
			// box (so labels don't float over neighbouring content). Compare the
			// anchor's viewport position against the scroller's. The small top
			// slack accounts for labels rendered just above the line.
			const scrollerRect = scroller.getBoundingClientRect();
			let outOfView: boolean;
			if (clipTarget) {
				// Whatever the anchor belongs to is still in flow inside the
				// scroller, so its rect already carries the scroll. It counts as in
				// view while any of it is, the anchor being allowed to hang outside.
				const targetRect = clipTarget.getBoundingClientRect();
				outOfView = targetRect.right < scrollerRect.left - 1
					|| targetRect.left > scrollerRect.right + 1
					|| targetRect.bottom < scrollerRect.top - 1
					|| targetRect.top > scrollerRect.bottom + 1;
			} else {
				const anchorViewportLeft = widgetRect.left + left;
				const anchorViewportTop = widgetRect.top + top;
				outOfView = anchorViewportLeft < scrollerRect.left - 1
					|| anchorViewportLeft > scrollerRect.right + 1
					|| anchorViewportTop < scrollerRect.top - 12
					|| anchorViewportTop > scrollerRect.bottom + 1;
			}
			anchor.style.visibility = outOfView ? 'hidden' : '';
		}

		// A hoisted anchor is absolutely positioned at the widget root, so it
		// only moves when the loop above writes its offsets. Any panel hanging
		// off one has to be re-placed afterwards, not from its own scroll
		// listener, which would read the pre-scroll position.
		this.repositionHoistedDropdowns();
	}

	/**
	 * Dispose segment-label scroll listeners. The reparented anchors live inside
	 * `this.domNode` and are discarded when its innerHTML is replaced (or when
	 * the widget is disposed), so they need no explicit removal here.
	 */
	private cleanupHoistedSegmentLabels(): void {
		for (const d of this.hoistedSegmentLabelListeners) {
			d.dispose();
		}
		this.hoistedSegmentLabelListeners = [];
		this.hoistedSegmentLabels = [];
	}

	/**
	 * Update the widget's position (called when scrolling or content changes)
	 */
	updatePosition(): void {
		this.editor.layoutOverlayWidget(this);
	}

	/**
	 * Take every code-handing attribute off a read-only render, so that even
	 * HTML that still carries one (a visualizer that doesn't know about the
	 * setting, say) has no handle to drag, no action to hover, and no shortcut
	 * into a code box. Python leaves these out already; this is the editor
	 * making sure.
	 */
	private stripCodeAffordances(root: HTMLElement): void {
		const attrs = ['snc-py-exps', 'data-action-expr', 'snc-add-at-cursor', 'snc-add-target', 'snc-py-exp-align'];
		for (const el of Array.from(root.querySelectorAll(attrs.map(a => `[${a}]`).join(',')))) {
			for (const attr of attrs) {
				el.removeAttribute(attr);
			}
			el.classList.remove('py-exp-grab');
		}
		for (const el of Array.from(root.querySelectorAll('[draggable="true"]'))) {
			el.removeAttribute('draggable');
		}
	}

	/**
	 * Show/update or hide the link-chain icon in the widget's lower-left corner.
	 *
	 * - 'hidden':   no chain (widget doesn't support linking, or isn't focused).
	 * - 'linked':   accent chain; hovering it (or the arrow) swaps to an ✕ that
	 *               unlinks on click.
	 * - 'unlinked': dimmed chain that persists so the user can re-link; clicking
	 *               it re-establishes a link.
	 */
	setLinkChain(state: 'hidden' | 'linked' | 'unlinked'): void {
		// Linking writes a line of code; a read-only visualizer offers no chain.
		if (state === 'hidden' || this.isReadOnly()) {
			if (this.linkChainEl) {
				this.linkChainEl.remove();
				this.linkChainEl = null;
			}
			return;
		}
		// A link already points at a specific line, which need not be the next
		// one; only re-linking is defined in terms of the next line.
		const tooltip = state === 'linked'
			? 'Unlink from line of code'
			: 'Link to next line of code';
		if (!this.linkChainEl) {
			const chain = document.createElement('div');
			chain.className = 'snc-link-chain';
			// Set data-tooltip before appendChild so a mouseover that fires
			// when the icon appears under the cursor already sees the attribute
			// (the delegated tooltip attacher runs during insertion).
			chain.setAttribute('data-tooltip', tooltip);
			const icon = document.createElement('span');
			icon.className = 'snc-link-chain-icon';
			const setIconSvg = (svg: string) => {
				if (svg) {
					icon.innerHTML = (ttPolicy?.createHTML(svg) ?? svg) as string;
				}
			};
			if (chainSvgMarkup !== null) {
				setIconSvg(chainSvgMarkup);
			} else {
				// SVG still loading: fill the icon once it arrives.
				loadChainSvg().then(setIconSvg);
			}
			const x = document.createElement('span');
			x.className = 'snc-link-chain-x';
			x.textContent = '\u2715'; // ✕
			chain.appendChild(icon);
			chain.appendChild(x);
			// Swallow the mousedown so it neither starts a visualizer drag nor
			// (in small mode) triggers click-to-expand.
			this._register(dom.addDisposableListener(chain, 'mousedown', (ev: MouseEvent) => {
				ev.preventDefault();
				ev.stopPropagation();
				studyLog.log('widget.chainClick', { line: this.lineNumber, visIndex: this.visIndex, state: this.linkChainEl?.classList.contains('linked') ? 'linked' : 'unlinked' }, this.editor.getModel()?.uri.toString());
				this.onLinkChainClick();
			}));
			this.linkChainEl = chain;
			this.domNode.appendChild(chain);
		}
		this.linkChainEl.classList.toggle('linked', state === 'linked');
		this.linkChainEl.classList.toggle('unlinked', state === 'unlinked');
		this.linkChainEl.setAttribute('data-tooltip', tooltip);
	}

	/** Viewport rect of the chain icon, for drawing the arrow. Null if hidden. */
	getLinkChainAnchorRect(): DOMRect | null {
		if (!this.linkChainEl) {
			return null;
		}
		return this.linkChainEl.getBoundingClientRect();
	}

	/** Toggle the hover cue (chain → ✕) driven from the arrow, not the icon. */
	setLinkHoverCue(on: boolean): void {
		if (this.linkChainEl) {
			this.linkChainEl.classList.toggle('snc-link-hover', on);
		}
	}

	/**
	 * Dispose of the widget
	 */
	override dispose(): void {
		this.hidePyExpTooltip();
		this.hideActionTooltip();
		this.hideSimpleTooltip();
		this.hideHoverMenu();
		this.hideHoistedHover();
		this.cleanupHoistedDropdowns();
		this.cleanupHoistedSegmentLabels();
		this.editor.removeOverlayWidget(this);
		super.dispose();
	}
}

/**
 * The slider beside a loop header (or a `def`) that picks which iteration (or
 * call) the lines inside it show. It sits at the end of the line, ahead of the
 * line's own visualizer, which moves over by `WIDTH` to make room.
 */
class LoopSliderWidget extends Disposable implements IOverlayWidget {
	/** Width in px, including the gap to the visualizer after it. */
	static readonly WIDTH = 136;

	private readonly domNode: HTMLElement;
	private readonly input: HTMLInputElement;
	private readonly label: HTMLElement;
	private count = 0;
	/** The thumb is the user's while it's pressed; nothing else moves it. */
	private dragging = false;

	constructor(
		private readonly editor: ICodeEditor,
		private readonly lineNumber: number,
		private readonly onChange: (iteration: number) => void,
	) {
		super();
		this.domNode = document.createElement('div');
		this.domNode.className = 'snc-loop-slider';
		this.input = document.createElement('input');
		this.input.type = 'range';
		this.input.min = '0';
		this.input.step = '1';
		this.label = document.createElement('span');
		this.label.className = 'snc-loop-slider-label';
		this.domNode.appendChild(this.input);
		this.domNode.appendChild(this.label);

		this._register(dom.addDisposableListener(this.input, 'input', () => {
			const iteration = Number(this.input.value);
			studyLog.log('widget.loopSlider', { line: this.lineNumber, iteration, max: Number(this.input.max), dragging: this.dragging }, this.editor.getModel()?.uri.toString());
			this.setLabel(iteration);
			this.onChange(iteration);
		}));
		// A press on the slider is not a click in the editor: it must not move
		// the cursor (which would also change the focused line and rerun).
		this._register(dom.addDisposableListener(this.domNode, 'mousedown', (ev: MouseEvent) => { ev.stopPropagation(); }));
		this._register(dom.addDisposableListener(this.input, 'pointerdown', () => { this.dragging = true; }));
		this._register(dom.addDisposableListener(this.input, 'pointerup', () => { this.dragging = false; }));
		this._register(dom.addDisposableListener(this.input, 'pointercancel', () => { this.dragging = false; }));
		// Arrow keys step the slider rather than moving the cursor.
		this._register(dom.addDisposableListener(this.input, 'keydown', (ev: KeyboardEvent) => { ev.stopPropagation(); }));

		this.editor.addOverlayWidget(this);
	}

	getId(): string {
		return `editor.contrib.sncLoopSlider-${this.lineNumber}`;
	}

	getDomNode(): HTMLElement {
		return this.domNode;
	}

	getPosition(): IOverlayWidgetPosition | null {
		const model = this.editor.getModel();
		if (!model || this.lineNumber > model.getLineCount()) {
			return null;
		}
		const column = model.getLineMaxColumn(this.lineNumber);
		const pixelPosition = this.editor.getScrolledVisiblePosition({ lineNumber: this.lineNumber, column });
		if (!pixelPosition) {
			return null;
		}
		return { preference: { top: pixelPosition.top, left: pixelPosition.left + 8 } };
	}

	/** Show `iteration` of `count`. */
	update(count: number, iteration: number): void {
		this.count = count;
		if (this.dragging) {
			// Repositioning the thumb under a drag would end it; the label
			// tracks what the thumb says, and the next update settles the rest.
			this.input.max = String(Math.max(Number(this.input.max), count - 1));
			this.setLabel(Number(this.input.value));
			return;
		}
		this.input.max = String(Math.max(0, count - 1));
		this.input.value = String(iteration);
		this.setLabel(iteration);
	}

	private setLabel(iteration: number): void {
		this.label.textContent = `${iteration + 1} / ${this.count}`;
	}

	updatePosition(): void {
		this.editor.layoutOverlayWidget(this);
	}

	override dispose(): void {
		this.editor.removeOverlayWidget(this);
		super.dispose();
	}
}

/**
 * If the inserted edit text introduces a new identifier the user is likely to want
 * to rename (an assignment target or a `for` loop iteration variable), return a
 * Selection covering that identifier in the post-edit document.
 *
 * - Variable assignment `<indent><name> = <expr>` → selects `<name>`.
 * - For loop `<indent>for <name> in ...` → selects `<name>`.
 * - For loop with tuple unpacking `<indent>for <i>, <name> in ...` → selects the
 *   non-index name (the last variable), since the index is usually fine as-is.
 * - Imports and other statements → returns null (no selection change).
 *
 * `insertedRange` is the range of the inserted text in the post-edit document
 * (as returned by `pushEditOperations`'s inverseEditOperations). When
 * `isPrependedToFirstLine` is true the inserted text is `editText + '\n'` placed
 * at the start of the file; otherwise it's `'\n' + editText` placed after some
 * existing line, so the first line of editText starts on the line after
 * `insertedRange.startLineNumber`.
 */
/**
 * The comment a visualizer's saved config lives in -- see "Per-line config"
 * in visualizer_utils.py. It trails the line it configures: `#%click` at the
 * start of the line or after whitespace (and followed by whitespace or the
 * end of the line), running to the end of the line. Mirrors
 * _CONFIG_COMMENT_RE in visualizer_utils.py.
 */
const CONFIG_COMMENT_PREFIX = '#%click';
const CONFIG_COMMENT_RE = new RegExp(`(?:^|(?<=\\s))${CONFIG_COMMENT_PREFIX}(?=\\s|$)`);

/**
 * Column of the `#` where `lineContent`'s trailing `#%click` comment starts,
 * or 0 when the line has none.
 */
function configCommentStartColumn(lineContent: string): number {
	const match = CONFIG_COMMENT_RE.exec(lineContent);
	return match ? match.index + 1 : 0;
}

/**
 * `lineContent` without its trailing `#%click` comment and the whitespace
 * separating it from the code, for the places that must see only the code:
 * linked ranges, takeover checks.
 */
function stripConfigComment(lineContent: string): string {
	const startCol = configCommentStartColumn(lineContent);
	return startCol ? lineContent.slice(0, startCol - 1).trimEnd() : lineContent;
}

/** Identifies a widget within a run: its line and its site on that line. */
function widgetKey(line: number, visIndex: number): string {
	return `${line}:${visIndex}`;
}

/**
 * How far into the program a run may start -- the `execution_step` of the
 * earliest widget it has to render itself, or undefined when it has to start
 * from the top. A warm worker paused at or before this can serve the run by
 * running forward; see `IProcessOptions.checkpoint3ResumeAtStep`.
 *
 * Every widget with events still queued counts, not just the one being
 * dispatched -- which is already among them, since `runProgram` queues the
 * event before it gets here. Nothing else stops a pre-checkpoint widget's
 * events from sitting out a run that starts past them and then being swept at
 * run end with no run scheduled to answer them: `scheduleQueuedEventRun` fires
 * only when an item arrives, and no item arrives for a widget behind the pause.
 */
export function resumeAtStepFor(items: readonly IVisualizationItem[]): number | undefined {
	let earliest: number | undefined;
	for (const item of items) {
		if (item.unhandledEvents?.length && (earliest === undefined || item.execution_step < earliest)) {
			earliest = item.execution_step;
		}
	}
	return earliest;
}

/**
 * The items to keep when a run ends. Ordinarily just the run's own: anything
 * older would show a visualizer for a line whose content has changed.
 *
 * A run served by a checkpoint 3 worker emits no item for the widgets behind
 * its pause -- they ran during the warm, and the copies already on screen are
 * the ones that run produced. Those are kept, and re-stamped with this run's id
 * so the *next* run's filter still passes them.
 */
export function carryForwardItems(items: readonly IVisualizationItem[], currentRunId: string, resumedFromStep: number | null): IVisualizationItem[] {
	if (resumedFromStep === null) {
		return items.filter(item => item.runId === currentRunId);
	}
	return items
		.filter(item => item.runId === currentRunId || item.execution_step < resumedFromStep)
		.map(item => item.runId === currentRunId ? item : { ...item, runId: currentRunId });
}

/** How many lines an insert edit adds; several imports can share one edit. */
function editLineCount(edit: NewCodeEdit): number {
	return edit.text.split('\n').length;
}

/**
 * One expression a handle offers: the code, whatever it can't run without, and
 * what it reads as when the code alone doesn't say.
 */
interface IPyExp {
	readonly expr: string;
	readonly imports: string[];
	readonly label?: string;
}

/**
 * What an expression handle offers, in the order the visualizer listed it
 * (`snc-py-exps`, or `data-action-expr` on an action button -- both written by
 * `py_exp_attrs` in visualizer_utils.py). The first is the one the handle
 * itself drags; the rest are the tooltip's to show.
 *
 * Empty for a handle with nothing to hand over, so a caller can ask without
 * checking first.
 */
function pyExpsOf(el: Element | null, attr: string): IPyExp[] {
	const raw = el?.getAttribute(attr);
	if (!raw) {
		return [];
	}
	try {
		const parsed = JSON.parse(raw);
		if (!Array.isArray(parsed)) {
			return [];
		}
		return parsed
			.filter(entry => entry && typeof entry.expr === 'string')
			.map(entry => ({
				expr: entry.expr as string,
				imports: Array.isArray(entry.imports)
					? entry.imports.filter((i: unknown) => typeof i === 'string')
					: [],
				label: typeof entry.label === 'string' ? entry.label : undefined,
			}));
	} catch {
		return [];
	}
}

/**
 * Put a dragged expression on the clipboard data in both forms: `text/plain` so
 * it can land anywhere, and SNC's own mime carrying the imports beside it so a
 * drop into a Python editor can bring them along (see SncPyExpDropProvider).
 */
function setPyExpDragData(dataTransfer: DataTransfer, expression: string, imports: string[]): void {
	dataTransfer.setData('text/plain', expression);
	dataTransfer.setData(SNC_PY_EXP_MIME, JSON.stringify({ expr: expression, imports }));
	dataTransfer.effectAllowed = 'copy';
}

/**
 * The edits that add whatever a generated expression needs imported, skipping
 * anything the file already has.
 *
 * The visualizer that wrote the code declares the imports — on a NewCode
 * command, or beside the expression they belong to in `snc-py-exps` on a drag
 * handle. Where they go is pythonImportInsertion's single answer, so the two
 * ways in agree; several missing imports share one edit, landing in the order
 * they were declared.
 */
function importEdits(model: ITextModel, imports: readonly string[] | undefined): NewCodeEdit[] {
	if (!imports?.length) {
		return [];
	}
	const lines = model.getLinesContent();
	const missing: string[] = [];
	let insertion: IPythonImportInsertion | undefined;
	for (const importStatement of imports) {
		const where = pythonImportInsertion(lines, importStatement);
		if (where) {
			missing.push(importStatement);
			insertion = where;
		}
	}
	if (!insertion || !missing.length) {
		return [];
	}
	const edits: NewCodeEdit[] = [
		{ type: 'insert', afterLine: insertion.afterLine, text: missing.join('\n') },
	];
	if (insertion.needsSeparator) {
		edits.push({ type: 'insert', afterLine: insertion.afterLine, text: '' });
	}
	return edits;
}

function computeRenameSelectionForEdit(editText: string, isPrependedToFirstLine: boolean, insertedRange: Range): Selection | null {
	const firstLine = editText.split('\n')[0] ?? '';

	let baseLine: number;
	let baseCol: number;
	if (isPrependedToFirstLine) {
		baseLine = insertedRange.startLineNumber;
		baseCol = insertedRange.startColumn;
	} else {
		baseLine = insertedRange.startLineNumber + 1;
		baseCol = 1;
	}

	// Variable assignment: `<indent><name> = ...` (avoid matching `==`).
	const assignMatch = firstLine.match(/^(\s*)([A-Za-z_][A-Za-z0-9_]*)\s*=(?!=)/);
	if (assignMatch) {
		const prefix = assignMatch[1];
		const name = assignMatch[2];
		const startCol = baseCol + prefix.length;
		return new Selection(baseLine, startCol, baseLine, startCol + name.length);
	}

	// `for <name>[, <name>...] in ...` → select the last name. For tuple
	// unpacking the leading names are usually indices (e.g. `i`) while the
	// trailing name is the actual item the user wants to rename.
	const forMatch = firstLine.match(/^(\s*for\s+)([A-Za-z_][A-Za-z0-9_]*(?:\s*,\s*[A-Za-z_][A-Za-z0-9_]*)*)\s+in\b/);
	if (forMatch) {
		const prefix = forMatch[1];
		const varList = forMatch[2];
		const idRegex = /[A-Za-z_][A-Za-z0-9_]*/g;
		let lastIdStart = 0;
		let lastId = '';
		let m: RegExpExecArray | null;
		while ((m = idRegex.exec(varList)) !== null) {
			lastIdStart = m.index;
			lastId = m[0];
		}
		const startCol = baseCol + prefix.length + lastIdStart;
		return new Selection(baseLine, startCol, baseLine, startCol + lastId.length);
	}

	return null;
}

/**
 * Whether `expr` is a Python expression that can legally sit on the right-hand
 * side of an assignment (`<name> = <expr>`). Some visualizer-generated snippets
 * are whole statements rather than expressions — e.g. `for item in xs:\n    pass`
 * or `if any(...):\n    pass` — and assigning those to a variable would produce
 * invalid Python, so the tooltip's "new var" button is suppressed for them.
 */
export function isAssignableExpression(expr: string): boolean {
	const e = expr.trim();
	if (!e) { return false; }
	// Generated statements (for/if/while bodies) always span multiple lines.
	if (/\n/.test(e)) { return false; }
	// A leading statement keyword means it isn't an expression.
	if (/^(?:for|while|if|elif|else|with|def|class|return|import|from|pass|raise|try|except|finally|del|global|nonlocal|assert|break|continue|async|yield)\b/.test(e)) {
		return false;
	}
	// A bare assignment/target list (`x = ...`, `a, b = ...`) isn't an RHS.
	// Guard against comparison/aug ops so `x == y`, `x <= y`, `x += y` stay.
	if (/^[A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*\s*=(?!=)/.test(e)) { return false; }
	return true;
}

const NEW_VAR_METHOD_NAMES: Record<string, string> = {
	join: 'joined', upper: 'uppercased', lower: 'lowercased',
	strip: 'stripped', lstrip: 'stripped', rstrip: 'stripped',
	split: 'parts', rsplit: 'parts', splitlines: 'lines',
	replace: 'replaced', title: 'titled', capitalize: 'capitalized',
	findall: 'matches', finditer: 'matches', group: 'group', groups: 'groups',
	keys: 'keys', values: 'values', items: 'entries',
};

const NEW_VAR_FUNC_NAMES: Record<string, string> = {
	len: 'length', sum: 'total', min: 'minimum', max: 'maximum',
	sorted: 'ordered', reversed: 'reversed', any: 'result', all: 'result',
	next: 'match', list: 'items', set: 'unique', tuple: 'items',
	dict: 'mapping', abs: 'absolute', round: 'rounded', count: 'count',
	Counter: 'tally',
};

/**
 * Suggest a descriptive base variable name for an expression, so the "new var"
 * tooltip action inserts something more meaningful than `new_var`. Falls back to
 * `new_var` when no reasonable name can be derived. The caller is responsible for
 * de-duplicating the name against identifiers already in the document.
 *
 * Heuristics (first match wins): a trailing method call (`s.upper()` → `uppercased`),
 * a leading builtin/function call (`len(x)` → `length`, `foo(...)` → `foo`), a
 * comprehension's iterable (`[i for i in orfs]` → `orfs`), or the leading root
 * identifier of a subscript/attribute chain (`data[0]` → `data`).
 */
export function suggestVarNameForExpression(expr: string): string {
	const e = expr.trim();
	if (!e) { return 'new_var'; }

	// Prefer the last method call: `<...>.method(...)`.
	const methodMatches = [...e.matchAll(/\.([A-Za-z_]\w*)\s*\(/g)];
	if (methodMatches.length > 0) {
		const name = methodMatches[methodMatches.length - 1][1];
		return NEW_VAR_METHOD_NAMES[name] ?? name;
	}

	// A leading function/builtin call: `len(x)`, `any(...)`, `foo(...)`.
	const funcMatch = e.match(/^([A-Za-z_]\w*)\s*\(/);
	if (funcMatch) {
		const name = funcMatch[1];
		return NEW_VAR_FUNC_NAMES[name] ?? name;
	}

	// A comprehension / generator: name after the iterable's root identifier.
	const compMatch = e.match(/\bfor\b[\s\S]*?\bin\s+([A-Za-z_]\w*)/);
	if (compMatch) { return compMatch[1]; }

	// Subscript / attribute / plain reference: use the leading root identifier.
	const rootMatch = e.match(/^([A-Za-z_]\w*)/);
	if (rootMatch) { return rootMatch[1]; }

	return 'new_var';
}

/**
 * Every live controller in this window, and how many runs have reached a
 * conclusion. Both exist for `_sncPythonStatus` (see the end of the
 * constructor), which is what `ui_testing_tools/wait_for_python.js` polls.
 *
 * Window-wide rather than per-editor because the backend is one worker pool
 * shared by every editor, and a test asking "is Python done?" has no way to
 * know which editor's controller to ask. An idle controller contributes
 * nothing, so the union across all of them is the honest answer.
 */
const sncControllers = new Set<SNCController>();

/**
 * Storage key for the "are SNC widgets shown" flag. One boolean for the whole
 * profile, not per editor: hiding the visualizers is a mode the user is in
 * ("let me just read the code for a while"), not a property of any one file,
 * and a per-file flag would mean re-hiding in every tab. Profile scope so it
 * follows the user across workspaces, and USER target so it syncs with the
 * rest of their preferences.
 */
const SNC_WIDGETS_VISIBLE_KEY = 'snc.widgetsVisible';

/**
 * The small eye button in the editor's top-right corner that toggles all SNC
 * widgets. It is the one piece of SNC chrome that stays when the widgets are
 * hidden, so it is what brings them back. Sits next to the find widget's
 * corner as an overlay widget, so it never occupies a line of code; it is
 * faded until hovered so it does not compete with the text under it.
 */
class ToggleWidgetsButton extends Disposable implements IOverlayWidget {
	private static nextId = 0;
	private readonly id = `snc.toggleWidgetsButton.${ToggleWidgetsButton.nextId++}`;
	private readonly domNode: HTMLElement;
	private readonly icon: HTMLElement;
	private readonly hover = this._register(new DisposableStore());

	constructor(
		private readonly editor: ICodeEditor,
		private readonly hoverService: IHoverService,
		onToggle: () => void,
	) {
		super();
		this.domNode = document.createElement('div');
		this.domNode.className = 'snc-toggle-widgets-button';
		this.domNode.setAttribute('role', 'button');
		this.domNode.tabIndex = 0;
		this.icon = document.createElement('span');
		this.domNode.appendChild(this.icon);
		this._register(dom.addDisposableListener(this.domNode, 'click', e => {
			e.preventDefault();
			e.stopPropagation();
			onToggle();
		}));
		this._register(dom.addDisposableListener(this.domNode, 'keydown', (e: KeyboardEvent) => {
			if (e.key === 'Enter' || e.key === ' ') {
				e.preventDefault();
				onToggle();
			}
		}));
		this.editor.addOverlayWidget(this);
	}

	/** Reflect the global flag: the icon shows what clicking will do. */
	setVisible(widgetsVisible: boolean): void {
		const label = widgetsVisible
			? localize('sncHideWidgets', "Hide Clickacode Visualizers")
			: localize('sncShowWidgets', "Show Clickacode Visualizers");
		this.icon.className = ThemeIcon.asClassName(widgetsVisible ? Codicon.eye : Codicon.eyeClosed);
		this.domNode.classList.toggle('snc-widgets-hidden', !widgetsVisible);
		this.domNode.setAttribute('aria-label', label);
		this.domNode.setAttribute('aria-pressed', String(!widgetsVisible));
		this.hover.clear();
		this.hover.add(this.hoverService.setupDelayedHover(this.domNode, {
			content: label,
			style: HoverStyle.Pointer,
		}));
	}

	getId(): string {
		return this.id;
	}

	getDomNode(): HTMLElement {
		return this.domNode;
	}

	getPosition(): IOverlayWidgetPosition | null {
		return { preference: OverlayWidgetPositionPreference.TOP_RIGHT_CORNER };
	}

	override dispose(): void {
		this.editor.removeOverlayWidget(this);
		super.dispose();
	}
}
let sncRunsSettled = 0;

export class SNCController extends Disposable implements IEditorContribution {
	public static readonly ID = 'editor.contrib.snc';

	static get(editor: ICodeEditor): SNCController | null {
		return editor.getContribution<SNCController>(SNCController.ID);
	}

	/**
	 * Whether SNC's widgets are on screen. Global across every editor (see
	 * SNC_WIDGETS_VISIBLE_KEY); this is the storage value as of the last
	 * change event. Python keeps running while hidden and `visualizationItems`
	 * keeps filling, so showing again is a redraw, not a rerun -- but nothing
	 * is rendered into the DOM until then.
	 */
	private widgetsVisible = true;
	private toggleWidgetsButton: ToggleWidgetsButton | null = null;

	private visualizationWidgets: Map<number, VisualizationWidget[]> = new Map();
	private viewZones: Map<number, string> = new Map(); // line number -> view zone id
	// Synthetic empty space above line 1. Used to keep a focused/clicked
	// visualizer pixel-stable when content above it shrinks while the file is
	// scrolled near the top: scrollTop can't go below 0, so the deficit is
	// added as a spacer instead of letting the anchor jump upward.
	private topSpacerZoneId: string | null = null;
	private topSpacerHeight = 0;
	private isAdjustingTopSpacer = false;
	/**
	 * Height in px of each line's view zone, kept in step with `viewZones`.
	 * A zone can only be resized by removing and re-adding it, which relays out
	 * everything below; knowing the current height lets us skip that when the
	 * new height is the same (the common case on a hover re-render).
	 */
	private viewZoneHeights: Map<number, number> = new Map();
	private debounceTimer: any = null;
	/** The folded-away JSON of each `#%click` comment; see updateConfigCommentFolding. */
	private readonly configCommentDecorations = this.editor.createDecorationsCollection();

	/**
	 * The one config comment shown in full, or null. Opened only by clicking
	 * its chip (onConfigCommentMouseDown); folds again for good once the
	 * cursor leaves its line, until the next click.
	 */
	private openConfigCommentLine: number | null = null;
	private readonly debounceDelay = 100; // ms

	// Streaming state
	private currentRunId: string | null = null;
	/**
	 * Where each line the run in flight was told about has got to since: keyed
	 * by the number Python was given, valued at the number the file has now.
	 *
	 * A command names the line its visualizer was on when the run's source was
	 * taken, and the file can have moved on before the command lands -- an
	 * import this run inserted above it, a sibling's config comment, the user
	 * typing. Kept in step by adjustVisualizationItemsForContentChange, beside
	 * the item and link lines it already corrects, so all three agree about
	 * where a widget went.
	 */
	private readonly reportedLineNow = new Map<number, number>();
	/**
	 * File whose console the run in flight belongs to. Held separately from the
	 * editor's model because the user can switch tabs mid-run, and the output
	 * still belongs to the file that produced it.
	 */
	private consoleFilePath: string = '';
	// True from the moment runProgram commits to a run until that run has an id.
	// It awaits the cancellation of the previous run in between, and a status
	// poll landing in that gap would otherwise see no run in flight and no run
	// scheduled, and call the backend idle just as it is starting work.
	private runStarting = false;

	/** Source of `UiEvent.id`, stamped in sendEventToPython. */
	private lastEventId = 0;

	/**
	 * Widgets the current run has already produced an item for. A run can still
	 * be handed events for a widget it hasn't reached; once it has, anything
	 * further needs a new run. Cleared when a run starts.
	 */
	private readonly itemsThisRun = new Set<string>();

	/**
	 * The widget the user last interacted with, and so the one worth warming a
	 * worker up to -- see `IProcessOptions.checkpoint3WarmAt`. Cleared on a
	 * model change and on any edit: it holds a raw line number, and an edit
	 * above it moves the widget without moving this.
	 */
	private lastInteractedWidget: { line: number; visIndex: number } | null = null;

	/**
	 * The `execution_step` the current run resumed from, when a warm worker
	 * served it; null on every other run. Widgets before it produce no item this
	 * run, so the copies already on screen are carried forward at run end.
	 */
	private resumedFromStep: number | null = null;

	/** Pending `queued-events` rerun, so a burst of items only schedules one. */
	private requeuedRunTimer: any = null;

	// Sticky notification shown when the python executable can't be launched
	// (e.g. neither the Python extension's selection nor the 'python3'
	// fallback exists). Auto-dismissed when a subsequent run starts producing
	// output, indicating Python is working again.
	private pythonSpawnFailureNotification: INotificationHandle | null = null;

	// ---- Loop sliders ----
	/**
	 * The iteration each loop (or function) is pinned to. A pin is keyed by a
	 * decoration on the header line rather than the line number, so inserting
	 * lines above it doesn't re-key it. Sent to Python on every run as
	 * `loopSelections`; a loop with no pin shows its first iteration.
	 */
	private loopSelections: { decorationId: string; iteration: number }[] = [];
	/**
	 * How many iterations each loop/def header line ran, from `loop` messages.
	 * Mid-run this only grows (a function reports after every call, and a
	 * slider that shrank -- or vanished, at count 1 -- under a drag would end
	 * it); the run's final counts replace it when the run ends.
	 */
	private loopCounts: Map<number, number> = new Map();
	/** Counts reported by the run in flight. */
	private loopCountsThisRun: Map<number, number> = new Map();
	private loopSliders: Map<number, LoopSliderWidget> = new Map();

	private _visualizationItems: IVisualizationItem[] = [];
	/**
	 * How far the DOM is behind the items. Bumped by every assignment to
	 * `visualizationItems` and caught up by `updateVisualizationWidgets`, so
	 * `itemsVersion !== renderedVersion` means Python has handed over HTML that
	 * is not on screen yet. A property pair rather than a flag set at each of
	 * the assignment sites: there are five of them, spread across the stream
	 * handler, the content-change adjuster and the error paths, and one missed
	 * would make the status quietly wrong in the direction that matters (saying
	 * it is rendered when it is not).
	 */
	private itemsVersion = 0;
	private renderedVersion = 0;
	private get visualizationItems(): IVisualizationItem[] {
		return this._visualizationItems;
	}
	private set visualizationItems(items: IVisualizationItem[]) {
		this._visualizationItems = items;
		this.itemsVersion++;
	}
	private syntaxErrorActive = false;
	private streamSubscription: { dispose(): void } | null = null;
	private streamUpdateTimer: any = null;
	private cursorUpdateTimer: any = null;

	// Focus state for small-mode handling. Default focused line is the cursor
	// line; clicking a small widget pins focus to its line until the cursor
	// moves to a different line. The effective focused line is sent to Python
	// on every run so log_value can render non-focused lines with small=True.
	private explicitFocusedLine: number | null = null;
	private lastCursorLine: number | null = null;
	private focusRerunTimer: any = null;
	private readonly focusRerunDelay = 150; // ms

	// Linked-editing state: each entry tracks one editor range that is live-synced
	// with a specific visualizer, keyed by that visualizer's (line, visIndex).
	// A per-visualizer list (rather than a single global link) is required so
	// several linked lines can coexist without cross-talk: an update from one
	// visualizer must edit its own inserted line, not whichever line was linked
	// most recently. Every link is established programmatically (by an
	// auto-generated LOC or a chain-icon relink); there is no user-text-selection
	// path anymore.
	private linkedSelections: {
		line: number;
		visIndex: number;
		decorationId: string;
	}[] = [];
	// SVG arrows drawn from a focused, linked visualizer's chain icon to its
	// linked line of code, keyed by `${line}:${visIndex}`. Only top-level
	// widgets get an arrow — nested visualizers never do.
	private linkArrows: Map<string, HTMLElement> = new Map();
	// Guards our own linked-line rewrite (ChangeSelectedText) so the resulting
	// model-content change doesn't make pruneDeadLinks react to the momentary
	// mid-edit decoration collapse.
	private isApplyingLinkedEdit = false;
	// (line:visIndex) keys that already received a reconciliation Unlink, so we
	// don't repeatedly re-send it while Python converges. Cleared once the model
	// stops claiming to be linked.
	private reconciledUnlinkKeys: Set<string> = new Set();

	// Timing tracking: all frontend times use performance.now()
	private runTriggerMsById: Map<string, number> = new Map();        // When runProgram was called (frontend)
	private runSpawnTimingById: Map<string, SNCTimingData> = new Map(); // Backend spawn timing data
	private runFirstItemReceivedMsById: Map<string, number> = new Map(); // When first 'item' message received (frontend)
	private runFirstRenderMsById: Map<string, number> = new Map();    // When first render completed synchronously (frontend)
	private runFirstRenderFrameMsById: Map<string, number> = new Map(); // When first render frame completed via rAF (frontend)

	// Event-target timing: same measurements but for the visualizer that received the event
	private runEventTargetById: Map<string, { line: number; visIndex: number }> = new Map();
	private runEventTargetItemReceivedMsById: Map<string, number> = new Map();
	private runEventTargetRenderMsById: Map<string, number> = new Map();
	private runEventTargetRenderFrameMsById: Map<string, number> = new Map();

	// ---- Study logging ----
	/**
	 * Mouse move/out events that go to Python are logged in abbreviated form:
	 * one record when the Python event string (i.e. the hovered target) changes,
	 * otherwise at most one per 250ms, with the count of suppressed events on
	 * the next record and a trailing record after the pointer settles.
	 */
	private readonly moveLogCoalescer = new StudyLogCoalescer('widget.mouseMove', 250);

	/**
	 * The last mousemove sent to Python, as line:visIndex:eventStr:payload.
	 * A repeat of it is skipped (same model in, same model out); anything that
	 * can change the model -- another event, a run from an edit -- clears it,
	 * so the same move becomes worth sending again.
	 */
	private lastSentMoveKey: string | null = null;
	/** What each run was started for, keyed by run id, so run.end can say. */
	private runTriggerById: Map<string, string> = new Map();
	private runStartWallById: Map<string, number> = new Map();

	constructor(
		private readonly editor: ICodeEditor,
		@IMainProcessService private readonly mainProcessService: IMainProcessService,
		@IWorkspaceContextService private readonly workspaceContextService: IWorkspaceContextService,
		@IHostService private readonly hostService: IHostService,
		@IEditorService private readonly editorService: IEditorService,
		@IClipboardService private readonly clipboardService: IClipboardService,
		@ICommandService private readonly commandService: ICommandService,
		@IConfigurationService private readonly configurationService: IConfigurationService,
		@INotificationService private readonly notificationService: INotificationService,
		@ISNCConsoleService private readonly consoleService: ISNCConsoleService,
		@IStorageService private readonly storageService: IStorageService,
		@IHoverService private readonly hoverService: IHoverService,
	) {
		super();

		this.widgetsVisible = this.storageService.getBoolean(SNC_WIDGETS_VISIBLE_KEY, StorageScope.PROFILE, true);
		// Every controller listens to storage rather than to the one that was
		// clicked, so a toggle in any editor reaches every editor (and any
		// other window sharing the profile).
		this._register(this.storageService.onDidChangeValue(StorageScope.PROFILE, SNC_WIDGETS_VISIBLE_KEY, this._store)(() => {
			this.applyWidgetsVisible(this.storageService.getBoolean(SNC_WIDGETS_VISIBLE_KEY, StorageScope.PROFILE, true));
		}));
		this.updateToggleWidgetsButton();

		// The stdin document is an input to the program exactly like the source
		// is, so editing it reruns on the same debounce.
		this._register(this.consoleService.onDidChangeStdin(filePath => {
			if (filePath === this.currentFilePath()) {
				this.scheduleRun('stdin');
			}
		}));

		// Register event handlers
		this._register(editor.onDidChangeModelContent((e) => { this.onDidChangeModelContent(e); }));
		this._register(editor.onDidChangeModel(() => {
			// Cancel anything in-flight from the previous model so its results
			// don't leak into the new (potentially non-Python) editor.
			if (this.debounceTimer) {
				clearTimeout(this.debounceTimer);
				this.debounceTimer = null;
			}
			this.cancelCurrentRun();
			this.visualizationItems = [];
			this.clearVisualizationWidgets();
			this.loopSelections = [];
			this.lastInteractedWidget = null;
			this.openConfigCommentLine = null;
			this.updateToggleWidgetsButton();
			// Set up language change listener for the new model
			this.setupLanguageChangeListener();
			// Re-resolve the Python interpreter for the new model's workspace
			// folder. In multi-root workspaces the user may have a different
			// interpreter selected per-folder.
			this.resolveAndSetPythonExecutable();
			this.updateConfigCommentFolding();
			// Trigger initial visualization when a new model loads
			this.triggerInitialVisualization();
		}));
		this._register(editor.onDidDispose(() => {
			this.clearVisualizationWidgets();
			this.toggleWidgetsButton?.dispose();
			this.toggleWidgetsButton = null;
		}));
		this._register(editor.onDidChangeCursorPosition(e => {
			// An open config comment folds again as soon as the cursor leaves
			// its line -- and stays folded until its chip is clicked again.
			if (this.openConfigCommentLine !== null && e.position.lineNumber !== this.openConfigCommentLine) {
				this.openConfigCommentLine = null;
			}
			this.updateConfigCommentFolding();
			this.onCursorPositionChanged();
		}));
		this._register(editor.onMouseDown(e => { this.onConfigCommentMouseDown(e); }));

		// Register scroll event handler to update overlay widget positions
		this._register(editor.onDidScrollChange(() => {
			this.updateOverlayWidgetPositions();
			this.absorbTopSpacerOnScroll();
		}));

		// Register window focus change handler to update visualizations when window becomes visible
		this._register(this.hostService.onDidChangeFocus((focused: boolean) => {
			if (focused) {
				this.onWindowBecameVisible();
			}
		}));

		// Register editor visibility change handler to update visualizations when editors become visible
		this._register(this.editorService.onDidVisibleEditorsChange(() => {
			this.onEditorsVisibilityChanged();
		}));

		// Set up language change listener for the initial model
		this.setupLanguageChangeListener();

		// Trigger initial visualization when controller is created
		this.triggerInitialVisualization();

		// Track shift/alt/ctrl held state on document.body so the string visualizer's
		// tool toolbar can highlight the transient override (shift -> literal,
		// option/alt -> fuzzy, ctrl -> index) and switch the visualizer's
		// chrome (e.g. hide regex anchors in index mode) without a Python roundtrip.
		// Ctrl (not cmd/meta) is the index modifier - cmd is reserved for
		// cmd-backspace / cmd-r / cmd-z editor actions.
		// Listening on window catches releases that happen outside the editor DOM.
		this._register(dom.addDisposableListener(window, 'keydown', (ev: KeyboardEvent) => {
			if (ev.shiftKey) { document.body.classList.add('snc-shift-down'); }
			if (ev.altKey) { document.body.classList.add('snc-alt-down'); }
			if (ev.ctrlKey) { document.body.classList.add('snc-ctrl-down'); }
		}, true));
		this._register(dom.addDisposableListener(window, 'keyup', (ev: KeyboardEvent) => {
			if (!ev.shiftKey) { document.body.classList.remove('snc-shift-down'); }
			if (!ev.altKey) { document.body.classList.remove('snc-alt-down'); }
			if (!ev.ctrlKey) { document.body.classList.remove('snc-ctrl-down'); }
		}, true));
		this._register(dom.addDisposableListener(window, 'blur', () => {
			document.body.classList.remove('snc-shift-down');
			document.body.classList.remove('snc-alt-down');
			document.body.classList.remove('snc-ctrl-down');
		}));

		// Re-resolve the Python interpreter when the user edits the relevant
		// settings. Status-bar interpreter picks aren't surfaced as a config
		// change, but tab switches re-resolve via onDidChangeModel above.
		this._register(this.configurationService.onDidChangeConfiguration(e => {
			if (e.affectsConfiguration('python.defaultInterpreterPath')
				|| e.affectsConfiguration('python.pythonPath')) {
				this.resolveAndSetPythonExecutable();
			}
			// The affordances are in the rendered HTML, so a change to the
			// setting is a re-render: rerun, and hide the chains right away
			// (they are the editor's own chrome, not Python's).
			if (e.affectsConfiguration(SNC_READ_ONLY_VISUALIZERS_SETTING)) {
				this.updateLinkChrome();
				this.scheduleRun();
			}
		}));

		this.updateConfigCommentFolding();

		// Initial resolve. This races with the first run's pool spawn — if
		// the resolve loses, the first run uses 'python3' and subsequent
		// runs pick up the resolved interpreter once setPythonExecutable
		// drains/refills the pools.
		this.resolveAndSetPythonExecutable();

		// Exposed for ui_testing_tools/ CDP scripts (buffer.js, scroll.js).
		// Monaco only renders visible lines in the DOM, so CDP can't read the
		// full text buffer or control scroll position without model access.
		(globalThis as any)._sncEditor = editor;

		// Exposed for ui_testing_tools/wait_for_python.js. Nothing in the DOM
		// says whether Python is still working -- a visualizer mid-run looks
		// exactly like a finished one -- so a test that clicked something has no
		// way to know when to start reading. See `pythonStatus`.
		sncControllers.add(this);
		this._register({ dispose: () => { sncControllers.delete(this); } });
		(globalThis as any)._sncPythonStatus = () => SNCController.pythonStatus();
	}

	/**
	 * Whether the window still has Python work outstanding, and why.
	 *
	 * `runsSettled` matters as much as `busy` does: a window that has not
	 * started its first run yet is idle in exactly the same way as one that has
	 * finished, so a waiter has to see a run conclude before it believes an idle
	 * reading. `reasons` is for the timeout message -- "still busy" is not worth
	 * printing, "still running" versus "still scheduled" is.
	 */
	private static pythonStatus(): { python: boolean | null; busy: boolean; reasons: string[]; runsSettled: number } {
		const reasons = new Set<string>();
		// null until some editor has a model to have an opinion about. A
		// controller exists from the moment its editor is constructed, which
		// during startup is before the file it will show has loaded -- and
		// answering `false` there reads as "no run is coming", which is how a
		// waiter concludes it has nothing to wait for and starts reading a
		// window that has not drawn yet.
		let python: boolean | null = null;
		for (const controller of sncControllers) {
			if (controller.editor.getModel()) {
				python = python || controller.isPythonModel();
			}
			if (controller.runStarting) { reasons.add('starting'); }
			if (controller.currentRunId) { reasons.add('running'); }
			if (controller.debounceTimer) { reasons.add('scheduled'); }
			if (controller.focusRerunTimer) { reasons.add('focus-rerun'); }
			if (controller.cursorUpdateTimer) { reasons.add('re-rendering'); }
			if (controller.itemsVersion !== controller.renderedVersion) { reasons.add('un-rendered'); }
		}
		return { python, busy: reasons.size > 0, reasons: [...reasons], runsSettled: sncRunsSettled };
	}

	/**
	 * Ask the Python extension which interpreter to use for the current
	 * editor's workspace folder, and forward it to the main-process pool.
	 * Falls back to `'python3'` whenever the Python extension is missing,
	 * not yet activated, or returns nothing useful.
	 */
	private async resolveAndSetPythonExecutable(): Promise<void> {
		let executable = 'python3';
		try {
			const model = this.editor.getModel();
			const folder = model
				? this.workspaceContextService.getWorkspaceFolder(model.uri)
				: this.workspaceContextService.getWorkspace().folders[0];
			if (folder) {
				const resolved = await this.commandService.executeCommand<string>(
					'python.interpreterPath',
					{ workspaceFolder: folder.uri.fsPath }
				);
				if (resolved && resolved.length > 0) {
					executable = resolved;
				}
			}
		} catch {
			// Python extension not installed / not activated yet / command
			// errored out — keep the 'python3' fallback.
		}

		try {
			const channel = this.mainProcessService.getChannel('sncProcess');
			await channel.call('setPythonExecutable', [executable]);
		} catch (err) {
			console.error('SNC: failed to set Python executable on main process:', err);
		}
	}

	private showPythonSpawnFailureNotification(message: string): void {
		if (this.pythonSpawnFailureNotification) {
			this.pythonSpawnFailureNotification.updateMessage(message);
			return;
		}
		const handle = this.notificationService.notify({
			id: 'snc.python-spawn-failure',
			severity: Severity.Error,
			message,
			sticky: true,
		});
		this.pythonSpawnFailureNotification = handle;
		handle.onDidClose(() => {
			if (this.pythonSpawnFailureNotification === handle) {
				this.pythonSpawnFailureNotification = null;
			}
		});
	}

	private dismissPythonSpawnFailureNotification(): void {
		if (!this.pythonSpawnFailureNotification) { return; }
		const handle = this.pythonSpawnFailureNotification;
		this.pythonSpawnFailureNotification = null;
		try { handle.close(); } catch { /* ignore */ }
	}

	getProgram(): string {
		return this.editor.getModel()!.getLinesContent().join('\n');
	}

	/**
	 * SNC only runs for Python files. All execution paths (initial visualization,
	 * keystroke debounce, editor visibility change, UI events) funnel through
	 * runProgram, which short-circuits for non-Python models, but most callers
	 * also gate themselves to avoid scheduling no-op timers.
	 */
	/** Flip the global flag; storage's change event does the actual work. */
	toggleWidgetsVisible(): void {
		const visible = !this.storageService.getBoolean(SNC_WIDGETS_VISIBLE_KEY, StorageScope.PROFILE, true);
		this.storageService.store(SNC_WIDGETS_VISIBLE_KEY, visible, StorageScope.PROFILE, StorageTarget.USER);
	}

	/**
	 * Hide: tear down every widget, slider, arrow and view zone so the code
	 * reflows as if SNC were not there, keeping the items and loop counts.
	 * Show: draw what those hold. Either way the button stays.
	 */
	private applyWidgetsVisible(visible: boolean): void {
		if (visible === this.widgetsVisible) {
			return;
		}
		this.widgetsVisible = visible;
		this.toggleWidgetsButton?.setVisible(visible);
		if (!this.isPythonModel()) {
			return;
		}
		if (visible) {
			this.updateConfigCommentFolding();
			this.updateLoopSliders();
			this.updateVisualizationWidgets(this.visualizationItems);
		} else {
			this.removeWidgetDom();
			this.updateConfigCommentFolding();
		}
	}

	/** The button exists exactly while the editor shows a Python model. */
	private updateToggleWidgetsButton(): void {
		if (this.isPythonModel()) {
			if (!this.toggleWidgetsButton) {
				this.toggleWidgetsButton = new ToggleWidgetsButton(this.editor, this.hoverService, () => this.toggleWidgetsVisible());
			}
			this.toggleWidgetsButton.setVisible(this.widgetsVisible);
		} else if (this.toggleWidgetsButton) {
			this.toggleWidgetsButton.dispose();
			this.toggleWidgetsButton = null;
		}
	}

	private isPythonModel(): boolean {
		const model = this.editor.getModel();
		if (!model) {
			return false;
		}
		const languageId = model.getLanguageId();
		return languageId === 'python' || languageId === 'py';
	}

	onDidChangeModelContent(e: IModelContentChangedEvent): void {
		if (!this.isPythonModel()) {
			return;
		}
		this.updateConfigCommentFolding();

		// An edit above it shifts the widget without shifting the raw line
		// number stored here -- including a NewCode edit the visualizer itself
		// just asked for. A target nothing logs at makes every warm worker
		// execute the whole program speculatively and exit with nothing, so
		// forget it and let the next interaction re-establish it. Costs one
		// checkpoint-2-served run, which is what an edit costs anyway.
		this.lastInteractedWidget = null;

		// Immediately adjust visualization items for line changes (deletions/insertions)
		// so stale visualizers don't linger on deleted or shifted lines.
		this.adjustVisualizationItemsForContentChange(e);

		// Drop links whose tracked range collapsed or vanished (e.g. the user
		// deleted the linked line). Skip while we ourselves are rewriting a
		// linked range via ChangeSelectedText — that edit is not a teardown.
		if (!this.isApplyingLinkedEdit) {
			this.pruneDeadLinks();
		}

		// Debounce to avoid running on every keystroke
		if (this.debounceTimer) {
			clearTimeout(this.debounceTimer);
		}

		this.debounceTimer = setTimeout(() => {
			this.debounceTimer = null;
			this.runProgram(this.getProgram(), undefined, 'edit');
		}, this.debounceDelay);
	}

	/**
	 * Adjust visualization items when lines are inserted or deleted.
	 * Removes items on deleted lines and shifts line numbers for items below the change.
	 * This ensures visualizers don't appear on stale/wrong lines during the debounce
	 * period before the new run completes.
	 */
	private adjustVisualizationItemsForContentChange(e: IModelContentChangedEvent): void {
		if (this.visualizationItems.length === 0) {
			return;
		}

		// Process changes bottom-to-top to avoid cascading offset issues
		// (each change uses original line numbers; processing bottom-up means
		// earlier changes don't affect the line numbers of later changes)
		const changes = [...e.changes].sort((a, b) => b.range.startLineNumber - a.range.startLineNumber);
		let itemsChanged = false;

		for (const change of changes) {
			const startLine = change.range.startLineNumber;
			const endLine = change.range.endLineNumber;
			const oldLineCount = endLine - startLine + 1;
			const newLineCount = (change.text.match(/\n/g) || []).length + 1;
			const lineDelta = newLineCount - oldLineCount;

			if (lineDelta === 0) {
				continue;
			}

			// A pure insertion at the very start of a line (empty range at
			// column 1) prepends whole lines, pushing that line's existing content
			// — and any visualizer anchored to it — downward. This happens when an
			// auto-generated line of code also injects `import re` at the top of the
			// file. Shift items at or below the insertion line so their models stay
			// matched to the right source line.
			const isStartOfLineInsertion =
				change.range.startLineNumber === change.range.endLineNumber
				&& change.range.startColumn === change.range.endColumn
				&& change.range.startColumn === 1
				&& lineDelta > 0;

			const newItems: IVisualizationItem[] = [];

			for (const item of this.visualizationItems) {
				if (isStartOfLineInsertion && item.line >= startLine) {
					// Content at/below the insertion point moved down.
					newItems.push({ ...item, line: item.line + lineDelta });
					itemsChanged = true;
				} else if (item.line < startLine) {
					// Before the change: unaffected
					newItems.push(item);
				} else if (item.line > endLine) {
					// After the change: shift line number
					newItems.push({ ...item, line: item.line + lineDelta });
					itemsChanged = true;
				} else if (lineDelta < 0 && item.line > startLine + newLineCount - 1) {
					// Within the changed range, on a line that was deleted
					itemsChanged = true;
					// Don't push - remove this item
				} else {
					// Within the changed range but on a line that still exists
					// (content may have changed; will be corrected by the re-run)
					newItems.push(item);
				}
			}

			this.visualizationItems = newItems;

			// Keep linked-selection keys aligned with the shifted visualizer
			// lines. The linked range decoration tracks its own position via
			// stickiness; here we only fix each link's (line) key so a later
			// ChangeSelectedText from that visualizer still resolves to it.
			if (this.linkedSelections.length > 0) {
				const survivingLinks: typeof this.linkedSelections = [];
				const deadLinks: typeof this.linkedSelections = [];
				for (const link of this.linkedSelections) {
					if (isStartOfLineInsertion && link.line >= startLine) {
						link.line += lineDelta;
						survivingLinks.push(link);
					} else if (link.line < startLine) {
						survivingLinks.push(link);
					} else if (link.line > endLine) {
						link.line += lineDelta;
						survivingLinks.push(link);
					} else if (lineDelta < 0 && link.line > startLine + newLineCount - 1) {
						// The visualizer's trigger line was deleted; tear down.
						deadLinks.push(link);
					} else {
						survivingLinks.push(link);
					}
				}
				this.linkedSelections = survivingLinks;
				for (const link of deadLinks) {
					this.teardownLink(link);
				}
			}

			// And the lines the run in flight was told about, by the same rule:
			// a command still names the number it was given, so this is what
			// says where that line is now. A line that was deleted keeps its
			// last position rather than being dropped -- a command for it is
			// answered by handleSetConfigComment's own bounds check, and a
			// missing key would silently read as "never moved".
			for (const [reported, current] of this.reportedLineNow) {
				if (isStartOfLineInsertion ? current >= startLine : current > endLine) {
					this.reportedLineNow.set(reported, current + lineDelta);
				}
			}
		}

		if (itemsChanged) {
			this.updateVisualizationWidgets(this.visualizationItems);
		}
	}

	private onWindowBecameVisible(): void {
		// Re-render existing visualizations when window becomes visible
		const data = this.visualizationItems;
		if (data && data.length > 0) {
			this.updateVisualizationWidgets(data);
		}
	}

	private onCursorPositionChanged(): void {
		// Re-render visualizations when cursor moves; do NOT rerun the program
		const data = this.visualizationItems;
		if (!data || data.length === 0) {
			this.lastCursorLine = this.cursorFocusLine();
			return;
		}
		if (this.cursorUpdateTimer) {
			clearTimeout(this.cursorUpdateTimer);
		}
		this.cursorUpdateTimer = setTimeout(() => {
			this.cursorUpdateTimer = null;
			this.updateVisualizationWidgets(data);
		}, 50);

		// When the cursor moves to a different line, the effective focused line
		// changes (cursor line is the default). Drop any pinned focus from a
		// prior click and trigger a debounced re-run so non-focused widgets
		// re-render with small=True (and the new focused widget renders full).
		const newLine = this.cursorFocusLine();
		if (newLine !== this.lastCursorLine) {
			this.lastCursorLine = newLine;
			this.explicitFocusedLine = null;
			if (this.isPythonModel()) {
				if (this.focusRerunTimer) { clearTimeout(this.focusRerunTimer); }
				this.focusRerunTimer = setTimeout(() => {
					this.focusRerunTimer = null;
					this.runProgram(this.getProgram(), undefined, 'cursor-line');
				}, this.focusRerunDelay);
			}
		}
	}

	/**
	 * The 1-indexed line the cursor is attending to.
	 *
	 * Usually just the cursor's line, but a whole-line selection (triple click,
	 * or a drag that runs past the end of a line) swallows the trailing newline,
	 * leaving the cursor parked at column 1 of the *next* line. The user is
	 * looking at the selected text, not at the empty position after it, so
	 * credit the last line that actually has something selected — otherwise
	 * focus (and the scroll anchor pinned to it) slides one line down and the
	 * selected line moves out from under the pointer.
	 */
	private cursorFocusLine(): number | null {
		const selection = this.editor.getSelection();
		if (!selection) { return null; }
		if (!selection.isEmpty()
			&& selection.getDirection() === SelectionDirection.LTR
			&& selection.endLineNumber > selection.startLineNumber
			&& selection.endColumn === 1) {
			return selection.endLineNumber - 1;
		}
		return selection.getPosition().lineNumber;
	}

	/**
	 * The 1-indexed line whose top-level visualizer should render full-size.
	 * Cursor line by default; an explicit pin (from clicking a small widget)
	 * wins until the cursor moves to a different line.
	 */
	private effectiveFocusedLine(): number | null {
		if (this.explicitFocusedLine !== null) {
			return this.explicitFocusedLine;
		}
		return this.cursorFocusLine();
	}

	/**
	 * Pin focus to `line` and immediately re-run so that line's top-level
	 * widget renders with `small=False`. Called when the user clicks a small
	 * (non-focused) widget.
	 */
	private requestExpand(line: number): void {
		if (this.effectiveFocusedLine() === line) { return; }
		studyLog.log('widget.expand', { line, previousFocusedLine: this.effectiveFocusedLine() }, this.editor.getModel()?.uri.toString());
		this.explicitFocusedLine = line;
		// Cancel any pending cursor-driven re-run; this click supersedes it.
		if (this.focusRerunTimer) {
			clearTimeout(this.focusRerunTimer);
			this.focusRerunTimer = null;
		}
		if (this.isPythonModel()) {
			this.runProgram(this.getProgram(), undefined, 'expand');
		}
	}

	/** Find the link tracked for a specific visualizer, if any. */
	private findLink(line: number, visIndex: number) {
		return this.linkedSelections.find(l => l.line === line && l.visIndex === visIndex);
	}

	/**
	 * Record (or update) the link for a visualizer. Replaces any existing entry
	 * for the same (line, visIndex) in place, keeping the list one-per-visualizer.
	 */
	private setLink(line: number, visIndex: number, decorationId: string): void {
		const existing = this.findLink(line, visIndex);
		if (existing) {
			existing.decorationId = decorationId;
		} else {
			this.linkedSelections.push({ line, visIndex, decorationId });
		}
	}

	/**
	 * Remove a link locally only: drop its decoration and its linkedSelections
	 * entry (and its arrow), WITHOUT notifying Python. Used when the model
	 * already agrees the link is gone, so sending Unlink would only trigger a
	 * pointless re-run.
	 */
	private removeLinkLocal(link: { line: number; visIndex: number; decorationId: string }): void {
		const editorModel = this.editor.getModel();
		if (editorModel) {
			editorModel.deltaDecorations([link.decorationId], []);
		}
		this.linkedSelections = this.linkedSelections.filter(l => l !== link);
		this.removeLinkArrow(`${link.line}:${link.visIndex}`);
	}

	/**
	 * Fully tear down a link: remove it locally and notify the visualizer so its
	 * Python model clears linked_action (stops emitting ChangeSelectedText into a
	 * dead range).
	 */
	private teardownLink(link: { line: number; visIndex: number; decorationId: string }): void {
		this.removeLinkLocal(link);
		const event: UiEventSpec = {
			line: link.line,
			visIndex: link.visIndex,
			pythonEventStr: 'lambda e: Unlink()',
			eventJSON: { type: 'unlink' },
		};
		this.sendEventToPython(event);
	}

	/** Whether a visualizer model participates in linked editing. */
	private static supportsLinking(model: unknown): boolean {
		return !!model && typeof model === 'object' && 'linked_action' in (model as object);
	}

	/**
	 * Whether a visualizer model is currently linked, per Python's own state
	 * (its linked_action is truthy). Distinct from supportsLinking, which only
	 * checks that the model participates in linking at all.
	 */
	private static isModelLinked(model: unknown): boolean {
		return SNCController.supportsLinking(model)
			&& !!(model as { linked_action?: unknown }).linked_action;
	}

	/**
	 * Handle a click on a widget's chain icon. When the visualizer is currently
	 * linked, unlink it; otherwise (re)establish a link.
	 */
	/**
	 * Whether visualizers are read-only (clickacode.readOnlyVisualizers): views that
	 * hand out no code. Python renders without the affordances when told so
	 * (see IProcessOptions.readOnly); here it also decides what the editor
	 * refuses -- every command but a copy to the clipboard, the "+" in a
	 * tooltip, the link chain -- so that no path from a visualizer to the file
	 * stays open whatever the HTML says.
	 */
	private isReadOnly(): boolean {
		return this.configurationService.getValue<boolean>(SNC_READ_ONLY_VISUALIZERS_SETTING) === true;
	}

	private onLinkChainClick(line: number, visIndex: number): void {
		if (this.isReadOnly()) {
			return;
		}
		const editorModel = this.editor.getModel();
		const link = this.findLink(line, visIndex);
		studyLog.log('snc.chainClick', { ...this.visInfo(line, visIndex), wasLinked: !!link, linkedRange: link && editorModel ? editorModel.getDecorationRange(link.decorationId)?.toString() : undefined }, editorModel?.uri.toString());
		if (editorModel && link) {
			const range = editorModel.getDecorationRange(link.decorationId);
			if (range && !range.isEmpty()) {
				this.teardownLink(link);
				this.updateLinkChrome();
				return;
			}
		}
		this.relinkVisualizer(line, visIndex);
	}

	/**
	 * Re-establish a link for a visualizer whose chain icon was clicked while
	 * unlinked. Takes over the next line of code when the visualizer could have
	 * generated it there; otherwise inserts a fresh linked line. The concrete
	 * edit is produced by Python (Relink → ChangeSelectedText/NewCode).
	 */
	private relinkVisualizer(line: number, visIndex: number): void {
		const editorModel = this.editor.getModel();
		if (!editorModel) {
			return;
		}
		const vizIndent = this.getLineIndent(line);
		const lineCount = editorModel.getLineCount();

		// Find the first non-blank line after the visualizer's source line.
		let nextLine = 0;
		for (let l = line + 1; l <= lineCount; l++) {
			if (editorModel.getLineContent(l).trim() !== '') {
				nextLine = l;
				break;
			}
		}

		let mode: 'takeover' | 'insert' = 'insert';
		let takeoverText = '';
		if (nextLine > 0) {
			// The line's trailing config comment (if any) is not code: it stays
			// out of the shape checks, the adopted text, and the linked range.
			const nextContent = stripConfigComment(editorModel.getLineContent(nextLine));
			const nextIndent = nextContent.length - nextContent.trimStart().length;
			// Take over the line an insertion would have landed on: the same
			// block level, or the first body line when the visualizer sits on a
			// block header (a loop variable's visualizer owns code inside the
			// loop). A dedent means the block ended, so there is nothing of ours
			// to take over. The line itself must be shaped like generated code —
			// an assignment or a statement header — rather than arbitrary code.
			const ownsNextLine = nextIndent >= vizIndent;
			const takeoverable = !!SNCController.splitAssignment(nextContent)
				|| SNCController.opensBlock(nextContent);
			if (ownsNextLine && takeoverable) {
				mode = 'takeover';
				// Send the taken-over line's content so a fresh Python model can
				// adopt the existing expression instead of clobbering it.
				takeoverText = nextContent.trim();
				const linkedRange = new Range(
					nextLine, editorModel.getLineFirstNonWhitespaceColumn(nextLine) || 1,
					nextLine, nextContent.length + 1
				);
				// Link the existing line first so the ChangeSelectedText that
				// Python emits in response lands in it.
				this.establishLinkForRange(linkedRange, line, visIndex);
			}
		}

		const event: UiEventSpec = {
			line,
			visIndex,
			pythonEventStr: "lambda e: Relink(mode=e.get('mode', 'insert'), text=e.get('text', ''))",
			eventJSON: { type: 'relink', mode, text: takeoverText },
		};
		this.sendEventToPython(event);
	}

	/**
	 * Refresh chain-icon state on every top-level widget and (re)draw arrows for
	 * focused, linked visualizers. Nested visualizers are rendered inside a
	 * parent widget's HTML rather than as their own widget, so they are never
	 * considered here and never get a chain icon or arrow.
	 */
	private updateLinkChrome(): void {
		const editorModel = this.editor.getModel();
		const focusedLine = this.effectiveFocusedLine();
		const liveKeys = new Set<string>();
		for (const [lineNumber, widgets] of this.visualizationWidgets.entries()) {
			for (const widget of widgets) {
				const visIndex = widget.getVisIndex();
				const item = this.visualizationItems.find(
					it => it.line === lineNumber && it.visIndex === visIndex);
				const supported = !!item && SNCController.supportsLinking(item.model);
				const key = `${lineNumber}:${visIndex}`;
				// Chain icon and arrow are shown only for the active (focused)
				// visualizer, keeping unfocused previews uncluttered.
				if (!supported || focusedLine !== lineNumber || this.isReadOnly()) {
					widget.setLinkChain('hidden');
					this.removeLinkArrow(key);
					continue;
				}
				const link = this.findLink(lineNumber, visIndex);
				const range = link && editorModel
					? editorModel.getDecorationRange(link.decorationId) : null;
				const rangeAlive = !!range && !range.isEmpty();
				// Derive the icon state from Python's model (linked_action), gated
				// by a live front-end range. This gives the right transient
				// behavior: an unlink-click removes the decoration synchronously so
				// the icon flips to "unlinked" instantly, while a relink shows
				// "linked" only once the updated model returns.
				const isLinked = SNCController.isModelLinked(item.model) && rangeAlive;
				widget.setLinkChain(isLinked ? 'linked' : 'unlinked');
				if (isLinked && range) {
					this.drawLinkArrow(key, widget, range.startLineNumber);
					liveKeys.add(key);
				} else {
					this.removeLinkArrow(key);
				}
			}
		}
		// Drop arrows whose widget/link disappeared.
		for (const key of Array.from(this.linkArrows.keys())) {
			if (!liveKeys.has(key)) {
				this.removeLinkArrow(key);
			}
		}
	}

	/**
	 * Draw (or reposition) the arrow from a widget's chain icon to the first
	 * column of its linked line. Hidden when the linked line is scrolled out of
	 * view. Positioned with fixed/viewport coordinates like the SNC tooltips.
	 */
	private drawLinkArrow(key: string, widget: VisualizationWidget, targetLine: number): void {
		const chainRect = widget.getLinkChainAnchorRect();
		const targetPos = this.editor.getScrolledVisiblePosition({ lineNumber: targetLine, column: 1 });
		const editorDom = this.editor.getDomNode();
		if (!chainRect || !targetPos || !editorDom) {
			this.removeLinkArrow(key);
			return;
		}
		const editorRect = editorDom.getBoundingClientRect();
		const lineHeight = this.editor.getOption(EditorOption.lineHeight);

		const startX = chainRect.left;
		const startY = chainRect.top + chainRect.height / 2;
		const targetX = editorRect.left + targetPos.left - 2;
		const targetY = editorRect.top + targetPos.top + lineHeight / 2;

		// Hide when the linked line is outside the editor's visible band.
		if (targetY < editorRect.top || targetY > editorRect.bottom) {
			this.removeLinkArrow(key);
			return;
		}

		const pad = 8; // margin
		const xdist = 8; // how far left to go
		const minX = Math.min(startX, targetX) - pad - xdist;
		const minY = Math.min(startY, targetY) - pad;
		const width = Math.abs(targetX - startX) + xdist + pad * 2;
		const height = Math.abs(targetY - startY) + pad * 2;

		let svg = this.linkArrows.get(key) as unknown as SVGSVGElement | undefined;
		let path: SVGPathElement;
		if (!svg) {
			const ns = 'http://www.w3.org/2000/svg';
			svg = document.createElementNS(ns, 'svg') as SVGSVGElement;
			svg.setAttribute('class', 'snc-link-arrow');
			const markerId = `snc-link-arrowhead-${key.replace(':', '-')}`;
			const defs = document.createElementNS(ns, 'defs');
			const marker = document.createElementNS(ns, 'marker');
			marker.setAttribute('id', markerId);
			marker.setAttribute('markerWidth', '6');
			marker.setAttribute('markerHeight', '6');
			marker.setAttribute('refX', '5');
			marker.setAttribute('refY', '3');
			marker.setAttribute('orient', 'auto');
			const head = document.createElementNS(ns, 'path');
			head.setAttribute('d', 'M0,0 L6,3 L0,6 Z');
			head.setAttribute('class', 'snc-link-arrowhead');
			marker.appendChild(head);
			defs.appendChild(marker);
			svg.appendChild(defs);
			path = document.createElementNS(ns, 'path') as SVGPathElement;
			path.setAttribute('class', 'snc-link-arrow-line');
			path.setAttribute('marker-end', `url(#${markerId})`);
			svg.appendChild(path);
			// Hovering the arrow cues the chain's ✕ (unlink) affordance.
			path.addEventListener('mouseenter', () => widget.setLinkHoverCue(true));
			path.addEventListener('mouseleave', () => widget.setLinkHoverCue(false));
			this.editor.getContainerDomNode().appendChild(svg);
			this.linkArrows.set(key, svg as unknown as HTMLElement);
		} else {
			path = svg.querySelector('path.snc-link-arrow-line') as SVGPathElement;
		}

		svg.style.left = `${minX}px`;
		svg.style.top = `${minY}px`;
		svg.setAttribute('width', `${width}`);
		svg.setAttribute('height', `${height}`);

		// Orthogonal (right-angle) connector: drop vertically from the chain
		// icon, round the corner, then run horizontally into the linked line.
		const x1 = startX - minX;
		const y1 = startY - minY;
		const xleft = pad;
		const x2 = targetX - minX;
		const y2 = targetY - minY;
		// const dirV = Math.sign(y2 - y1) || 1;
		// const dirH = Math.sign(x2 - x1) || 1;
		// const r = Math.max(0, Math.min(8, Math.abs(y2 - y1), Math.abs(x2 - x1)));
		const d = `M ${x1} ${y1} L ${xleft} ${y1} L ${xleft} ${y2} L ${x2} ${y2}`;
		path.setAttribute('d', d);
	}

	private removeLinkArrow(key: string): void {
		const svg = this.linkArrows.get(key);
		if (svg) {
			svg.remove();
			this.linkArrows.delete(key);
		}
	}

	private clearLinkArrows(): void {
		for (const svg of this.linkArrows.values()) {
			svg.remove();
		}
		this.linkArrows.clear();
	}

	/**
	 * Tear down every link whose tracked decoration is missing or empty —
	 * typically because the user deleted the linked line of code. Without this,
	 * a later visualizer event would rewrite into the collapsed join point
	 * (e.g. append the expression to the end of the previous line).
	 */
	private pruneDeadLinks(): void {
		const editorModel = this.editor.getModel();
		if (!editorModel || this.linkedSelections.length === 0) {
			return;
		}
		const dead = this.linkedSelections.filter(link => {
			const range = editorModel.getDecorationRange(link.decorationId);
			return !range || range.isEmpty();
		});
		for (const link of dead) {
			this.teardownLink(link);
		}
	}

	/**
	 * Reconcile front-end links against the (now-fresh) Python models at the end
	 * of a run, so the chain icon and decorations can't diverge from what the
	 * model actually thinks. Two mismatch cases are fixed:
	 *
	 *  1. A front-end link is alive but the model is not linked → remove the
	 *     orphan decoration LOCALLY only (the model already agrees; sending
	 *     Unlink would just trigger a pointless re-run). This resolves the
	 *     relink-takeover failure edge where the decoration was established
	 *     before Python responded but adoption+generation both failed.
	 *  2. The model claims linked_action but the front-end has no live link →
	 *     send Unlink so Python clears its stale state. Converges after one
	 *     re-run; tracked in reconciledUnlinkKeys so it isn't re-sent every run.
	 *
	 * Visualizers with still-queued events are skipped (their model is about to
	 * change again).
	 */
	private reconcileLinksWithModels(): void {
		const editorModel = this.editor.getModel();
		if (!editorModel) {
			return;
		}
		const pendingKeys = new Set<string>();
		for (const item of this.visualizationItems) {
			if (item.unhandledEvents && item.unhandledEvents.length > 0) {
				pendingKeys.add(`${item.line}:${item.visIndex}`);
			}
		}

		// Case 1: front-end link alive but the fresh model is not linked.
		for (const link of [...this.linkedSelections]) {
			const key = `${link.line}:${link.visIndex}`;
			if (pendingKeys.has(key)) {
				continue;
			}
			const item = this.visualizationItems.find(
				it => it.line === link.line && it.visIndex === link.visIndex);
			if (item && SNCController.supportsLinking(item.model)
				&& !SNCController.isModelLinked(item.model)) {
				this.removeLinkLocal(link);
			}
		}

		// Case 2: model claims a link but the front-end has none (or a dead range).
		for (const item of this.visualizationItems) {
			const key = `${item.line}:${item.visIndex}`;
			if (!SNCController.isModelLinked(item.model)) {
				// Model no longer claims linked; drop any reconciliation tracking.
				this.reconciledUnlinkKeys.delete(key);
				continue;
			}
			if (pendingKeys.has(key)) {
				continue;
			}
			const link = this.findLink(item.line, item.visIndex);
			const range = link ? editorModel.getDecorationRange(link.decorationId) : null;
			const linkAlive = !!range && !range.isEmpty();
			if (linkAlive) {
				// Consistent (model linked + live range); drop any tracking.
				this.reconciledUnlinkKeys.delete(key);
				continue;
			}
			if (this.reconciledUnlinkKeys.has(key)) {
				// Already asked Python to clear this; wait for it to converge.
				continue;
			}
			this.reconciledUnlinkKeys.add(key);
			// Remove a stale (dead-range) link entry locally before asking Python.
			if (link) {
				this.removeLinkLocal(link);
			}
			this.sendEventToPython({
				line: item.line,
				visIndex: item.visIndex,
				pythonEventStr: 'lambda e: Unlink()',
				eventJSON: { type: 'unlink' },
			});
		}
	}

	private getLineIndent(lineNumber: number): number {
		const model = this.editor.getModel();
		if (!model || lineNumber < 1 || lineNumber > model.getLineCount()) {
			return 0;
		}
		const content = model.getLineContent(lineNumber);
		return content.length - content.trimStart().length;
	}

	/** The line's leading whitespace, preserving tabs. */
	private getLineIndentText(lineNumber: number): string {
		const model = this.editor.getModel();
		if (!model || lineNumber < 1 || lineNumber > model.getLineCount()) {
			return '';
		}
		return model.getLineContent(lineNumber).slice(0, this.getLineIndent(lineNumber));
	}

	private setupLanguageChangeListener(): void {
		const model = this.editor.getModel();
		if (!model) {
			return;
		}

		// Listen for language changes on the model
		this._register(model.onDidChangeLanguageConfiguration(() => {
			this.onLanguageChanged();
		}));

		// Also listen for when the language changes
		this._register(model.onDidChangeLanguage(() => {
			this.onLanguageChanged();
		}));
	}

	private onLanguageChanged(): void {
		this.updateToggleWidgetsButton();
		this.updateConfigCommentFolding();
		if (this.isPythonModel()) {
			this.triggerInitialVisualization();
		} else {
			// Language switched away from Python: tear down widgets, drop stale
			// items, and cancel any pending/in-flight run so the now-non-Python
			// buffer doesn't keep getting re-executed.
			if (this.debounceTimer) {
				clearTimeout(this.debounceTimer);
				this.debounceTimer = null;
			}
			this.visualizationItems = [];
			this.clearVisualizationWidgets();
			this.cancelCurrentRun();
		}
	}

	private cancelCurrentRun(): void {
		if (!this.currentRunId) {
			return;
		}
		const channel = this.mainProcessService.getChannel('sncProcess');
		const runId = this.currentRunId;
		this.currentRunId = null;
		this.logRunCancelled(runId, 'cancelCurrentRun');
		try {
			channel.call('cancel', [runId]).catch(() => { /* ignore */ });
		} catch { /* ignore */ }
	}

	private onEditorsVisibilityChanged(): void {
		if (!this.isPythonModel()) {
			return;
		}

		// Check if this editor is currently visible in the editor service
		const visibleEditors = this.editorService.visibleTextEditorControls;
		const isThisEditorVisible = visibleEditors.includes(this.editor);

		if (isThisEditorVisible) {
			if (this.debounceTimer) {
				clearTimeout(this.debounceTimer);
			}

			this.debounceTimer = setTimeout(() => {
				this.debounceTimer = null;
				this.runProgram(this.getProgram(), undefined, 'editor-visible');
			}, this.debounceDelay);
		}
	}

	private triggerInitialVisualization(): void {
		if (!this.isPythonModel()) {
			return;
		}

		const content = this.getProgram();
		if (!content || content.trim().length === 0) {
			return;
		}

		// Use longer debounce delay for initial trigger to ensure system is ready
		if (this.debounceTimer) {
			clearTimeout(this.debounceTimer);
		}

		this.debounceTimer = setTimeout(() => {
			this.debounceTimer = null;
			this.runProgram(content, undefined, 'initial');
		}, 1);
	}

	private clearVisualizationWidgets(): void {
		this.syntaxErrorActive = false;
		this.loopCounts.clear();
		this.removeWidgetDom();

		// Tearing the widgets down is a render too. Its callers drop the items
		// first, so the empty DOM is the truth; the one that does not (a run
		// that failed to launch) is an error path where the next run redraws
		// everything anyway, and leaving the version behind there would hang
		// every waiting tool rather than let it read a screen that is not going
		// to change.
		this.renderedVersion = this.itemsVersion;
	}

	/**
	 * Everything SNC has put in the editor's DOM comes out: widgets (and with
	 * them their hoisted dropdowns and tooltips), loop sliders, link arrows and
	 * view zones. The state that produced it (items, loop counts, pins, links)
	 * is left alone, so this is what hiding the widgets does.
	 */
	private removeWidgetDom(): void {
		for (const widgets of this.visualizationWidgets.values()) {
			for (const widget of widgets) {
				widget.dispose();
			}
		}
		this.visualizationWidgets.clear();
		this.clearLinkArrows();
		for (const slider of this.loopSliders.values()) {
			slider.dispose();
		}
		this.loopSliders.clear();

		// Remove all view zones (including the top spacer)
		this.editor.changeViewZones((accessor) => {
			for (const viewZoneId of this.viewZones.values()) {
				accessor.removeZone(viewZoneId);
			}
			if (this.topSpacerZoneId !== null) {
				accessor.removeZone(this.topSpacerZoneId);
				this.topSpacerZoneId = null;
			}
		});
		this.viewZones.clear();
		this.viewZoneHeights.clear();
		this.topSpacerHeight = 0;
	}

	private setSyntaxErrorState(active: boolean): void {
		if (this.syntaxErrorActive === active) {
			return;
		}
		this.syntaxErrorActive = active;
		this.applySyntaxErrorClassToWidgets();
	}

	private applySyntaxErrorClassToWidgets(): void {
		for (const widgets of this.visualizationWidgets.values()) {
			for (const widget of widgets) {
				widget.getDomNode().classList.toggle('snc-syntax-error', this.syntaxErrorActive);
			}
		}
	}

	private updateOverlayWidgetPositions(): void {
		// Update positions of all overlay widgets when scrolling
		for (const widgets of this.visualizationWidgets.values()) {
			for (const widget of widgets) {
				widget.updatePosition();
			}
		}
		for (const slider of this.loopSliders.values()) {
			slider.updatePosition();
		}
		// Keep link arrows glued to their (moved) chain icons and code lines.
		this.updateLinkChrome();
	}

	/**
	 * Resize (or remove) the synthetic top spacer view zone placed before line
	 * 1. Pass 0 to remove it. Kept out of `this.viewZones` so the per-line
	 * add/remove bookkeeping never touches it.
	 */
	private setTopSpacerHeight(height: number): void {
		const target = Math.max(0, Math.round(height));
		if (target === this.topSpacerHeight && (target === 0) === (this.topSpacerZoneId === null)) {
			return;
		}
		this.editor.changeViewZones((accessor) => {
			if (this.topSpacerZoneId !== null) {
				accessor.removeZone(this.topSpacerZoneId);
				this.topSpacerZoneId = null;
			}
			if (target > 0) {
				this.topSpacerZoneId = accessor.addZone({
					afterLineNumber: 0,
					heightInPx: target,
					domNode: document.createElement('div'),
					suppressMouseDown: true
				});
			}
		});
		this.topSpacerHeight = target;
	}

	/**
	 * Convert spacer into real scroll as the user scrolls down. The spacer is
	 * phantom space above line 1; any portion the user has scrolled past is
	 * pointless, so trade it for an equal reduction in scrollTop. This keeps the
	 * visible content perfectly still while the spacer melts away the moment the
	 * user scrolls off the top, instead of leaving permanent empty space.
	 */
	private absorbTopSpacerOnScroll(): void {
		if (this.isAdjustingTopSpacer || this.topSpacerHeight === 0) {
			return;
		}
		const scrollTop = this.editor.getScrollTop();
		const absorb = Math.min(scrollTop, this.topSpacerHeight);
		if (absorb <= 0) {
			return;
		}
		this.isAdjustingTopSpacer = true;
		try {
			this.setTopSpacerHeight(this.topSpacerHeight - absorb);
			this.editor.setScrollTop(scrollTop - absorb, ScrollType.Immediate);
		} finally {
			this.isAdjustingTopSpacer = false;
		}
	}

	// private modelKey(line: number, visIndex?: number | null): string {
	// 	return `${line}:${visIndex ?? 0}`;
	// }

	private updateVisualizationWidgets(visualizationData: IVisualizationItem[]): void {
		if (!this.widgetsVisible) {
			// Nothing to draw into; the items are kept for when the widgets are
			// shown again. As far as anything waiting on the DOM is concerned,
			// hidden is rendered.
			this.renderedVersion = this.itemsVersion;
			return;
		}

		// console.log("visualizationData", visualizationData);

		// Group visualization items by line number
		const groupedByLine = new Map<number, IVisualizationItem[]>();
		for (const item of visualizationData) {
			if (!groupedByLine.has(item.line)) {
				groupedByLine.set(item.line, []);
			}
			groupedByLine.get(item.line)!.push(item);
		}
		// console.log("groupedByLine", groupedByLine)

		const presentLines = new Set<number>(Array.from(groupedByLine.keys()));
		const lineHeight = this.editor.getOption(EditorOption.lineHeight);
		const getViewZoneHeightInPx = (widgets: VisualizationWidget[]): number => {
			if (widgets.length === 0) {
				return 0;
			}

			const maxHeight = Math.max(...widgets.map(w => w.getDomNode().getBoundingClientRect().height));
			const usesBlockLayout = widgets.some(w => w.usesBlockLayout());

			if (usesBlockLayout) {
				return Math.max(Math.ceil(maxHeight) + 10, lineHeight);
			}

			if (maxHeight > 22) {
				return Math.ceil(maxHeight) - 12;
			}

			return 0;
		};

		// console.log("presentLines", presentLines)


		// Collect widgets that need repositioning; calling updatePosition()
		// inside changeViewZones would force a synchronous render while the
		// zone data structures are mid-mutation, causing crashes in ViewZones.render.
		const widgetsToReposition: VisualizationWidget[] = [];

		// Capture scroll state so we can stabilize after view zone changes.
		// Anchor to the focused visualizer's line if visible, otherwise the line
		// just above the viewport midpoint. We do NOT bail when scrollTop === 0:
		// focusing a visualizer shrinks the previously-focused one above it, and
		// the focused line must stay anchored even when the file is at the top.
		const scrollTop = this.editor.getScrollTop();
		const shouldStabilizeScroll = !this.editor.hasPendingScrollAnimation();
		let anchorLineNumber = 0;
		let anchorDelta = 0;

		if (shouldStabilizeScroll) {
			const visibleRanges = this.editor.getVisibleRanges();
			if (visibleRanges.length > 0) {
				const focusedLine = this.effectiveFocusedLine();
				const firstVisibleLine = visibleRanges[0].startLineNumber;
				const lastVisibleLine = visibleRanges[visibleRanges.length - 1].endLineNumber;

				// Prefer anchoring to the focused visualizer's line (the
				// explicitly focused line, or the cursor line) when it is
				// visible, so the focused visualizer stays put as view zones
				// are added/removed. Fall back to the viewport midpoint.
				if (focusedLine !== null && focusedLine >= firstVisibleLine && focusedLine <= lastVisibleLine) {
					anchorLineNumber = focusedLine;
				} else {
					const midPixel = scrollTop + this.editor.getLayoutInfo().height / 2;
					anchorLineNumber = firstVisibleLine;
					for (let line = firstVisibleLine; line <= lastVisibleLine; line++) {
						if (this.editor.getTopForLineNumber(line) + lineHeight > midPixel) {
							break;
						}
						anchorLineNumber = line;
					}
				}
				anchorDelta = scrollTop - this.editor.getTopForLineNumber(anchorLineNumber);
			}
		}

		// Set when a view zone is added, removed, or resized. Such a change moves
		// every widget below it, including widgets whose own content did not
		// change, so they all have to be repositioned rather than just the ones
		// in `widgetsToReposition`.
		let zonesChanged = false;

		this.editor.changeViewZones((accessor) => {
			// Remove widgets/view zones for lines no longer present
			for (const [line, widgets] of Array.from(this.visualizationWidgets.entries())) {
				if (!presentLines.has(line)) {
					// console.log("disposing", line, widgets)
					for (const w of widgets) { w.dispose(); }
					this.visualizationWidgets.delete(line);
					const vz = this.viewZones.get(line);
					if (vz) {
						accessor.removeZone(vz);
						this.viewZones.delete(line);
						this.viewZoneHeights.delete(line);
						zonesChanged = true;
					}
				}
			}

			// Update or create for each present line
			for (const [lineNumber, items] of groupedByLine.entries()) {
				// One item per log site on the line (Python picks the iteration;
				// see loopSelections), in source order.
				const stepItems = items.slice().sort((a, b) => a.visIndex - b.visIndex);

				const existing = this.visualizationWidgets.get(lineNumber);
				// console.log("existing", lineNumber, existing)


				if (existing && existing.length === stepItems.length) {
					// Incremental update: reuse widgets, just update content
					let anyChanged = false;
					for (let i = 0; i < stepItems.length; i++) {
						if (existing[i].updateContent(stepItems[i].html)) {
							anyChanged = true;
						}
					}

					if (anyChanged) {
						widgetsToReposition.push(...existing);

						// Adjust view zone height if needed
						const viewZoneHeightInPx = getViewZoneHeightInPx(existing);
						const existingZoneId = this.viewZones.get(lineNumber);
						if (viewZoneHeightInPx > 0) {
							// A zone's height can only be changed by replacing it, and that
							// relays out every line below. Content re-renders that leave the
							// widget the same height (a hover repaint, say) must not pay for
							// that, so an unchanged height is left strictly alone.
							if (!existingZoneId || this.viewZoneHeights.get(lineNumber) !== viewZoneHeightInPx) {
								if (existingZoneId) {
									accessor.removeZone(existingZoneId);
								}
								const viewZone: IViewZone = {
									afterLineNumber: lineNumber,
									heightInPx: viewZoneHeightInPx,
									domNode: document.createElement('div'),
									suppressMouseDown: false
								};
								const viewZoneId = accessor.addZone(viewZone);
								this.viewZones.set(lineNumber, viewZoneId);
								this.viewZoneHeights.set(lineNumber, viewZoneHeightInPx);
								zonesChanged = true;
							}
						} else if (existingZoneId) {
							accessor.removeZone(existingZoneId);
							this.viewZones.delete(lineNumber);
							this.viewZoneHeights.delete(lineNumber);
							zonesChanged = true;
						}
					}
				} else {
					// Rebuild for this line
					if (existing) {
						for (const w of existing) { w.dispose(); }
						this.visualizationWidgets.delete(lineNumber);
						const oldZone = this.viewZones.get(lineNumber);
						if (oldZone) {
							accessor.removeZone(oldZone);
							this.viewZones.delete(lineNumber);
							this.viewZoneHeights.delete(lineNumber);
							zonesChanged = true;
						}
					}

					const widgets: VisualizationWidget[] = [];
					for (let i = 0; i < stepItems.length; i++) {
						const item = stepItems[i];
						const visIndex = item.visIndex;
						const widget = new VisualizationWidget(
							this.editor,
							lineNumber,
							visIndex,
							(pythonEventStr, ev, overrideRect?) => { this.onPointerEvent(lineNumber, visIndex, pythonEventStr, ev, overrideRect); },
							(pythonEventStr, ev) => { this.onKeyboardEvent(lineNumber, visIndex, pythonEventStr, ev); },
							(pythonEventStr, value) => { this.onInputEvent(lineNumber, visIndex, pythonEventStr, value); },
							() => this.effectiveFocusedLine() === lineNumber,
							() => this.isReadOnly(),
							() => this.requestExpand(lineNumber),
							(expression, imports) => { this.insertNewVarFromExpression(lineNumber, expression, imports); },
							() => { this.onLinkChainClick(lineNumber, visIndex); },
							this.clipboardService
						);
						widget.leftInset = this.loopSliders.has(lineNumber) ? LoopSliderWidget.WIDTH : 0;
						widget.updateContent(item.html);
						widgets.push(widget);
					}
					if (widgets.length > 0) {
						this.visualizationWidgets.set(lineNumber, widgets);
						widgetsToReposition.push(...widgets);
					}

					const viewZoneHeightInPx = getViewZoneHeightInPx(widgets);
					if (viewZoneHeightInPx > 0) {
						const viewZone: IViewZone = {
							afterLineNumber: lineNumber,
							heightInPx: viewZoneHeightInPx,
							domNode: document.createElement('div'),
							suppressMouseDown: false
						};
						const viewZoneId = accessor.addZone(viewZone);
						this.viewZones.set(lineNumber, viewZoneId);
						this.viewZoneHeights.set(lineNumber, viewZoneHeightInPx);
						zonesChanged = true;
					}
				}
			}
		});

		if (shouldStabilizeScroll && anchorLineNumber > 0) {
			// Clear any prior spacer so the anchor's top reflects real content,
			// then work out where restoring the anchor lands. `anchorDelta` is a
			// spacer-independent viewport offset, so `desiredScrollTop` is the
			// scroll (with no spacer) that keeps the anchor visually put.
			this.setTopSpacerHeight(0);
			const anchorTopAfter = this.editor.getTopForLineNumber(anchorLineNumber);
			const desiredScrollTop = anchorTopAfter + anchorDelta;
			if (desiredScrollTop < 0) {
				// Not enough real lines above the anchor to absorb the shrink:
				// scrollTop would clamp at 0 and let the anchor jump up. Fill the
				// deficit with a top spacer so the anchor stays pixel-stable.
				this.setTopSpacerHeight(-desiredScrollTop);
				this.editor.setScrollTop(0, ScrollType.Immediate);
			} else {
				this.editor.setScrollTop(desiredScrollTop, ScrollType.Immediate);
			}
		}

		// A zone that was added, removed, or resized shifted every line below it,
		// so widgets whose own content never changed are now sitting at a stale
		// `top`. Monaco keeps the last position it was handed rather than asking
		// for a fresh one, so nothing corrects them until the next scroll event.
		const repositionTargets = zonesChanged
			? Array.from(this.visualizationWidgets.values()).flat()
			: widgetsToReposition;
		for (const widget of repositionTargets) {
			widget.updatePosition();
		}
		if (zonesChanged) {
			for (const slider of this.loopSliders.values()) {
				slider.updatePosition();
			}
		}
		this.applySyntaxErrorClassToWidgets();
		this.updateLinkChrome();

		// The DOM now shows these items -- but only claim so when they are still
		// the current ones. The cursor-move re-render captures the array it was
		// given and draws it 50ms later, by which time a run may have replaced
		// it, and that render caught up with nothing.
		if (visualizationData === this._visualizationItems) {
			this.renderedVersion = this.itemsVersion;
		}
	}

	/**
	 * Handle pointer event from VisualizationWidget
	 */

	private onPointerEvent(lineNumber: number, visIndex: number, pythonEventStr: string, ev: MouseEvent, overrideRect?: DOMRect): void {
		const rect = overrideRect ?? (ev.target as HTMLElement).getBoundingClientRect();

		// What Python needs to interpret the event: buttons for drag state,
		// detail for double-clicks, modifiers for tool overrides. offsetY /
		// elementHeight / timeStamp / button ride along only in the study log
		// below -- nothing in Python reads them, and keeping them out of the
		// payload makes identical moves *identical*, so repeats can be deduped
		// instead of each costing a program run.
		const eventJSON = { type: ev.type, buttons: ev.buttons, detail: ev.detail, altKey: ev.altKey, ctrlKey: ev.ctrlKey, metaKey: ev.metaKey, shiftKey: ev.shiftKey };
		const logEventJSON = { ...eventJSON, button: ev.button, offsetY: ev.clientY - rect.top, elementHeight: rect.height, timeStamp: ev.timeStamp };

		const event: UiEventSpec = { line: lineNumber, visIndex, pythonEventStr, eventJSON };
		console.log('SNC viz_pointer event', JSON.stringify(event));
		// An empty event string is a no-op in Python that still costs a run
		// (and supersedes the one in flight). The dispatchers never send one
		// now; if one turns up it is a bug, and the log should say so.
		if (pythonEventStr === '') {
			studyLog.log('widget.emptyEventStr', { ...this.visInfo(lineNumber, visIndex), event: logEventJSON, target: describeEventTarget(ev.target as Node, ev.currentTarget as Element) }, this.editor.getModel()?.uri.toString());
			return;
		}
		if (ev.type === 'mousemove' || ev.type === 'mouseout' || ev.type === 'mouseleave') {
			// A mouseout's offsetY is measured against the element being LEFT,
			// from wherever the pointer is now, so it reads as nonsense on its
			// own; where the pointer went is what makes sense of it.
			const to = ev.type === 'mousemove' ? undefined : describeEventTarget(ev.relatedTarget as Node | null, ev.currentTarget as Element);
			this.moveLogCoalescer.note(`${lineNumber}:${visIndex}:${pythonEventStr}`, { ...this.visInfo(lineNumber, visIndex), pythonEventStr, event: logEventJSON, ...(to ? { to } : {}) }, this.editor.getModel()?.uri.toString());
		} else {
			this.moveLogCoalescer.flush();
			studyLog.log('widget.mouse', { ...this.visInfo(lineNumber, visIndex), pythonEventStr, event: logEventJSON }, this.editor.getModel()?.uri.toString());
		}

		if (ev.type === 'mousemove') {
			// A move identical to the last one sent would re-run the program to
			// arrive at the same model. The pointer crossing back into a char it
			// left produces a genuinely new (well, resurrected) key; sub-char
			// jitter does not.
			const key = `${lineNumber}:${visIndex}:${pythonEventStr}:${JSON.stringify(eventJSON)}`;
			if (key === this.lastSentMoveKey) {
				return;
			}
			this.lastSentMoveKey = key;
		}

		// Rerun on every pointer event to keep backend authoritative for selections
		this.sendEventToPython(event);
	}

	/**
	 * Handle keyboard event from VisualizationWidget
	 *
	 * If it's not a key the widget handles, let it pass through to VS Code.
	 */
	private onKeyboardEvent(lineNumber: number, visIndex: number, pythonEventStr: string, ev: KeyboardEvent): void {
		// Look up the model for this visualization to get handledKeys
		const visItem = this.visualizationItems.find(
			item => item.line === lineNumber && item.visIndex === visIndex
		);
		const model = visItem?.model as { handledKeys?: string[] } | undefined;
		const handledKeys = model?.handledKeys ?? [];

		// Normalize a key string: sort modifiers alphabetically, keep the main key last
		const normalizeKeyString = (s: string): string => {
			const [mainKey, ...parts] = s.toLowerCase().split(' ').reverse();
			return [...parts.sort(), mainKey].join(' ');
		};

		// Build key string from event: e.g. "cmd shift z", "escape", "enter"
		const keyString = normalizeKeyString(`${ev.metaKey ? 'cmd ' : ''}${ev.ctrlKey ? 'ctrl ' : ''}${ev.altKey ? 'alt ' : ''}${ev.shiftKey ? 'shift ' : ''}${ev.key.toLowerCase()}`);

		// Check if this key combo should be intercepted (normalize both sides)
		const isHandled = handledKeys.some(hk => normalizeKeyString(hk) === keyString);
		if (isHandled) {
			ev.preventDefault();
			ev.stopPropagation();
		}

		const eventJSON = {
			type: ev.type,
			key: ev.key,
			code: ev.code,
			timeStamp: ev.timeStamp,
			altKey: ev.altKey,
			ctrlKey: ev.ctrlKey,
			metaKey: ev.metaKey,
			shiftKey: ev.shiftKey
		};

		const event: UiEventSpec = { line: lineNumber, visIndex, pythonEventStr, eventJSON };
		// console.log('SNC keyboard event', JSON.stringify(event));
		studyLog.log('widget.key', { ...this.visInfo(lineNumber, visIndex), pythonEventStr, keyString, handled: isHandled, event: eventJSON }, this.editor.getModel()?.uri.toString());

		this.sendEventToPython(event);
	}

	/**
	 * Handle input event from VisualizationWidget (for text inputs with snc-input attribute)
	 */
	private onInputEvent(lineNumber: number, visIndex: number, pythonEventStr: string, value: string): void {
		const eventJSON = { type: 'input', value };
		const event: UiEventSpec = { line: lineNumber, visIndex, pythonEventStr, eventJSON };
		studyLog.log('widget.input', { ...this.visInfo(lineNumber, visIndex), pythonEventStr, value }, this.editor.getModel()?.uri.toString());
		this.sendEventToPython(event);
	}

	/**
	 * Run again for events no run has managed to apply.
	 *
	 * The gate in `runProgram` hands events to the run in flight rather than
	 * starting a new one, which leaves them stranded if that run was already
	 * past the widget (or never reached it). This is how they get picked up.
	 * Deferred so a burst of items schedules one run, and so we aren't
	 * re-entering `runProgram` from inside the stream handler.
	 */
	private scheduleQueuedEventRun(): void {
		if (this.requeuedRunTimer) { return; }
		this.requeuedRunTimer = setTimeout(() => {
			this.requeuedRunTimer = null;
			if (this.isPythonModel() && this.visualizationItems.some(v => v.unhandledEvents?.length)) {
				this.runProgram(this.getProgram(), undefined, 'queued-events');
			}
		}, 0);
	}

	private sendEventToPython(event: UiEventSpec) {
		// Any event other than a move can change the model, which makes a
		// repeat of the last move meaningful again (moves themselves stamp
		// their own key in onPointerEvent before reaching this funnel).
		if (event.eventJSON?.type !== 'mousemove') {
			this.lastSentMoveKey = null;
		}
		// Every event gets its id here, the one place they all funnel through.
		// The runner echoes the ids it applied back on the item, which is how a
		// queued event is retired -- see IVisualizationItem.handledEventIds.
		const queued: UiEvent = { ...event, id: ++this.lastEventId };
		// The same funnel is where we learn which widget is worth warming to.
		this.lastInteractedWidget = { line: event.line, visIndex: event.visIndex };
		this.runProgram(this.getProgram(), queued, `widget:${queued.eventJSON?.type ?? 'event'}`);
	}

	/** Line, visIndex and (best-effort) visualizer type of a widget, for the study log. */
	private visInfo(line: number, visIndex: number): { line: number; visIndex: number; visType?: string; focused: boolean } {
		const item = this.visualizationItems.find(i => i.line === line && i.visIndex === visIndex);
		return { line, visIndex, visType: item ? visualizerTypeOf(item.html) : undefined, focused: this.effectiveFocusedLine() === line };
	}

	private logRunCancelled(runId: string, by: string): void {
		const started = this.runStartWallById.get(runId);
		studyLog.log('run.cancelled', { runId, by, trigger: this.runTriggerById.get(runId), elapsedMs: started ? Date.now() - started : undefined }, this.editor.getModel()?.uri.toString());
		this.runTriggerById.delete(runId);
		this.runStartWallById.delete(runId);
	}

	/** The rendered visualizers as the study log records them: where, what kind, how big. */
	private describeItemsForLog(): unknown[] {
		const full = this.configurationService.getValue<boolean>('clickacode.studyLogging.logFullHtml') === true;
		return this.visualizationItems.map(item => ({
			line: item.line, visIndex: item.visIndex, executionStep: item.execution_step, path: item.path,
			visType: visualizerTypeOf(item.html), htmlLength: item.html.length, hasModel: !!item.model,
			...(full ? { html: item.html, model: item.model } : {}),
		}));
	}

	/**
	 * Handle commands from visualizers (Elm-style commands)
	 */
	private handleCommand(command: SNCCommand): void {
		// Python sends none of these under read-only, but the setting can flip
		// while a run is in flight, and a visualizer that doesn't know the
		// setting might still ask. Nothing that changes the file gets through.
		if (this.isReadOnly() && command.type !== 'CopyToClipboard') {
			console.log('SNC: read-only visualizers, ignoring command', command.type);
			return;
		}
		studyLog.log('snc.command', { runId: this.currentRunId, trigger: this.currentRunId ? this.runTriggerById.get(this.currentRunId) : undefined, command: command.type === 'CopyToClipboard' ? { ...command, text: truncateForLog(command.text) } : command }, this.editor.getModel()?.uri.toString());
		if (command.type === 'NewCode') {
			const model = this.editor.getModel();
			if (!model || (command.edits.length === 0 && !command.imports?.length)) {
				return;
			}

			// The visualizer said what its code needs to run; turning that into
			// edits is ours, since only we know the file as it stands now. They
			// join the command's own edits so everything below — the ordering,
			// the scroll anchor, the shifted trigger line — sees one list.
			//
			// A nested action sends imports and no edits of its own: its code
			// stayed in the visualizer as a column, but the file still has to
			// be able to run it. Nothing lands on the trigger line, so nothing
			// below links or moves the cursor, and the scroll anchor keeps the
			// view still while the import goes in above.
			const edits = [...command.edits, ...importEdits(model, command.imports)];
			if (edits.length === 0) {
				return;
			}

			// Sort edits bottom-to-top so line numbers remain valid as we insert
			const sortedEdits = [...edits].sort((a, b) => b.afterLine - a.afterLine);

			// Capture a scroll anchor so inserting lines above the viewport (e.g.
			// an auto-added `import re` at the top of the file) doesn't make the
			// whole view jump down. Anchor to the focused visualizer's line when
			// it is visible, falling back to the first visible line. Note we do
			// NOT bail when scrollTop === 0: the very case we care about is the
			// focused line being at the top of the file, where inserting above
			// must scroll so the focused line stays put at the top.
			const scrollTop = this.editor.getScrollTop();
			const shouldStabilizeScroll = !this.editor.hasPendingScrollAnimation();
			let anchorLineNumber = 0;
			let anchorDelta = 0;
			if (shouldStabilizeScroll) {
				const visibleRanges = this.editor.getVisibleRanges();
				if (visibleRanges.length > 0) {
					const focusedLine = this.effectiveFocusedLine();
					const firstVisibleLine = visibleRanges[0].startLineNumber;
					const lastVisibleLine = visibleRanges[visibleRanges.length - 1].endLineNumber;
					anchorLineNumber = (focusedLine !== null && focusedLine >= firstVisibleLine && focusedLine <= lastVisibleLine)
						? focusedLine
						: firstVisibleLine;
					anchorDelta = scrollTop - this.editor.getTopForLineNumber(anchorLineNumber);
				}
			}

			const editOperations = sortedEdits.map(edit => {
				if (edit.afterLine === 0) {
					return {
						range: new Range(1, 1, 1, 1),
						text: edit.text + '\n'
					};
				}
				const col = model.getLineMaxColumn(edit.afterLine);
				return {
					range: new Range(edit.afterLine, col, edit.afterLine, col),
					text: '\n' + edit.text
				};
			});

			// After inserting, capture (a) the inverse range of the main inserted
			// line so we can link it for live updates, and (b) a rename selection
			// if a new variable name was introduced.
			let mainInverseRange: Range | null = null;
			const newSelections = studyLog.withEditOrigin('NewCode', () => model.pushEditOperations([], editOperations, (inverseEdits) => {
				let renameSel: Selection | null = null;
				for (let i = 0; i < sortedEdits.length; i++) {
					const edit = sortedEdits[i];
					const inv = inverseEdits[i];
					if (!inv) {
						continue;
					}
					// The main inserted line is the edit on the trigger line.
					if (edit.afterLine === command.triggerLine) {
						mainInverseRange = inv.range;
					}
					if (!renameSel) {
						renameSel = computeRenameSelectionForEdit(edit.text, edit.afterLine === 0, inv.range);
					}
				}
				return renameSel ? [renameSel] : null;
			}));

			// Link the freshly inserted line so subsequent visualizer interactions
			// update it in place (via ChangeSelectedText) instead of stacking new
			// lines. The inverse range of a (\n + text) insert includes the leading
			// newline boundary, so narrow it to just the inserted code line.
			if (mainInverseRange) {
				// Other edits inserted above the trigger line (e.g. an auto-added
				// `import re`) shift the visualizer's source line down. Account for
				// that so the link and cursor target the actual (post-edit) line.
				const linesInsertedAbove = edits.reduce(
					(n, e) => n + (e.afterLine < command.triggerLine ? editLineCount(e) : 0), 0);
				const actualTriggerLine = command.triggerLine + linesInsertedAbove;

				// The assignment is always inserted immediately after the (shifted)
				// trigger line. Derive the linked range directly from that line
				// rather than from inverse-range arithmetic, which is unreliable
				// across the multi-region edit when an import is also inserted.
				const mainEdit = edits.find(e => e.afterLine === command.triggerLine);
				const insertedLine = actualTriggerLine + 1;
				// A statement's body is the user's, so the link covers only the
				// header lines Python reported -- and not the trailing config
				// comment the line may open with, which SetConfigComment owns.
				const lastHeaderLine = insertedLine + Math.max(1, mainEdit?.headerLines ?? 1) - 1;
				const linkedRange = new Range(
					insertedLine, model.getLineFirstNonWhitespaceColumn(insertedLine) || 1,
					lastHeaderLine, stripConfigComment(model.getLineContent(lastHeaderLine)).length + 1
				);
				this.establishLinkForRange(linkedRange, actualTriggerLine, command.triggerVisIndex);

				// The user is still interacting with the triggering visualizer (e.g.
				// typing in its search box). Inserting moved the editor cursor onto
				// the new line, which would collapse the focused visualizer and steal
				// DOM focus. Keep the cursor on the trigger line so that visualizer
				// stays focused/expanded and the user can keep interacting.
				const triggerCol = model.getLineMaxColumn(actualTriggerLine);
				this.editor.setPosition({ lineNumber: actualTriggerLine, column: triggerCol });
			} else if (newSelections && newSelections.length > 0) {
				this.editor.setSelection(newSelections[0]);
				this.editor.focus();
			}

			// Restore the scroll offset so the anchored line stays visually put.
			// Lines inserted strictly above the anchor (e.g. an auto-added
			// `import re`) push it down; count them and re-anchor accordingly.
			if (shouldStabilizeScroll && anchorLineNumber > 0) {
				const linesInsertedAboveAnchor = edits.reduce(
					(n, e) => n + (e.afterLine < anchorLineNumber ? editLineCount(e) : 0), 0);
				const newAnchorLine = anchorLineNumber + linesInsertedAboveAnchor;
				const newAnchorTop = this.editor.getTopForLineNumber(newAnchorLine);
				this.editor.setScrollTop(newAnchorTop + anchorDelta, ScrollType.Immediate);
			}
		} else if (command.type === 'ChangeSelectedText') {
			this.handleChangeSelectedText(
				command.expression,
				command.suggested_var_name ?? null,
				command.triggerLine,
				command.triggerVisIndex
			);
		} else if (command.type === 'ChangeSourceExpr') {
			this.handleChangeSourceExpr(command);
		} else if (command.type === 'SetConfigComment') {
			this.handleSetConfigComment(command);
		} else if (command.type === 'CopyToClipboard') {
			this.clipboardService.writeText(command.text);
		}
	}

	/**
	 * Return a variable name based on `desired` that doesn't collide with any
	 * identifier already present in the document. Mirrors the Python runner's
	 * `_find_available_variable_name`: appends/increments a numeric suffix
	 * (`data` → `data2` → `data3`, `x1` → `x2`).
	 *
	 * `reserved` is for names the document is about to gain in the same edit —
	 * an import going in beside the assignment. `Counter = Counter(data)` reads
	 * fine until the next line calls `Counter` again, so a name we are in the
	 * act of binding has to count as taken.
	 */
	private findAvailableVarName(desired: string, excludedRange?: Range, reserved: readonly string[] = []): string {
		const model = this.editor.getModel();
		if (!model) {
			return desired;
		}
		let text = model.getValue();
		if (excludedRange) {
			const startOffset = model.getOffsetAt(excludedRange.getStartPosition());
			const endOffset = model.getOffsetAt(excludedRange.getEndPosition());
			text = text.slice(0, startOffset) + text.slice(endOffset);
		}
		const existing = new Set([...(text.match(/[A-Za-z_]\w*/g) ?? []), ...reserved]);
		if (!existing.has(desired)) {
			return desired;
		}
		const suffixMatch = desired.match(/^(.*?)(\d+)$/);
		let base: string;
		let next: number;
		if (suffixMatch) {
			base = suffixMatch[1];
			next = parseInt(suffixMatch[2], 10) + 1;
		} else {
			base = desired;
			next = 2;
		}
		while (existing.has(`${base}${next}`)) {
			next++;
		}
		return `${base}${next}`;
	}

	/**
	 * Insert the expression as new code on the line below `lineNumber`, matching
	 * that line's indentation. An assignable expression becomes a
	 * `<name> = <expr>` assignment (name derived from the expression and
	 * de-duplicated); a whole statement (e.g. a `for`/`if` snippet) is inserted
	 * verbatim without an assignment. The cursor is placed on the identifier the
	 * user is most likely to rename (the assignment target or loop variable).
	 * Triggered by the "+" button in an expression tooltip.
	 */
	private insertNewVarFromExpression(lineNumber: number, expression: string, imports?: readonly string[]): void {
		const model = this.editor.getModel();
		if (!model || this.isReadOnly()) {
			return;
		}
		studyLog.log('widget.insertNewVar', { line: lineNumber, expression, imports }, model.uri.toString());
		const expr = expression.trim();
		if (!expr) {
			return;
		}

		// Whatever the expression needs imported goes in with it, so the names
		// those imports bind are already spoken for by the time we pick one.
		const imported = importEdits(model, imports);
		const importedNames = imported.flatMap(edit => edit.text.match(/[A-Za-z_]\w*/g) ?? []);

		// Match the trigger line's indentation so the new statement lands at the
		// same block level.
		const firstNonWs = model.getLineFirstNonWhitespaceColumn(lineNumber);
		const indent = firstNonWs > 0
			? model.getLineContent(lineNumber).slice(0, firstNonWs - 1)
			: '';
		let editText: string;
		if (isAssignableExpression(expr)) {
			// Derive a descriptive name from the expression, de-duplicated against
			// identifiers already present so we don't shadow an existing variable.
			const varName = this.findAvailableVarName(
				suggestVarNameForExpression(expr), undefined, importedNames);
			editText = `${indent}${varName} = ${expr}`;
		} else {
			// A whole statement (e.g. a `for`/`if` snippet): insert it verbatim,
			// indenting every non-empty line to the trigger line's block level.
			editText = expr.split('\n').map(line => (line ? indent + line : line)).join('\n');
		}

		const col = model.getLineMaxColumn(lineNumber);
		const editOperation = {
			range: new Range(lineNumber, col, lineNumber, col),
			text: '\n' + editText
		};

		// The imports go in with the assignment, in one edit operation: one undo
		// step, and the line count can't shift between the two halves. What they
		// insert lands above the trigger line, so the cursor comes down by that
		// much.
		const importOperations = imported.map(edit => ({
			range: new Range(edit.afterLine + 1, 1, edit.afterLine + 1, 1),
			text: edit.text + '\n',
		}));
		const linesInsertedAbove = imported.reduce(
			(n, edit) => n + (edit.afterLine < lineNumber ? editLineCount(edit) : 0), 0);

		const newSelections = studyLog.withEditOrigin('InsertNewVar', () => model.pushEditOperations([], [editOperation, ...importOperations], (inverseEdits) => {
			const inv = inverseEdits[0];
			if (!inv) {
				return null;
			}
			const sel = computeRenameSelectionForEdit(editText, false, inv.range);
			return sel ? [sel] : null;
		}));

		if (newSelections && newSelections.length > 0) {
			this.editor.setSelection(newSelections[0]);
		} else {
			this.editor.setPosition({ lineNumber: lineNumber + 1 + linesInsertedAbove, column: 1 });
		}
		this.editor.focus();
	}

	/**
	 * Track the given editor range as the linked selection for a visualizer, so
	 * subsequent interactions update that range in place (ChangeSelectedText).
	 * Used for a range that SNC just inserted (auto-link) or an existing line
	 * taken over via the chain-icon relink.
	 */
	private establishLinkForRange(range: Range, line: number, visIndex: number): void {
		const editorModel = this.editor.getModel();
		if (!editorModel) {
			return;
		}
		const existing = this.findLink(line, visIndex);
		const decorationIds = editorModel.deltaDecorations(
			existing ? [existing.decorationId] : [],
			[{
				range,
				options: {
					description: 'snc-linked-selection',
					stickiness: TrackedRangeStickiness.NeverGrowsWhenTypingAtEdges,
				}
			}]
		);
		const decorationId = decorationIds[0] ?? null;
		if (decorationId) {
			this.setLink(line, visIndex, decorationId);
		}
	}

	/**
	 * Prefix every line after the first with `baseIndent`. A linked range starts
	 * at its line's first non-whitespace column, so the opening line is already
	 * positioned but the rest of a multi-line statement header starts at
	 * column 1.
	 */
	private static indentContinuationLines(code: string, baseIndent: string): string {
		if (!baseIndent || !code.includes('\n')) {
			return code;
		}
		return code.split('\n')
			.map((codeLine, i) => (i === 0 || codeLine === '' ? codeLine : baseIndent + codeLine))
			.join('\n');
	}

	/** One level of Python block indentation. Mirrors BLOCK_INDENT in visualizer_utils.py. */
	private static readonly BLOCK_INDENT = 4;

	/**
	 * The range of a linked statement's body: from the end of the linked range
	 * down through the last line indented past the header's own level. Starts at
	 * the header's end rather than the body's start so that removing it takes
	 * the newline between them too — and at the linked range's end rather than
	 * the line's, so anything the user has added after the header (a trailing
	 * comment) is neither swallowed nor read as part of the body.
	 *
	 * Null when no line below is indented past the header — which is every
	 * expression, and any header whose body the user has since deleted.
	 */
	private linkedBodyRange(headerRange: Range, baseIndent: string): Range | null {
		const model = this.editor.getModel();
		if (!model) {
			return null;
		}
		let last = 0;
		for (let l = headerRange.endLineNumber + 1; l <= model.getLineCount(); l++) {
			const firstNonWhitespace = model.getLineFirstNonWhitespaceColumn(l);
			if (firstNonWhitespace === 0) {
				continue; // blank line within the body
			}
			if (firstNonWhitespace - 1 <= baseIndent.length) {
				break; // dedent to the header's level or beyond ends the body
			}
			last = l;
		}
		return last === 0 ? null : new Range(
			headerRange.endLineNumber, headerRange.endColumn,
			last, model.getLineMaxColumn(last)
		);
	}

	/** Leading whitespace of the last line of generated code, in characters. */
	private static trailingHeaderDepth(code: string): number {
		const lines = code.split('\n');
		if (lines.length < 2) {
			return 0;
		}
		const last = lines[lines.length - 1];
		return last.length - last.trimStart().length;
	}

	/**
	 * Edits that move a linked statement's body along with its header.
	 *
	 * Switching loop actions can nest the header a level deeper (`for ...:`
	 * becoming `for ...:` plus `if ...:`) or lift it back out. The body below is
	 * the user's code, so rather than regenerating it we shift it by the same
	 * amount the header's depth changed, which also preserves whatever
	 * indentation width the body already uses.
	 */
	private bodyReindentEdits(headerRange: Range, expression: string, baseIndent: string)
		: { range: Range; text: string }[] {
		const model = this.editor.getModel();
		if (!model) {
			return [];
		}
		const oldDepth = headerRange.endLineNumber > headerRange.startLineNumber
			? Math.max(0, this.getLineIndent(headerRange.endLineNumber) - baseIndent.length)
			: 0;
		const delta = SNCController.trailingHeaderDepth(expression) - oldDepth;
		if (delta === 0) {
			return [];
		}

		const edits: { range: Range; text: string }[] = [];
		for (let l = headerRange.endLineNumber + 1; l <= model.getLineCount(); l++) {
			const firstNonWhitespace = model.getLineFirstNonWhitespaceColumn(l);
			if (firstNonWhitespace === 0) {
				continue; // blank line within the body
			}
			const indentLength = firstNonWhitespace - 1;
			if (indentLength <= baseIndent.length) {
				break; // dedent to the header's level or beyond ends the body
			}
			const existing = model.getLineContent(l).slice(0, indentLength);
			const shifted = delta > 0
				? existing + ' '.repeat(delta)
				: existing.slice(0, Math.max(baseIndent.length + 1, indentLength + delta));
			edits.push({ range: new Range(l, 1, l, firstNonWhitespace), text: shifted });
		}
		return edits;
	}

	/**
	 * Whether a line is a block header (`for ...:`, `if ...:`). Such a line can
	 * be a link target: the visualizer owns the header and the body below it
	 * belongs to the user. Mirrors opens_block in visualizer_utils.py.
	 */
	private static opensBlock(text: string): boolean {
		return text.trimEnd().endsWith(':');
	}

	/**
	 * Split an assignment line into (leadingWhitespace, varName, rhs). Returns
	 * null if the text isn't a simple `name = rhs` assignment (e.g. a bare
	 * expression or a statement), in which case the caller leaves it untouched.
	 */
	private static splitAssignment(text: string): { indent: string; name: string; rhs: string } | null {
		const m = /^(\s*)([A-Za-z_]\w*)\s*=\s*([\s\S]+)$/.exec(text);
		if (!m) {
			return null;
		}
		return { indent: m[1], name: m[2], rhs: m[3] };
	}

	/**
	 * Whether `name` appears as an identifier anywhere in the document outside
	 * the given range. Used to decide if renaming the linked line's assignment
	 * target is safe (won't orphan references elsewhere).
	 */
	private isVarNameUsedOutsideRange(name: string, range: Range): boolean {
		const editorModel = this.editor.getModel();
		if (!editorModel) {
			return true; // be conservative
		}
		const wordRe = new RegExp(`\\b${name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\b`, 'g');
		const fullText = editorModel.getValue();
		const startOffset = editorModel.getOffsetAt(range.getStartPosition());
		const endOffset = editorModel.getOffsetAt(range.getEndPosition());
		let match: RegExpExecArray | null;
		while ((match = wordRe.exec(fullText)) !== null) {
			const idx = match.index;
			// Ignore occurrences that fall inside the linked range itself.
			if (idx >= startOffset && idx < endOffset) {
				continue;
			}
			return true;
		}
		return false;
	}

	private handleChangeSelectedText(expression: string, suggestedVarName: string | null, line: number, visIndex: number): void {
		const editorModel = this.editor.getModel();
		const link = this.findLink(line, visIndex);
		if (!editorModel || !link) {
			return;
		}
		const trackedRange = editorModel.getDecorationRange(link.decorationId);
		// Missing or empty range means the linked text is gone (deleted line,
		// cleared selection). Tear down instead of inserting at the collapse
		// point (which would append to the end of the previous line).
		if (!trackedRange || trackedRange.isEmpty()) {
			this.teardownLink(link);
			return;
		}

		const currentText = editorModel.getValueInRange(trackedRange);

		// A linked range starts past the line's indentation, so continuation
		// lines of a multi-line statement header must carry it themselves.
		const baseIndent = this.getLineIndentText(trackedRange.startLineNumber);
		const indented = SNCController.indentContinuationLines(expression, baseIndent);

		// The editor range is the source of truth for the target name — Python
		// sends only a replacement expression plus an optional semantic rename
		// request when the action changes. The *shape* is the new expression's
		// to decide, though: switching Join to Loop hands over a block header,
		// and keeping the `name = ` the line happens to carry would write
		// `name = for item in ...:`.
		const current = SNCController.opensBlock(expression)
			? null
			: SNCController.splitAssignment(currentText);
		let newText: string;
		if (current) {
			let targetName = current.name;
			if (suggestedVarName && suggestedVarName !== current.name
				&& !this.isVarNameUsedOutsideRange(current.name, trackedRange)) {
				targetName = this.findAvailableVarName(suggestedVarName, trackedRange);
			}
			newText = `${current.indent}${targetName} = ${indented}`;
		} else {
			const indent = /^[ \t]*/.exec(currentText)?.[0] ?? '';
			newText = `${indent}${indented}`;
		}

		if (currentText === newText) {
			return;
		}

		// The body has to follow the header's shape. A `pass` is scaffolding this
		// code wrote itself (with_pass_body, in python_runner.py) and comes away
		// with the block it was holding open; a body the user has written is
		// theirs and stays where they put it, even where an expression leaves it
		// stranded — better a break they can undo than code deleted under them.
		const bodyRange = this.linkedBodyRange(trackedRange, baseIndent);
		let editRange = trackedRange;
		let editText = newText;
		if (SNCController.opensBlock(expression)) {
			if (!bodyRange) {
				// An expression becoming a header has nothing indented below it,
				// so it needs the placeholder a freshly inserted statement gets.
				const depth = SNCController.trailingHeaderDepth(expression) + SNCController.BLOCK_INDENT;
				editText = `${newText}\n${baseIndent}${' '.repeat(depth)}pass`;
			}
		} else if (bodyRange && editorModel.getValueInRange(bodyRange).trim() === 'pass') {
			editRange = Range.fromPositions(trackedRange.getStartPosition(), bodyRange.getEndPosition());
		}
		const absorbedBody = editRange !== trackedRange;

		this.isApplyingLinkedEdit = true;
		studyLog.withEditOrigin('ChangeSelectedText', () => editorModel.pushEditOperations([], [
			{ range: editRange, text: editText },
			// A deeper or shallower header has to take its body with it; done in
			// the same operation so it is a single undo step. Nothing to reindent
			// when the body just came away with the header.
			...(absorbedBody ? [] : this.bodyReindentEdits(trackedRange, expression, baseIndent)),
		], () => null));

		// Update the tracked decoration to cover the newly inserted text
		const startOffset = editorModel.getOffsetAt(trackedRange.getStartPosition());
		const newEnd = editorModel.getPositionAt(startOffset + newText.length);
		const newRange = new Range(
			trackedRange.startLineNumber, trackedRange.startColumn,
			newEnd.lineNumber, newEnd.column
		);
		const ids = editorModel.deltaDecorations(
			[link.decorationId],
			[{
				range: newRange,
				options: {
					description: 'snc-linked-selection',
					stickiness: TrackedRangeStickiness.NeverGrowsWhenTypingAtEdges,
				},
			}]
		);
		const newDecorationId = ids[0] ?? null;
		if (newDecorationId) {
			link.decorationId = newDecorationId;
		}

		// The linked line may have moved/resized; re-anchor its arrow.
		this.updateLinkChrome();

		setTimeout(() => { this.isApplyingLinkedEdit = false; }, 0);
	}

	/**
	 * Turn a 0-based UTF-8 byte offset into the editor's 1-based column.
	 *
	 * Python's parser counts bytes; the editor counts UTF-16 code units. The two
	 * agree until a line carries a non-ASCII character ahead of the expression,
	 * and then a byte offset used as a column would land mid-expression.
	 */
	private static byteOffsetToColumn(lineText: string, byteOffset: number): number {
		if (byteOffset <= 0) {
			return 1;
		}
		const encoder = new TextEncoder();
		let bytes = 0;
		let units = 0;
		// By code point, not by index: indexing a string splits surrogate pairs,
		// and half a pair encodes as the replacement character's three bytes.
		for (const ch of lineText) {
			if (bytes >= byteOffset) {
				break;
			}
			bytes += encoder.encode(ch).length;
			units += ch.length;
		}
		return units + 1;
	}

	/**
	 * Replace the expression a visualizer's own line is showing (Sort).
	 *
	 * Simpler than handleChangeSelectedText: there is no assignment to split —
	 * the range covers the expression and nothing else, so an `x = `, a
	 * `return ` or an `if ` around it is untouched by construction — and no
	 * decoration to re-anchor, since this line is found by number rather than
	 * tracked. The cursor is deliberately left where it is, so the visualizer
	 * that asked for the edit keeps focus and its menu stays open.
	 */
	private handleChangeSourceExpr(command: Extract<SNCCommand, { type: 'ChangeSourceExpr' }>): void {
		const editorModel = this.editor.getModel();
		if (!editorModel) {
			return;
		}
		const lineCount = editorModel.getLineCount();
		if (command.start_line < 1 || command.end_line > lineCount) {
			// The file has moved on since the span was reported.
			return;
		}

		const startColumn = SNCController.byteOffsetToColumn(
			editorModel.getLineContent(command.start_line), command.start_col);
		const endColumn = SNCController.byteOffsetToColumn(
			editorModel.getLineContent(command.end_line), command.end_col);
		const range = new Range(command.start_line, startColumn, command.end_line, endColumn);

		const baseIndent = this.getLineIndentText(command.start_line);
		const newText = SNCController.indentContinuationLines(command.expression, baseIndent);
		if (editorModel.getValueInRange(range) === newText) {
			return;
		}

		this.isApplyingLinkedEdit = true;
		studyLog.withEditOrigin('ChangeSourceExpr', () => editorModel.pushEditOperations([], [{ range, text: newText }], () => null));
		setTimeout(() => { this.isApplyingLinkedEdit = false; }, 0);
	}

	/**
	 * Rewrite (or write, or remove) the trailing `#%click` comment on the
	 * visualizer's line. Replacing in place rather than appending makes a
	 * repeated command -- an event replayed across two runs -- harmless.
	 */
	private handleSetConfigComment(command: Extract<SNCCommand, { type: 'SetConfigComment' }>): void {
		const model = this.editor.getModel();
		if (!model) {
			return;
		}
		// Where that line is NOW: an import this run inserted above it has
		// already gone in by the time this lands, and the comment belongs on
		// the line as it stands, not as Python was told about it. Left as
		// reported when the run had nothing to say about the line -- there is
		// nothing better to go on, and it is right whenever nothing moved.
		const boundLine = this.reportedLineNow.get(command.triggerLine) ?? command.triggerLine;
		if (boundLine < 1 || boundLine > model.getLineCount()) {
			// The file has moved on since the visualizer's line was reported.
			return;
		}
		const content = model.getLineContent(boundLine);
		const startCol = configCommentStartColumn(content);

		let edit: { range: Range; text: string };
		if (startCol) {
			if (command.comment === null) {
				// Take the whitespace separating the comment from the code too.
				const codeEnd = content.slice(0, startCol - 1).trimEnd().length;
				edit = { range: new Range(boundLine, codeEnd + 1, boundLine, model.getLineMaxColumn(boundLine)), text: '' };
			} else {
				if (content.slice(startCol - 1) === command.comment) {
					return;
				}
				edit = { range: new Range(boundLine, startCol, boundLine, model.getLineMaxColumn(boundLine)), text: command.comment };
			}
		} else {
			if (command.comment === null) {
				return;
			}
			const col = model.getLineMaxColumn(boundLine);
			edit = { range: new Range(boundLine, col, boundLine, col), text: '  ' + command.comment };
		}

		studyLog.withEditOrigin('SetConfigComment', () => model.pushEditOperations([], [edit], () => null));
	}

	/**
	 * Fold each `#%click` comment's JSON down to a `…` token, leaving the
	 * `#%click` prefix to say what the line is. What the JSON holds is what the
	 * visualizer shows, so the text is storage rather than something to read.
	 * The one comment the user has clicked open (`openConfigCommentLine`, see
	 * onConfigCommentMouseDown) is shown in full so it can be edited.
	 */
	private updateConfigCommentFolding(): void {
		const model = this.editor.getModel();
		if (!model || !this.isPythonModel() || !this.widgetsVisible) {
			this.configCommentDecorations.clear();
			return;
		}
		const decorations: IModelDeltaDecoration[] = [];
		const foldedLines = new Set<number>();
		for (const match of model.findMatches(CONFIG_COMMENT_PREFIX, false, false, true, null, false)) {
			const ln = match.range.startLineNumber;
			if (ln === this.openConfigCommentLine || foldedLines.has(ln)) {
				continue;
			}
			const content = model.getLineContent(ln);
			const startCol = configCommentStartColumn(content);
			if (!startCol) {
				continue;
			}
			foldedLines.add(ln);
			const payloadStart = startCol - 1 + CONFIG_COMMENT_PREFIX.length + 1;
			if (payloadStart >= content.length) {
				continue;
			}
			decorations.push({
				range: new Range(ln, payloadStart + 1, ln, model.getLineMaxColumn(ln)),
				options: {
					description: 'snc-config-comment-fold',
					inlineClassName: 'snc-config-payload',
					after: { content: '…', inlineClassName: 'snc-config-ellipsis' },
				},
			});
		}
		this.configCommentDecorations.set(decorations);
	}

	/**
	 * Open a folded config comment when its chip -- the `#%click …` tail of
	 * the line -- is clicked. Moving the cursor onto the line is deliberately
	 * not enough: the JSON is storage, so it stays folded until asked for, and
	 * once the cursor leaves the line it folds again (see the cursor listener)
	 * until the next click.
	 */
	private onConfigCommentMouseDown(e: IEditorMouseEvent): void {
		const model = this.editor.getModel();
		const position = e.target.position;
		if (!model || !position || e.target.type !== MouseTargetType.CONTENT_TEXT) {
			return;
		}
		if (position.lineNumber === this.openConfigCommentLine) {
			return;
		}
		const startCol = configCommentStartColumn(model.getLineContent(position.lineNumber));
		if (startCol && position.column >= startCol) {
			this.openConfigCommentLine = position.lineNumber;
			this.updateConfigCommentFolding();
		}
	}

	/**
	 * Log comprehensive visualizer timing data.
	 *
	 * Measurements:
	 * 1. triggerToSpawn: Time from trigger (runProgram call) to Python spawn
	 * 2. spawnToFirstStdout: Time from spawn to first visualizer data on stdout (backend)
	 * 3. firstStdoutToFirstRender: Time from first stdout to first render completion (frontend)
	 * 4. total: Total time from trigger to first render completion
	 */
	private logVisualizerTiming(runId: string, backendTiming: SNCTimingData | undefined, tEnd: number): void {
		const triggerMs = this.runTriggerMsById.get(runId);
		const firstItemReceivedMs = this.runFirstItemReceivedMsById.get(runId);
		const firstRenderMs = this.runFirstRenderMsById.get(runId);
		const firstRenderFrameMs = this.runFirstRenderFrameMsById.get(runId);
		const spawnTiming = this.runSpawnTimingById.get(runId);

		// If we don't have the spawn timing from the spawn message, use the one from the end message
		const timing = spawnTiming || backendTiming;

		if (typeof triggerMs !== 'number' || !timing) {
			// Not enough data for timing - likely the run was cancelled or errored early
			return;
		}

		// Calculate timings
		// Note: We can't directly compare frontend (performance.now) and backend (Date.now) times,
		// but we can use the backend's relative timings and our frontend measurements.

		// 1. Trigger to spawn: approximate using the time the spawn message was processed
		//    Since spawn message is emitted immediately after spawn and IPC is fast,
		//    this gives us a reasonable approximation
		const triggerToFirstItemReceived = typeof firstItemReceivedMs === 'number' ? firstItemReceivedMs - triggerMs : undefined;

		// 2. Spawn to first stdout (backend timing)
		const spawnToFirstStdout = timing.spawnToStdoutFirstMs;

		// 3. Spawn to first item parsed (backend timing)
		const spawnToFirstItem = timing.spawnToFirstItemMs;

		// 4. First item received to first render (frontend timing, sync DOM mutation)
		const firstItemToFirstRender = (typeof firstItemReceivedMs === 'number' && typeof firstRenderMs === 'number')
			? firstRenderMs - firstItemReceivedMs
			: undefined;

		// 5. First render sync to render frame (editor's rAF render pass cost)
		const firstRenderToFrame = (typeof firstRenderMs === 'number' && typeof firstRenderFrameMs === 'number')
			? firstRenderFrameMs - firstRenderMs
			: undefined;

		// 6. Total from trigger to first render (sync)
		const triggerToFirstRender = typeof firstRenderMs === 'number' ? firstRenderMs - triggerMs : undefined;

		// 7. Total from trigger to first render frame (rAF)
		const triggerToFirstRenderFrame = typeof firstRenderFrameMs === 'number' ? firstRenderFrameMs - triggerMs : undefined;

		// 8. Total from trigger to end
		const triggerToEnd = tEnd - triggerMs;

		// Build timing summary
		const timingSummary = {
			runId,
			// Frontend timings (all relative to trigger)
			triggerToFirstItemReceivedMs: triggerToFirstItemReceived !== undefined ? Math.round(triggerToFirstItemReceived * 100) / 100 : undefined,
			firstItemReceivedToFirstRenderMs: firstItemToFirstRender !== undefined ? Math.round(firstItemToFirstRender * 100) / 100 : undefined,
			firstRenderToFrameMs: firstRenderToFrame !== undefined ? Math.round(firstRenderToFrame * 100) / 100 : undefined,
			triggerToFirstRenderMs: triggerToFirstRender !== undefined ? Math.round(triggerToFirstRender * 100) / 100 : undefined,
			triggerToFirstRenderFrameMs: triggerToFirstRenderFrame !== undefined ? Math.round(triggerToFirstRenderFrame * 100) / 100 : undefined,
			triggerToEndMs: Math.round(triggerToEnd * 100) / 100,
			// Backend timings (all relative to spawn)
			spawnToStdinEndMs: timing.spawnToStdinEndMs,
			spawnToFirstStdoutMs: spawnToFirstStdout,
			spawnToFirstItemParsedMs: spawnToFirstItem,
			spawnToEndMs: timing.spawnToEndMs,
		};

		console.log('SNC Visualizer Timing:', timingSummary);

		// Log a human-readable summary
		const parts: string[] = [];
		if (triggerToFirstItemReceived !== undefined) {
			parts.push(`trigger→firstItem: ${Math.round(triggerToFirstItemReceived)}ms`);
		}
		if (spawnToFirstStdout !== undefined) {
			parts.push(`spawn→stdout: ${spawnToFirstStdout}ms`);
		}
		if (firstItemToFirstRender !== undefined) {
			parts.push(`firstItem→render: ${Math.round(firstItemToFirstRender)}ms`);
		}
		if (firstRenderToFrame !== undefined) {
			parts.push(`render→frame: ${Math.round(firstRenderToFrame)}ms`);
		}
		if (triggerToFirstRenderFrame !== undefined) {
			parts.push(`TOTAL trigger→frame: ${Math.round(triggerToFirstRenderFrame)}ms`);
		} else if (triggerToFirstRender !== undefined) {
			parts.push(`TOTAL trigger→render: ${Math.round(triggerToFirstRender)}ms`);
		}
		if (parts.length > 0) {
			console.log(`SNC Timing Summary: ${parts.join(' | ')}`);
		}

		// Event-target timing (only when this run was triggered by an event)
		const eventTarget = this.runEventTargetById.get(runId);
		if (eventTarget) {
			const evtItemMs = this.runEventTargetItemReceivedMsById.get(runId);
			const evtRenderMs = this.runEventTargetRenderMsById.get(runId);
			const evtFrameMs = this.runEventTargetRenderFrameMsById.get(runId);

			const triggerToEvtItem = typeof evtItemMs === 'number' ? evtItemMs - triggerMs : undefined;
			const evtItemToRender = (typeof evtItemMs === 'number' && typeof evtRenderMs === 'number')
				? evtRenderMs - evtItemMs : undefined;
			const evtRenderToFrame = (typeof evtRenderMs === 'number' && typeof evtFrameMs === 'number')
				? evtFrameMs - evtRenderMs : undefined;
			const triggerToEvtFrame = typeof evtFrameMs === 'number' ? evtFrameMs - triggerMs : undefined;
			const triggerToEvtRender = typeof evtRenderMs === 'number' ? evtRenderMs - triggerMs : undefined;

			const evtParts: string[] = [];
			if (triggerToEvtItem !== undefined) {
				evtParts.push(`trigger→evtItem: ${Math.round(triggerToEvtItem)}ms`);
			}
			if (evtItemToRender !== undefined) {
				evtParts.push(`evtItem→render: ${Math.round(evtItemToRender)}ms`);
			}
			if (evtRenderToFrame !== undefined) {
				evtParts.push(`render→frame: ${Math.round(evtRenderToFrame)}ms`);
			}
			if (triggerToEvtFrame !== undefined) {
				evtParts.push(`TOTAL trigger→frame: ${Math.round(triggerToEvtFrame)}ms`);
			} else if (triggerToEvtRender !== undefined) {
				evtParts.push(`TOTAL trigger→render: ${Math.round(triggerToEvtRender)}ms`);
			}
			if (evtParts.length > 0) {
				console.log(`SNC Event Target [${eventTarget.line}:${eventTarget.visIndex}]: ${evtParts.join(' | ')}`);
			}
		}
	}

	/** Path of the file this controller is showing, or '' for an unsaved buffer. */
	private currentFilePath(): string {
		const modelUri = this.editor.getModel()?.uri;
		return modelUri?.scheme === Schemas.file ? modelUri.fsPath : '';
	}

	// ---- Loop sliders ----

	private loopSelectionLine(selection: { decorationId: string }): number | null {
		const model = this.editor.getModel();
		return model?.getDecorationRange(selection.decorationId)?.startLineNumber ?? null;
	}

	/**
	 * `{ headerLine: iteration }` as Python takes it: every pinned loop, and
	 * for the rest the first iteration. Iteration 0 is the one index that
	 * survives the loop's count changing under an edit -- any run that entered
	 * the loop at all ran it -- so half-typed code can't move an unpinned loop
	 * off what is on screen. A loop nothing is known about yet streams every
	 * iteration.
	 */
	private loopSelectionsByLine(): Record<string, number> {
		const out: Record<string, number> = {};
		for (const [line, count] of this.loopCounts) {
			if (count > 0 && this.selectedIteration(line) === null) {
				out[String(line)] = 0;
			}
		}
		for (const selection of this.loopSelections) {
			const line = this.loopSelectionLine(selection);
			if (line !== null) {
				out[String(line)] = selection.iteration;
			}
		}
		return out;
	}

	private selectedIteration(line: number): number | null {
		const selection = this.loopSelections.find(s => this.loopSelectionLine(s) === line);
		return selection ? selection.iteration : null;
	}

	/** Pin the loop whose header is `line` to `iteration`, or unpin it with `null`. */
	private setLoopSelection(line: number, iteration: number | null): void {
		const model = this.editor.getModel();
		if (!model) {
			return;
		}
		const existing = this.loopSelections.find(s => this.loopSelectionLine(s) === line);
		if (iteration === null) {
			if (existing) {
				model.deltaDecorations([existing.decorationId], []);
				this.loopSelections = this.loopSelections.filter(s => s !== existing);
			}
			return;
		}
		if (existing) {
			existing.iteration = iteration;
			return;
		}
		const [decorationId] = model.deltaDecorations([], [{
			range: new Range(line, 1, line, 1),
			options: {
				description: 'snc-loop-selection',
				stickiness: TrackedRangeStickiness.NeverGrowsWhenTypingAtEdges,
			}
		}]);
		if (decorationId) {
			this.loopSelections.push({ decorationId, iteration });
		}
	}

	/**
	 * A loop finished. Size its slider, and:
	 *
	 * - Unpinned, the loop shows its first iteration. A loop nothing was known
	 *   about streamed every iteration, each item replacing the last, so what
	 *   is on screen is whatever ran latest. Now that the loop has reported,
	 *   those go and iteration 0 is what remains.
	 *
	 * A pin past the end is dealt with when the run ends (clampLoopSelections):
	 * a function reports after every call, so mid-run its count is still
	 * climbing and isn't something to clamp against.
	 */
	private onLoopReport(loop: ILoopReport): void {
		this.loopCountsThisRun.set(loop.line, loop.count);
		this.loopCounts.set(loop.line, Math.max(this.loopCounts.get(loop.line) ?? 0, loop.count));
		const selected = this.selectedIteration(loop.line);
		if (selected === null && loop.kind === 'loop') {
			// (A function's activations nest under recursion, so "the first
			// one" isn't one thing; there, whatever arrived last stays.)
			const under = (path: LoopPath): boolean => {
				const depth = path.findIndex(([line]) => line === loop.line);
				if (depth < 0 || depth !== loop.path.length) {
					return false;
				}
				return loop.path.every(([line, k], i) => path[i][0] === line && path[i][1] === k);
			};
			const kept = this.visualizationItems.filter(item =>
				!under(item.path) || item.path[loop.path.length][1] === 0);
			if (kept.length !== this.visualizationItems.length) {
				this.visualizationItems = kept;
			}
		}
		this.updateLoopSliders();
	}

	/**
	 * A pin past the end of its loop (the code changed and the loop got
	 * shorter) moves to the last iteration, and the program reruns for it.
	 * Only against counts this run finished reporting.
	 */
	private clampLoopSelections(): void {
		let changed = false;
		for (const selection of [...this.loopSelections]) {
			const line = this.loopSelectionLine(selection);
			if (line === null || !this.loopCountsThisRun.has(line)) {
				continue;
			}
			const count = this.loopCountsThisRun.get(line) ?? 0;
			if (selection.iteration >= count) {
				this.setLoopSelection(line, count > 0 ? count - 1 : null);
				changed = true;
			}
		}
		// (An unpinned loop needs nothing here: it is shown at iteration 0, which
		// stays in range however the count moved.)
		if (changed) {
			this.updateLoopSliders();
			this.scheduleRun();
		}
	}

	/** One slider per loop/def line that ran more than once; none elsewhere. */
	private updateLoopSliders(): void {
		if (!this.widgetsVisible) {
			return;
		}
		for (const [line, count] of this.loopCounts) {
			let slider = this.loopSliders.get(line);
			if (count < 2) {
				if (slider) {
					slider.dispose();
					this.loopSliders.delete(line);
				}
				continue;
			}
			if (!slider) {
				slider = new LoopSliderWidget(this.editor, line, iteration => {
					this.setLoopSelection(line, iteration);
					this.scheduleRun('loop-slider');
				});
				this.loopSliders.set(line, slider);
			}
			slider.update(count, this.selectedIteration(line) ?? 0);
		}
		for (const [line, slider] of Array.from(this.loopSliders.entries())) {
			if (!this.loopCounts.has(line)) {
				slider.dispose();
				this.loopSliders.delete(line);
			}
		}
		// The visualizer on a slider's line sits after the slider.
		for (const [line, widgets] of this.visualizationWidgets) {
			const inset = this.loopSliders.has(line) ? LoopSliderWidget.WIDTH : 0;
			for (const widget of widgets) {
				if (widget.leftInset !== inset) {
					widget.leftInset = inset;
					widget.updatePosition();
				}
			}
		}
		for (const slider of this.loopSliders.values()) {
			slider.updatePosition();
		}
	}

	/** Rerun after the usual debounce, as a source edit would. */
	/** Why the next scheduleRun() fires, for the study log; reset after each run. */
	private scheduledRunTrigger = 'scheduled';

	private scheduleRun(trigger: string = 'scheduled'): void {
		if (!this.isPythonModel()) {
			return;
		}
		this.scheduledRunTrigger = trigger;
		if (this.debounceTimer) {
			clearTimeout(this.debounceTimer);
		}
		this.debounceTimer = setTimeout(() => {
			this.debounceTimer = null;
			this.runProgram(this.getProgram(), undefined, this.scheduledRunTrigger);
			this.scheduledRunTrigger = 'scheduled';
		}, this.debounceDelay);
	}

	private async runProgram(content: string, uiEvent?: UiEvent, trigger: string = 'unknown'): Promise<void> {
		// Defensive guard: every caller should already gate on isPythonModel(),
		// but make sure we never spawn a Python worker for a non-Python buffer.
		if (!this.isPythonModel()) {
			return;
		}

		// A run from anything but a move (an edit, cursor line change, ...) can
		// rebuild the model from scratch; a repeat of the last move is then
		// worth sending again, e.g. to restore hover state the reset dropped.
		if (!trigger.startsWith('widget:mousemove')) {
			this.lastSentMoveKey = null;
		}

		// Committed to a run from here on; see the field's comment.
		this.runStarting = true;

		// Get the working directory from the first workspace folder
		const workingDirectory = this.workspaceContextService.getWorkspace().folders[0]?.uri.fsPath || '';
		const filePath = this.currentFilePath();
		const channel = this.mainProcessService.getChannel('sncProcess');

		// Add event to appropriate visualizer. This happens synchronously,
		// before the cancel below is awaited: an item from the run being
		// cancelled could otherwise still arrive in that gap and be taken as
		// current, having handled nothing of this event.
		if (uiEvent) {
			let found = false;
			this.visualizationItems = this.visualizationItems.map(visItem => {
				if (visItem.line == uiEvent.line && visItem.visIndex == uiEvent.visIndex) {
					found = true;
					return {
						...visItem,
						unhandledEvents: [...(visItem.unhandledEvents || []), uiEvent]
					}
				}
				return visItem;
			});
			if (!found) {
				console.error(`SNC: No vis at ${uiEvent.line}:${uiEvent.visIndex} to queue event on!`)
			}

			// The run in flight hasn't reached this widget yet, so it can still
			// answer this event. Killing it to start another would only pay the
			// startup again and put us further behind -- a gesture at 60Hz
			// outruns any number of workers. Hand the event over instead; the
			// run reports what it applied and `itemArrived` starts the next run
			// if anything is left over.
			if (this.currentRunId && !this.itemsThisRun.has(widgetKey(uiEvent.line, uiEvent.visIndex))) {
				this.runStarting = false;
				try { await channel.call('sendEvents', [[uiEvent]]); } catch { /* run is ending; it stays queued */ }
				return;
			}
		}

		// Cancel any previous streaming run. Disown it first so nothing more it
		// streams during the await is applied: its models predate the events
		// queued above.
		const previousRunId = this.currentRunId;
		let cancelledPrevious: string | null = null;
		if (previousRunId) {
			cancelledPrevious = previousRunId;
			this.logRunCancelled(previousRunId, `superseded:${trigger}`);
			this.currentRunId = null;
			try { await channel.call('cancel', [previousRunId]); } catch { /* ignore */ }
			// Another call may have started a run while this one waited. Its
			// event snapshot is older than the one taken below, so it gives way.
			if (this.currentRunId) {
				const overtakenRunId = this.currentRunId;
				this.logRunCancelled(overtakenRunId, `overtaken:${trigger}`);
				this.currentRunId = null;
				try { await channel.call('cancel', [overtakenRunId]); } catch { /* ignore */ }
			}
		}

		this.streamUpdateTimer = null;

		// Ensure we are subscribed to the streaming event once
		if (!this.streamSubscription) {
			const ev = channel.listen<SNCStreamMessage>('onStream');
			this.streamSubscription = ev((msg) => {
				// Filter by run id for this controller
				if (!this.currentRunId || msg.runId !== this.currentRunId) {
					return;
				}

				const now = () => (typeof performance !== 'undefined' ? performance.now() : Date.now());

				if (msg.type === 'spawn') {
					// Store backend spawn timing data
					this.runSpawnTimingById.set(msg.runId, msg.timing);
				} else if (msg.type === 'output') {
					if (this.consoleFilePath) {
						this.consoleService.appendOutput(this.consoleFilePath, {
							stream: msg.stream,
							text: msg.text,
							stdinOffset: msg.stdinOffset
						});
					}
				} else if (msg.type === 'resumed') {
					// A warm worker took this run at its pause, so the program is
					// already past every widget behind `msg.step` and will emit
					// no item for any of them.
					this.resumedFromStep = msg.step;
					// Seed them as already-seen. Load-bearing twice over: the
					// mid-run gate must refuse to hand one of them an event to a
					// run that is past it (and start a fresh run instead), and
					// the sweep at the end of this handler must not read "no item
					// arrived" as "this widget isn't part of the execution" and
					// throw its queued events away.
					let strandedBehindThePause = false;
					for (const item of this.visualizationItems) {
						if (item.execution_step < msg.step) {
							this.itemsThisRun.add(widgetKey(item.line, item.visIndex));
							strandedBehindThePause ||= !!item.unhandledEvents?.length;
						}
					}
					// `resumeAtStepFor` keeps a run that owes a widget behind the
					// pause off a warm worker, so anything queued there now was
					// handed over in the moment between this run being dispatched
					// and this message arriving. No item will arrive for it, so
					// the usual retry (on item arrival) never fires -- schedule
					// the run here instead of leaving the event to wait for the
					// user's next gesture.
					if (strandedBehindThePause) {
						this.scheduleQueuedEventRun();
					}
				} else if (msg.type === 'item') {
					// console.log(msg.item.model)
					// Timing: first item arrival for this run
					const isFirstItem = !this.runFirstItemReceivedMsById.has(msg.runId);
					if (isFirstItem) {
						this.runFirstItemReceivedMsById.set(msg.runId, now());
						// Python is producing output again — clear any stale
						// spawn-failure toast so the user knows it's resolved.
						this.dismissPythonSpawnFailureNotification();
					}

					// Timing: event-target item arrival
					const eventTarget = this.runEventTargetById.get(msg.runId);
					const isEventTargetItem = eventTarget
						&& msg.item.line === eventTarget.line
						&& msg.item.visIndex === eventTarget.visIndex;
					if (isEventTargetItem && !this.runEventTargetItemReceivedMsById.has(msg.runId)) {
						this.runEventTargetItemReceivedMsById.set(msg.runId, now());
					}

					// The commands ride on the item so a kill between the two can't
					// split them (see IVisualizationItem.commands). They are for
					// the editor, not for the model, so the stored item goes
					// without them; they are applied once, below.
					const { commands: itemCommands, ...item } = msg.item;

					// replace prior items as new ones come in
					let found = false;
					this.visualizationItems = this.visualizationItems.map(visItem => {
						if (visItem.line == item.line && visItem.visIndex == item.visIndex) {
							found = true;
							// What the runner says it applied, not what we sent it:
							// it declines to replay onto a rebuilt model, and it
							// may have picked up events queued after dispatch.
							const handled = new Set(item.handledEventIds ?? []);
							return {
								...item,
								unhandledEvents: (visItem.unhandledEvents || []).filter(ev => !handled.has(ev.id))
							};
						}
						return visItem;
					});
					if (!found) {
						this.visualizationItems = [...this.visualizationItems, item];
					}

					// This run is past that widget now, so whatever it didn't
					// apply needs another run -- events race in just behind the
					// widget, and the runner won't replay onto a model it had
					// to rebuild. Unless this run *was* that retry: then it has
					// declined them twice and will keep doing so, so drop them
					// rather than spin runs forever.
					this.itemsThisRun.add(widgetKey(msg.item.line, msg.item.visIndex));
					const isThisItem = (v: IVisualizationItem) =>
						v.line === msg.item.line && v.visIndex === msg.item.visIndex;
					const leftover = this.visualizationItems.find(isThisItem)?.unhandledEvents ?? [];
					let droppedEvents: UiEvent[] = [];
					if (leftover.length) {
						if (this.runTriggerById.get(msg.runId) === 'queued-events') {
							droppedEvents = leftover;
							this.visualizationItems = this.visualizationItems.map(v =>
								isThisItem(v) ? { ...v, unhandledEvents: [] } : v);
						} else {
							this.scheduleQueuedEventRun();
						}
					}
					// The item is the unit the cancel/requeue logic reasons about,
					// and it used to be invisible in the log: which events a run
					// answered, and what it asked for, could only be inferred from
					// the next run's queue count. Plain items -- most of them, in a
					// loop-heavy program -- are counted at run.end instead.
					if (item.handledEventIds?.length || itemCommands?.length || leftover.length) {
						studyLog.log('run.item', {
							runId: msg.runId, trigger: this.runTriggerById.get(msg.runId),
							line: item.line, visIndex: item.visIndex, step: item.execution_step,
							handledEventIds: item.handledEventIds ?? [],
							commands: (itemCommands ?? []).map(c => c.type),
							stillQueued: leftover.map(e => ({ id: e.id, type: e.eventJSON?.type, pythonEventStr: e.pythonEventStr })),
							dropped: droppedEvents.length ? 'declined-twice' : undefined,
						}, this.editor.getModel()?.uri.toString());
					}

					// Throttle UI updates
					if (!this.streamUpdateTimer) {
						this.updateVisualizationWidgets(this.visualizationItems);

						// Track first render timing:
						// 1. Sync: DOM mutations from changeViewZones are complete
						// 2. rAF: fires after the editor's scheduled render pass
						//    (registered after _scheduleRender's rAF, so runs after it)
						if (isFirstItem && !this.runFirstRenderMsById.has(msg.runId)) {
							this.runFirstRenderMsById.set(msg.runId, now());
							const runId = msg.runId;
							dom.getActiveWindow().requestAnimationFrame(() => {
								this.runFirstRenderFrameMsById.set(runId, now());
							});
						}

						// Track event-target render timing (may arrive later than firstItem)
						if (this.runEventTargetItemReceivedMsById.has(msg.runId)
							&& !this.runEventTargetRenderMsById.has(msg.runId)) {
							this.runEventTargetRenderMsById.set(msg.runId, now());
							const runId = msg.runId;
							dom.getActiveWindow().requestAnimationFrame(() => {
								this.runEventTargetRenderFrameMsById.set(runId, now());
							});
						}

						this.streamUpdateTimer = setTimeout(() => {
							this.streamUpdateTimer = null;
						}, 16);
					}

					// Now that the item is taken -- and its events retired -- what
					// it asked for. Same order as when these were messages of
					// their own, just no longer separable from the item.
					for (const command of itemCommands ?? []) {
						this.handleCommand(command);
					}
				} else if (msg.type === 'loop') {
					this.onLoopReport(msg.loop);
				} else if (msg.type === 'end') {
					// console.log('program end');
					const tEnd = now();
					{
						const started = this.runStartWallById.get(msg.runId);
						const triggerMs = this.runTriggerMsById.get(msg.runId);
						studyLog.log('run.end', {
							runId: msg.runId, trigger: this.runTriggerById.get(msg.runId),
							durationMs: started ? Date.now() - started : undefined,
							toFirstItemMs: triggerMs !== undefined && this.runFirstItemReceivedMsById.has(msg.runId) ? Math.round(this.runFirstItemReceivedMsById.get(msg.runId)! - triggerMs) : undefined,
							toFirstRenderMs: triggerMs !== undefined && this.runFirstRenderMsById.has(msg.runId) ? Math.round(this.runFirstRenderMsById.get(msg.runId)! - triggerMs) : undefined,
							exitCode: msg.result.exitCode, syntaxError: !!msg.result.syntaxError, awaitingInput: !!msg.result.awaitingInput, awaitingKind: msg.result.awaitingKind,
							stderr: msg.result.stderr ? truncateForLog(msg.result.stderr) : undefined,
							backendTiming: this.runSpawnTimingById.get(msg.runId) ?? msg.timing,
							loopCounts: Object.fromEntries(this.loopCountsThisRun),
							itemCount: this.visualizationItems.filter(i => i.runId === msg.runId).length,
							items: this.describeItemsForLog(),
						}, this.editor.getModel()?.uri.toString());
						this.runTriggerById.delete(msg.runId);
						this.runStartWallById.delete(msg.runId);
					}

					// Comprehensive timing logging
					this.logVisualizerTiming(msg.runId, msg.timing, tEnd);

					// Timing cleanup
					this.runTriggerMsById.delete(msg.runId);
					this.runSpawnTimingById.delete(msg.runId);
					this.runFirstItemReceivedMsById.delete(msg.runId);
					this.runFirstRenderMsById.delete(msg.runId);
					this.runFirstRenderFrameMsById.delete(msg.runId);
					this.runEventTargetById.delete(msg.runId);
					this.runEventTargetItemReceivedMsById.delete(msg.runId);
					this.runEventTargetRenderMsById.delete(msg.runId);
					this.runEventTargetRenderFrameMsById.delete(msg.runId);

					clearTimeout(this.streamUpdateTimer);

					const hasSyntaxError = !!msg.result.syntaxError;
					if (hasSyntaxError) {
						// Keep existing widgets/zones stable while user is typing invalid syntax.
						this.setSyntaxErrorState(true);
					} else {
						// Only keep items from the current run. Prior-run items are stale
						// and would show visualizers on lines whose content has changed.
						// Except the ones a warm worker ran through before this run
						// took it over: those ARE this run's, they just went out
						// under the id of the run that warmed it.
						this.visualizationItems = carryForwardItems(
							this.visualizationItems, this.currentRunId!, this.resumedFromStep);
						this.setSyntaxErrorState(false);
						// Every model is fresh now: reconcile front-end links against
						// the models so the chain icon and decorations can't drift.
						this.reconcileLinksWithModels();
						// The run's own counts are the truth now: a loop that got
						// shorter, or is gone from the program, loses its slider.
						this.loopCounts = new Map(this.loopCountsThisRun);
						this.updateLoopSliders();
						this.clampLoopSelections();
						this.updateVisualizationWidgets(this.visualizationItems);
					}

					// `awaitingInput` is a normal end, not a failure: the program
					// is parked on a read the stdin document can't satisfy yet.
					// It deliberately doesn't take the syntax-error path above,
					// so the statements that did run keep their visualizers.
					if (this.consoleFilePath) {
						if (hasSyntaxError) {
							// Half-typed code produces no transcript. Hold the last
							// good one, the same way the widgets above are held.
							this.consoleService.runAbandoned(this.consoleFilePath);
						} else {
							this.consoleService.runFinished(this.consoleFilePath, msg.result);
						}
					}

					// The run finished without ever reaching these widgets, so
					// they aren't part of this execution and events queued for
					// them are for something that is gone. (A superseded run
					// never gets here -- it is disowned above, so its events
					// survive for the run that replaced it.)
					// Nothing drawn reads `unhandledEvents`, so this sweep is not a
					// render anything should wait for -- but it is an assignment,
					// and it lands after the render above, so left alone it ends
					// every run one version ahead of the DOM and `pythonStatus`
					// reports 'un-rendered' forever. Carry the mark across when
					// the DOM was already caught up; when it was not, a real
					// render is still owed and the status should keep saying so.
					const wasRendered = this.renderedVersion === this.itemsVersion;
					const swept = this.visualizationItems.filter(v =>
						v.unhandledEvents?.length && !this.itemsThisRun.has(widgetKey(v.line, v.visIndex)));
					if (swept.length) {
						// Silent before: if this ever eats a real gesture, nothing
						// would have said so.
						studyLog.log('run.eventsDropped', {
							runId: msg.runId, trigger: this.runTriggerById.get(msg.runId), reason: 'widget-not-reached',
							widgets: swept.map(v => ({ line: v.line, visIndex: v.visIndex, events: (v.unhandledEvents ?? []).map(e => ({ id: e.id, type: e.eventJSON?.type, pythonEventStr: e.pythonEventStr })) })),
						}, this.editor.getModel()?.uri.toString());
					}
					this.visualizationItems = this.visualizationItems.map(v =>
						v.unhandledEvents?.length && !this.itemsThisRun.has(widgetKey(v.line, v.visIndex))
							? { ...v, unhandledEvents: [] }
							: v);
					if (wasRendered) {
						this.renderedVersion = this.itemsVersion;
					}

					this.currentRunId = null;
					this.resumedFromStep = null;
					// Counted after the widgets are updated above, so a waiter
					// that sees this can already read the new DOM.
					sncRunsSettled++;
				} else if (msg.type === 'warning') {
					console.warn('SNC warning:', msg.warning);
					studyLog.log('run.warning', { runId: msg.runId, warning: truncateForLog(msg.warning) }, this.editor.getModel()?.uri.toString());
				} else if (msg.type === 'error') {
					console.error('SNC streaming error:', msg.error);
					{
						const started = this.runStartWallById.get(msg.runId);
						studyLog.log('run.error', { runId: msg.runId, trigger: this.runTriggerById.get(msg.runId), durationMs: started ? Date.now() - started : undefined, error: truncateForLog(msg.error) }, this.editor.getModel()?.uri.toString());
						this.runTriggerById.delete(msg.runId);
						this.runStartWallById.delete(msg.runId);
					}
					// Surface python-spawn-failure errors as a sticky toast so
					// the user understands why visualizers stopped working.
					// Other errors (timeouts, etc.) still just log to console.
					if (msg.error && msg.error.startsWith('Clickacode: failed to launch Python')) {
						this.showPythonSpawnFailureNotification(msg.error);
					}
					// Cleanup timing tracking on error
					this.runTriggerMsById.delete(msg.runId);
					this.runSpawnTimingById.delete(msg.runId);
					this.runFirstItemReceivedMsById.delete(msg.runId);
					this.runFirstRenderMsById.delete(msg.runId);
					this.runFirstRenderFrameMsById.delete(msg.runId);
					this.runEventTargetById.delete(msg.runId);
					this.runEventTargetItemReceivedMsById.delete(msg.runId);
					this.runEventTargetRenderMsById.delete(msg.runId);
					this.runEventTargetRenderFrameMsById.delete(msg.runId);

					// Publish whatever the run managed to print before it died,
					// so the console doesn't sit on the previous run's output.
					if (this.consoleFilePath) {
						this.consoleService.runFinished(this.consoleFilePath, undefined);
					}

					this.currentRunId = null;
					this.visualizationItems = [];
					this.clearVisualizationWidgets();
					sncRunsSettled++;
				}
			});
			this._register({ dispose: () => { this.streamSubscription?.dispose(); this.streamSubscription = null; } });
		}

		const models_and_events = this.visualizationItems.filter(visItem => visItem.model || visItem.unhandledEvents).map(visItem => {
			const model_and_events: any = {
				line: visItem.line,
				visIndex: visItem.visIndex,
			};
			if (visItem.model) { model_and_events['model'] = visItem.model }
			if (visItem.unhandledEvents) { model_and_events['events'] = visItem.unhandledEvents } // don't transform events: they are compared by == i.e. exact objectid
			return model_and_events;
		});

		// Start a new streaming run
		const runId = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
		this.currentRunId = runId;
		// The lines this run is about to be told about, as they stand now. Its
		// commands come back naming these numbers, and the file can have moved
		// on by then -- see reportedLineNow.
		this.reportedLineNow.clear();
		for (const visItem of this.visualizationItems) {
			this.reportedLineNow.set(visItem.line, visItem.line);
		}
		// No widget has been reached yet, so the run can be handed events
		// for any of them (see the gate above). A warm worker taking this run
		// says otherwise, and seeds the set -- see the 'resumed' handler.
		this.itemsThisRun.clear();
		this.resumedFromStep = null;
		this.consoleFilePath = filePath;
		if (filePath) {
			this.consoleService.runStarted(filePath);
		}
		// The run has an id now, so `currentRunId` speaks for it from here.
		this.runStarting = false;
		const nowMs = (typeof performance !== 'undefined' ? performance.now() : Date.now());
		// Track trigger time for timing measurement
		this.runTriggerMsById.set(runId, nowMs);
		if (uiEvent) {
			this.runEventTargetById.set(runId, { line: uiEvent.line, visIndex: uiEvent.visIndex });
		}
		this.runTriggerById.set(runId, trigger);
		this.runStartWallById.set(runId, Date.now());
		studyLog.log('run.start', {
			runId, trigger, cancelledPrevious, filePath,
			contentLength: content.length, contentLines: content.split('\n').length,
			focusedLine: this.effectiveFocusedLine(), loopSelections: this.loopSelectionsByLine(),
			event: uiEvent ? { line: uiEvent.line, visIndex: uiEvent.visIndex, pythonEventStr: uiEvent.pythonEventStr, type: uiEvent.eventJSON?.type } : undefined,
			queuedEvents: models_and_events.reduce((n, m) => n + (m['events']?.length ?? 0), 0),
			modelsSent: models_and_events.length,
		}, this.editor.getModel()?.uri.toString());

		try {
			const focusedLine = this.effectiveFocusedLine();
			// An unsaved buffer has nowhere to keep a stdin document, so it runs
			// with an unterminated empty stream: a read starves rather than
			// seeing a spurious EOF.
			const { stdin, stdinEof } = filePath ? this.consoleService.stdinFor(filePath) : { stdin: '', stdinEof: false };
			// Where to warm the next workers, and how far into the program this
			// run may start. Both absent when nothing has been interacted with,
			// which is when there is no prefix worth skipping and the backend
			// leaves the checkpoint 3 pool empty.
			const resumeAtStep = resumeAtStepFor(this.visualizationItems);
			const options: IProcessOptions = {
				modelsAndEventsJson: JSON.stringify(models_and_events),
				timeout: 60_000,
				workingDirectory,
				filePath,
				stdin,
				stdinEof,
				loopSelections: this.loopSelectionsByLine(),
				readOnly: this.isReadOnly(),
				...(focusedLine !== null ? { focusedLine } : {}),
				...(this.lastInteractedWidget ? { checkpoint3WarmAt: this.lastInteractedWidget } : {}),
				...(resumeAtStep !== undefined ? { checkpoint3ResumeAtStep: resumeAtStep } : {})
			};
			this.loopCountsThisRun = new Map();
			await channel.call('startProgram', [content, options, runId]);
		} catch (error) {
			console.error('Failed to start streaming run:', error);
			studyLog.log('run.startFailed', { runId, trigger, error: String(error) }, this.editor.getModel()?.uri.toString());
			this.runTriggerById.delete(runId);
			this.runStartWallById.delete(runId);
			if (this.consoleFilePath) {
				// The run never happened, so it has no transcript to publish, but
				// its collection state has to be released either way.
				this.consoleService.runAbandoned(this.consoleFilePath);
			}
			this.currentRunId = null;
			this.clearVisualizationWidgets();
			// A run that never started is as over as one that ran, and a waiter
			// that only counted successes would wait out its whole timeout here.
			sncRunsSettled++;
		}
	}

	override dispose(): void {
		this.toggleWidgetsButton?.dispose();
		this.toggleWidgetsButton = null;
		super.dispose();
	}

}

registerEditorContribution(SNCController.ID, SNCController, EditorContributionInstantiation.AfterFirstRender);

/**
 * The same toggle as the corner button, as a command so it can be keybound.
 * No precondition: the flag is global, so flipping it from a non-Python
 * editor is as meaningful as from a Python one.
 */
registerEditorAction(class extends EditorAction {
	constructor() {
		super({
			id: 'snc.toggleWidgets',
			label: localize('sncToggleWidgets', "Clickacode: Toggle Visualizer Widgets"),
			alias: 'Clickacode: Toggle Visualizer Widgets',
			precondition: undefined,
		});
	}
	run(_accessor: ServicesAccessor, editor: ICodeEditor): void {
		SNCController.get(editor)?.toggleWidgetsVisible();
	}
});
