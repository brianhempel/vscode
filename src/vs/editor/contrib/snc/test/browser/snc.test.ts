/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { IVisualizationItem, UiEvent } from '../../../../../platform/snc/common/snc.js';
import { carryForwardItems, resumeAtStepFor } from '../../browser/snc.js';

function item(over: Partial<IVisualizationItem> & { execution_step: number }): IVisualizationItem {
	return {
		line: over.execution_step, visIndex: 0, runId: 'old', html: '', path: [], ...over
	};
}

function event(line: number): UiEvent {
	return { id: 1, line, visIndex: 0, pythonEventStr: '', eventJSON: {} };
}

suite('SNC checkpoint 3 bookkeeping', () => {

	ensureNoDisposablesAreLeakedInTestSuite();

	suite('resumeAtStepFor', () => {

		test('is the earliest widget with events still queued', () => {
			assert.strictEqual(resumeAtStepFor([
				item({ execution_step: 3, unhandledEvents: [event(3)] }),
				item({ execution_step: 10, unhandledEvents: [event(10)] }),
			]), 3);
		});

		test('a widget behind the pause forces a run that starts from the top', () => {
			// Nothing else keeps its events alive: no item arrives for a widget
			// behind the pause, so `scheduleQueuedEventRun` never fires for it
			// and the run-end sweep would clear them. Relax this and events
			// strand silently.
			assert.strictEqual(resumeAtStepFor([
				item({ execution_step: 3, unhandledEvents: [event(3)] }),
			]), 3);
		});

		test('is undefined when nothing is waiting on an answer', () => {
			assert.strictEqual(resumeAtStepFor([
				item({ execution_step: 3 }),
				item({ execution_step: 10, unhandledEvents: [] }),
			]), undefined);
		});
	});

	suite('carryForwardItems', () => {

		test('an ordinary run keeps only its own items', () => {
			const kept = carryForwardItems([
				item({ execution_step: 3, runId: 'old' }),
				item({ execution_step: 10, runId: 'now' }),
			], 'now', null);
			assert.deepStrictEqual(kept.map(i => i.execution_step), [10]);
		});

		test('a resumed run keeps the widgets its warm ran through', () => {
			// They ran during the warm and were dropped rather than re-sent, so
			// the copies on screen are the ones this run produced.
			const kept = carryForwardItems([
				item({ execution_step: 3, runId: 'old' }),
				item({ execution_step: 10, runId: 'now' }),
				item({ execution_step: 20, runId: 'now' }),
			], 'now', 10);
			assert.deepStrictEqual(kept.map(i => i.execution_step), [3, 10, 20]);
		});

		test('a carried item is re-stamped, so the next run keeps it too', () => {
			const kept = carryForwardItems([item({ execution_step: 3, runId: 'old' })], 'now', 10);
			assert.strictEqual(kept[0].runId, 'now');
			assert.deepStrictEqual(carryForwardItems(kept, 'now', null).map(i => i.execution_step), [3]);
		});

		test('a widget at the pause is not carried -- the run re-emits it', () => {
			// The pause lands before that widget is visualized, so its item is
			// this run's own work and arrives with this run's id.
			const kept = carryForwardItems([item({ execution_step: 10, runId: 'old' })], 'now', 10);
			assert.deepStrictEqual(kept, []);
		});

		test('a stale item after the pause is still dropped', () => {
			const kept = carryForwardItems([item({ execution_step: 20, runId: 'old' })], 'now', 10);
			assert.deepStrictEqual(kept, []);
		});
	});
});
