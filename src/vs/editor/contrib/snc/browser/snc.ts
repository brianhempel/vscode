import { registerEditorContribution, EditorContributionInstantiation } from '../../../browser/editorExtensions.js';
import { Disposable, IDisposable } from '../../../../base/common/lifecycle.js';
import { IEditorContribution, ScrollType } from '../../../common/editorCommon.js';
import { ICodeEditor, IViewZone, IOverlayWidget, IOverlayWidgetPosition, IOverlayWidgetPositionCoordinates } from '../../../browser/editorBrowser.js';
import { Position } from '../../../common/core/position.js';
import { Range } from '../../../common/core/range.js';
import { Selection } from '../../../common/core/selection.js';
import { EditorOption } from '../../../common/config/editorOptions.js';
import { IModelContentChangedEvent } from '../../../common/textModelEvents.js';
import { TrackedRangeStickiness } from '../../../common/model.js';
import { IProcessOptions, IVisualizationItem, SNCCommand, SNCStreamMessage, SNCTimingData, UiEvent } from '../../../../platform/snc/common/snc.js';
import { IMainProcessService } from '../../../../platform/ipc/common/mainProcessService.js';
import { IWorkspaceContextService } from '../../../../platform/workspace/common/workspace.js';
import { createTrustedTypesPolicy } from '../../../../base/browser/trustedTypes.js';
import { IHostService } from '../../../../workbench/services/host/browser/host.js';
import { IEditorService } from '../../../../workbench/services/editor/common/editorService.js';
import { IClipboardService } from '../../../../platform/clipboard/common/clipboardService.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { INotificationService, INotificationHandle, Severity } from '../../../../platform/notification/common/notification.js';
import * as dom from '../../../../base/browser/dom.js';
import './snc.css';

// 'sncVisualization' is a trusted name defined in src/vs/code/electron-sandbox/workbench/workbench(-dev).html
const ttPolicy = createTrustedTypesPolicy('sncVisualization', { createHTML: value => value });


/**
 * Widget that displays visualization data for a specific line of code.
 */
class VisualizationWidget extends Disposable implements IOverlayWidget {
	private static readonly BLOCK_LAYOUT_THRESHOLD_PX = 150;
	private readonly editor: ICodeEditor;
	private readonly domNode: HTMLElement;
	private position: Position | null = null;
	private lastOnscreenPixelPosition: IOverlayWidgetPositionCoordinates | null = null;
	private readonly visIndex: number;
	private readonly lineNumber: number;
	private readonly onPointerEvent: (pythonEventStr: string, ev: MouseEvent, overrideRect?: DOMRect) => void;
	private readonly onKeyboardEvent: (pythonEventStr: string, ev: KeyboardEvent) => void;
	private readonly onInputEvent: (pythonEventStr: string, value: string) => void;
	// Invoked when the user clicks the "+" button in an expression tooltip to
	// assign that expression to a new variable on the line below.
	private readonly onInsertNewVar: (expression: string) => void;
	// Returns true when this widget's line is currently the focused line and
	// thus rendered full-size. When false, the widget is in small mode and
	// the first mousedown is intercepted as an "expand" request instead of
	// being dispatched as a Python event.
	private readonly isFocused: () => boolean;
	private readonly onExpandRequest: () => void;
	private moveThrottleTimer: any = null;
	private readonly moveThrottleDelay = 16;
	private lastRenderedHtml: string | null = null;
	private focusRestoreVersion = 0;
	private hoistedDropdown: HTMLElement | null = null;
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
	}[] = [];
	private hoistedSegmentLabelListeners: IDisposable[] = [];
	private useBlockLayout = false;
	private readonly clipboardService: IClipboardService;
	private pyExpTooltip: HTMLElement | null = null;
	private pyExpTooltipTimer: any = null;
	private pyExpTooltipHideTimer: any = null;
	private pyExpCurrentTarget: Element | null = null;
	private pyExpTooltipDragInProgress = false;
	private lastMouseDownTarget: Node | null = null;
	private actionTooltip: HTMLElement | null = null;
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
	constructor(editor: ICodeEditor, lineNumber: number, visIndex: number, onPointerEvent: (pythonEventStr: string, ev: MouseEvent, overrideRect?: DOMRect) => void, onKeyboardEvent: (pythonEventStr: string, ev: KeyboardEvent) => void, onInputEvent: (pythonEventStr: string, value: string) => void, isFocused: () => boolean, onExpandRequest: () => void, onInsertNewVar: (expression: string) => void, clipboardService: IClipboardService) {
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
		this.onExpandRequest = onExpandRequest;
		this.clipboardService = clipboardService;

		// Create the widget DOM node
		this.domNode = document.createElement('div');
		this.domNode.className = 'snc-visualization-widget';

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
			this.lastMouseDownTarget = ev.target as Node;
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
			if (this.moveThrottleTimer) { return; }
			this.moveThrottleTimer = setTimeout(() => { this.moveThrottleTimer = null; }, this.moveThrottleDelay);
			this.dispatch_mouse_python_event('snc-mouse-move', ev);
		}));
		this._register(dom.addDisposableListener(this.domNode, 'mouseup', (ev: MouseEvent) => {
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
		this._register(dom.addDisposableListener(this.domNode, 'input', (ev: Event) => {
			this.dispatch_input_event('snc-input', ev);
		}));

		// Drag-and-drop for snc-py-exp elements.
		// Only allow drag from the border/padding of the snc-py-exp wrapper,
		// not from inside nested visualizer content (marked draggable="false").
		this._register(dom.addDisposableListener(this.domNode, 'dragstart', (ev: DragEvent) => {
			const pyExpEl = this.findAncestorWithAttr(ev.target as Node, 'snc-py-exp');
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

				const expression = pyExpEl.getAttribute('snc-py-exp') ?? '';
				ev.dataTransfer.setData('text/plain', expression);
				ev.dataTransfer.effectAllowed = 'copy';
				this.hidePyExpTooltip();

				const dragGhost = document.createElement('div');
				dragGhost.textContent = expression;
				dragGhost.className = 'snc-py-exp-drag-ghost';
				document.body.appendChild(dragGhost);
				ev.dataTransfer.setDragImage(dragGhost, 0, 0);
				setTimeout(() => dragGhost.remove(), 0);
			}
		}));

		// Allow snc-input elements to accept snc-py-exp drops
		this._register(dom.addDisposableListener(this.domNode, 'dragover', (ev: DragEvent) => {
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
			const input = this.findAncestorWithAttr(ev.target as Node, 'snc-input');
			if (input && ev.dataTransfer) {
				ev.preventDefault();
				ev.stopPropagation();
				const text = ev.dataTransfer.getData('text/plain');
				const inputEl = input as HTMLInputElement;
				const pos = inputEl.selectionStart ?? inputEl.value.length;
				inputEl.value = inputEl.value.slice(0, pos) + text + inputEl.value.slice(pos);
				inputEl.selectionStart = inputEl.selectionEnd = pos + text.length;
				input.classList.remove('snc-drop-target');
				inputEl.dispatchEvent(new Event('input', { bubbles: true }));
			}
		}));

		// Tooltip + highlight on hover for snc-py-exp draggable zones.
		// Only activate when the cursor is over the draggable border/padding
		// of an snc-py-exp element, not over inner content (marked draggable="false").
		this._register(dom.addDisposableListener(this.domNode, 'mouseover', (ev: MouseEvent) => {
			const pyExpEl = this.findAncestorWithAttr(ev.target as Node, 'snc-py-exp');
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
					}, 100);
				}
			} else if (this.pyExpCurrentTarget) {
				this.pyExpCurrentTarget.classList.remove('snc-py-exp-drag-hover');
				this.pyExpCurrentTarget = null;
				this.schedulePyExpTooltipHide();
			}
		}));
		this._register(dom.addDisposableListener(this.domNode, 'mouseout', (ev: MouseEvent) => {
			const relatedTarget = ev.relatedTarget as Node | null;
			// Don't hide if moving into the tooltip itself
			if (this.pyExpTooltip && relatedTarget && this.pyExpTooltip.contains(relatedTarget)) {
				return;
			}
			// Don't clean up if moving within the same snc-py-exp (mouseover will handle it)
			if (relatedTarget && this.findAncestorWithAttr(relatedTarget, 'snc-py-exp')) {
				return;
			}
			if (this.pyExpCurrentTarget) {
				this.pyExpCurrentTarget.classList.remove('snc-py-exp-drag-hover');
				this.pyExpCurrentTarget = null;
			}
			this.schedulePyExpTooltipHide();
		}));

		// Tooltip on hover for action buttons with data-action-expr
		this._register(dom.addDisposableListener(this.domNode, 'mouseover', (ev: MouseEvent) => {
			const btn = this.findAncestorWithAttr(ev.target as Node, 'data-action-expr');
			if (btn && btn.getAttribute('data-action-expr')) {
				clearTimeout(this.actionTooltipHideTimer);
				if (btn !== this.actionTooltipTarget) {
					this.hideActionTooltip();
					this.actionTooltipTarget = btn;
					this.actionTooltipTimer = setTimeout(() => {
						this.showActionTooltip(btn);
					}, 200);
				}
			} else if (this.actionTooltipTarget) {
				this.scheduleActionTooltipHide();
			}
		}));
		this._register(dom.addDisposableListener(this.domNode, 'mouseout', (ev: MouseEvent) => {
			const relatedTarget = ev.relatedTarget as Node | null;
			if (this.actionTooltip && relatedTarget && this.actionTooltip.contains(relatedTarget)) {
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

		// Simple tooltip on hover for elements with data-tooltip="<text>"
		// (lighter weight than the action/py-exp tooltips: just text, no copy
		// button, no draggable expression).
		this._register(dom.addDisposableListener(this.domNode, 'mouseover', (ev: MouseEvent) => {
			const target = this.findAncestorWithAttr(ev.target as Node, 'data-tooltip');
			if (target && target.getAttribute('data-tooltip')) {
				clearTimeout(this.simpleTooltipHideTimer);
				if (target !== this.simpleTooltipTarget) {
					this.hideSimpleTooltip();
					this.simpleTooltipTarget = target;
					this.simpleTooltipTimer = setTimeout(() => {
						this.showSimpleTooltip(target);
					}, 200);
				}
			} else if (this.simpleTooltipTarget) {
				this.scheduleSimpleTooltipHide();
			}
		}));
		this._register(dom.addDisposableListener(this.domNode, 'mouseout', (ev: MouseEvent) => {
			const relatedTarget = ev.relatedTarget as Node | null;
			if (relatedTarget && this.findAncestorWithAttr(relatedTarget, 'data-tooltip')) {
				return;
			}
			if (this.simpleTooltipTarget) {
				this.simpleTooltipTarget = null;
			}
			this.scheduleSimpleTooltipHide();
		}));

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

		// Add the widget to the editor
		this.editor.addOverlayWidget(this);
	}

	/**
	 * Walk up from a node to find the nearest ancestor (or itself) with the given attribute.
	 */
	private findAncestorWithAttr(node: Node | null, attr: string): Element | null {
		let el: Element | null = node?.nodeType === Node.ELEMENT_NODE ? (node as Element) : (node?.parentElement ?? null);
		while (el && el !== this.domNode) {
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
	 * Build a "+" button for an expression tooltip. Clicking it assigns the
	 * expression to a new variable on the line below (via onInsertNewVar) and
	 * dismisses the tooltip.
	 */
	private createNewVarButton(expression: string, hideTooltip: () => void): HTMLButtonElement {
		const newVarBtn = document.createElement('button');
		newVarBtn.className = 'snc-copy-btn snc-new-var-btn';
		newVarBtn.textContent = '+';
		newVarBtn.title = 'Assign to a new variable';
		newVarBtn.addEventListener('mousedown', (e) => {
			e.preventDefault();
			e.stopPropagation();
			hideTooltip();
			this.onInsertNewVar(expression);
		});
		return newVarBtn;
	}

	/**
	 * Show a tooltip with the Python expression and a copy button near the given element.
	 */
	private showPyExpTooltip(target: Element): void {
		// Remove any existing tooltip DOM without clearing highlight/tracking state
		if (this.pyExpTooltip) {
			this.pyExpTooltip.remove();
			this.pyExpTooltip = null;
		}

		const expression = target.getAttribute('snc-py-exp');
		if (!expression) { return; }

		const rect = target.getBoundingClientRect();
		const tooltip = document.createElement('div');
		tooltip.className = 'snc-tooltip snc-py-exp-tooltip';

		const copyBtn = document.createElement('button');
		copyBtn.className = 'snc-copy-btn';
		copyBtn.textContent = '\u{29C9}';
		copyBtn.title = 'Copy to clipboard';
		copyBtn.addEventListener('mousedown', (e) => {
			e.preventDefault();
			e.stopPropagation();
			this.clipboardService.writeText(expression);
			copyBtn.textContent = '\u2713';
			setTimeout(() => { copyBtn.textContent = '\u{29C9}'; }, 1000);
		});
		tooltip.appendChild(copyBtn);

		tooltip.appendChild(this.createNewVarButton(expression, () => this.hidePyExpTooltip()));

		const exprSpan = document.createElement('span');
		exprSpan.textContent = expression;
		exprSpan.draggable = true;
		exprSpan.style.cursor = 'grab';
		exprSpan.addEventListener('dragstart', (e) => {
			if (e.dataTransfer) {
				this.pyExpTooltipDragInProgress = true;
				clearTimeout(this.pyExpTooltipHideTimer);
				e.dataTransfer.setData('text/plain', expression);
				e.dataTransfer.effectAllowed = 'copy';

				const dragGhost = document.createElement('div');
				dragGhost.textContent = expression;
				dragGhost.className = 'snc-py-exp-drag-ghost';
				document.body.appendChild(dragGhost);
				e.dataTransfer.setDragImage(dragGhost, 0, 0);
				setTimeout(() => dragGhost.remove(), 0);
			}
		});
		exprSpan.addEventListener('dragend', () => {
			this.pyExpTooltipDragInProgress = false;
			this.hidePyExpTooltip();
		});
		tooltip.appendChild(exprSpan);

		// Keep tooltip alive while hovering it; also keep hover menu alive
		tooltip.addEventListener('mouseenter', () => {
			clearTimeout(this.pyExpTooltipHideTimer);
			clearTimeout(this.hoverMenuHideTimer);
		});
		tooltip.addEventListener('mouseleave', () => {
			this.schedulePyExpTooltipHide();
			if (this.hoverMenu) {
				this.scheduleHoverMenuHide();
			}
		});

		const align = target.getAttribute('snc-py-exp-align');

		if (align === 'right') {
			// Position to the right of the target, vertically centered
			tooltip.style.visibility = 'hidden';
			this.editor.getContainerDomNode().appendChild(tooltip);
			const tooltipRect = tooltip.getBoundingClientRect();
			let left = rect.right + 4;
			if (left + tooltipRect.width > window.innerWidth) {
				left = rect.left - tooltipRect.width - 4;
			}
			tooltip.style.left = `${left}px`;
			tooltip.style.top = `${rect.top + (rect.height - tooltipRect.height) / 2}px`;
			tooltip.style.visibility = '';
		} else {
			// Position above the target element
			tooltip.style.left = `${rect.left}px`;
			tooltip.style.top = `${rect.top - 28}px`;
			this.editor.getContainerDomNode().appendChild(tooltip);
			const tooltipRect = tooltip.getBoundingClientRect();
			if (tooltipRect.top < 0) {
				tooltip.style.top = `${rect.bottom + 4}px`;
			}
		}

		this.pyExpTooltip = tooltip;
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
	}

	private showActionTooltip(target: Element): void {
		this.hideActionTooltip();

		const expression = target.getAttribute('data-action-expr');
		if (!expression) { return; }

		const rect = target.getBoundingClientRect();
		const tooltip = document.createElement('div');
		tooltip.className = 'snc-tooltip snc-action-tooltip';

		const copyBtn = document.createElement('button');
		copyBtn.className = 'snc-copy-btn';
		copyBtn.textContent = '\u{29C9}';
		copyBtn.title = 'Copy to clipboard';
		copyBtn.addEventListener('mousedown', (e) => {
			e.preventDefault();
			e.stopPropagation();
			this.clipboardService.writeText(expression);
			copyBtn.textContent = '\u2713';
			setTimeout(() => { copyBtn.textContent = '\u{29C9}'; }, 1000);
		});
		tooltip.appendChild(copyBtn);

		tooltip.appendChild(this.createNewVarButton(expression, () => this.hideActionTooltip()));

		const exprSpan = document.createElement('span');
		exprSpan.className = 'snc-action-tooltip-expr';
		exprSpan.textContent = expression;
		exprSpan.draggable = true;
		exprSpan.style.cursor = 'grab';
		exprSpan.addEventListener('dragstart', (e) => {
			if (e.dataTransfer) {
				e.dataTransfer.setData('text/plain', expression);
				e.dataTransfer.effectAllowed = 'copy';
				const dragGhost = document.createElement('div');
				dragGhost.textContent = expression;
				dragGhost.className = 'snc-py-exp-drag-ghost';
				document.body.appendChild(dragGhost);
				e.dataTransfer.setDragImage(dragGhost, 0, 0);
				setTimeout(() => dragGhost.remove(), 0);
			}
		});
		tooltip.appendChild(exprSpan);

		tooltip.addEventListener('mouseenter', () => {
			clearTimeout(this.actionTooltipHideTimer);
		});
		tooltip.addEventListener('mouseleave', () => {
			this.scheduleActionTooltipHide();
		});

		tooltip.style.left = `${rect.left}px`;
		tooltip.style.top = `${rect.top - 32}px`;

		this.editor.getContainerDomNode().appendChild(tooltip);
		this.actionTooltip = tooltip;

		const tooltipRect = tooltip.getBoundingClientRect();
		if (tooltipRect.top < 0) {
			tooltip.style.top = `${rect.bottom + 4}px`;
		}
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
	}

	private showSimpleTooltip(target: Element): void {
		this.hideSimpleTooltip();

		const text = target.getAttribute('data-tooltip');
		if (!text) { return; }

		const rect = target.getBoundingClientRect();
		const tooltip = document.createElement('div');
		tooltip.className = 'snc-tooltip snc-simple-tooltip';
		tooltip.textContent = text;

		// Same placement convention as snc-py-exp tooltips:
		//   data-tooltip-align="right" -> render to the right of the target,
		//                                 vertically centered (with a fallback
		//                                 to the left if it would overflow)
		//   default                    -> render above the target (with a
		//                                 fallback to below if it overflows).
		const align = target.getAttribute('data-tooltip-align');
		const viewportWidth = dom.getWindow(this.editor.getContainerDomNode()).innerWidth;

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
		} else {
			tooltip.style.left = `${rect.left}px`;
			tooltip.style.top = `${rect.top - 28}px`;
			this.editor.getContainerDomNode().appendChild(tooltip);
			const tooltipRect = tooltip.getBoundingClientRect();
			if (tooltipRect.top < 0) {
				tooltip.style.top = `${rect.bottom + 4}px`;
			}
			if (tooltipRect.right > viewportWidth) {
				tooltip.style.left = `${Math.max(0, rect.right - tooltipRect.width)}px`;
			}
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

		const triggerRect = trigger.getBoundingClientRect();
		const align = panel.getAttribute('snc-dropdown-align') || 'left';

		const clone = panel.cloneNode(true) as HTMLElement;
		clone.classList.add('snc-hover-menu');
		clone.style.display = '';
		clone.removeAttribute('data-hover-menu');

		if (align === 'right') {
			clone.style.right = `${window.innerWidth - triggerRect.right}px`;
		} else {
			clone.style.left = `${triggerRect.left}px`;
		}
		clone.style.top = `${triggerRect.bottom + 2}px`;

		// Wire up event listeners on the hoisted panel
		const wrapEvent = (raw: string, attrEl: Element): string => {
			return this.wrapWithChildKeys(raw, attrEl.parentElement, this.domNode);
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
			const pyExpEl = this.findAncestorWithAttr(ev.target as Node, 'snc-py-exp');
			if (pyExpEl) {
				clearTimeout(this.pyExpTooltipHideTimer);
				if (pyExpEl !== this.pyExpCurrentTarget) {
					this.pyExpCurrentTarget = pyExpEl;
					clearTimeout(this.pyExpTooltipTimer);
					this.pyExpTooltipTimer = setTimeout(() => {
						this.showPyExpTooltip(pyExpEl);
					}, 100);
				}
			} else if (this.pyExpCurrentTarget) {
				this.pyExpCurrentTarget = null;
				this.schedulePyExpTooltipHide();
			}
		});
		clone.addEventListener('mouseout', (ev: MouseEvent) => {
			const relatedTarget = ev.relatedTarget as Node | null;
			if (this.pyExpTooltip && relatedTarget && this.pyExpTooltip.contains(relatedTarget)) {
				return;
			}
			if (relatedTarget && this.findAncestorWithAttr(relatedTarget, 'snc-py-exp')) {
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
	 * Check if target is in the draggable zone of an snc-py-exp element
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

		while (el && el != this.domNode) {
			if (el.hasAttribute(attr_name) || el.hasAttribute(`snc-mouse`)) {
				let pythonEventStr: string;
				if (el.hasAttribute(attr_name)) {
					pythonEventStr = el.getAttribute(attr_name) ?? '';
				} else {
					// snc-mouse="5" is shorthand for snc-mouse-move="MouseMove(5)" snc-mouse-down="MouseDown(5)" snc-mouse-up="MouseUp(5)"
					pythonEventStr = {
						'snc-mouse-move': `MouseMove(${el.getAttribute(`snc-mouse`)})`,
						'snc-mouse-down': `MouseDown(${el.getAttribute(`snc-mouse`)})`,
						'snc-mouse-up': `MouseUp(${el.getAttribute(`snc-mouse`)})`,
					}[attr_name] ?? '';
				}
				pythonEventStr = this.wrapWithChildKeys(pythonEventStr, el.parentElement, this.domNode);
				this.onPointerEvent(pythonEventStr, ev);
				return;
			}
			el = el.parentElement;
		}

		// Fallback: use caretRangeFromPoint for grouped text spans (snc-text-start)
		const caretRange = document.caretRangeFromPoint(ev.clientX, ev.clientY);
		if (caretRange && caretRange.startContainer.nodeType === Node.TEXT_NODE) {
			let groupEl = caretRange.startContainer.parentElement;
			while (groupEl && groupEl !== this.domNode) {
				const startAttr = groupEl.getAttribute('snc-text-start');
				if (startAttr !== null) {
					const textLen = caretRange.startContainer.textContent?.length ?? 1;
					const offset = Math.min(caretRange.startOffset, textLen - 1);
					const charIndex = parseInt(startAttr) + offset;
					let pythonEventStr: string = {
						'snc-mouse-move': `MouseMove(${charIndex})`,
						'snc-mouse-down': `MouseDown(${charIndex})`,
						'snc-mouse-up': `MouseUp(${charIndex})`,
					}[attr_name] ?? '';
					pythonEventStr = this.wrapWithChildKeys(pythonEventStr, groupEl.parentElement, this.domNode);
					// Build a per-character rect for accurate offsetY/elementHeight
					const charRange = document.createRange();
					charRange.setStart(caretRange.startContainer, offset);
					charRange.setEnd(caretRange.startContainer, Math.min(offset + 1, textLen));
					this.onPointerEvent(pythonEventStr, ev, charRange.getBoundingClientRect());
					return;
				}
				groupEl = groupEl.parentElement;
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
		if (!ev.target) { return false; }
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
			pixelPosition.left += this.useBlockLayout ? 0 : 8;

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
	private static isScrollableElement(el: HTMLElement): boolean {
		return el.scrollTop !== 0
			|| el.scrollLeft !== 0
			|| el.scrollHeight > el.clientHeight
			|| el.scrollWidth > el.clientWidth;
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

		// Any pending focus restoration from an older render should be ignored.
		const currentFocusRestoreVersion = ++this.focusRestoreVersion;

		// Save focus state BEFORE cleaning up the hoisted dropdown (removing it
		// from the DOM would cause the browser to lose focus on any input inside it).
		const activeElement = document.activeElement;
		let focusedIndex = -1;
		let savedSelectionStart: number | null = null;
		let savedSelectionEnd: number | null = null;
		const savedWidgetScrollTop = this.domNode.scrollTop;
		const savedWidgetScrollLeft = this.domNode.scrollLeft;
		const oldScrollableElements = Array.from(this.domNode.querySelectorAll('*'))
			.filter(dom.isHTMLElement)
			.filter(VisualizationWidget.isScrollableElement);
		const savedScrollOffsets = oldScrollableElements.map((el) => ({
			top: el.scrollTop,
			left: el.scrollLeft
		}));

		// Build the combined list of focusable elements across widget + hoisted dropdown
		const widgetFocusable = Array.from(this.domNode.querySelectorAll(VisualizationWidget.FOCUSABLE_SELECTOR));
		const oldHoistedFocusable = this.hoistedDropdown
			? Array.from(this.hoistedDropdown.querySelectorAll(VisualizationWidget.FOCUSABLE_SELECTOR))
			: [];
		const allOldFocusable = [...widgetFocusable, ...oldHoistedFocusable];

		// Track whether an [autofocus] element existed in the OLD render. If
		// one is in the NEW render but wasn't in the old one, it's "newly
		// appearing" - we want to focus it even when an input was previously
		// focused (e.g. user clicked a label trigger to open an edit popup
		// while the search box still held focus).
		const hadAutoFocusEl = !!(this.domNode.querySelector('[autofocus]')
			|| (this.hoistedDropdown && this.hoistedDropdown.querySelector('[autofocus]')));

		if (activeElement && (this.domNode.contains(activeElement) || (this.hoistedDropdown && this.hoistedDropdown.contains(activeElement)))) {
			for (let i = 0; i < allOldFocusable.length; i++) {
				if (allOldFocusable[i] === activeElement) {
					focusedIndex = i;
					break;
				}
			}
			// Save cursor position for input/textarea elements
			if (activeElement instanceof HTMLInputElement || activeElement instanceof HTMLTextAreaElement) {
				savedSelectionStart = activeElement.selectionStart;
				savedSelectionEnd = activeElement.selectionEnd;
			}
		}

		// Now safe to clean up the old hoisted dropdown
		this.cleanupHoistedDropdown();
		this.cleanupHoistedSegmentLabels();

		const trustedHtml = ttPolicy?.createHTML(html) ?? html;
		this.domNode.innerHTML = trustedHtml as string;
		this.lastRenderedHtml = html;

		// Hoist any dropdown panel outside the overflow container
		this.hoistDropdownPanel();
		// Hoist segment labels out of the scrollable string container so they
		// aren't clipped by its overflow.
		this.hoistSegmentLabels();
		this.updateLayoutMode();

		// Scroll any element marked for scroll-into-view (e.g. selected autocomplete item)
		const scrollTarget = (this.hoistedDropdown ?? this.domNode).querySelector('[snc-scroll-into-view]') as HTMLElement | null;
		if (scrollTarget) {
			scrollTarget.scrollIntoView({ block: 'nearest' });
		}

		// Restore scroll/focus after DOM replacement settles. Restore scroll first
		// so focus restoration with preventScroll does not fight with scroll offsets.
		const shouldRestoreScroll = savedWidgetScrollTop !== 0
			|| savedWidgetScrollLeft !== 0
			|| savedScrollOffsets.some((offset) => offset.top !== 0 || offset.left !== 0);
		// [autofocus] elements may live inside the hoisted dropdown panel
		// (which is taken out of this.domNode so it can be position:fixed).
		// Look in both places.
		const autoFocusEl = (this.domNode.querySelector('[autofocus]')
			|| (this.hoistedDropdown ? this.hoistedDropdown.querySelector('[autofocus]') : null)
		) as HTMLElement | null;
		const hasScrollToMatch = this.domNode.querySelector('[snc-scroll-to-match]') !== null;
		if (shouldRestoreScroll || focusedIndex >= 0 || autoFocusEl || hasScrollToMatch) {
			// Defer to next frame so layout/DOM updates settle, and ensure only the
			// latest update in a burst is allowed to restore scroll/focus.
			dom.getWindow(this.domNode).requestAnimationFrame(() => {
				if (currentFocusRestoreVersion !== this.focusRestoreVersion) {
					return;
				}

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
					// Select all text if requested (e.g. editing an existing field)
					if (autoFocusEl.hasAttribute('snc-select-all') && autoFocusEl instanceof HTMLInputElement) {
						autoFocusEl.select();
					}
				} else if (focusedIndex >= 0) {
					// Restore focus to the same nth focusable element
					// Look in both the widget and any hoisted dropdown
					const widgetFocusable = Array.from(this.domNode.querySelectorAll(VisualizationWidget.FOCUSABLE_SELECTOR));
					const hoistedFocusable = this.hoistedDropdown
						? Array.from(this.hoistedDropdown.querySelectorAll(VisualizationWidget.FOCUSABLE_SELECTOR))
						: [];
					const allFocusable = [...widgetFocusable, ...hoistedFocusable];
					if (focusedIndex < allFocusable.length) {
						const el = allFocusable[focusedIndex] as HTMLElement;
						el.focus({ preventScroll: true });
						// Restore cursor position for input/textarea elements
						if (savedSelectionStart !== null && (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement)) {
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
		let container: HTMLElement | null = matchTarget.parentElement;
		while (container && container !== this.domNode) {
			if (container.scrollHeight > container.clientHeight
				|| container.scrollWidth > container.clientWidth) {
				break;
			}
			container = container.parentElement;
		}
		if (!container || container === this.domNode) {
			return;
		}

		const targetRect = matchTarget.getBoundingClientRect();
		const containerRect = container.getBoundingClientRect();

		// Vertical: if not fully visible, align to top of container
		if (targetRect.top < containerRect.top || targetRect.bottom > containerRect.bottom) {
			container.scrollTop += targetRect.top - containerRect.top - 2;
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

	/**
	 * Hoist a dropdown panel out of this widget's overflow container and
	 * position it as a fixed overlay in the editor container.
	 */
	private hoistDropdownPanel(): void {
		const panel = this.domNode.querySelector('.snc-dropdown-panel:not([data-hover-menu])') as HTMLElement;
		if (!panel) { return; }

		const trigger = panel.closest('.snc-dropdown-trigger') as HTMLElement;
		if (!trigger) { return; }

		// Get trigger's viewport position before moving anything
		const triggerRect = trigger.getBoundingClientRect();
		const align = panel.getAttribute('snc-dropdown-align') || 'left';

		// Capture child-key chain before removing from DOM (ancestors will be lost)
		const childKeyChain: string[] = [];
		let ancestor = panel.parentElement;
		while (ancestor && ancestor !== this.domNode) {
			const ck = ancestor.getAttribute('snc-child-key');
			if (ck) { childKeyChain.push(ck); }
			ancestor = ancestor.parentElement;
		}
		if (childKeyChain.length > 0) {
			panel.setAttribute('snc-child-key-chain', JSON.stringify(childKeyChain));
		}

		// Remove from the widget DOM
		panel.remove();

		// Position as fixed overlay
		panel.style.position = 'fixed';
		panel.style.top = `${triggerRect.bottom}px`;
		if (align === 'right') {
			panel.style.left = '';
			panel.style.right = `${dom.getWindow(this.editor.getContainerDomNode()).innerWidth - triggerRect.right}px`;
		} else {
			panel.style.left = `${triggerRect.left}px`;
			panel.style.right = '';
		}
		panel.style.zIndex = '10000';

		// Append to the editor's container so it escapes widget overflow
		this.editor.getContainerDomNode().appendChild(panel);
		this.hoistedDropdown = panel;

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
		this.hoistedDropdownListeners.push(
			dom.addDisposableListener(panel, 'input', (ev: Event) => {
				const target = ev.target as HTMLElement;
				if (!target) { return; }
				let el: Element | null = target;
				while (el && el !== panel.parentElement) {
					if (el.hasAttribute('snc-input')) {
						const pythonEventStr = wrapHoistedEvent(el.getAttribute('snc-input') ?? '', el);
						const value = (target as HTMLInputElement).value ?? '';
						this.onInputEvent(pythonEventStr, value);
						return;
					}
					el = el.parentElement;
				}
			})
		);
	}

	/**
	 * Remove any hoisted dropdown panel and dispose its event listeners.
	 */
	private cleanupHoistedDropdown(): void {
		if (this.hoistedDropdown) {
			this.hoistedDropdown.remove();
			this.hoistedDropdown = null;
		}
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

	/**
	 * Recompute hoisted segment-label positions from their scroll container and
	 * hide any that have scrolled out of the container's visible area.
	 */
	private repositionHoistedSegmentLabels(): void {
		if (this.hoistedSegmentLabels.length === 0) { return; }
		const widgetRect = this.domNode.getBoundingClientRect();
		for (const entry of this.hoistedSegmentLabels) {
			const { anchor, scroller, baseLeft, baseTop, baseScrollLeft, baseScrollTop } = entry;
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
			const anchorViewportLeft = widgetRect.left + left;
			const anchorViewportTop = widgetRect.top + top;
			const outOfView = anchorViewportLeft < scrollerRect.left - 1
				|| anchorViewportLeft > scrollerRect.right + 1
				|| anchorViewportTop < scrollerRect.top - 12
				|| anchorViewportTop > scrollerRect.bottom + 1;
			anchor.style.visibility = outOfView ? 'hidden' : '';
		}
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
	 * Dispose of the widget
	 */
	override dispose(): void {
		this.hidePyExpTooltip();
		this.hideActionTooltip();
		this.hideSimpleTooltip();
		this.hideHoverMenu();
		this.cleanupHoistedDropdown();
		this.cleanupHoistedSegmentLabels();
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
function computeRenameSelectionForEdit(editText: string, isPrependedToFirstLine: boolean, insertedRange: Range): Selection | null {
	const firstLine = editText.split('\n')[0];

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

export class SNCController extends Disposable implements IEditorContribution {
	public static readonly ID = 'editor.contrib.snc';

	private visualizationWidgets: Map<number, VisualizationWidget[]> = new Map();
	private viewZones: Map<number, string> = new Map(); // line number -> view zone id
	// Synthetic empty space above line 1. Used to keep a focused/clicked
	// visualizer pixel-stable when content above it shrinks while the file is
	// scrolled near the top: scrollTop can't go below 0, so the deficit is
	// added as a spacer instead of letting the anchor jump upward.
	private topSpacerZoneId: string | null = null;
	private topSpacerHeight = 0;
	private isAdjustingTopSpacer = false;
	private debounceTimer: any = null;
	private readonly debounceDelay = 100; // ms

	// Streaming state
	private currentRunId: string | null = null;

	// Sticky notification shown when the python executable can't be launched
	// (e.g. neither the Python extension's selection nor the 'python3'
	// fallback exists). Auto-dismissed when a subsequent run starts producing
	// output, indicating Python is working again.
	private pythonSpawnFailureNotification: INotificationHandle | null = null;
	private eventsBeingHandledCurrentRun: { line: number; visIndex: number; events: UiEvent[] }[] = [];
	private visualizationItems: IVisualizationItem[] = [];
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
	// several auto-linked lines can coexist without cross-talk: an update from
	// one visualizer must edit its own inserted line, not whichever line was
	// linked most recently.
	//
	// autoEstablished is true when the link was created programmatically by an
	// auto-generated LOC (vs. by the user selecting text). Auto-established links
	// must not be torn down just because the editor selection is empty — the user
	// is interacting with the visualizer, not the editor.
	private linkedSelections: {
		line: number;
		visIndex: number;
		decorationId: string;
		autoEstablished: boolean;
	}[] = [];
	private suppressSelectionEvent = false;
	private selectionDebounceTimer: any = null;

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
	) {
		super();

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
			// Set up language change listener for the new model
			this.setupLanguageChangeListener();
			// Re-resolve the Python interpreter for the new model's workspace
			// folder. In multi-root workspaces the user may have a different
			// interpreter selected per-folder.
			this.resolveAndSetPythonExecutable();
			// Trigger initial visualization when a new model loads
			this.triggerInitialVisualization();
		}));
		this._register(editor.onDidDispose(() => { this.clearVisualizationWidgets(); }));
		this._register(editor.onDidChangeCursorPosition(() => {
			this.onCursorPositionChanged();
		}));
		this._register(editor.onDidChangeCursorSelection(() => {
			this.onSelectionChanged();
		}));

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
		}));

		// Initial resolve. This races with the first run's pool spawn — if
		// the resolve loses, the first run uses 'python3' and subsequent
		// runs pick up the resolved interpreter once setPythonExecutable
		// drains/refills the pools.
		this.resolveAndSetPythonExecutable();

		// Exposed for ui_testing_tools/ CDP scripts (buffer.js, scroll.js).
		// Monaco only renders visible lines in the DOM, so CDP can't read the
		// full text buffer or control scroll position without model access.
		(globalThis as any)._sncEditor = editor;
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

		// Immediately adjust visualization items for line changes (deletions/insertions)
		// so stale visualizers don't linger on deleted or shifted lines.
		this.adjustVisualizationItemsForContentChange(e);

		// Debounce to avoid running on every keystroke
		if (this.debounceTimer) {
			clearTimeout(this.debounceTimer);
		}

		this.debounceTimer = setTimeout(() => {
			this.runProgram(this.getProgram());
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
				const editorModel = this.editor.getModel();
				const survivingLinks: typeof this.linkedSelections = [];
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
						// The visualizer's trigger line was deleted; drop the link.
						if (editorModel) {
							editorModel.deltaDecorations([link.decorationId], []);
						}
					} else {
						survivingLinks.push(link);
					}
				}
				this.linkedSelections = survivingLinks;
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
			this.lastCursorLine = this.editor.getPosition()?.lineNumber ?? null;
			return;
		}
		if (this.cursorUpdateTimer) {
			clearTimeout(this.cursorUpdateTimer);
		}
		this.cursorUpdateTimer = setTimeout(() => {
			this.updateVisualizationWidgets(data);
		}, 50);

		// When the cursor moves to a different line, the effective focused line
		// changes (cursor line is the default). Drop any pinned focus from a
		// prior click and trigger a debounced re-run so non-focused widgets
		// re-render with small=True (and the new focused widget renders full).
		const newLine = this.editor.getPosition()?.lineNumber ?? null;
		if (newLine !== this.lastCursorLine) {
			this.lastCursorLine = newLine;
			this.explicitFocusedLine = null;
			if (this.isPythonModel()) {
				if (this.focusRerunTimer) { clearTimeout(this.focusRerunTimer); }
				this.focusRerunTimer = setTimeout(() => {
					this.focusRerunTimer = null;
					this.runProgram(this.getProgram());
				}, this.focusRerunDelay);
			}
		}
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
		return this.editor.getPosition()?.lineNumber ?? null;
	}

	/**
	 * Pin focus to `line` and immediately re-run so that line's top-level
	 * widget renders with `small=False`. Called when the user clicks a small
	 * (non-focused) widget.
	 */
	private requestExpand(line: number): void {
		if (this.effectiveFocusedLine() === line) { return; }
		this.explicitFocusedLine = line;
		// Cancel any pending cursor-driven re-run; this click supersedes it.
		if (this.focusRerunTimer) {
			clearTimeout(this.focusRerunTimer);
			this.focusRerunTimer = null;
		}
		if (this.isPythonModel()) {
			this.runProgram(this.getProgram());
		}
	}

	private onSelectionChanged(): void {
		if (this.suppressSelectionEvent) {
			return;
		}
		if (this.selectionDebounceTimer) {
			clearTimeout(this.selectionDebounceTimer);
		}
		this.selectionDebounceTimer = setTimeout(() => {
			this.handleEditorSelection();
		}, 150);
	}

	private handleEditorSelection(): void {
		const editorModel = this.editor.getModel();
		const selection = this.editor.getSelection();
		if (!editorModel || !selection || selection.isEmpty()) {
			// An auto-established link (from an auto-generated LOC) is driven by the
			// visualizer, not the editor selection; an empty editor selection (just
			// a cursor) must not tear it down, or continued visualizer interaction
			// would orphan the inserted line and trigger a duplicate insert.
			this.unlinkUserSelections();
			return;
		}

		const selectedText = editorModel.getValueInRange(selection);
		if (!selectedText || selectedText.length < 3) {
			this.unlinkUserSelections();
			return;
		}

		const selStartLine = selection.startLineNumber;
		const selIndent = this.getLineIndent(selStartLine);

		// Walk backward to find the first non-blank line with a visualizer at same/lesser indent
		let targetVisItem: IVisualizationItem | undefined;
		for (let line = selStartLine - 1; line >= 1; line--) {
			const content = editorModel.getLineContent(line);
			if (content.trim() === '') {
				continue;
			}
			const lineIndent = content.length - content.trimStart().length;
			if (lineIndent > selIndent) {
				continue;
			}
			targetVisItem = this.visualizationItems.find(item => item.line === line);
			if (targetVisItem) {
				break;
			}
			if (lineIndent < selIndent) {
				break;
			}
		}

		if (!targetVisItem) {
			return;
		}

		// Moving the selection to a different visualizer supersedes any prior
		// user-established link; tear those down first (auto links are untouched).
		this.unlinkUserSelections();

		// Track the selection range via a decoration so it survives edits
		const existing = this.findLink(targetVisItem.line, targetVisItem.visIndex);
		const decorationIds = editorModel.deltaDecorations(
			existing ? [existing.decorationId] : [],
			[{
				range: selection,
				options: {
					description: 'snc-linked-selection',
					stickiness: TrackedRangeStickiness.NeverGrowsWhenTypingAtEdges,
				}
			}]
		);
		const decorationId = decorationIds[0] ?? null;
		if (decorationId) {
			// This link is driven by an explicit user text selection, not an
			// auto-generated LOC, so empty-selection unlinking should apply to it.
			this.setLink(targetVisItem.line, targetVisItem.visIndex, decorationId, false);
		}

		const pythonEventStr = "lambda e: EditorTextSelect(text=e.get('text', ''))";
		const eventJSON = { type: 'editorTextSelect', text: selectedText };
		const event: UiEvent = {
			line: targetVisItem.line,
			visIndex: targetVisItem.visIndex,
			pythonEventStr,
			eventJSON,
		};
		this.sendEventToPython(event);
	}

	/** Find the link tracked for a specific visualizer, if any. */
	private findLink(line: number, visIndex: number) {
		return this.linkedSelections.find(l => l.line === line && l.visIndex === visIndex);
	}

	/**
	 * Record (or update) the link for a visualizer. Replaces any existing entry
	 * for the same (line, visIndex) in place, keeping the list one-per-visualizer.
	 */
	private setLink(line: number, visIndex: number, decorationId: string, autoEstablished: boolean): void {
		const existing = this.findLink(line, visIndex);
		if (existing) {
			existing.decorationId = decorationId;
			existing.autoEstablished = autoEstablished;
		} else {
			this.linkedSelections.push({ line, visIndex, decorationId, autoEstablished });
		}
	}

	/**
	 * Tear down every user-established (non-auto) link: remove its decoration and
	 * notify its visualizer so its Python model clears its linked state. Auto
	 * links (from auto-generated LOCs) are left intact.
	 */
	private unlinkUserSelections(): void {
		const editorModel = this.editor.getModel();
		const userLinks = this.linkedSelections.filter(l => !l.autoEstablished);
		this.linkedSelections = this.linkedSelections.filter(l => l.autoEstablished);
		for (const link of userLinks) {
			if (editorModel) {
				editorModel.deltaDecorations([link.decorationId], []);
			}
			const event: UiEvent = {
				line: link.line,
				visIndex: link.visIndex,
				pythonEventStr: 'lambda e: Unlink()',
				eventJSON: { type: 'unlink' },
			};
			this.sendEventToPython(event);
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
		this.eventsBeingHandledCurrentRun = [];
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
				this.runProgram(this.getProgram());
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
			this.runProgram(content);
		}, 1);
	}

	private clearVisualizationWidgets(): void {
		this.syntaxErrorActive = false;

		// Remove all existing widgets
		for (const widgets of this.visualizationWidgets.values()) {
			for (const widget of widgets) {
				widget.dispose();
			}
		}
		this.visualizationWidgets.clear();

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

		// console.log("visualizationData", visualizationData);

		// Get current cursor position
		const cursorPosition = this.editor.getPosition();
		const cursorLine = cursorPosition?.lineNumber || 1;

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

		this.editor.changeViewZones((accessor) => {
			// Remove widgets/view zones for lines no longer present
			for (const [line, widgets] of Array.from(this.visualizationWidgets.entries())) {
				if (!presentLines.has(line)) {
					// console.log("disposing", line, widgets)
					for (const w of widgets) { w.dispose(); }
					this.visualizationWidgets.delete(line);
					const vz = this.viewZones.get(line);
					if (vz) { accessor.removeZone(vz); this.viewZones.delete(line); }
				}
			}

			// Update or create for each present line
			for (const [lineNumber, items] of groupedByLine.entries()) {
				// Decide first vs last iteration
				const shouldUseFirst = items.some(item =>
					item.last_line_in_containing_loop !== undefined &&
					cursorLine <= item.last_line_in_containing_loop + 1
				);

				// Group by execution step and pick one step
				const groupedByStep = new Map<number, IVisualizationItem[]>();
				for (const item of items) {
					if (!groupedByStep.has(item.execution_step)) {
						groupedByStep.set(item.execution_step, []);
					}
					groupedByStep.get(item.execution_step)!.push(item);
				}
				const selectedStep = (shouldUseFirst ? Math.min : Math.max)(...groupedByStep.keys());
				const stepItems = groupedByStep.get(selectedStep) || [];

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
						} else if (existingZoneId) {
							accessor.removeZone(existingZoneId);
							this.viewZones.delete(lineNumber);
						}
					}
				} else {
					// Rebuild for this line
					if (existing) {
						for (const w of existing) { w.dispose(); }
						this.visualizationWidgets.delete(lineNumber);
						const oldZone = this.viewZones.get(lineNumber);
						if (oldZone) { accessor.removeZone(oldZone); this.viewZones.delete(lineNumber); }
					}

					const widgets: VisualizationWidget[] = [];
					for (let i = 0; i < stepItems.length; i++) {
						const item = stepItems[i];
						const visIndex = (item as any).visIndex ?? i;
						const widget = new VisualizationWidget(
							this.editor,
							lineNumber,
							visIndex,
							(pythonEventStr, ev, overrideRect?) => { this.onPointerEvent(lineNumber, visIndex, pythonEventStr, ev, overrideRect); },
							(pythonEventStr, ev) => { this.onKeyboardEvent(lineNumber, visIndex, pythonEventStr, ev); },
							(pythonEventStr, value) => { this.onInputEvent(lineNumber, visIndex, pythonEventStr, value); },
							() => this.effectiveFocusedLine() === lineNumber,
							() => this.requestExpand(lineNumber),
							(expression) => { this.insertNewVarFromExpression(lineNumber, expression); },
							this.clipboardService
						);
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

		for (const widget of widgetsToReposition) {
			widget.updatePosition();
		}
		this.applySyntaxErrorClassToWidgets();
	}

	/**
	 * Handle pointer event from VisualizationWidget
	 */

	private onPointerEvent(lineNumber: number, visIndex: number, pythonEventStr: string, ev: MouseEvent, overrideRect?: DOMRect): void {
		const rect = overrideRect ?? (ev.target as HTMLElement).getBoundingClientRect();

		const eventJSON = { type: ev.type, button: ev.button, buttons: ev.buttons, detail: ev.detail, offsetY: ev.clientY - rect.top, elementHeight: rect.height, timeStamp: ev.timeStamp, altKey: ev.altKey, ctrlKey: ev.ctrlKey, metaKey: ev.metaKey, shiftKey: ev.shiftKey };

		const event: UiEvent = { line: lineNumber, visIndex, pythonEventStr, eventJSON };
		// console.log('SNC viz_pointer event', JSON.stringify(event));

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

		const event: UiEvent = { line: lineNumber, visIndex, pythonEventStr, eventJSON };
		// console.log('SNC keyboard event', JSON.stringify(event));

		this.sendEventToPython(event);
	}

	/**
	 * Handle input event from VisualizationWidget (for text inputs with snc-input attribute)
	 */
	private onInputEvent(lineNumber: number, visIndex: number, pythonEventStr: string, value: string): void {
		const eventJSON = { type: 'input', value };
		const event: UiEvent = { line: lineNumber, visIndex, pythonEventStr, eventJSON };
		this.sendEventToPython(event);
	}

	private sendEventToPython(event: UiEvent) {
		this.runProgram(this.getProgram(), event);
	}

	/**
	 * Handle commands from visualizers (Elm-style commands)
	 */
	private handleCommand(command: SNCCommand): void {
		if (command.type === 'NewCode') {
			const model = this.editor.getModel();
			if (!model || command.edits.length === 0) {
				return;
			}

			// Sort edits bottom-to-top so line numbers remain valid as we insert
			const sortedEdits = [...command.edits].sort((a, b) => b.afterLine - a.afterLine);

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
			const newSelections = model.pushEditOperations([], editOperations, (inverseEdits) => {
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
			});

			// Link the freshly inserted line so subsequent visualizer interactions
			// update it in place (via ChangeSelectedText) instead of stacking new
			// lines. The inverse range of a (\n + text) insert includes the leading
			// newline boundary, so narrow it to just the inserted code line.
			if (mainInverseRange) {
				// Other edits inserted above the trigger line (e.g. an auto-added
				// `import re`) shift the visualizer's source line down. Account for
				// that so the link and cursor target the actual (post-edit) line.
				const linesInsertedAbove = command.edits.reduce(
					(n, e) => n + (e.afterLine < command.triggerLine ? 1 : 0), 0);
				const actualTriggerLine = command.triggerLine + linesInsertedAbove;

				// The assignment is always inserted immediately after the (shifted)
				// trigger line. Derive the linked range directly from that line
				// rather than from inverse-range arithmetic, which is unreliable
				// across the multi-region edit when an import is also inserted.
				const insertedLine = actualTriggerLine + 1;
				const linkedRange = new Range(
					insertedLine, model.getLineFirstNonWhitespaceColumn(insertedLine) || 1,
					insertedLine, model.getLineMaxColumn(insertedLine)
				);
				this.establishLinkForRange(linkedRange, actualTriggerLine, command.triggerVisIndex);

				// The user is still interacting with the triggering visualizer (e.g.
				// typing in its search box). Inserting moved the editor cursor onto
				// the new line, which would collapse the focused visualizer and steal
				// DOM focus. Keep the cursor on the trigger line so that visualizer
				// stays focused/expanded and the user can keep interacting.
				this.suppressSelectionEvent = true;
				const triggerCol = model.getLineMaxColumn(actualTriggerLine);
				this.editor.setPosition({ lineNumber: actualTriggerLine, column: triggerCol });
				setTimeout(() => { this.suppressSelectionEvent = false; }, 0);
			} else if (newSelections && newSelections.length > 0) {
				this.editor.setSelection(newSelections[0]);
				this.editor.focus();
			}

			// Restore the scroll offset so the anchored line stays visually put.
			// Lines inserted strictly above the anchor (e.g. an auto-added
			// `import re`) push it down; count them and re-anchor accordingly.
			if (shouldStabilizeScroll && anchorLineNumber > 0) {
				const linesInsertedAboveAnchor = command.edits.reduce(
					(n, e) => n + (e.afterLine < anchorLineNumber ? 1 : 0), 0);
				const newAnchorLine = anchorLineNumber + linesInsertedAboveAnchor;
				const newAnchorTop = this.editor.getTopForLineNumber(newAnchorLine);
				this.editor.setScrollTop(newAnchorTop + anchorDelta, ScrollType.Immediate);
			}
		} else if (command.type === 'ChangeSelectedText') {
			this.handleChangeSelectedText(command.text, command.new_var_name ?? null, command.triggerLine, command.triggerVisIndex);
		} else if (command.type === 'CopyToClipboard') {
			this.clipboardService.writeText(command.text);
		}
	}

	/**
	 * Insert `new_var = <expression>` on the line below `lineNumber`, matching
	 * that line's indentation, and place the cursor on the new variable name so
	 * the user can rename it immediately. Triggered by the "+" button in an
	 * expression tooltip.
	 */
	private insertNewVarFromExpression(lineNumber: number, expression: string): void {
		const model = this.editor.getModel();
		if (!model) {
			return;
		}
		const expr = expression.trim();
		if (!expr) {
			return;
		}

		// Match the trigger line's indentation so the new statement lands at the
		// same block level.
		const firstNonWs = model.getLineFirstNonWhitespaceColumn(lineNumber);
		const indent = firstNonWs > 0
			? model.getLineContent(lineNumber).slice(0, firstNonWs - 1)
			: '';
		const editText = `${indent}new_var = ${expr}`;

		const col = model.getLineMaxColumn(lineNumber);
		const editOperation = {
			range: new Range(lineNumber, col, lineNumber, col),
			text: '\n' + editText
		};

		const newSelections = model.pushEditOperations([], [editOperation], (inverseEdits) => {
			const inv = inverseEdits[0];
			if (!inv) {
				return null;
			}
			const sel = computeRenameSelectionForEdit(editText, false, inv.range);
			return sel ? [sel] : null;
		});

		if (newSelections && newSelections.length > 0) {
			this.editor.setSelection(newSelections[0]);
		} else {
			this.editor.setPosition({ lineNumber: lineNumber + 1, column: 1 });
		}
		this.editor.focus();
	}

	/**
	 * Track the given editor range as the linked selection for a visualizer, so
	 * subsequent interactions update that range in place (ChangeSelectedText).
	 * Mirrors the decoration bookkeeping in handleEditorSelection, but for a
	 * range that SNC just inserted rather than one the user manually selected.
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
			this.setLink(line, visIndex, decorationId, true);
		}
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

	private handleChangeSelectedText(newText: string, newVarName: string | null, line: number, visIndex: number): void {
		const editorModel = this.editor.getModel();
		const link = this.findLink(line, visIndex);
		if (!editorModel || !link) {
			return;
		}
		const trackedRange = editorModel.getDecorationRange(link.decorationId);
		if (!trackedRange) {
			return;
		}

		const currentText = editorModel.getValueInRange(trackedRange);

		// Resolve the assignment target. The editor's current line is the source
		// of truth for the variable name; Python may rename it (new_var_name) only
		// when the prior name is unused elsewhere in the document. We rebuild the
		// new line's leading `name =` accordingly, ignoring whatever name Python
		// happened to put in the text.
		const incoming = SNCController.splitAssignment(newText);
		if (incoming) {
			const current = SNCController.splitAssignment(currentText);
			let targetName = current ? current.name : incoming.name;
			if (newVarName && current && newVarName !== current.name
				&& !this.isVarNameUsedOutsideRange(current.name, trackedRange)) {
				targetName = newVarName;
			}
			newText = `${incoming.indent}${targetName} = ${incoming.rhs}`;
		}

		if (currentText === newText) {
			return;
		}

		this.suppressSelectionEvent = true;
		editorModel.pushEditOperations([], [{
			range: trackedRange,
			text: newText,
		}], () => null);

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

		// Keep the text selected so the user can see what's linked, but only when
		// the editor already has focus. If the user is driving this update from a
		// visualizer control (e.g. typing in the search box of an auto-linked
		// line), stealing the editor selection would yank DOM focus out of that
		// control and break continued interaction.
		if (this.editor.hasTextFocus()) {
			this.editor.setSelection(newRange);
		}

		setTimeout(() => { this.suppressSelectionEvent = false; }, 0);
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

	private async runProgram(content: string, uiEvent?: UiEvent): Promise<void> {
		// Defensive guard: every caller should already gate on isPythonModel(),
		// but make sure we never spawn a Python worker for a non-Python buffer.
		if (!this.isPythonModel()) {
			return;
		}

		// Get the working directory from the first workspace folder
		const workingDirectory = this.workspaceContextService.getWorkspace().folders[0]?.uri.fsPath || '';
		const channel = this.mainProcessService.getChannel('sncProcess');

		// Cancel any previous streaming run
		if (this.currentRunId) {
			try { await channel.call('cancel', [this.currentRunId]); } catch { /* ignore */ }
			this.currentRunId = null;
			this.eventsBeingHandledCurrentRun = [];
		}

		this.streamUpdateTimer = null;

		// Add event to appropriate visualizer
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
		}

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

					// replace prior items as new ones come in
					let found = false;
					this.visualizationItems = this.visualizationItems.map(visItem => {
						if (visItem.line == msg.item.line && visItem.visIndex == msg.item.visIndex) {
							found = true;
							const handled_events: UiEvent[] = this.eventsBeingHandledCurrentRun.find(ev => ev.line == msg.item.line && ev.visIndex == msg.item.visIndex)?.events || [];
							return {
								...msg.item,
								unhandledEvents: (visItem.unhandledEvents || []).filter(ev => !handled_events.includes(ev))
							};
						}
						return visItem;
					});
					if (!found) {
						this.visualizationItems = [...this.visualizationItems, msg.item];
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
				} else if (msg.type === 'command') {
					// Handle commands from visualizers
					this.handleCommand(msg.command);
				} else if (msg.type === 'end') {
					// console.log('program end');
					const tEnd = now();

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
						this.visualizationItems = this.visualizationItems.filter(visItem =>
							visItem.runId === this.currentRunId
						);
						this.setSyntaxErrorState(false);
						this.updateVisualizationWidgets(this.visualizationItems);
					}

					if (msg.result.stdout) {
						console.log('Program output:', msg.result.stdout);
					}
					if (msg.result.stderr) {
						console.error('Program errors:', msg.result.stderr);
					}

					this.currentRunId = null;
					this.eventsBeingHandledCurrentRun = [];
				} else if (msg.type === 'warning') {
					console.warn('SNC warning:', msg.warning);
				} else if (msg.type === 'error') {
					console.error('SNC streaming error:', msg.error);
					// Surface python-spawn-failure errors as a sticky toast so
					// the user understands why visualizers stopped working.
					// Other errors (timeouts, etc.) still just log to console.
					if (msg.error && msg.error.startsWith('Sculpt-n-Code: failed to launch Python')) {
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

					this.currentRunId = null;
					this.eventsBeingHandledCurrentRun = [];
					this.visualizationItems = [];
					this.clearVisualizationWidgets();
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
		const nowMs = (typeof performance !== 'undefined' ? performance.now() : Date.now());
		// Track trigger time for timing measurement
		this.runTriggerMsById.set(runId, nowMs);
		if (uiEvent) {
			this.runEventTargetById.set(runId, { line: uiEvent.line, visIndex: uiEvent.visIndex });
		}

		this.eventsBeingHandledCurrentRun = models_and_events.map(m_e => ({
			line: m_e.line,
			visIndex: m_e.visIndex,
			events: m_e['events'] || []
		}))

		try {
			const focusedLine = this.effectiveFocusedLine();
			const options: IProcessOptions = {
				modelsAndEventsJson: JSON.stringify(models_and_events),
				timeout: 60_000,
				workingDirectory,
				...(focusedLine !== null ? { focusedLine } : {})
			};
			await channel.call('startProgram', [content, options, runId]);
		} catch (error) {
			console.error('Failed to start streaming run:', error);
			this.currentRunId = null;
			this.eventsBeingHandledCurrentRun = [];
			this.clearVisualizationWidgets();
		}
	}

}

registerEditorContribution(SNCController.ID, SNCController, EditorContributionInstantiation.AfterFirstRender);
