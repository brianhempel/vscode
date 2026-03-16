import { registerEditorContribution, EditorContributionInstantiation } from '../../../browser/editorExtensions.js';
import { Disposable, IDisposable } from '../../../../base/common/lifecycle.js';
import { IEditorContribution, ScrollType } from '../../../common/editorCommon.js';
import { ICodeEditor, IViewZone, IOverlayWidget, IOverlayWidgetPosition, IOverlayWidgetPositionCoordinates } from '../../../browser/editorBrowser.js';
import { Position } from '../../../common/core/position.js';
import { Range } from '../../../common/core/range.js';
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
	private moveThrottleTimer: any = null;
	private readonly moveThrottleDelay = 16;
	private lastRenderedHtml: string | null = null;
	private focusRestoreVersion = 0;
	private hoistedDropdown: HTMLElement | null = null;
	private hoistedDropdownListeners: IDisposable[] = [];
	private useBlockLayout = false;
	private readonly clipboardService: IClipboardService;
	private pyExpTooltip: HTMLElement | null = null;
	private pyExpTooltipTimer: any = null;
	private pyExpTooltipHideTimer: any = null;
	private pyExpCurrentTarget: Element | null = null;
	private pyExpTooltipDragInProgress = false;
	private lastMouseDownTarget: Node | null = null;

	constructor(editor: ICodeEditor, lineNumber: number, visIndex: number, onPointerEvent: (pythonEventStr: string, ev: MouseEvent, overrideRect?: DOMRect) => void, onKeyboardEvent: (pythonEventStr: string, ev: KeyboardEvent) => void, onInputEvent: (pythonEventStr: string, value: string) => void, clipboardService: IClipboardService) {
		super();
		this.editor = editor;
		this.position = new Position(lineNumber, 1);
		this.visIndex = visIndex;
		this.lineNumber = lineNumber;
		this.onPointerEvent = onPointerEvent;
		this.onKeyboardEvent = onKeyboardEvent;
		this.onInputEvent = onInputEvent;
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
		tooltip.className = 'snc-py-exp-tooltip';

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

		const copyBtn = document.createElement('button');
		copyBtn.className = 'snc-copy-btn';
		copyBtn.textContent = '\u{29C9}';  // clipboard emoji
		copyBtn.title = 'Copy to clipboard';
		copyBtn.addEventListener('mousedown', (e) => {
			e.preventDefault();
			e.stopPropagation();
			this.clipboardService.writeText(expression);
			copyBtn.textContent = '\u2713';  // check mark
			setTimeout(() => { copyBtn.textContent = '\u{29C9}'; }, 1000);
		});
		tooltip.appendChild(copyBtn);

		// Keep tooltip alive while hovering it
		tooltip.addEventListener('mouseenter', () => {
			clearTimeout(this.pyExpTooltipHideTimer);
		});
		tooltip.addEventListener('mouseleave', () => {
			this.schedulePyExpTooltipHide();
		});

		// Position tooltip above the target element
		tooltip.style.left = `${rect.left}px`;
		tooltip.style.top = `${rect.top - 28}px`;

		this.editor.getContainerDomNode().appendChild(tooltip);
		this.pyExpTooltip = tooltip;

		// Adjust if tooltip goes off screen top
		const tooltipRect = tooltip.getBoundingClientRect();
		if (tooltipRect.top < 0) {
			tooltip.style.top = `${rect.bottom + 4}px`;
		}
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
			el = el.parentElement;
		}
		return pythonEventStr;
	}

	private dispatch_mouse_python_event(attr_name: string, ev: MouseEvent): void {
		if (!ev.target) { return; }

		let node = ev.target as Node;
		let el: Element | null = node.nodeType === Node.ELEMENT_NODE ? (node as Element) : (node.parentElement);

		while (el && el != this.domNode) {
			if (el.hasAttribute(attr_name) || el.hasAttribute(`snc-mouse`)) {
				let pythonEventStr: string;
				if (el.hasAttribute(`snc-mouse`)) {
					// snc-mouse="5" is shorthand for snc-mouse-move="MouseMove(5)" snc-mouse-down="MouseDown(5)" snc-mouse-up="MouseUp(5)"
					pythonEventStr = {
						'snc-mouse-move': `MouseMove(${el.getAttribute(`snc-mouse`)})`,
						'snc-mouse-down': `MouseDown(${el.getAttribute(`snc-mouse`)})`,
						'snc-mouse-up': `MouseUp(${el.getAttribute(`snc-mouse`)})`,
					}[attr_name] ?? '';
				} else {
					pythonEventStr = el.getAttribute(attr_name) ?? '';
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

		// Dismiss any active py-exp tooltip since the DOM is being replaced
		this.hidePyExpTooltip();

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

		const trustedHtml = ttPolicy?.createHTML(html) ?? html;
		this.domNode.innerHTML = trustedHtml as string;
		this.lastRenderedHtml = html;

		// Hoist any dropdown panel outside the overflow container
		this.hoistDropdownPanel();
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
		const autoFocusEl = this.domNode.querySelector('[autofocus]') as HTMLElement | null;
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
				// If the previously focused element was already an input (savedSelectionStart != null),
				// use normal focus restoration to preserve cursor position.
				// Otherwise (e.g. focus was on the outer div), autofocus the new input.
				if (autoFocusEl && savedSelectionStart === null) {
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
		const panel = this.domNode.querySelector('.snc-dropdown-panel') as HTMLElement;
		if (!panel) { return; }

		const trigger = this.domNode.querySelector('.snc-dropdown-trigger') as HTMLElement;
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
		this.cleanupHoistedDropdown();
		this.editor.removeOverlayWidget(this);
		super.dispose();
	}
}

export class SNCController extends Disposable implements IEditorContribution {
	public static readonly ID = 'editor.contrib.snc';

	private visualizationWidgets: Map<number, VisualizationWidget[]> = new Map();
	private viewZones: Map<number, string> = new Map(); // line number -> view zone id
	private debounceTimer: any = null;
	private readonly debounceDelay = 100; // ms

	// Streaming state
	private currentRunId: string | null = null;
	private eventsBeingHandledCurrentRun: { line: number; visIndex: number; events: UiEvent[] }[] = [];
	private visualizationItems: IVisualizationItem[] = [];
	private syntaxErrorActive = false;
	private streamSubscription: { dispose(): void } | null = null;
	private streamUpdateTimer: any = null;
	private cursorUpdateTimer: any = null;

	// Linked-editing state: tracks the editor selection that is live-synced with a visualizer
	private linkedSelectionDecorationId: string | null = null;
	private linkedVisualizerLine: number | null = null;
	private linkedVisualizerVisIndex: number | null = null;
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
	) {
		super();

		// Register event handlers
		this._register(editor.onDidChangeModelContent((e) => { this.onDidChangeModelContent(e); }));
		this._register(editor.onDidChangeModel(() => {
			this.clearVisualizationWidgets();
			// Set up language change listener for the new model
			this.setupLanguageChangeListener();
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

		// Exposed for ui_testing_tools/ CDP scripts (buffer.js, scroll.js).
		// Monaco only renders visible lines in the DOM, so CDP can't read the
		// full text buffer or control scroll position without model access.
		(globalThis as any)._sncEditor = editor;
	}

	getProgram(): string {
		return this.editor.getModel()!.getLinesContent().join('\n');
	}

	onDidChangeModelContent(e: IModelContentChangedEvent): void {
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

			const newItems: IVisualizationItem[] = [];

			for (const item of this.visualizationItems) {
				if (item.line < startLine) {
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
			return;
		}
		if (this.cursorUpdateTimer) {
			clearTimeout(this.cursorUpdateTimer);
		}
		this.cursorUpdateTimer = setTimeout(() => {
			this.updateVisualizationWidgets(data);
		}, 50);
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
			if (this.linkedVisualizerLine !== null) {
				this.sendUnlinkEvent();
			}
			return;
		}

		const selectedText = editorModel.getValueInRange(selection);
		if (!selectedText || selectedText.length < 3) {
			if (this.linkedVisualizerLine !== null) {
				this.sendUnlinkEvent();
			}
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

		// Track the selection range via a decoration so it survives edits
		const decorationIds = editorModel.deltaDecorations(
			this.linkedSelectionDecorationId ? [this.linkedSelectionDecorationId] : [],
			[{
				range: selection,
				options: {
					description: 'snc-linked-selection',
					stickiness: TrackedRangeStickiness.NeverGrowsWhenTypingAtEdges,
				}
			}]
		);
		this.linkedSelectionDecorationId = decorationIds[0] ?? null;
		this.linkedVisualizerLine = targetVisItem.line;
		this.linkedVisualizerVisIndex = targetVisItem.visIndex;

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

	private sendUnlinkEvent(): void {
		if (this.linkedVisualizerLine === null || this.linkedVisualizerVisIndex === null) {
			return;
		}
		const pythonEventStr = 'lambda e: Unlink()';
		const eventJSON = { type: 'unlink' };
		const event: UiEvent = {
			line: this.linkedVisualizerLine,
			visIndex: this.linkedVisualizerVisIndex,
			pythonEventStr,
			eventJSON,
		};

		// Clean up linked state
		if (this.linkedSelectionDecorationId) {
			const editorModel = this.editor.getModel();
			if (editorModel) {
				editorModel.deltaDecorations([this.linkedSelectionDecorationId], []);
			}
			this.linkedSelectionDecorationId = null;
		}
		this.linkedVisualizerLine = null;
		this.linkedVisualizerVisIndex = null;

		this.sendEventToPython(event);
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
		const model = this.editor.getModel();
		if (!model) {
			return;
		}

		const languageId = model.getLanguageId();

		// If language changed to Python, trigger visualization
		if (languageId === 'python' || languageId === 'py') {
			this.triggerInitialVisualization();
		}
	}

	private onEditorsVisibilityChanged(): void {
		// Check if this editor has a model and is Python
		const model = this.editor.getModel();
		if (!model) {
			return;
		}

		const languageId = model.getLanguageId();
		if (languageId !== 'python' && languageId !== 'py') {
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
		// Only trigger for Python files
		const model = this.editor.getModel();
		if (!model) {
			return;
		}

		const languageId = model.getLanguageId();
		if (languageId !== 'python' && languageId !== 'py') {
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

		// Remove all view zones
		this.editor.changeViewZones((accessor) => {
			for (const viewZoneId of this.viewZones.values()) {
				accessor.removeZone(viewZoneId);
			}
		});
		this.viewZones.clear();
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
				return Math.max(Math.ceil(maxHeight) + 4, lineHeight);
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
		// Anchor to the cursor line if visible, otherwise the line just above the viewport midpoint.
		const scrollTop = this.editor.getScrollTop();
		const shouldStabilizeScroll = scrollTop > 0 && !this.editor.hasPendingScrollAnimation();
		let anchorLineNumber = 0;
		let anchorDelta = 0;

		if (shouldStabilizeScroll) {
			const visibleRanges = this.editor.getVisibleRanges();
			if (visibleRanges.length > 0) {
				const cursorPos = this.editor.getPosition();
				const firstVisibleLine = visibleRanges[0].startLineNumber;
				const lastVisibleLine = visibleRanges[visibleRanges.length - 1].endLineNumber;

				if (cursorPos && cursorPos.lineNumber >= firstVisibleLine && cursorPos.lineNumber <= lastVisibleLine) {
					anchorLineNumber = cursorPos.lineNumber;
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
			const anchorTopAfter = this.editor.getTopForLineNumber(anchorLineNumber);
			this.editor.setScrollTop(anchorTopAfter + anchorDelta, ScrollType.Immediate);
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

			model.pushEditOperations([], editOperations, () => null);
		} else if (command.type === 'ChangeSelectedText') {
			this.handleChangeSelectedText(command.text);
		} else if (command.type === 'CopyToClipboard') {
			this.clipboardService.writeText(command.text);
		}
	}

	private handleChangeSelectedText(newText: string): void {
		const editorModel = this.editor.getModel();
		if (!editorModel || !this.linkedSelectionDecorationId) {
			return;
		}
		const trackedRange = editorModel.getDecorationRange(this.linkedSelectionDecorationId);
		if (!trackedRange) {
			return;
		}

		const currentText = editorModel.getValueInRange(trackedRange);
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
			[this.linkedSelectionDecorationId],
			[{
				range: newRange,
				options: {
					description: 'snc-linked-selection',
					stickiness: TrackedRangeStickiness.NeverGrowsWhenTypingAtEdges,
				},
			}]
		);
		this.linkedSelectionDecorationId = ids[0] ?? null;

		// Keep the text selected so the user can see what's linked
		this.editor.setSelection(newRange);

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
			const options: IProcessOptions = {
				modelsAndEventsJson: JSON.stringify(models_and_events),
				timeout: 60_000,
				workingDirectory
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
