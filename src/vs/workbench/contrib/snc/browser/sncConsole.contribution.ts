/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Codicon } from '../../../../base/common/codicons.js';
import { KeyCode, KeyMod } from '../../../../base/common/keyCodes.js';
import { Disposable } from '../../../../base/common/lifecycle.js';
import { localize, localize2 } from '../../../../nls.js';
import { Action2, MenuId, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { ContextKeyExpr } from '../../../../platform/contextkey/common/contextkey.js';
import { SyncDescriptor } from '../../../../platform/instantiation/common/descriptors.js';
import { ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { KeybindingWeight } from '../../../../platform/keybinding/common/keybindingsRegistry.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { ViewPaneContainer } from '../../../browser/parts/views/viewPaneContainer.js';
import { registerWorkbenchContribution2, WorkbenchPhase } from '../../../common/contributions.js';
import { Extensions as ViewContainerExtensions, IViewContainersRegistry, IViewsRegistry, ViewContainer, ViewContainerLocation } from '../../../common/views.js';
import { IViewsService } from '../../../services/views/common/viewsService.js';
import { ISNCConsoleService } from '../common/sncConsole.js';
import './sncConsoleService.js';
import { CONTEXT_IN_SNC_CONSOLE, SNCConsoleViewPane, SNC_CONSOLE_TITLE, SNC_CONSOLE_VIEW_ID, sncConsoleViewIcon } from './sncConsoleView.js';

/**
 * The console lives in the panel rather than in an editor tab so that it can sit
 * beside the code: `workbench.action.positionPanelLeft/Right` moves the whole
 * panel to a side, and dragging the view into the Secondary Side Bar puts it
 * next to the source. VS Code remembers whichever the user picks.
 */
const VIEW_CONTAINER: ViewContainer = Registry.as<IViewContainersRegistry>(ViewContainerExtensions.ViewContainersRegistry).registerViewContainer({
	id: SNC_CONSOLE_VIEW_ID,
	title: SNC_CONSOLE_TITLE,
	icon: sncConsoleViewIcon,
	order: 2,
	ctorDescriptor: new SyncDescriptor(ViewPaneContainer, [SNC_CONSOLE_VIEW_ID, { mergeViewWithContainerWhenSingleView: true }]),
	storageId: SNC_CONSOLE_VIEW_ID,
	hideIfEmpty: true,
}, ViewContainerLocation.Panel, { doNotRegisterOpenCommand: true });

Registry.as<IViewsRegistry>(ViewContainerExtensions.ViewsRegistry).registerViews([{
	id: SNC_CONSOLE_VIEW_ID,
	name: SNC_CONSOLE_TITLE,
	containerIcon: sncConsoleViewIcon,
	canMoveView: true,
	canToggleVisibility: true,
	ctorDescriptor: new SyncDescriptor(SNCConsoleViewPane),
	openCommandActionDescriptor: {
		id: 'workbench.action.snc.toggleConsole',
		mnemonicTitle: localize({ key: 'miToggleSNCConsole', comment: ['&& denotes a mnemonic'] }, "&&Console"),
		order: 2,
	},
}], VIEW_CONTAINER);

/**
 * Opens the console the first time a file's program prints or asks for input,
 * so the user doesn't have to know the view exists. Latched per file by the
 * service, so a program parked on `input()` can't reopen it every rerun.
 */
class SNCConsoleAutoOpenContribution extends Disposable {

	static readonly ID = 'workbench.contrib.sncConsoleAutoOpen';

	constructor(
		@ISNCConsoleService consoleService: ISNCConsoleService,
		@IViewsService private readonly viewsService: IViewsService,
	) {
		super();
		this._register(consoleService.onDidRequestOpen(({ focus }) => {
			// Focus only when the program is actually waiting to be typed at;
			// plain output must not pull the caret out of the source editor.
			this.viewsService.openView(SNC_CONSOLE_VIEW_ID, focus);
		}));
	}
}

registerWorkbenchContribution2(SNCConsoleAutoOpenContribution.ID, SNCConsoleAutoOpenContribution, WorkbenchPhase.AfterRestored);

function consoleView(accessor: ServicesAccessor): SNCConsoleViewPane | undefined {
	const view = accessor.get(IViewsService).getActiveViewWithId(SNC_CONSOLE_VIEW_ID);
	return view instanceof SNCConsoleViewPane ? view : undefined;
}

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'workbench.action.snc.console.insertEof',
			title: localize2('sncConsoleInsertEof', "End Input Stream"),
			icon: Codicon.debugStop,
			f1: false,
			keybinding: {
				// Ctrl-D is muscle memory for end-of-input at a terminal, but in
				// an editor it is Add Selection To Next Find Match. Scoped to
				// this editor so the default keeps working everywhere else.
				when: CONTEXT_IN_SNC_CONSOLE,
				primary: KeyMod.CtrlCmd | KeyCode.KeyD,
				weight: KeybindingWeight.WorkbenchContrib + 1,
			},
			menu: [{
				id: MenuId.ViewTitle,
				when: ContextKeyExpr.equals('view', SNC_CONSOLE_VIEW_ID),
				group: 'navigation',
				order: 1,
			}],
		});
	}
	run(accessor: ServicesAccessor): void {
		consoleView(accessor)?.insertEofMarker();
	}
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'workbench.action.snc.console.clear',
			title: localize2('sncConsoleClear', "Clear Console Input"),
			icon: Codicon.clearAll,
			f1: false,
			menu: [{
				id: MenuId.ViewTitle,
				when: ContextKeyExpr.equals('view', SNC_CONSOLE_VIEW_ID),
				group: 'navigation',
				order: 2,
			}],
		});
	}
	run(accessor: ServicesAccessor): void {
		consoleView(accessor)?.clearSession();
	}
});
