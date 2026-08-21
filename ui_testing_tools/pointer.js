// Mouse targeting, shared by dwell.js, click.js and clicks.js.

import { send, sleep, measure, waitFor, waitForPython } from './cdp.js';

// How long to let the pointer rest before pressing. Much of the table's
// furniture is `.snc-hover-hidden`, which is `visibility: hidden` until an
// ancestor is hovered, and a hidden element is not a hit target: a bare press
// falls straight through it and lands on whatever is behind. So the pointer is
// moved there first and the style given a moment to recalculate, which is what
// a real click does anyway. Kept under snc.ts's DWELL_MS (150) on purpose: a
// style recalc is wanted, a submenu opening under the press is not.
export const HOVER_SETTLE_MS = 80;

const COORDS = /^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$/;

// `500,300` is a place on screen; anything else is a selector.
export function parseTarget(arg) {
	const coords = COORDS.exec(arg);
	if (coords) {
		return { x: Number(coords[1]), y: Number(coords[2]), label: arg };
	}
	return { selector: arg, label: `"${arg}"` };
}

async function moveTo(ws, x, y) {
	await send(ws, 'Input.dispatchMouseEvent', { type: 'mouseMoved', x, y, buttons: 0 });
}

// A pointer already on the target has not *moved* onto it, and the dwell menus
// only re-arm when the element under the pointer changes (snc.ts arms on
// `mouseover` and returns early when the dwell ancestor is the one it is
// already waiting on). Since the pointer is left where it was put, being
// already on the target is the normal case after any click -- so the target is
// always entered from just outside it, which is the one thing a real mouse
// never fails to do. A step of two pixels past the top edge: near enough that
// nothing far away is crossed, and whatever it does cross is left again in the
// same tick, before any dwell of its own could arm.
export async function hoverAt(ws, x, y, rect) {
	const above = rect ? y - rect.h / 2 - 2 : y - 4;
	await moveTo(ws, x, above > 0 ? above : y + (rect ? rect.h / 2 : 0) + 2);
	await moveTo(ws, x, y);
	await sleep(HOVER_SETTLE_MS);
}

export async function pressAt(ws, x, y) {
	await send(ws, 'Input.dispatchMouseEvent', {
		type: 'mousePressed', x, y, button: 'left', buttons: 1, clickCount: 1,
	});
	await send(ws, 'Input.dispatchMouseEvent', {
		type: 'mouseReleased', x, y, button: 'left', buttons: 0, clickCount: 1,
	});
}

// The pointer is left where it was put rather than moved away, so a menu that
// stays open only while hovered is still open to read afterwards.
//
// Resolving a selector waits for Python first. A selector is a question about
// what is on screen, and the answer is only worth having once the render that
// the last event kicked off has landed -- otherwise the element found is the
// one from the previous frame, in the place it used to be. Coordinates are not
// a question, so they are aimed at as given.
export async function hoverTarget(ws, target, { timeout = 10000 } = {}) {
	if (target.selector === undefined) {
		await hoverAt(ws, target.x, target.y);
		return { x: target.x, y: target.y, where: `(${target.x}, ${target.y})` };
	}
	await waitForPython(ws, timeout);
	const rect = await waitFor(ws, target.selector, { timeout });
	await hoverAt(ws, rect.x, rect.y, rect);
	// Measured again: revealing what the hover reveals can move the thing being
	// aimed at, and a press at the old spot would miss it. Against the same
	// selector, so an element that went away under the pointer is reported
	// rather than acted on blindly.
	const settled = await measure(ws, target.selector) || rect;
	if (settled.x !== rect.x || settled.y !== rect.y) {
		await hoverAt(ws, settled.x, settled.y, settled);
	}
	return { x: settled.x, y: settled.y, where: `(${settled.x}, ${settled.y}) [${settled.w}x${settled.h}]` };
}

// Every click is a full Python re-render, so the click is not over until that
// render is on screen. Waiting here rather than in the callers is what lets
// click.js and clicks.js be read as "this happened" rather than "this was
// sent".
export async function clickTarget(ws, target, options) {
	const at = await hoverTarget(ws, target, options);
	await pressAt(ws, at.x, at.y);
	await waitForPython(ws, options?.timeout ?? 10000);
	return at;
}
