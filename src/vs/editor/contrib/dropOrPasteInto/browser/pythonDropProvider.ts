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
import { studyLog } from '../../../../platform/snc/common/sncStudyLog.js';

const urllibImport = 'import urllib.request';
const csvImport = 'import csv';
const jsonImport = 'import json';
const pandasImport = 'import pandas as pd';

/** Kind of the "read this into a string" drop edit, shared with its callers. */
export const pythonReadDropEditKind = HierarchicalKind.Empty.append('uri', 'python', 'openRead');

/** Kind of the "drop an expression dragged out of a visualizer" edit. */
export const sncPyExpDropEditKind = HierarchicalKind.Empty.append('text', 'python', 'sncPyExp');

/**
 * A file to read from disk, or a URL to read over the network. A spreadsheet is
 * worth reading as the table it is rather than as its bytes, and JSON as the
 * value it encodes, so the structured formats get their own reads; everything
 * else is text.
 */
type ReadSource =
	| { readonly type: 'text'; readonly path: string }
	| { readonly type: 'csv'; readonly path: string }
	| { readonly type: 'json'; readonly path: string }
	| { readonly type: 'excel'; readonly path: string }
	| { readonly type: 'url'; readonly url: string };

/** Everything about a source that depends on which kind of read it gets. */
const readKinds = {
	text: { variablePrefix: 'str', importStatement: undefined, phrase: 'open().read()' },
	csv: { variablePrefix: 'rows', importStatement: csvImport, phrase: 'csv.reader()' },
	json: { variablePrefix: 'data', importStatement: jsonImport, phrase: 'json.load()' },
	excel: { variablePrefix: 'sheets', importStatement: pandasImport, phrase: 'read_excel()' },
	url: { variablePrefix: 'str', importStatement: urllibImport, phrase: 'urlopen().read()' },
} as const satisfies Record<ReadSource['type'], { variablePrefix: string; importStatement: string | undefined; phrase: string }>;

const excelExtensions = ['.xlsx', '.xlsm', '.xlsb', '.xls'];

/** Which read a dropped file's name asks for. */
function fileReadType(path: string): 'text' | 'csv' | 'json' | 'excel' {
	const lower = path.toLowerCase();
	if (excelExtensions.some(extension => lower.endsWith(extension))) {
		return 'excel';
	}
	if (lower.endsWith('.csv')) {
		return 'csv';
	}
	return lower.endsWith('.json') ? 'json' : 'text';
}

function pythonStringLiteral(value: string): string {
	return `"${value.replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`;
}

/** The expression that reads a source, as the value of the dropped assignment. */
function readExpression(source: ReadSource): string {
	switch (source.type) {
		case 'text':
			return `open(${pythonStringLiteral(source.path)}).read()`;
		case 'csv':
			return `list(csv.reader(open(${pythonStringLiteral(source.path)}, newline='')))`;
		case 'json':
			return `json.load(open(${pythonStringLiteral(source.path)}))`;
		case 'excel': {
			// Every sheet, because which one holds the data isn't ours to guess.
			const path = pythonStringLiteral(source.path);
			return `{sheet_name: pd.read_excel(${path}, sheet_name=sheet_name).to_dict('records') for sheet_name in pd.ExcelFile(${path}).sheet_names}`;
		}
		case 'url':
			return `urllib.request.urlopen(${pythonStringLiteral(source.url)}).read().decode()`;
	}
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
 * The placements for everything a drop needs imported, ready to go into one edit.
 *
 * Several imports stacking at the same anchor is fine: they all ride in the same
 * edit, so they land in the order they were declared rather than racing.
 */
function importPlacements(model: ITextModel, importStatements: readonly string[], position: IPosition): { readonly inlineText: string; readonly separateEdits: { range: Range; text: string }[] } {
	const inline: string[] = [];
	const separateEdits: { range: Range; text: string }[] = [];
	for (const importStatement of new Set(importStatements)) {
		const placement = importPlacement(model, importStatement, position);
		if (placement?.kind === 'inline') {
			// Only the first inline import needs the break off the drop position.
			inline.push(inline.length ? placement.text.replace(/^\n/, '') : placement.text);
		} else if (placement?.kind === 'separateEdit') {
			separateEdits.push(placement);
		}
	}
	return { inlineText: inline.join(''), separateEdits };
}

/**
 * The edit that leaves the file ending in a blank line once a drop at
 * `position` has landed -- or nothing, when the file will end blank anyway.
 *
 * A visualizer takes so much of the screen that when its line is the last
 * one, there is nowhere below it to click and press return for the next
 * line. An empty line closing the file is always there to click on.
 *
 * A drop on the last line fills it; anywhere else leaves it as it is. Dropped
 * at the very end of the file, the insert and this edit share a position,
 * and apply in the order given: the insert, then this, as the last of the
 * additional edits.
 */
function trailingBlankLineEdit(model: ITextModel, position: IPosition): { range: Range; text: string } | undefined {
	const lastLine = model.getLineCount();
	if (position.lineNumber < lastLine && /^\s*$/.test(model.getLineContent(lastLine))) {
		return undefined;
	}
	const col = model.getLineMaxColumn(lastLine);
	return { range: new Range(lastLine, col, lastLine, col), text: '\n' };
}

/**
 * Drops a file or a URL into Python as a line that reads it.
 *
 * A `.csv` comes in as its rows, a `.json` as its parsed value, and a
 * spreadsheet as its sheets, since that is what the file is; anything else is
 * read as text. URLs are read with
 * `urllib.request`; the runner caches the response by URL so a rerun on every
 * keystroke doesn't refetch. See `url_cache.py`.
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
					sources.push({ type: fileReadType(uri.path), path: relPath ?? uri.fsPath });
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

		// Each kind of read names its variables after what it produces, so the
		// numbering runs per prefix rather than across the whole drop.
		const text = model.getValue();
		const usedNumbers = new Map<string, Set<number>>();
		const takeNumber = (prefix: string): number => {
			let used = usedNumbers.get(prefix);
			if (!used) {
				used = new Set<number>();
				const re = new RegExp(`\\b${prefix}(\\d+)\\b`, 'g');
				let match;
				while ((match = re.exec(text)) !== null) {
					used.add(parseInt(match[1], 10));
				}
				usedNumbers.set(prefix, used);
			}
			let n = 1;
			while (used.has(n)) {
				n++;
			}
			used.add(n);
			return n;
		};

		const lines: string[] = [];
		const imports: string[] = [];
		for (const source of sources) {
			const { variablePrefix, importStatement } = readKinds[source.type];
			lines.push(`${variablePrefix}${takeNumber(variablePrefix)} = ${readExpression(source)}`);
			if (importStatement) {
				imports.push(importStatement);
			}
		}

		const { inlineText, separateEdits } = importPlacements(model, imports, position);
		const blankLineEdit = trailingBlankLineEdit(model, position);
		if (blankLineEdit) {
			separateEdits.push(blankLineEdit);
		}

		studyLog.log('editor.fileDrop', { sources, lines, imports, position: [position.lineNumber, position.column] }, model.uri.toString());

		return {
			edits: [{
				insertText: inlineText + lines.join('\n'),
				title: this.title(sources),
				kind: this.kind,
				handledMimeType: Mimes.uriList,
				additionalEdit: separateEdits.length
					? { edits: separateEdits.map(edit => ({ resource: model.uri, versionId: undefined, textEdit: edit })) }
					: undefined,
			}],
			dispose() { },
		};
	}

	private title(sources: readonly ReadSource[]): string {
		const types = new Set(sources.map(source => source.type));
		const suffix = sources.length > 1 ? ' calls' : '';
		// Mixed kinds have no one call to name.
		const phrase = types.size === 1 ? readKinds[sources[0].type].phrase : 'read';
		return `Insert as Python ${phrase}${suffix}`;
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
		studyLog.log('editor.pyExpDrop', { expr, imports: payload.imports, position: [position.lineNumber, position.column] }, model.uri.toString());

		// Every import that isn't there yet, in declaration order.
		const { inlineText, separateEdits } = importPlacements(model, payload.imports ?? [], position);
		const blankLineEdit = trailingBlankLineEdit(model, position);
		if (blankLineEdit) {
			separateEdits.push(blankLineEdit);
		}

		return {
			edits: [{
				insertText: inlineText + expr,
				title: 'Insert Python expression',
				kind: this.kind,
				handledMimeType: SNC_PY_EXP_MIME,
				additionalEdit: separateEdits.length
					? { edits: separateEdits.map(edit => ({ resource: model.uri, versionId: undefined, textEdit: edit })) }
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
