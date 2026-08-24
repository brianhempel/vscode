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
import { pythonImportInsertion } from '../../../../platform/snc/common/pythonImports.js';
import { SNC_PY_EXP_MIME } from '../../../../platform/snc/common/snc.js';
import { IWorkspaceContextService } from '../../../../platform/workspace/common/workspace.js';
import { IPosition, Position } from '../../../common/core/position.js';
import { Range } from '../../../common/core/range.js';
import { DocumentDropEditProvider, DocumentDropEditsSession } from '../../../common/languages.js';
import { ITextModel } from '../../../common/model.js';
import { ILanguageFeaturesService } from '../../../common/services/languageFeatures.js';

const urllibImport = 'import urllib.request';

/** Kind of the "read this into a string" drop edit, shared with its callers. */
export const pythonReadDropEditKind = HierarchicalKind.Empty.append('uri', 'python', 'openRead');

/** Kind of the "drop an expression dragged out of a visualizer" edit. */
export const sncPyExpDropEditKind = HierarchicalKind.Empty.append('text', 'python', 'sncPyExp');

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
 * Where an auto-added import goes relative to what is being dropped. The anchor
 * itself comes from pythonImportInsertion, which is the one place that reads the
 * file's prologue; only the choice between riding along and standing apart is
 * this provider's, since only it has a drop position.
 */
function importPlacement(model: ITextModel, importStatement: string, position: IPosition): ImportPlacement | undefined {
	const insertion = pythonImportInsertion(model.getLinesContent(), importStatement);
	if (!insertion) {
		return undefined;
	}

	const lineCount = model.getLineCount();
	const range = insertion.atEndOfFile
		? new Range(lineCount, model.getLineMaxColumn(lineCount), lineCount, model.getLineMaxColumn(lineCount))
		: new Range(insertion.afterLine + 1, 1, insertion.afterLine + 1, 1);

	// The import rides along with the dropped text unless it belongs strictly
	// above it. Landing on the same position, two insertions would apply in an
	// arbitrary order; landing below, a separate edit would put the import after
	// the line that uses it. The dropped line is then what follows the import,
	// hence the blank line.
	if (!Position.isBefore(range.getStartPosition(), position)) {
		const lead = position.column > 1 ? '\n' : '';
		return { kind: 'inline', text: `${lead}${importStatement}\n\n` };
	}

	const separator = insertion.needsSeparator ? '\n' : '';
	const lead = insertion.atEndOfFile ? '\n' : '';
	return { kind: 'separateEdit', range, text: `${lead}${importStatement}\n${separator}` };
}

/**
 * Drops a file or a URL into Python as a line that reads it into a string.
 *
 * URLs are read with `urllib.request`; the runner caches the response so a
 * rerun on every keystroke doesn't refetch. See `url_cache.py`.
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

/**
 * Drops an expression dragged out of an SNC visualizer, bringing whatever it
 * needs imported along with it.
 *
 * The visualizer that rendered the handle declares those imports (see
 * `py_exp_attrs` in visualizer_utils.py); the drag carries them beside the
 * expression on SNC's own mime type, and this is where they meet the file.
 * `text/plain` still carries the expression alone, so dropping into a terminal,
 * another editor, or a search box works as it always has.
 */
export class SncPyExpDropProvider implements DocumentDropEditProvider {

	readonly kind = sncPyExpDropEditKind;
	readonly providedDropEditKinds = [this.kind];
	readonly dropMimeTypes = [SNC_PY_EXP_MIME];

	async provideDocumentDropEdits(model: ITextModel, position: IPosition, dataTransfer: IReadonlyVSDataTransfer, token: CancellationToken): Promise<DocumentDropEditsSession | undefined> {
		const entry = dataTransfer.get(SNC_PY_EXP_MIME);
		if (!entry) {
			return;
		}

		const raw = await entry.asString();
		if (token.isCancellationRequested) {
			return;
		}

		let payload: { expr?: string; imports?: string[] };
		try {
			payload = JSON.parse(raw);
		} catch {
			return;
		}
		const expr = payload.expr;
		if (!expr) {
			return;
		}

		// Every import that isn't there yet, in declaration order. Two of them
		// stacking at the same anchor is fine: each rides in the same edit, so
		// they land in the order they were declared rather than racing.
		const inline: string[] = [];
		const separate: { range: Range; text: string }[] = [];
		for (const importStatement of payload.imports ?? []) {
			const placement = importPlacement(model, importStatement, position);
			if (placement?.kind === 'inline') {
				inline.push(placement.text);
			} else if (placement?.kind === 'separateEdit') {
				separate.push({ range: placement.range, text: placement.text });
			}
		}

		return {
			edits: [{
				insertText: inline.join('') + expr,
				title: 'Insert Python expression',
				kind: this.kind,
				handledMimeType: SNC_PY_EXP_MIME,
				additionalEdit: separate.length
					? { edits: separate.map(edit => ({ resource: model.uri, versionId: undefined, textEdit: edit })) }
					: undefined,
			}],
			dispose() { },
		};
	}
}

export class PythonDropProvidersFeature extends Disposable {
	constructor(
		@ILanguageFeaturesService languageFeaturesService: ILanguageFeaturesService,
		@IWorkspaceContextService workspaceContextService: IWorkspaceContextService,
	) {
		super();
		this._register(languageFeaturesService.documentDropEditProvider.register({ language: 'python' }, new PythonReadDropProvider(workspaceContextService)));
		this._register(languageFeaturesService.documentDropEditProvider.register({ language: 'python' }, new SncPyExpDropProvider()));
	}
}
