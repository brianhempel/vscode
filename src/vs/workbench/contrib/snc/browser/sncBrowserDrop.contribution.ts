/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { CancellationToken } from '../../../../base/common/cancellation.js';
import { createStringDataTransferItem, IReadonlyVSDataTransfer, UriList, VSDataTransfer } from '../../../../base/common/dataTransfer.js';
import { Disposable } from '../../../../base/common/lifecycle.js';
import { Mimes } from '../../../../base/common/mime.js';
import { Schemas } from '../../../../base/common/network.js';
import { URI } from '../../../../base/common/uri.js';
import { BrowserViewUri } from '../../../../platform/browserView/common/browserViewUri.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { IWorkspaceContextService } from '../../../../platform/workspace/common/workspace.js';
import { IPosition } from '../../../../editor/common/core/position.js';
import { DocumentDropEditProvider, DocumentDropEditsSession } from '../../../../editor/common/languages.js';
import { ITextModel } from '../../../../editor/common/model.js';
import { ILanguageFeaturesService } from '../../../../editor/common/services/languageFeatures.js';
import { pythonReadDropEditKind, PythonReadDropProvider } from '../../../../editor/contrib/dropOrPasteInto/browser/pythonDropProvider.js';
import { registerWorkbenchContribution2, WorkbenchPhase } from '../../../common/contributions.js';
import { IBrowserViewWorkbenchService } from '../../browserView/common/browserView.js';

/**
 * Drops an integrated browser tab into Python as a line that reads the page the
 * tab is pointed at.
 *
 * The drag only carries the tab's `vscode-browser:/<id>` resource, and the URL
 * behind that id is only known here in the workbench, so this resolves the id
 * and then hands a plain URL to the editor-layer provider that generates the
 * code.
 */
class PythonBrowserReadDropProvider implements DocumentDropEditProvider {

	private readonly _readProvider: PythonReadDropProvider;

	readonly kind = pythonReadDropEditKind;
	readonly providedDropEditKinds = [this.kind];
	readonly dropMimeTypes = [Mimes.uriList];

	constructor(
		@IBrowserViewWorkbenchService private readonly _browserViewService: IBrowserViewWorkbenchService,
		@IWorkspaceContextService workspaceContextService: IWorkspaceContextService,
	) {
		this._readProvider = new PythonReadDropProvider(workspaceContextService);
	}

	async provideDocumentDropEdits(model: ITextModel, position: IPosition, dataTransfer: IReadonlyVSDataTransfer, token: CancellationToken): Promise<DocumentDropEditsSession | undefined> {
		const urlListEntry = dataTransfer.get(Mimes.uriList);
		if (!urlListEntry) {
			return;
		}

		const strUriList = await urlListEntry.asString();
		if (token.isCancellationRequested) {
			return;
		}

		const urls: string[] = [];
		for (const entry of UriList.parse(strUriList)) {
			try {
				const resource = URI.parse(entry);
				if (resource.scheme !== Schemas.vscodeBrowser) {
					continue;
				}
				const url = this.urlOf(resource);
				if (url) {
					urls.push(url);
				}
			} catch {
				// noop
			}
		}

		if (!urls.length) {
			return;
		}

		const resolved = new VSDataTransfer();
		resolved.append(Mimes.uriList, createStringDataTransferItem(UriList.create(urls)));
		return this._readProvider.provideDocumentDropEdits(model, position, resolved, token);
	}

	private urlOf(resource: URI): string | undefined {
		const id = BrowserViewUri.getId(resource);
		const url = id ? this._browserViewService.getKnownBrowserViews().get(id)?.url : undefined;
		if (!url) {
			return undefined;
		}
		// A blank or internal page has nothing to read.
		const scheme = url.slice(0, url.indexOf(':')).toLowerCase();
		return scheme === Schemas.http || scheme === Schemas.https ? url : undefined;
	}
}

class SNCBrowserDropContribution extends Disposable {

	static readonly ID = 'workbench.contrib.sncBrowserDrop';

	constructor(
		@ILanguageFeaturesService languageFeaturesService: ILanguageFeaturesService,
		@IInstantiationService instantiationService: IInstantiationService,
	) {
		super();
		this._register(languageFeaturesService.documentDropEditProvider.register(
			{ language: 'python' },
			instantiationService.createInstance(PythonBrowserReadDropProvider)));
	}
}

registerWorkbenchContribution2(SNCBrowserDropContribution.ID, SNCBrowserDropContribution, WorkbenchPhase.AfterRestored);
