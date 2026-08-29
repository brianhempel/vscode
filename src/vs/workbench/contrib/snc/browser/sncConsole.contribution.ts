/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { KeyCode, KeyMod } from '../../../../base/common/keyCodes.js';
import { Disposable } from '../../../../base/common/lifecycle.js';
import { localize } from '../../../../nls.js';
import { ICodeEditor } from '../../../../editor/browser/editorBrowser.js';
import { EditorAction, EditorContributionInstantiation, registerEditorAction, registerEditorContribution, ServicesAccessor } from '../../../../editor/browser/editorExtensions.js';
import { KeybindingWeight } from '../../../../platform/keybinding/common/keybindingsRegistry.js';
import { registerWorkbenchContribution2, WorkbenchPhase } from '../../../common/contributions.js';
import { IEditorGroup, IEditorGroupsService } from '../../../services/editor/common/editorGroupsService.js';
import { IEditorService, SIDE_GROUP } from '../../../services/editor/common/editorService.js';
import { ISNCConsoleService } from '../common/sncConsole.js';
import { CONTEXT_IN_SNC_CONSOLE, SNCConsoleEditorContribution } from './sncConsoleEditor.js';
import './sncConsoleService.js';

registerEditorContribution(
	SNCConsoleEditorContribution.ID,
	SNCConsoleEditorContribution,
	// The stdin document is usually opened by the auto-open below, which happens
	// after a run; there is nothing to draw before the editor has rendered once.
	EditorContributionInstantiation.AfterFirstRender
);

/**
 * Opens the stdin document the first time a file's program prints or asks for
 * input, so the user doesn't have to know it exists. It goes into the group
 * beside the source, which is where a console wants to be — and because it is
 * an ordinary editor the user can move it anywhere they'd move any other tab,
 * and the workbench remembers that.
 *
 * Latched per file by the service, so a program parked on `input()` can't
 * reopen it on every rerun.
 */
class SNCConsoleAutoOpenContribution extends Disposable {

	static readonly ID = 'workbench.contrib.sncConsoleAutoOpen';

	/** Widest the console may open as a fraction of the editor area. */
	private static readonly MAX_WIDTH_FRACTION = 1 / 3;

	constructor(
		@ISNCConsoleService private readonly consoleService: ISNCConsoleService,
		@IEditorService private readonly editorService: IEditorService,
		@IEditorGroupsService private readonly editorGroupsService: IEditorGroupsService,
	) {
		super();
		this._register(this.consoleService.onDidRequestOpen(({ filePath, focus }) => this.open(filePath, focus)));
	}

	private async open(filePath: string, focus: boolean): Promise<void> {
		const resource = await this.consoleService.ensureStdinFile(filePath);
		if (this._store.isDisposed) {
			return;
		}
		const groupsBefore = this.editorGroupsService.count;
		// Focus only when the program is actually waiting to be typed at; plain
		// output must not pull the caret out of the source editor.
		const pane = await this.editorService.openEditor(
			{ resource, options: { preserveFocus: !focus, pinned: true } },
			SIDE_GROUP
		);
		if (pane && this.editorGroupsService.count > groupsBefore) {
			this.narrowNewGroup(pane.group);
		}
	}

	/**
	 * A fresh side group is split evenly, which hands half the window to a
	 * console the user didn't ask to see. Take it down to a third — enough
	 * for output, but the code stays the thing on screen. Only ever on the
	 * group this open just created: a group the user already sized is theirs.
	 */
	private narrowNewGroup(group: IEditorGroup): void {
		const available = this.editorGroupsService.getPart(group).contentDimension.width;
		const size = this.editorGroupsService.getSize(group);
		// Width narrower than the whole part means the split went sideways; a
		// group stacked above or below is already as wide as everything else,
		// and squeezing it would be squeezing the wrong dimension.
		if (size.width >= available) {
			return;
		}
		const max = Math.round(available * SNCConsoleAutoOpenContribution.MAX_WIDTH_FRACTION);
		if (size.width > max) {
			this.editorGroupsService.setSize(group, { width: max, height: size.height });
		}
	}
}

registerWorkbenchContribution2(SNCConsoleAutoOpenContribution.ID, SNCConsoleAutoOpenContribution, WorkbenchPhase.AfterRestored);

registerEditorAction(class extends EditorAction {
	constructor() {
		super({
			id: 'snc.console.insertEof',
			label: localize('sncConsoleInsertEof', "End Input Stream"),
			alias: 'End Input Stream',
			precondition: CONTEXT_IN_SNC_CONSOLE,
			kbOpts: {
				// Ctrl-D is muscle memory for end-of-input at a terminal, but in
				// an editor it is Add Selection To Next Find Match. The
				// precondition scopes it to stdin documents, so the default
				// keeps working in every other file.
				kbExpr: CONTEXT_IN_SNC_CONSOLE,
				primary: KeyMod.CtrlCmd | KeyCode.KeyD,
				// Literally Ctrl-D on macOS too: `CtrlCmd` would be Cmd there,
				// which is neither what a terminal uses nor what the hint says.
				mac: { primary: KeyMod.WinCtrl | KeyCode.KeyD },
				weight: KeybindingWeight.EditorContrib + 1,
			},
			contextMenuOpts: { group: 'snc', order: 1 },
		});
	}
	run(_accessor: ServicesAccessor, editor: ICodeEditor): void {
		SNCConsoleEditorContribution.get(editor)?.insertEofMarker();
	}
});

registerEditorAction(class extends EditorAction {
	constructor() {
		super({
			id: 'snc.console.clear',
			label: localize('sncConsoleClear', "Clear Recorded Input"),
			alias: 'Clear Recorded Input',
			precondition: CONTEXT_IN_SNC_CONSOLE,
			contextMenuOpts: { group: 'snc', order: 2 },
		});
	}
	run(_accessor: ServicesAccessor, editor: ICodeEditor): void {
		SNCConsoleEditorContribution.get(editor)?.clearSession();
	}
});
