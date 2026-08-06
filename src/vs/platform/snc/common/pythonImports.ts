/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

/**
 * Where an auto-added Python import goes, for every way SNC writes one in.
 *
 * A visualizer says what its code needs to run — on a NewCode command, or in
 * `snc-py-exp-imports` on whatever the user is dragging. Deciding whether the
 * file already has that import, and where a missing one would land, is the
 * editor's alone: it is the only side that knows the file as it stands now, so
 * this is the one place that answers it.
 */

/** Where a missing import goes; undefined when the file already has it. */
export interface IPythonImportInsertion {
	/** 1-indexed line to insert after; 0 means before the first line. */
	readonly afterLine: number;
	/** The anchor is past the last line, so the import appends rather than inserts. */
	readonly atEndOfFile: boolean;
	/** The line below the anchor is code, so a blank line has to separate them. */
	readonly needsSeparator: boolean;
}

/**
 * Last line of a string literal opening at `start`, or undefined if that line is
 * something other than a string literal.
 */
function stringLiteralEnd(lines: readonly string[], start: number): number | undefined {
	// Drop any of the prefixes Python allows on a literal, e.g. r"""...""".
	const text = lines[start].trim().replace(/^[a-zA-Z]{1,2}(?=['"])/, '');
	const triple = text.startsWith('"""') ? '"""' : text.startsWith('\'\'\'') ? '\'\'\'' : undefined;
	if (!triple) {
		// A one-line 'doc' counts; an expression like 'a' + 'b' does not.
		return /^(['"])(?:[^'"\\]|\\.)*\1$/.test(text) ? start : undefined;
	}
	if (text.length > triple.length && text.endsWith(triple)) {
		return start;
	}
	for (let i = start + 1; i < lines.length; i++) {
		if (lines[i].includes(triple)) {
			return i;
		}
	}
	return undefined;
}

/**
 * Where to put an auto-added import: after the file's prologue — a module docstring
 * and any leading imports — followed by a blank line. Landing above a docstring would
 * push it into the body, where the runner treats it as an expression to visualize.
 *
 * Returns undefined when the file already has the import, which is the same answer
 * as "nothing to do".
 */
export function pythonImportInsertion(lines: readonly string[], importStatement: string): IPythonImportInsertion | undefined {
	if (lines.some(line => line.trim() === importStatement)) {
		return undefined;
	}

	let insertAfter = 0; // 1-indexed line to insert after; 0 means before line 1
	for (let i = 0; i < lines.length;) {
		const trimmed = lines[i].trim();
		if (!trimmed || trimmed.startsWith('#')) {
			i++;
			continue;
		}
		if (trimmed.startsWith('import ') || trimmed.startsWith('from ')) {
			insertAfter = i + 1;
			i++;
			continue;
		}
		// Only a string literal ahead of every import can be the module docstring.
		const docstringEnd = insertAfter === 0 ? stringLiteralEnd(lines, i) : undefined;
		if (docstringEnd === undefined) {
			break;
		}
		insertAfter = docstringEnd + 1;
		i = docstringEnd + 1;
	}

	const atEndOfFile = insertAfter >= lines.length;
	return {
		afterLine: insertAfter,
		atEndOfFile,
		// Separate the import block from the code below it, unless something already does.
		needsSeparator: !atEndOfFile && lines[insertAfter].trim() !== '',
	};
}
