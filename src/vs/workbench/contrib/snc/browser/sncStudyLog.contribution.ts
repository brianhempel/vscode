/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { mainWindow } from '../../../../base/browser/window.js';
import { Disposable, DisposableStore } from '../../../../base/common/lifecycle.js';
import { OS, OperatingSystem, platform, PlatformToString } from '../../../../base/common/platform.js';
import { ProxyChannel } from '../../../../base/parts/ipc/common/ipc.js';
import { ITextModel } from '../../../../editor/common/model.js';
import { IModelService } from '../../../../editor/common/services/model.js';
import { ICodeEditor } from '../../../../editor/browser/editorBrowser.js';
import { ICodeEditorService } from '../../../../editor/browser/services/codeEditorService.js';
import { localize2 } from '../../../../nls.js';
import { Action2, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { ConfigurationScope, Extensions as ConfigurationExtensions, IConfigurationRegistry } from '../../../../platform/configuration/common/configurationRegistry.js';
import { ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { IMainProcessService } from '../../../../platform/ipc/common/mainProcessService.js';
import { INativeHostService } from '../../../../platform/native/common/native.js';
import { INotificationService } from '../../../../platform/notification/common/notification.js';
import { IProductService } from '../../../../platform/product/common/productService.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { installStudyLogSink, ISNCStudyLogEvent, ISNCStudyLogRepoInfo, ISNCStudyLogSink, ISNCStudyLogWriter, SNC_STUDY_LOG_CHANNEL, StudyLogCoalescer, studyLog, truncateForLog, uninstallStudyLogSink } from '../../../../platform/snc/common/sncStudyLog.js';
import { registerWorkbenchContribution2, WorkbenchPhase } from '../../../common/contributions.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { IHostService } from '../../../services/host/browser/host.js';
import { ILifecycleService } from '../../../services/lifecycle/common/lifecycle.js';
import { ITextFileService } from '../../../services/textfile/common/textfiles.js';

const SETTING_ENABLED = 'clickacode.studyLogging.enabled';
const SETTING_DIRECTORY = 'clickacode.studyLogging.directory';
const SETTING_FULL_HTML = 'clickacode.studyLogging.logFullHtml';
const SETTING_SNAPSHOT_INTERVAL = 'clickacode.studyLogging.snapshotIntervalSeconds';

/** How often the buffer is flushed to the main process. */
const FLUSH_INTERVAL_MS = 1000;
/** Flush early once this many events are waiting. */
const FLUSH_AT_EVENTS = 500;
/** Take a full snapshot after this many content changes, even if the timer hasn't fired. */
const SNAPSHOT_EVERY_N_CHANGES = 200;

Registry.as<IConfigurationRegistry>(ConfigurationExtensions.Configuration).registerConfiguration({
	id: 'clickacode',
	title: 'Clickacode',
	type: 'object',
	properties: {
		[SETTING_ENABLED]: {
			type: 'boolean',
			default: true,
			scope: ConfigurationScope.APPLICATION,
			description: 'Record how Clickacode is used (editor edits, visualizer interactions, Python runs) to JSON-lines files for the user study. Files are written locally under the user data directory (see "Clickacode: Reveal Study Log Folder") and never uploaded.',
		},
		[SETTING_DIRECTORY]: {
			type: 'string',
			default: '',
			scope: ConfigurationScope.APPLICATION,
			description: 'Absolute path of the folder study logs are written to. Empty means `<user data dir>/snc-study-logs`.',
		},
		[SETTING_FULL_HTML]: {
			type: 'boolean',
			default: false,
			scope: ConfigurationScope.APPLICATION,
			description: 'Include the full HTML of every rendered visualizer in the study log (large!). Off records only its length and type.',
		},
		[SETTING_SNAPSHOT_INTERVAL]: {
			type: 'number',
			default: 60,
			minimum: 5,
			scope: ConfigurationScope.APPLICATION,
			description: 'Seconds between full-text snapshots of a changed file in the study log.',
		},
	},
});

/**
 * Renderer-side study log service. Buffers events and ships them to the main
 * process writer once a second, on shutdown, and whenever the buffer grows
 * large. Installs itself as the `studyLog` sink so product code can log with
 * one call and no injected dependency.
 */
class SNCStudyLogService extends Disposable implements ISNCStudyLogSink {

	private readonly writer: ISNCStudyLogWriter;
	private sessionId = 'pending';
	private readonly windowId = mainWindow.vscodeWindowId;
	private seq = 0;
	private buffer: string[] = [];
	private flushTimer: ReturnType<typeof setTimeout> | undefined;
	private flushing: Promise<void> = Promise.resolve();
	private enabled: boolean;
	private lastFilePath: string | undefined;
	private dropped = 0;
	private counts: Map<string, number> = new Map();

	constructor(
		@IMainProcessService mainProcessService: IMainProcessService,
		@IConfigurationService private readonly configurationService: IConfigurationService,
		@ILifecycleService private readonly lifecycleService: ILifecycleService,
		@IProductService private readonly productService: IProductService,
		@IHostService private readonly hostService: IHostService,
	) {
		super();
		this.writer = ProxyChannel.toService<ISNCStudyLogWriter>(mainProcessService.getChannel(SNC_STUDY_LOG_CHANNEL));
		this.enabled = this.configurationService.getValue<boolean>(SETTING_ENABLED) !== false;

		installStudyLogSink(this);
		this._register({ dispose: () => uninstallStudyLogSink(this) });

		this.writer.getSessionInfo().then(info => {
			this.sessionId = info.sessionId;
			this.logSessionStart(info.startedAt, undefined, info.repo);
		}, err => {
			this.sessionId = `window-${this.windowId}`;
			this.logSessionStart(undefined, String(err));
		});

		this._register(this.configurationService.onDidChangeConfiguration(e => {
			if (e.affectsConfiguration('clickacode')) {
				const wasEnabled = this.enabled;
				this.enabled = this.configurationService.getValue<boolean>(SETTING_ENABLED) !== false;
				if (!wasEnabled && this.enabled) {
					this.log('settings.loggingEnabled', {});
				}
				this.log('settings.changed', { snc: this.configurationService.getValue('clickacode'), source: e.source });
				if (wasEnabled && !this.enabled) {
					// The record that says logging went off is the last one.
					this.buffer.push(this.serialize('settings.loggingDisabled', {}));
					this.scheduleFlush(0);
				}
			}
		}));

		this._register(this.hostService.onDidChangeFocus(focus => this.log(focus ? 'app.focus' : 'app.blur', {})));

		this._register(this.lifecycleService.onWillShutdown(e => {
			this.log('app.shutdown', { reason: e.reason, counts: Object.fromEntries(this.counts), dropped: this.dropped });
			e.join(this.flush(), { id: 'snc.studyLog.flush', label: 'Flushing Clickacode study log' });
		}));
	}

	private logSessionStart(startedAt: string | undefined, error?: string, repo?: ISNCStudyLogRepoInfo): void {
		this.log('session.start', {
			startedAt,
			error,
			version: this.productService.version,
			commit: this.productService.commit,
			repo,
			quality: this.productService.quality,
			nameLong: this.productService.nameLong,
			os: PlatformToString(platform),
			osFamily: OS === OperatingSystem.Macintosh ? 'mac' : OS === OperatingSystem.Windows ? 'windows' : 'linux',
			userAgent: mainWindow.navigator.userAgent,
			language: mainWindow.navigator.language,
			screen: { width: mainWindow.screen.width, height: mainWindow.screen.height, dpr: mainWindow.devicePixelRatio },
			timezoneOffsetMinutes: new Date().getTimezoneOffset(),
			settings: this.configurationService.getValue('clickacode'),
		});
	}

	log(type: string, payload?: unknown, file?: string): void {
		if (!this.enabled) {
			return;
		}
		try {
			this.buffer.push(this.serialize(type, payload, file));
			this.counts.set(type, (this.counts.get(type) ?? 0) + 1);
			if (this.buffer.length >= FLUSH_AT_EVENTS) {
				this.scheduleFlush(0);
			} else {
				this.scheduleFlush(FLUSH_INTERVAL_MS);
			}
		} catch {
			this.dropped++;
		}
	}

	private serialize(type: string, payload?: unknown, file?: string): string {
		const event: ISNCStudyLogEvent = {
			t: new Date().toISOString(),
			ms: Math.round(mainWindow.performance.now() * 100) / 100,
			seq: this.seq++,
			session: this.sessionId,
			window: this.windowId,
			type,
			...(file ? { file } : {}),
			...(payload !== undefined ? { payload } : {}),
		};
		try {
			return JSON.stringify(event);
		} catch (err) {
			// A payload that can't be serialized (cycles, BigInt) still leaves a trace.
			return JSON.stringify({ ...event, payload: { unserializable: String(err) } });
		}
	}

	private scheduleFlush(delay: number): void {
		if (delay === 0) {
			if (this.flushTimer !== undefined) {
				clearTimeout(this.flushTimer);
				this.flushTimer = undefined;
			}
			this.flush();
			return;
		}
		if (this.flushTimer === undefined) {
			this.flushTimer = setTimeout(() => {
				this.flushTimer = undefined;
				this.flush();
			}, delay);
		}
	}

	private flush(): Promise<void> {
		if (this.buffer.length === 0) {
			return this.flushing;
		}
		const lines = this.buffer;
		this.buffer = [];
		const directory = this.configurationService.getValue<string>(SETTING_DIRECTORY) || undefined;
		this.flushing = this.flushing
			.then(() => this.writer.append(directory, lines))
			.then(path => { this.lastFilePath = path; }, err => {
				this.dropped += lines.length;
				console.error('SNC study log: failed to write', err);
			});
		return this.flushing;
	}

	/** Absolute path of the current log file, or the folder it will be created in. */
	async currentLogLocation(): Promise<{ file?: string; directory: string }> {
		await this.flush();
		const info = await this.writer.getSessionInfo();
		const directory = this.configurationService.getValue<string>(SETTING_DIRECTORY) || info.defaultDirectory;
		return { file: this.lastFilePath, directory };
	}
}

let studyLogService: SNCStudyLogService | undefined;

/**
 * Wires the workbench up to the log: editor lifecycle, cursor/scroll/focus,
 * text-model changes (with periodic full snapshots) and saves. The
 * visualizer-side events are logged from `snc.ts` itself.
 */
class SNCStudyLogContribution extends Disposable {

	static readonly ID = 'workbench.contrib.sncStudyLog';

	private readonly cursorCoalescer = new StudyLogCoalescer('editor.cursor', 300);
	private readonly scrollCoalescer = new StudyLogCoalescer('editor.scroll', 500);
	private readonly perModel = new Map<string, { changes: number; lastSnapshotMs: number; lastVersionSnapshotted: number }>();
	private snapshotTimer: number | undefined;

	constructor(
		@ICodeEditorService private readonly codeEditorService: ICodeEditorService,
		@IModelService private readonly modelService: IModelService,
		@IEditorService private readonly editorService: IEditorService,
		@ITextFileService private readonly textFileService: ITextFileService,
		@IConfigurationService private readonly configurationService: IConfigurationService,
		@IMainProcessService mainProcessService: IMainProcessService,
		@ILifecycleService lifecycleService: ILifecycleService,
		@IProductService productService: IProductService,
		@IHostService private readonly hostService: IHostService,
	) {
		super();
		studyLogService = this._register(new SNCStudyLogService(mainProcessService, configurationService, lifecycleService, productService, hostService));
		this._register({ dispose: () => { studyLogService = undefined; } });

		try {
			this.wireEditors();
			this.wireModels();
			this.wireWorkbench();
		} catch (err) {
			studyLog.log('log.internalError', { where: 'contribution', error: String(err) });
		}
	}

	// ---- editors ----

	private wireEditors(): void {
		for (const editor of this.codeEditorService.listCodeEditors()) {
			this.attachEditor(editor);
		}
		this._register(this.codeEditorService.onCodeEditorAdd(editor => this.attachEditor(editor)));
	}

	private attachEditor(editor: ICodeEditor): void {
		const store = new DisposableStore();
		const file = () => editor.getModel()?.uri.toString();
		const editorInfo = () => ({ editorId: editor.getId(), file: file(), language: editor.getModel()?.getLanguageId() });

		studyLog.log('editor.created', editorInfo(), file());
		store.add(editor.onDidChangeModel(e => {
			studyLog.log('editor.modelChanged', { ...editorInfo(), from: e.oldModelUrl?.toString(), to: e.newModelUrl?.toString() }, file());
		}));
		store.add(editor.onDidChangeCursorSelection(e => {
			const s = e.selection;
			this.cursorCoalescer.note(
				// A new record whenever the line changes; same-line moves coalesce.
				`${editor.getId()}:${s.positionLineNumber}:${s.isEmpty()}`,
				{
					editorId: editor.getId(),
					selection: [s.startLineNumber, s.startColumn, s.endLineNumber, s.endColumn],
					position: [s.positionLineNumber, s.positionColumn],
					empty: s.isEmpty(),
					secondary: e.secondarySelections.length,
					source: e.source,
					reason: e.reason,
				},
				file());
		}));
		store.add(editor.onDidScrollChange(e => {
			if (!e.scrollTopChanged && !e.scrollLeftChanged) { return; }
			this.scrollCoalescer.note(`${editor.getId()}`, {
				editorId: editor.getId(),
				scrollTop: Math.round(e.scrollTop),
				scrollLeft: Math.round(e.scrollLeft),
				scrollHeight: Math.round(e.scrollHeight),
				visibleRanges: editor.getVisibleRanges().map(r => [r.startLineNumber, r.endLineNumber]),
			}, file());
		}));
		store.add(editor.onDidFocusEditorText(() => studyLog.log('editor.focus', editorInfo(), file())));
		store.add(editor.onDidBlurEditorText(() => {
			this.cursorCoalescer.flush();
			studyLog.log('editor.blur', { ...editorInfo(), activeElement: describeActiveElement() }, file());
		}));
		store.add(editor.onDidDispose(() => {
			studyLog.log('editor.disposed', editorInfo(), file());
			store.dispose();
		}));
		this._register(store);
	}

	// ---- text models ----

	private wireModels(): void {
		for (const model of this.modelService.getModels()) {
			this.attachModel(model);
		}
		this._register(this.modelService.onModelAdded(model => this.attachModel(model)));
		this._register(this.modelService.onModelRemoved(model => {
			this.snapshot(model, 'close');
			this.perModel.delete(model.uri.toString());
			studyLog.log('file.close', { language: model.getLanguageId() }, model.uri.toString());
		}));
		this._register(this.modelService.onModelLanguageChanged(e => {
			studyLog.log('file.languageChanged', { from: e.oldLanguageId, to: e.model.getLanguageId() }, e.model.uri.toString());
		}));
		this.snapshotTimer = mainWindow.setInterval(() => this.periodicSnapshots(), 5000);
		this._register({ dispose: () => mainWindow.clearInterval(this.snapshotTimer) });
	}

	private isInteresting(model: ITextModel): boolean {
		// Python files and SNC's own stdin documents; not settings, output panes, etc.
		const scheme = model.uri.scheme;
		if (scheme !== 'file' && scheme !== 'untitled') { return false; }
		const lang = model.getLanguageId();
		return lang === 'python' || model.uri.path.endsWith('.py') || model.uri.path.includes('.snc');
	}

	private attachModel(model: ITextModel): void {
		if (!this.isInteresting(model)) {
			return;
		}
		const key = model.uri.toString();
		this.perModel.set(key, { changes: 0, lastSnapshotMs: Date.now(), lastVersionSnapshotted: model.getVersionId() });
		studyLog.log('file.open', { language: model.getLanguageId(), lineCount: model.getLineCount(), length: model.getValueLength() }, key);
		this.snapshot(model, 'open');

		const store = new DisposableStore();
		store.add(model.onDidChangeContent(e => {
			const origin = studyLog.currentEditOrigin();
			const changes = e.changes.map(c => ({
				range: [c.range.startLineNumber, c.range.startColumn, c.range.endLineNumber, c.range.endColumn],
				rangeLength: c.rangeLength,
				text: truncateForLog(c.text, 4000),
			}));
			studyLog.log(origin ? 'file.sncEdit' : 'file.userEdit', {
				origin,
				versionId: e.versionId,
				isUndoing: e.isUndoing,
				isRedoing: e.isRedoing,
				isFlush: e.isFlush,
				isEolChange: e.isEolChange,
				changes,
			}, key);
			if (e.isUndoing) { studyLog.log('editor.undo', { versionId: e.versionId }, key); }
			if (e.isRedoing) { studyLog.log('editor.redo', { versionId: e.versionId }, key); }
			const state = this.perModel.get(key);
			if (state && ++state.changes >= SNAPSHOT_EVERY_N_CHANGES) {
				this.snapshot(model, 'changes');
			}
		}));
		store.add(model.onWillDispose(() => store.dispose()));
		this._register(store);
	}

	private periodicSnapshots(): void {
		const intervalMs = Math.max(5, this.configurationService.getValue<number>(SETTING_SNAPSHOT_INTERVAL) || 60) * 1000;
		const now = Date.now();
		for (const model of this.modelService.getModels()) {
			const state = this.perModel.get(model.uri.toString());
			if (state && now - state.lastSnapshotMs >= intervalMs && model.getVersionId() !== state.lastVersionSnapshotted) {
				this.snapshot(model, 'periodic');
			}
		}
	}

	private snapshot(model: ITextModel, reason: 'open' | 'close' | 'save' | 'periodic' | 'changes'): void {
		try {
			if (model.isDisposed()) { return; }
			const state = this.perModel.get(model.uri.toString());
			if (state) {
				state.changes = 0;
				state.lastSnapshotMs = Date.now();
				state.lastVersionSnapshotted = model.getVersionId();
			}
			studyLog.log('file.snapshot', {
				reason,
				versionId: model.getVersionId(),
				lineCount: model.getLineCount(),
				text: model.getValue(),
			}, model.uri.toString());
		} catch (err) {
			studyLog.log('log.internalError', { where: 'snapshot', error: String(err) });
		}
	}

	// ---- workbench ----

	private wireWorkbench(): void {
		this._register(this.editorService.onDidActiveEditorChange(() => {
			const active = this.editorService.activeEditor;
			studyLog.log('editor.activeChanged', {
				name: active?.getName(),
				typeId: active?.typeId,
				visible: this.editorService.visibleEditors.map(e => e.resource?.toString()),
			}, active?.resource?.toString());
		}));
		this._register(this.editorService.onDidCloseEditor(e => {
			studyLog.log('editor.closed', { name: e.editor.getName(), context: e.context }, e.editor.resource?.toString());
		}));
		this._register(this.textFileService.files.onDidSave(e => {
			const model = e.model.textEditorModel;
			studyLog.log('file.save', { reason: e.reason, source: e.source }, e.model.resource.toString());
			if (model) {
				this.snapshot(model, 'save');
			}
		}));
		this._register(this.hostService.onDidChangeFocus(focus => {
			if (!focus) {
				this.cursorCoalescer.flush();
				this.scrollCoalescer.flush();
			}
		}));
	}
}

function describeActiveElement(): string | undefined {
	try {
		const el = mainWindow.document.activeElement;
		if (!el) { return undefined; }
		const cls = typeof el.className === 'string' ? el.className.split(/\s+/).slice(0, 4).join('.') : '';
		return `${el.tagName.toLowerCase()}${cls ? '.' + cls : ''}`;
	} catch {
		return undefined;
	}
}

registerWorkbenchContribution2(SNCStudyLogContribution.ID, SNCStudyLogContribution, WorkbenchPhase.BlockRestore);

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'clickacode.studyLogging.revealFolder',
			title: localize2('sncRevealStudyLogFolder', "Clickacode: Reveal Study Log Folder"),
			f1: true,
		});
	}
	async run(accessor: ServicesAccessor): Promise<void> {
		const nativeHostService = accessor.get(INativeHostService);
		const notificationService = accessor.get(INotificationService);
		studyLog.log('command.revealStudyLogFolder', {});
		const location = await studyLogService?.currentLogLocation();
		if (!location) {
			notificationService.warn('Study logging is not running in this window.');
			return;
		}
		await nativeHostService.showItemInFolder(location.file ?? location.directory);
	}
});
