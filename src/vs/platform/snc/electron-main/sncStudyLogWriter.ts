/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { promises as fs } from 'fs';
import { join } from '../../../base/common/path.js';
import { generateUuid } from '../../../base/common/uuid.js';
import { IEnvironmentMainService } from '../../environment/electron-main/environmentMainService.js';
import { ISNCStudyLogSessionInfo, ISNCStudyLogWriter } from '../common/sncStudyLog.js';

/**
 * Main-process end of study logging: mints the session id and appends batches
 * of JSON lines to `<directory>/<sessionId>.jsonl`. Every window of the launch
 * shares the file; `append` calls are chained so their lines never interleave
 * mid-batch.
 */
export class SNCStudyLogWriter implements ISNCStudyLogWriter {

	declare readonly _serviceBrand: undefined;

	private readonly sessionInfo: ISNCStudyLogSessionInfo;
	private queue: Promise<unknown> = Promise.resolve();

	constructor(
		@IEnvironmentMainService environmentMainService: IEnvironmentMainService,
	) {
		const started = new Date();
		// Sortable by launch time, unique by the uuid tail: 20260826T153012-1a2b3c4d.
		const stamp = started.toISOString().replace(/[-:]/g, '').replace(/\.\d+Z$/, '');
		this.sessionInfo = {
			sessionId: `${stamp}-${generateUuid().slice(0, 8)}`,
			defaultDirectory: join(environmentMainService.userDataPath, 'snc-study-logs'),
			startedAt: started.toISOString(),
		};
	}

	async getSessionInfo(): Promise<ISNCStudyLogSessionInfo> {
		return this.sessionInfo;
	}

	append(directory: string | undefined, lines: string[]): Promise<string> {
		const dir = directory && directory.trim().length > 0 ? directory : this.sessionInfo.defaultDirectory;
		const file = join(dir, `${this.sessionInfo.sessionId}.jsonl`);
		const write = this.queue.then(async () => {
			if (lines.length === 0) {
				return file;
			}
			await fs.mkdir(dir, { recursive: true });
			await fs.appendFile(file, lines.join('\n') + '\n', 'utf8');
			return file;
		});
		// A failed write must not wedge every later one.
		this.queue = write.catch(() => undefined);
		return write;
	}
}
