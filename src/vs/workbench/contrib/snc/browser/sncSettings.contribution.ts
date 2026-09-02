/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { localize, localize2 } from '../../../../nls.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { IConfigurationRegistry, Extensions as ConfigurationExtensions } from '../../../../platform/configuration/common/configurationRegistry.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { Action2, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { SNC_LIVE_ONLY_VISUALIZERS_SETTING } from '../../../../platform/snc/common/snc.js';

Registry.as<IConfigurationRegistry>(ConfigurationExtensions.Configuration).registerConfiguration({
	id: 'clickacode',
	order: 100,
	title: localize('sncConfigurationTitle', "Clickacode"),
	type: 'object',
	properties: {
		[SNC_LIVE_ONLY_VISUALIZERS_SETTING]: {
			type: 'boolean',
			default: false,
			description: localize('clickacode.liveOnlyVisualizers', "Show visualizations as live-only views: every control that would write code into the file (action buttons, drag handles on values, the link chain, drag-to-select, the column search, sort, compute and tally menus) is left out. What changes only the visualization itself still works -- expanding, scrolling, picking a loop iteration, and in tables resizing, reordering, removing and adding columns (as Python expressions), which are saved in the line's #%click comment. Takes effect on the next re-run, which changing it triggers."),
		},
	},
});

registerAction2(class ToggleLiveOnlyVisualizers extends Action2 {
	constructor() {
		super({
			id: 'snc.toggleLiveOnlyVisualizers',
			title: localize2('snc.toggleLiveOnlyVisualizers', "Clickacode: Toggle Live-Only Visualizers"),
			f1: true,
		});
	}

	override async run(accessor: ServicesAccessor): Promise<void> {
		const configurationService = accessor.get(IConfigurationService);
		const current = configurationService.getValue<boolean>(SNC_LIVE_ONLY_VISUALIZERS_SETTING) === true;
		await configurationService.updateValue(SNC_LIVE_ONLY_VISUALIZERS_SETTING, !current);
	}
});
