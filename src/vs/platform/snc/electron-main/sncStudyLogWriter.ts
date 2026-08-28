/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { execFile } from 'child_process';
import { createHash } from 'crypto';
import { promises as fs } from 'fs';
import { join } from '../../../base/common/path.js';
import { generateUuid } from '../../../base/common/uuid.js';
import { IEnvironmentMainService } from '../../environment/electron-main/environmentMainService.js';
import { ISNCStudyLogRepoInfo, ISNCStudyLogSessionInfo, ISNCStudyLogWriter } from '../common/sncStudyLog.js';

/** How many `git status` paths a session record keeps. */
const DIRTY_PATHS_CAP = 40;
/**
 * How long the launch-time git queries may take, all told. Each one is
 * milliseconds warm; `status` and `diff` on a cold cache in a tree this size
 * can be a second or two. Nothing waits on this but the session.start record.
 */
const GIT_TIMEOUT_MS = 5000;

function git(cwd: string, args: string[], deadline: number): Promise<string> {
	const timeout = Math.max(1, deadline - Date.now());
	return new Promise((resolve, reject) => {
		execFile('git', args, { cwd, timeout, maxBuffer: 16 * 1024 * 1024 }, (err, stdout) => {
			if (err) { reject(err); } else { resolve(stdout); }
		});
	});
}

/**
 * What git says about the checkout at `root`. Never throws: a packaged build
 * has no checkout, and a missing git is a fact worth logging, not a failure.
 */
async function describeRepo(root: string): Promise<ISNCStudyLogRepoInfo> {
	const info: ISNCStudyLogRepoInfo = { root };
	const deadline = Date.now() + GIT_TIMEOUT_MS;
	try {
		info.head = (await git(root, ['rev-parse', 'HEAD'], deadline)).trim();
	} catch (err) {
		info.error = err instanceof Error ? err.message : String(err);
		return info;
	}
	try {
		info.branch = (await git(root, ['rev-parse', '--abbrev-ref', 'HEAD'], deadline)).trim();
		info.describe = (await git(root, ['describe', '--tags', '--always', '--dirty'], deadline)).trim();
		const status = (await git(root, ['status', '--porcelain'], deadline)).split('\n').filter(l => l.length > 0);
		info.dirty = status.length > 0;
		info.dirtyFiles = status.length;
		info.dirtyPaths = status.slice(0, DIRTY_PATHS_CAP);
		if (info.dirty) {
			// Tracked changes only: an untracked file is listed above but has
			// no diff. Identical edits hash identically, so two sessions on
			// the same uncommitted work can be told apart from merely-dirty.
			info.diffSha1 = createHash('sha1').update(await git(root, ['diff', 'HEAD'], deadline)).digest('hex');
		}
	} catch (err) {
		info.error = err instanceof Error ? err.message : String(err);
	}
	return info;
}

/**
 * Main-process end of study logging: mints the session id and appends batches
 * of JSON lines to `<directory>/<sessionId>.jsonl`. Every window of the launch
 * shares the file; `append` calls are chained so their lines never interleave
 * mid-batch.
 */
export class SNCStudyLogWriter implements ISNCStudyLogWriter {

	declare readonly _serviceBrand: undefined;

	private readonly sessionInfo: ISNCStudyLogSessionInfo;
	/** Asked once, at launch; every window's session.start awaits the same answer. */
	private readonly repoInfo: Promise<ISNCStudyLogRepoInfo>;
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
		this.repoInfo = describeRepo(environmentMainService.appRoot);
	}

	async getSessionInfo(): Promise<ISNCStudyLogSessionInfo> {
		return { ...this.sessionInfo, repo: await this.repoInfo };
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
