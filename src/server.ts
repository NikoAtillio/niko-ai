import express, { Request, Response } from 'express';
import multer from 'multer';
import path from 'path';
import fs from 'fs';
import { spawn, ChildProcessWithoutNullStreams } from 'child_process';
import { ChartAIAnalyzer } from './services/ChartAIAnalyzer';

const app = express();

const upload = multer({ dest: 'uploads/' });
const chartAnalyzer = new ChartAIAnalyzer();

const WORKSPACE_ROOT = process.cwd();
const ARTIFACT_DIR = path.join(WORKSPACE_ROOT, 'backtest_artifacts');
const RUN_HISTORY_DIR = path.join(WORKSPACE_ROOT, 'saved_runs');
const RUN_HISTORY_FILE = path.join(RUN_HISTORY_DIR, 'strategy_runs.json');
const RUN_HISTORY_LIMIT = 100;
const ADMIN_SCAN_DIRS = [
	path.join(WORKSPACE_ROOT, 'uploads'),
	ARTIFACT_DIR,
	RUN_HISTORY_DIR,
];

const DEFAULT_DATA_FILES: Record<string, string> = {
	XAUUSD: '/Users/niko/Downloads/XAUUSD_M1_202404010105_202603302033.csv',
	NAS100: '/Users/niko/Downloads/NAS100_M1_202404010105_202603302033.csv',
};

const DEFAULT_TRADES_FILE = path.join(WORKSPACE_ROOT, 'mt5_xau_copilot_baseline', 'phantom_backtest_trades.csv');
const DEFAULT_REPORT_FILE = path.join(WORKSPACE_ROOT, 'mt5_xau_copilot_baseline', 'phantom_backtest_report.md');

type BacktestStatus = 'idle' | 'running' | 'completed' | 'failed';

interface BacktestMetrics {
	finalCapital?: number;
	totalReturnPct?: number;
	totalTrades?: number;
	winRatePct?: number;
	maxDrawdownPct?: number;
}

interface BacktestState {
	status: BacktestStatus;
	startedAt?: string;
	endedAt?: string;
	exitCode?: number;
	logs: string[];
	metrics: BacktestMetrics;
	artifacts: string[];
}

interface CandleRecord {
	ts: number;
	open: number;
	high: number;
	low: number;
	close: number;
	volume: number;
}

interface SRZone {
	kind: 'support' | 'resistance';
	low: number;
	high: number;
	center: number;
	strength: number;
}

interface TradeRecord {
	direction: string;
	entry_time: string;
	entry_price: number;
	exit_time: string;
	exit_price: number;
	exit_reason: string;
	qty: number;
	pnl: number;
	fees: number;
	r_value: number;
	win: boolean;
}

interface DataCacheEntry {
	raw: CandleRecord[];
	byTimeframe: Map<string, CandleRecord[]>;
}

interface StrategyRunRecord {
	id: string;
	createdAt: string;
	summary: unknown;
}

const MAX_LOG_LINES = 2000;

const backtestState: BacktestState = {
	status: 'idle',
	logs: [],
	metrics: {},
	artifacts: [],
};

let backtestProc: ChildProcessWithoutNullStreams | null = null;
const sseClients = new Set<Response>();

const dataCache = new Map<string, DataCacheEntry>();
const tradesCache = new Map<string, TradeRecord[]>();
const reportCache = new Map<string, Record<string, string>>();

function loadRunHistory(): StrategyRunRecord[] {
	try {
		if (!fs.existsSync(RUN_HISTORY_FILE)) {
			return [];
		}
		const text = fs.readFileSync(RUN_HISTORY_FILE, 'utf8');
		const parsed = JSON.parse(text);
		return Array.isArray(parsed) ? parsed : [];
	} catch {
		return [];
	}
}

function saveRunHistory(runs: StrategyRunRecord[]): void {
	fs.mkdirSync(RUN_HISTORY_DIR, { recursive: true });
	fs.writeFileSync(RUN_HISTORY_FILE, `${JSON.stringify(runs.slice(0, RUN_HISTORY_LIMIT), null, 2)}\n`, 'utf8');
}

function createRunId(): string {
	return `run_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
}

function listDirectoryEntries(dirPath: string): Array<{ name: string; isDirectory: boolean; size: number; modifiedAt: string | null }> {
	if (!fs.existsSync(dirPath)) {
		return [];
	}

	return fs.readdirSync(dirPath, { withFileTypes: true }).map((entry) => {
		const fullPath = path.join(dirPath, entry.name);
		const stat = fs.statSync(fullPath);
		return {
			name: entry.name,
			isDirectory: entry.isDirectory(),
			size: entry.isDirectory() ? 0 : stat.size,
			modifiedAt: stat.mtime.toISOString(),
		};
	});
}

function flattenRunSummary(run: StrategyRunRecord): Record<string, unknown> {
	const summary = (run.summary && typeof run.summary === 'object') ? run.summary as Record<string, unknown> : {};
	const best = (summary.best && typeof summary.best === 'object') ? summary.best as Record<string, unknown> : {};
	return {
		id: run.id,
		createdAt: run.createdAt,
		datasetTitle: summary.datasetTitle || '',
		market: summary.market || '',
		periodKey: summary.periodKey || '',
		startCapital: summary.startCapital ?? '',
		riskMultiplier: summary.riskMultiplier ?? '',
		withdrawalPct: summary.withdrawalPct ?? '',
		strategyLabel: best.label || '',
		avgReturnPct: best.avgRet ?? '',
		avgProfitFactor: best.avgPf ?? '',
		avgWinRatePct: best.avgWin ?? '',
		worstDrawdownPct: best.worstDD ?? '',
		compoundedProfit: best.compoundedProfit ?? '',
		compoundedCapital: best.compounded ?? '',
		note: summary.note || '',
	};
}

function toCsvValue(value: unknown): string {
	const text = value === null || value === undefined ? '' : String(value);
	if (/[",\n]/.test(text)) {
		return `"${text.replace(/"/g, '""')}"`;
	}
	return text;
}

function runsToCsv(runs: StrategyRunRecord[]): string {
	const rows = runs.map((run) => flattenRunSummary(run));
	const headers = Object.keys(rows[0] || {
		id: '', createdAt: '', datasetTitle: '', market: '', periodKey: '', startCapital: '', riskMultiplier: '', withdrawalPct: '', strategyLabel: '', avgReturnPct: '', avgProfitFactor: '', avgWinRatePct: '', worstDrawdownPct: '', compoundedProfit: '', compoundedCapital: '', note: '',
	});
	const lines = [headers.join(',')];
	for (const row of rows) {
		lines.push(headers.map((header) => toCsvValue(row[header])).join(','));
	}
	return `${lines.join('\n')}\n`;
}

function normalizePath(p: string): string {
	return path.resolve(p);
}

function fileExists(p: string): boolean {
	try {
		return fs.existsSync(p);
	} catch {
		return false;
	}
}

function parseDateToMs(input: unknown): number | undefined {
	if (typeof input !== 'string' || !input.trim()) {
		return undefined;
	}
	const ms = Date.parse(input);
	return Number.isFinite(ms) ? ms : undefined;
}

function parsePositiveInt(input: unknown, fallbackValue: number): number {
	const n = Number(input);
	if (!Number.isFinite(n) || n <= 0) {
		return fallbackValue;
	}
	return Math.floor(n);
}

function timeframeToMinutes(tf: string): number {
	if (tf === '1m') {
		return 1;
	}
	if (tf === '5m') {
		return 5;
	}
	if (tf === '15m') {
		return 15;
	}
	if (tf === '1h') {
		return 60;
	}
	if (tf === '4h') {
		return 240;
	}
	throw new Error(`Unsupported timeframe: ${tf}`);
}

function parseMt5Csv(filePath: string): CandleRecord[] {
	const absPath = normalizePath(filePath);
	const text = fs.readFileSync(absPath, 'utf8');
	const lines = text.split(/\r?\n/);

	const rows: CandleRecord[] = [];
	let lastTs = -1;

	for (let i = 1; i < lines.length; i += 1) {
		const line = lines[i].trim();
		if (!line) {
			continue;
		}

		const cols = line.split(/\s+/);
		if (cols.length < 6) {
			continue;
		}

		const datePart = cols[0];
		const timePart = cols[1];
		const open = Number(cols[2]);
		const high = Number(cols[3]);
		const low = Number(cols[4]);
		const close = Number(cols[5]);
		const tickVol = cols.length > 6 ? Number(cols[6]) : 0;

		if (![open, high, low, close].every((n) => Number.isFinite(n))) {
			continue;
		}

		const isoDate = `${datePart.replace(/\./g, '-')}`;
		const ts = Date.parse(`${isoDate}T${timePart}Z`);
		if (!Number.isFinite(ts)) {
			continue;
		}

		if (ts === lastTs) {
			continue;
		}

		lastTs = ts;
		rows.push({
			ts,
			open,
			high,
			low,
			close,
			volume: Number.isFinite(tickVol) ? tickVol : 0,
		});
	}

	if (!rows.length) {
		throw new Error('No valid MT5 candles parsed from file.');
	}

	return rows;
}

function getOrLoadData(filePath: string): DataCacheEntry {
	const absPath = normalizePath(filePath);
	const hit = dataCache.get(absPath);
	if (hit) {
		return hit;
	}

	if (!fileExists(absPath)) {
		throw new Error(`Data file not found: ${absPath}`);
	}

	const raw = parseMt5Csv(absPath);
	const entry: DataCacheEntry = {
		raw,
		byTimeframe: new Map<string, CandleRecord[]>([['1m', raw]]),
	};
	dataCache.set(absPath, entry);
	return entry;
}

function resampleCandles(candles: CandleRecord[], timeframe: string): CandleRecord[] {
	if (timeframe === '1m') {
		return candles;
	}

	const bucketMinutes = timeframeToMinutes(timeframe);
	const bucketMs = bucketMinutes * 60 * 1000;

	const out: CandleRecord[] = [];
	let currentBucket = -1;
	let open = 0;
	let high = 0;
	let low = 0;
	let close = 0;
	let volume = 0;

	for (const c of candles) {
		const bucket = Math.floor(c.ts / bucketMs) * bucketMs;
		if (bucket !== currentBucket) {
			if (currentBucket !== -1) {
				out.push({ ts: currentBucket, open, high, low, close, volume });
			}
			currentBucket = bucket;
			open = c.open;
			high = c.high;
			low = c.low;
			close = c.close;
			volume = c.volume;
		} else {
			high = Math.max(high, c.high);
			low = Math.min(low, c.low);
			close = c.close;
			volume += c.volume;
		}
	}

	if (currentBucket !== -1) {
		out.push({ ts: currentBucket, open, high, low, close, volume });
	}

	return out;
}

function getCandles(filePath: string, timeframe: string): CandleRecord[] {
	const cacheEntry = getOrLoadData(filePath);
	const hit = cacheEntry.byTimeframe.get(timeframe);
	if (hit) {
		return hit;
	}
	const built = resampleCandles(cacheEntry.raw, timeframe);
	cacheEntry.byTimeframe.set(timeframe, built);
	return built;
}

function buildSupportResistanceZones(candles: CandleRecord[], maxZones: number): SRZone[] {
	if (!candles.length) {
		return [];
	}

	const highs = candles.map((c) => c.high);
	const lows = candles.map((c) => c.low);
	const closes = candles.map((c) => c.close);
	const priceMin = Math.min(...lows);
	const priceMax = Math.max(...highs);
	const lastClose = closes[closes.length - 1] ?? (priceMin + priceMax) / 2;

	const span = Math.max(priceMax - priceMin, 1e-6);
	const binCount = Math.max(25, Math.min(80, Math.floor(Math.sqrt(candles.length))));
	const binSize = span / binCount;
	const bins = Array.from({ length: binCount }, () => 0);

	for (const c of candles) {
		const hiIdx = Math.max(0, Math.min(binCount - 1, Math.floor((c.high - priceMin) / binSize)));
		const loIdx = Math.max(0, Math.min(binCount - 1, Math.floor((c.low - priceMin) / binSize)));
		bins[hiIdx] += 1;
		bins[loIdx] += 1;
	}

	const peakBins: Array<{ idx: number; count: number }> = [];
	for (let i = 1; i < binCount - 1; i += 1) {
		if (bins[i] >= bins[i - 1] && bins[i] >= bins[i + 1] && bins[i] > 1) {
			peakBins.push({ idx: i, count: bins[i] });
		}
	}

	peakBins.sort((a, b) => b.count - a.count);
	const width = Math.max(span * 0.0035, binSize * 0.85);

	const chosen: SRZone[] = [];
	for (const peak of peakBins) {
		const center = priceMin + (peak.idx + 0.5) * binSize;
		const low = center - width;
		const high = center + width;

		const overlaps = chosen.some((z) => Math.abs(z.center - center) < width * 1.2);
		if (overlaps) {
			continue;
		}

		chosen.push({
			kind: center <= lastClose ? 'support' : 'resistance',
			low,
			high,
			center,
			strength: peak.count,
		});

		if (chosen.length >= maxZones * 2) {
			break;
		}
	}

	const supports = chosen
		.filter((z) => z.kind === 'support')
		.sort((a, b) => b.strength - a.strength)
		.slice(0, maxZones);

	const resistances = chosen
		.filter((z) => z.kind === 'resistance')
		.sort((a, b) => b.strength - a.strength)
		.slice(0, maxZones);

	return [...supports, ...resistances].sort((a, b) => a.center - b.center);
}

function parseSimpleCsvRows(filePath: string): Array<Record<string, string>> {
	const absPath = normalizePath(filePath);
	const text = fs.readFileSync(absPath, 'utf8');
	const lines = text.split(/\r?\n/).filter((l) => l.trim().length > 0);
	if (!lines.length) {
		return [];
	}

	const header = lines[0].split(',').map((h) => h.trim());
	const rows: Array<Record<string, string>> = [];

	for (let i = 1; i < lines.length; i += 1) {
		const cols = lines[i].split(',');
		if (!cols.length) {
			continue;
		}
		const row: Record<string, string> = {};
		for (let j = 0; j < header.length; j += 1) {
			row[header[j]] = (cols[j] ?? '').trim();
		}
		rows.push(row);
	}

	return rows;
}

function getOrLoadTrades(tradesFile: string): TradeRecord[] {
	const absPath = normalizePath(tradesFile);
	const hit = tradesCache.get(absPath);
	if (hit) {
		return hit;
	}

	if (!fileExists(absPath)) {
		throw new Error(`Trades file not found: ${absPath}`);
	}

	const rows = parseSimpleCsvRows(absPath);
	const out: TradeRecord[] = rows.map((r) => ({
		direction: r.direction || '',
		entry_time: r.entry_time || '',
		entry_price: Number(r.entry_price || 0),
		exit_time: r.exit_time || '',
		exit_price: Number(r.exit_price || 0),
		exit_reason: r.exit_reason || '',
		qty: Number(r.qty || 0),
		pnl: Number(r.pnl || 0),
		fees: Number(r.fees || 0),
		r_value: Number(r.r_value || 0),
		win: String(r.win || '').toLowerCase() === 'true',
	}));

	tradesCache.set(absPath, out);
	return out;
}

function getOrLoadReport(reportFile: string): Record<string, string> {
	const absPath = normalizePath(reportFile);
	const hit = reportCache.get(absPath);
	if (hit) {
		return hit;
	}

	if (!fileExists(absPath)) {
		throw new Error(`Report file not found: ${absPath}`);
	}

	const text = fs.readFileSync(absPath, 'utf8');
	const lines = text.split(/\r?\n/);
	const map: Record<string, string> = {};

	for (const line of lines) {
		const match = line.match(/^\-\s*([^:]+):\s*(.+)$/);
		if (match) {
			const key = match[1].trim();
			const value = match[2].trim();
			map[key] = value;
		}
	}

	reportCache.set(absPath, map);
	return map;
}

function pushLog(line: string): void {
	if (!line.trim()) {
		return;
	}
	backtestState.logs.push(line);
	if (backtestState.logs.length > MAX_LOG_LINES) {
		backtestState.logs = backtestState.logs.slice(-MAX_LOG_LINES);
	}
	broadcast('log', { line });
}

function broadcast(event: string, payload: unknown): void {
	const msg = `event: ${event}\ndata: ${JSON.stringify(payload)}\n\n`;
	for (const client of sseClients) {
		client.write(msg);
	}
}

function addArtifactIfExists(filename: string): void {
	const p = path.join(ARTIFACT_DIR, filename);
	if (fs.existsSync(p) && !backtestState.artifacts.includes(filename)) {
		backtestState.artifacts.push(filename);
		broadcast('artifacts', { artifacts: backtestState.artifacts });
	}
}

function maybeParseMetric(line: string): void {
	let m = line.match(/Final Capital:\s*\$([\d,]+(?:\.\d+)?)/i);
	if (m) {
		backtestState.metrics.finalCapital = Number(m[1].replace(/,/g, ''));
		broadcast('metrics', backtestState.metrics);
		return;
	}

	m = line.match(/Total Return:\s*([+-]?[\d.]+)%/i);
	if (m) {
		backtestState.metrics.totalReturnPct = Number(m[1]);
		broadcast('metrics', backtestState.metrics);
		return;
	}

	m = line.match(/Total Trades:\s*(\d+)/i);
	if (m) {
		backtestState.metrics.totalTrades = Number(m[1]);
		broadcast('metrics', backtestState.metrics);
		return;
	}

	m = line.match(/Win Rate:\s*([\d.]+)%/i);
	if (m) {
		backtestState.metrics.winRatePct = Number(m[1]);
		broadcast('metrics', backtestState.metrics);
		return;
	}

	m = line.match(/Max Drawdown:\s*([+-]?[\d.]+)%/i);
	if (m) {
		backtestState.metrics.maxDrawdownPct = Number(m[1]);
		broadcast('metrics', backtestState.metrics);
	}
}

function handleOutputChunk(chunk: Buffer): void {
	const lines = chunk.toString().split(/\r?\n/);
	for (const line of lines) {
		if (!line.trim()) {
			continue;
		}
		pushLog(line);
		maybeParseMetric(line);

		if (line.includes('Trades saved:')) {
			addArtifactIfExists('phantom_backtest_trades.csv');
		}
		if (line.includes('Report saved:')) {
			addArtifactIfExists('phantom_backtest_report.md');
		}
		if (line.includes('Chart saved:')) {
			addArtifactIfExists('phantom_backtest_results.png');
		}
		if (line.includes('Zone chart saved:')) {
			addArtifactIfExists('phantom_backtest_zones.png');
		}
	}
}

app.use(express.static('public'));
app.use(express.json());

app.get('/platform/config', (_req: Request, res: Response): void => {
	const dataFiles = Object.fromEntries(
		Object.entries(DEFAULT_DATA_FILES).map(([symbol, filePath]) => [
			symbol,
			{
				filePath,
				exists: fileExists(filePath),
			},
		]),
	);

	res.json({
		workspaceRoot: WORKSPACE_ROOT,
		defaultDataFiles: dataFiles,
		defaultTradesFile: {
			filePath: DEFAULT_TRADES_FILE,
			exists: fileExists(DEFAULT_TRADES_FILE),
		},
		defaultReportFile: {
			filePath: DEFAULT_REPORT_FILE,
			exists: fileExists(DEFAULT_REPORT_FILE),
		},
		supportedTimeframes: ['1m', '5m', '15m', '1h', '4h'],
	});
});

app.get('/platform/candles', (req: Request, res: Response): void => {
	try {
		const symbol = String(req.query.symbol || 'XAUUSD').toUpperCase();
		const timeframe = String(req.query.timeframe || '15m');
		const maxPoints = parsePositiveInt(req.query.maxPoints, 5000);

		const userDataFile = typeof req.query.dataFile === 'string' ? req.query.dataFile : '';
		const selectedFile = userDataFile || DEFAULT_DATA_FILES[symbol] || DEFAULT_DATA_FILES.XAUUSD;
		if (!selectedFile) {
			res.status(400).json({ error: 'No data file provided and no default found for symbol.' });
			return;
		}

		const candles = getCandles(selectedFile, timeframe);
		const fromMs = parseDateToMs(req.query.from);
		const toMs = parseDateToMs(req.query.to);

		let filtered = candles;
		if (fromMs !== undefined) {
			filtered = filtered.filter((c) => c.ts >= fromMs);
		}
		if (toMs !== undefined) {
			filtered = filtered.filter((c) => c.ts <= toMs);
		}

		let sampled = filtered;
		if (filtered.length > maxPoints) {
			const stride = Math.ceil(filtered.length / maxPoints);
			sampled = filtered.filter((_, idx) => idx % stride === 0);
		}

		res.json({
			symbol,
			timeframe,
			dataFile: normalizePath(selectedFile),
			rawCount: candles.length,
			filteredCount: filtered.length,
			returnedCount: sampled.length,
			candles: sampled,
			range: {
				from: sampled.length ? new Date(sampled[0].ts).toISOString() : null,
				to: sampled.length ? new Date(sampled[sampled.length - 1].ts).toISOString() : null,
			},
		});
	} catch (error) {
		res.status(400).json({ error: (error as Error).message });
	}
});

app.get('/platform/zones', (req: Request, res: Response): void => {
	try {
		const symbol = String(req.query.symbol || 'XAUUSD').toUpperCase();
		const timeframe = String(req.query.timeframe || '15m');
		const maxZones = Math.max(1, Math.min(8, parsePositiveInt(req.query.maxZones, 3)));

		const userDataFile = typeof req.query.dataFile === 'string' ? req.query.dataFile : '';
		const selectedFile = userDataFile || DEFAULT_DATA_FILES[symbol] || DEFAULT_DATA_FILES.XAUUSD;
		if (!selectedFile) {
			res.status(400).json({ error: 'No data file provided and no default found for symbol.' });
			return;
		}

		const candles = getCandles(selectedFile, timeframe);
		const fromMs = parseDateToMs(req.query.from);
		const toMs = parseDateToMs(req.query.to);

		let filtered = candles;
		if (fromMs !== undefined) {
			filtered = filtered.filter((c) => c.ts >= fromMs);
		}
		if (toMs !== undefined) {
			filtered = filtered.filter((c) => c.ts <= toMs);
		}

		if (!filtered.length) {
			res.json({
				symbol,
				timeframe,
				dataFile: normalizePath(selectedFile),
				count: 0,
				zones: [],
			});
			return;
		}

		const zones = buildSupportResistanceZones(filtered, maxZones);
		res.json({
			symbol,
			timeframe,
			dataFile: normalizePath(selectedFile),
			count: zones.length,
			zones,
			latestClose: filtered[filtered.length - 1].close,
		});
	} catch (error) {
		res.status(400).json({ error: (error as Error).message });
	}
});

app.get('/platform/trades', (req: Request, res: Response): void => {
	try {
		const tradesFile = typeof req.query.tradesFile === 'string' && req.query.tradesFile
			? req.query.tradesFile
			: DEFAULT_TRADES_FILE;

		const trades = getOrLoadTrades(tradesFile);
		const fromMs = parseDateToMs(req.query.from);
		const toMs = parseDateToMs(req.query.to);

		let filtered = trades;
		if (fromMs !== undefined) {
			filtered = filtered.filter((t) => {
				const ms = Date.parse(t.entry_time);
				return Number.isFinite(ms) ? ms >= fromMs : false;
			});
		}
		if (toMs !== undefined) {
			filtered = filtered.filter((t) => {
				const ms = Date.parse(t.entry_time);
				return Number.isFinite(ms) ? ms <= toMs : false;
			});
		}

		res.json({
			tradesFile: normalizePath(tradesFile),
			count: filtered.length,
			trades: filtered,
		});
	} catch (error) {
		res.status(400).json({ error: (error as Error).message });
	}
});

app.get('/platform/report', (req: Request, res: Response): void => {
	try {
		const reportFile = typeof req.query.reportFile === 'string' && req.query.reportFile
			? req.query.reportFile
			: DEFAULT_REPORT_FILE;

		const metrics = getOrLoadReport(reportFile);
		res.json({
			reportFile: normalizePath(reportFile),
			metrics,
		});
	} catch (error) {
		res.status(400).json({ error: (error as Error).message });
	}
});

app.get('/platform/runs', (_req: Request, res: Response): void => {
	const runs = loadRunHistory();
	res.json({
		count: runs.length,
		runs,
	});
});

app.get('/platform/runs/:id', (req: Request, res: Response): void => {
	const runs = loadRunHistory();
	const run = runs.find((entry) => entry.id === req.params.id);
	if (!run) {
		res.status(404).json({ error: 'Run not found' });
		return;
	}
	res.json(run);
});

app.get('/platform/admin/overview', (_req: Request, res: Response): void => {
	const runs = loadRunHistory();
	const directories = Object.fromEntries(ADMIN_SCAN_DIRS.map((dirPath) => [
		path.basename(dirPath),
		{
			path: dirPath,
			exists: fs.existsSync(dirPath),
			entries: listDirectoryEntries(dirPath),
		},
	]));

	res.json({
		workspaceRoot: WORKSPACE_ROOT,
		runHistoryFile: RUN_HISTORY_FILE,
		runs: runs.map((run) => ({ id: run.id, createdAt: run.createdAt, summary: run.summary })),
		directories,
		defaultDataFiles: DEFAULT_DATA_FILES,
		artifactsDir: ARTIFACT_DIR,
		runCount: runs.length,
	});
});

app.get('/platform/admin/export/runs.json', (_req: Request, res: Response): void => {
	const runs = loadRunHistory();
	res.json({
		count: runs.length,
		runs,
	});
});

app.get('/platform/admin/export/runs.csv', (_req: Request, res: Response): void => {
	const runs = loadRunHistory();
	res.setHeader('Content-Type', 'text/csv; charset=utf-8');
	res.setHeader('Content-Disposition', 'attachment; filename="strategy-runs.csv"');
	res.send(runsToCsv(runs));
});

app.get('/admin', (_req: Request, res: Response): void => {
	res.sendFile(path.join(WORKSPACE_ROOT, 'public', 'admin.html'));
});

app.get('/strategy-lab', (_req: Request, res: Response): void => {
	res.sendFile(path.join(WORKSPACE_ROOT, 'public', 'strategy-lab.html'));
});

app.post('/platform/runs', (req: Request, res: Response): void => {
	try {
		if (!req.body || typeof req.body !== 'object') {
			res.status(400).json({ error: 'Invalid run summary payload' });
			return;
		}

		const runs = loadRunHistory();
		const record: StrategyRunRecord = {
			id: createRunId(),
			createdAt: new Date().toISOString(),
			summary: req.body,
		};

		runs.unshift(record);
		saveRunHistory(runs);
		res.status(201).json(record);
	} catch (error) {
		res.status(500).json({ error: (error as Error).message });
	}
});

app.post('/analyze-chart', upload.single('chart'), async (req: Request, res: Response): Promise<void> => {
	try {
		if (!req.file) {
			res.status(400).json({ error: 'No file uploaded' });
			return;
		}

		const analysis = await chartAnalyzer.analyzeChart(req.file.path);
		res.json(analysis);
	} catch (error) {
		console.error('Analysis error:', error);
		res.status(500).json({ error: 'Analysis failed' });
	}
});

app.post('/backtest/start', async (req: Request, res: Response): Promise<void> => {
	if (backtestProc && backtestState.status === 'running') {
		res.status(409).json({ error: 'Backtest already running' });
		return;
	}

	const symbol = String(req.body?.symbol || 'XAUUSD=X');
	const interval = String(req.body?.interval || '1m');
	const lookbackDays = Number(req.body?.lookbackDays ?? req.body?.days ?? 30);
	const capital = Number(req.body?.capital ?? 3720);
	const risk = Number(req.body?.risk ?? 0.01);
	const skipPlots = Boolean(req.body?.skipPlots ?? false);

	fs.mkdirSync(ARTIFACT_DIR, { recursive: true });

	backtestState.status = 'running';
	backtestState.startedAt = new Date().toISOString();
	backtestState.endedAt = undefined;
	backtestState.exitCode = undefined;
	backtestState.logs = [];
	backtestState.metrics = {};
	backtestState.artifacts = [];
	broadcast('status', backtestState);

	const pythonExec = path.join(WORKSPACE_ROOT, '.venv', 'bin', 'python');
	const scriptPath = path.join(WORKSPACE_ROOT, 'phantom_xauusd_backtest.py');
	const args = [
		'-u',
		scriptPath,
		'--symbol', symbol,
		'--interval', interval,
		'--days', String(lookbackDays),
		'--capital', String(capital),
		'--risk', String(risk),
		'--outdir', ARTIFACT_DIR,
	];
	if (skipPlots) {
		args.push('--skip-plots');
	}

	backtestProc = spawn(pythonExec, args, {
		cwd: WORKSPACE_ROOT,
		env: { ...process.env, PYTHONUNBUFFERED: '1' },
	});
	pushLog(`Started backtest: ${pythonExec} ${args.join(' ')}`);

	backtestProc.stdout.on('data', handleOutputChunk);
	backtestProc.stderr.on('data', handleOutputChunk);

	backtestProc.on('close', (code) => {
		backtestState.exitCode = code ?? -1;
		backtestState.status = code === 0 ? 'completed' : 'failed';
		backtestState.endedAt = new Date().toISOString();

		addArtifactIfExists('phantom_backtest_trades.csv');
		addArtifactIfExists('phantom_backtest_report.md');
		addArtifactIfExists('phantom_backtest_results.png');
		addArtifactIfExists('phantom_backtest_zones.png');

		pushLog(`Backtest process exited with code ${backtestState.exitCode}`);
		broadcast('status', backtestState);
		backtestProc = null;
	});

	backtestProc.on('error', (err) => {
		backtestState.status = 'failed';
		backtestState.endedAt = new Date().toISOString();
		pushLog(`Failed to start process: ${err.message}`);
		broadcast('status', backtestState);
		backtestProc = null;
	});

	res.json({ ok: true, state: backtestState });
});

app.post('/backtest/stop', async (_req: Request, res: Response): Promise<void> => {
	if (!backtestProc || backtestState.status !== 'running') {
		res.status(409).json({ error: 'No running backtest' });
		return;
	}

	backtestProc.kill('SIGTERM');
	pushLog('Stop requested by user');
	res.json({ ok: true });
});

app.get('/backtest/status', (_req: Request, res: Response): void => {
	res.json(backtestState);
});

app.get('/backtest/stream', (req: Request, res: Response): void => {
	res.setHeader('Content-Type', 'text/event-stream');
	res.setHeader('Cache-Control', 'no-cache');
	res.setHeader('Connection', 'keep-alive');
	res.flushHeaders();

	sseClients.add(res);
	res.write(`event: snapshot\ndata: ${JSON.stringify(backtestState)}\n\n`);

	req.on('close', () => {
		sseClients.delete(res);
		res.end();
	});
});

app.get('/backtest/artifacts/:name', (req: Request, res: Response): void => {
	const allowed = new Set([
		'phantom_backtest_trades.csv',
		'phantom_backtest_report.md',
		'phantom_backtest_results.png',
		'phantom_backtest_zones.png',
	]);
	const filename = req.params.name;

	if (!allowed.has(filename)) {
		res.status(404).json({ error: 'Artifact not found' });
		return;
	}

	const absPath = path.join(ARTIFACT_DIR, filename);
	if (!fs.existsSync(absPath)) {
		res.status(404).json({ error: 'Artifact not generated yet' });
		return;
	}

	res.sendFile(absPath);
});

const PORT = process.env.PORT || 3000;

const startServer = async () => {
	try {
		app.listen(PORT, () => {
			console.log(`Server running on port ${PORT}`);
		});
	} catch (error) {
		console.error('Failed to start server:', error);
		process.exit(1);
	}
};

startServer();
