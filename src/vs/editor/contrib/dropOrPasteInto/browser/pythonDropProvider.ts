/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { CancellationToken } from '../../../../base/common/cancellation.js';
import { IReadonlyVSDataTransfer, UriList } from '../../../../base/common/dataTransfer.js';
import { HierarchicalKind } from '../../../../base/common/hierarchicalKind.js';
import { Disposable } from '../../../../base/common/lifecycle.js';
import { Mimes } from '../../../../base/common/mime.js';
import { Schemas } from '../../../../base/common/network.js';
import { relativePath } from '../../../../base/common/resources.js';
import { URI } from '../../../../base/common/uri.js';
import { IWorkspaceContextService } from '../../../../platform/workspace/common/workspace.js';
import { IPosition, Position } from '../../../common/core/position.js';
import { Range } from '../../../common/core/range.js';
import { DocumentDropEditProvider, DocumentDropEditsSession } from '../../../common/languages.js';
import { ITextModel } from '../../../common/model.js';
import { ILanguageFeaturesService } from '../../../common/services/languageFeatures.js';

const urllibImport = 'import urllib.request';

/** Kind of the "read this into a string" drop edit, shared with its callers. */
export const pythonReadDropEditKind = HierarchicalKind.Empty.append('uri', 'python', 'openRead');

/** A file to read from disk, or a URL to read over the network. */
type ReadSource =
	| { readonly type: 'file'; readonly path: string }
	| { readonly type: 'url'; readonly url: string };

function pythonStringLiteral(value: string): string {
	return `"${value.replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`;
}

/**
 * An auto-added import either becomes an edit of its own above the drop, or, when
 * it belongs exactly where we're dropping, part of the dropped text.
 */
type ImportPlacement =
	| { readonly kind: 'separateEdit'; readonly range: Range; readonly text: string }
	| { readonly kind: 'inline'; readonly text: string };

/**
 * Last line of a string literal opening at `start`, or undefined if that line is
 * something other than a string literal.
 */
function stringLiteralEnd(lines: string[], start: number): number | undefined {
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
 * and any leading imports — followed by a blank line, the way the Python backend
 * places the imports its visualizers need. Landing above a docstring would push it
 * into the body, where the runner treats it as an expression to visualize.
 */
function importPlacement(model: ITextModel, importStatement: string, position: IPosition): ImportPlacement | undefined {
	const lines = model.getLinesContent();
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

	const lineCount = model.getLineCount();
	const atEndOfFile = insertAfter >= lineCount;
	const range = atEndOfFile
		? new Range(lineCount, model.getLineMaxColumn(lineCount), lineCount, model.getLineMaxColumn(lineCount))
		: new Range(insertAfter + 1, 1, insertAfter + 1, 1);

	// The import rides along with the dropped text unless it belongs strictly
	// above it. Landing on the same position, two insertions would apply in an
	// arbitrary order; landing below, a separate edit would put the import after
	// the line that uses it. The dropped line is then what follows the import,
	// hence the blank line.
	if (!Position.isBefore(range.getStartPosition(), position)) {
		const lead = position.column > 1 ? '\n' : '';
		return { kind: 'inline', text: `${lead}${importStatement}\n\n` };
	}

	// Separate the import block from the code below it, unless something already does.
	const separator = !atEndOfFile && lines[insertAfter].trim() !== '' ? '\n' : '';
	const lead = atEndOfFile ? '\n' : '';
	return { kind: 'separateEdit', range, text: `${lead}${importStatement}\n${separator}` };
}

/**
 * Drops a file or a URL into Python as a line that reads it into a string.
 *
 * URLs are read with `urllib.request`; the runner caches the response so a
 * rerun on every keystroke doesn't refetch. See `io_cache.py`.
 */
export class PythonReadDropProvider implements DocumentDropEditProvider {

	readonly kind = pythonReadDropEditKind;
	readonly providedDropEditKinds = [this.kind];
	readonly dropMimeTypes = [Mimes.uriList];

	constructor(
		private readonly _workspaceContextService: IWorkspaceContextService,
	) { }

	async provideDocumentDropEdits(model: ITextModel, position: IPosition, dataTransfer: IReadonlyVSDataTransfer, token: CancellationToken): Promise<DocumentDropEditsSession | undefined> {
		const urlListEntry = dataTransfer.get(Mimes.uriList);
		if (!urlListEntry) {
			return;
		}

		const strUriList = await urlListEntry.asString();
		if (token.isCancellationRequested) {
			return;
		}

		const sources: ReadSource[] = [];
		for (const entry of UriList.parse(strUriList)) {
			try {
				const uri = URI.parse(entry);
				if (uri.scheme === Schemas.file) {
					const root = this._workspaceContextService.getWorkspaceFolder(uri);
					const relPath = root ? relativePath(root.uri, uri) : undefined;
					sources.push({ type: 'file', path: relPath ?? uri.fsPath });
				} else if (uri.scheme === Schemas.http || uri.scheme === Schemas.https) {
					// Keep the text as dragged; re-serializing a URI can re-encode it.
					sources.push({ type: 'url', url: entry.trim() });
				}
			} catch {
				// noop
			}
		}

		if (!sources.length) {
			return;
		}

		const text = model.getValue();
		const usedNumbers = new Set<number>();
		const re = /\bstr(\d+)\b/g;
		let match;
		while ((match = re.exec(text)) !== null) {
			usedNumbers.add(parseInt(match[1], 10));
		}

		const lines: string[] = [];
		for (const source of sources) {
			let n = 1;
			while (usedNumbers.has(n)) {
				n++;
			}
			usedNumbers.add(n);
			lines.push(source.type === 'file'
				? `str${n} = open(${pythonStringLiteral(source.path)}).read()`
				: `str${n} = urllib.request.urlopen(${pythonStringLiteral(source.url)}).read().decode()`);
		}

		const readsUrl = sources.some(source => source.type === 'url');
		const placement = readsUrl ? importPlacement(model, urllibImport, position) : undefined;

		return {
			edits: [{
				insertText: (placement?.kind === 'inline' ? placement.text : '') + lines.join('\n'),
				title: this.title(sources.length > 1, readsUrl),
				kind: this.kind,
				handledMimeType: Mimes.uriList,
				additionalEdit: placement?.kind === 'separateEdit'
					? { edits: [{ resource: model.uri, versionId: undefined, textEdit: { range: placement.range, text: placement.text } }] }
					: undefined,
			}],
			dispose() { },
		};
	}

	private title(plural: boolean, readsUrl: boolean): string {
		if (readsUrl) {
			return plural ? 'Insert as Python urlopen().read() calls' : 'Insert as Python urlopen().read()';
		}
		return plural ? 'Insert as Python open().read() calls' : 'Insert as Python open().read()';
	}
}

export class PythonDropProvidersFeature extends Disposable {
	constructor(
		@ILanguageFeaturesService languageFeaturesService: ILanguageFeaturesService,
		@IWorkspaceContextService workspaceContextService: IWorkspaceContextService,
	) {
		super();
		this._register(languageFeaturesService.documentDropEditProvider.register({ language: 'python' }, new PythonReadDropProvider(workspaceContextService)));
	}
}
