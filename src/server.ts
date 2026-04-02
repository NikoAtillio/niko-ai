import express, { Request, Response } from 'express';
import multer from 'multer';
import path from 'path';
import fs from 'fs';
import { spawn, ChildProcessWithoutNullStreams } from 'child_process';
import { ChartAIAnalyzer } from './services/ChartAIAnalyzer';

const app = express();

const upload = multer({ dest: 'uploads/' });
const datasetUpload = multer({ dest: path.join('uploads', '_incoming') });
const chartAnalyzer = new ChartAIAnalyzer();

const WORKSPACE_ROOT = process.cwd();
const UPLOADS_DIR = path.join(WORKSPACE_ROOT, 'uploads');
const DATASET_STORAGE_DIR = path.join(UPLOADS_DIR, 'datasets');
const DATASET_ALIAS_FILE = path.join(WORKSPACE_ROOT, 'config', 'dataset-symbol-aliases.json');
const ARTIFACT_DIR = path.join(WORKSPACE_ROOT, 'backtest_artifacts');
const RUN_HISTORY_DIR = path.join(WORKSPACE_ROOT, 'saved_runs');
const RUN_HISTORY_FILE = path.join(RUN_HISTORY_DIR, 'strategy_runs.json');
const STRATEGY_LIBRARY_FILE = path.join(RUN_HISTORY_DIR, 'strategy_library.json');
const RUN_HISTORY_LIMIT = 100;
const STRATEGY_LIBRARY_LIMIT = 250;
const ADMIN_SCAN_DIRS = [
	UPLOADS_DIR,
	ARTIFACT_DIR,
	RUN_HISTORY_DIR,
];

const DEFAULT_DATA_FILES: Record<string, string> = {
	XAUUSD: '/Users/niko/Downloads/XAUUSD_M1_202404010105_202603302033.csv',
	NAS100: '/Users/niko/Downloads/NAS100_M1_202404010105_202603302033.csv',
};

const DEFAULT_DATASET_SYMBOL_ALIASES: Record<string, string> = {
	BTC: 'BTCUSD',
	XAU: 'XAUUSD',
	US1002324: 'US100',
	US1002425: 'US100',
	US1002526: 'US100',
};

function loadDatasetSymbolAliases(): Record<string, string> {
	try {
		if (!fileExists(DATASET_ALIAS_FILE)) {
			return { ...DEFAULT_DATASET_SYMBOL_ALIASES };
		}

		const raw = fs.readFileSync(DATASET_ALIAS_FILE, 'utf8');
		const parsed = JSON.parse(raw);
		if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
			return { ...DEFAULT_DATASET_SYMBOL_ALIASES };
		}

		const out: Record<string, string> = {};
		for (const [key, value] of Object.entries(parsed as Record<string, unknown>)) {
			const alias = normalizeSymbolToken(String(key || ''));
			const canonical = normalizeSymbolToken(String(value || ''));
			if (!alias || !canonical || alias === canonical) {
				continue;
			}
			out[alias] = canonical;
		}

		return Object.keys(out).length ? out : { ...DEFAULT_DATASET_SYMBOL_ALIASES };
	} catch {
		return { ...DEFAULT_DATASET_SYMBOL_ALIASES };
	}
}

const DATASET_SYMBOL_ALIASES = loadDatasetSymbolAliases();

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
	linkedRunId?: string;
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

interface StrategyRecognitionInput {
	theoryText: string;
	templateName?: string;
	market: string;
	primaryTimeframe: string;
	riskPerTradePct: number;
	zoneWidthPct: number;
	minTouches: number;
	confirmation: string;
	dataFile?: string;
}

interface StrategyRecognitionResult {
	name: string;
	strategyType: string;
	confidence: number;
	confidenceBand?: 'low' | 'medium' | 'high';
	market: string;
	primaryTimeframe: string;
	timeframes: string[];
	sessions: string[];
	indicators: string[];
	entryStyle: string;
	stopStyle: string;
	targetStyle: string;
	bias: 'long' | 'short' | 'both' | 'neutral';
	objective: string;
	rules: Record<string, unknown>;
	notes: string[];
}

interface StrategyExecutionConfig {
	schemaVersion: string;
	emittedAt: string;
	name: string;
	market: string;
	execution: {
		primaryTimeframe: string;
		engineInterval: string;
		timeframes: string[];
		bias: 'long' | 'short' | 'both' | 'neutral';
		sessions: string[];
	};
	risk: {
		riskPerTradePct: number;
		zoneWidthPct: number;
		minTouches: number;
		rrTarget: number | null;
	};
	entry: {
		style: string;
		confirmation: string;
		invalidation: string;
	};
	exit: {
		targetStyle: string;
		objective: string;
	};
	indicators: string[];
	metadata: {
		strategyType: string;
		confidence: number;
		confidenceBand: 'low' | 'medium' | 'high';
		parserVersion: string;
		templateName: string;
		dataFile?: string;
	};
	notes: string[];
}

interface DatasetFileRef {
	timeframe: string;
	filePath: string;
	size: number;
}

interface MarketDataset {
	symbol: string;
	timeframes: string[];
	files: DatasetFileRef[];
	defaultDataFile: string | null;
}

interface StrategyDefinitionRecord {
	id: string;
	createdAt: string;
	updatedAt: string;
	status: 'draft' | 'confirmed';
	theoryText: string;
	recognition: StrategyRecognitionResult;
	strategyConfig: StrategyExecutionConfig;
}

interface StrategyProofExample {
	id: string;
	title: string;
	rationale: string;
	confidence: number;
	centerTs: number;
	centerPrice: number;
	window: CandleRecord[];
	overlays: Array<{
		kind: 'hline' | 'vline' | 'box' | 'channel';
		label: string;
		price?: number;
		ts?: number;
		startTs?: number;
		endTs?: number;
		low?: number;
		high?: number;
		upperStartPrice?: number;
		upperEndPrice?: number;
		lowerStartPrice?: number;
		lowerEndPrice?: number;
	}>;
}

const MAX_LOG_LINES = 2000;

const backtestState: BacktestState = {
	status: 'idle',
	logs: [],
	metrics: {},
	artifacts: [],
};

let backtestProc: ChildProcessWithoutNullStreams | null = null;
let activeStrategyLabRunId: string | null = null;
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

function loadStrategyLibrary(): StrategyDefinitionRecord[] {
	try {
		if (!fs.existsSync(STRATEGY_LIBRARY_FILE)) {
			return [];
		}
		const text = fs.readFileSync(STRATEGY_LIBRARY_FILE, 'utf8');
		const parsed = JSON.parse(text);
		return Array.isArray(parsed) ? parsed : [];
	} catch {
		return [];
	}
}

function saveStrategyLibrary(records: StrategyDefinitionRecord[]): void {
	fs.mkdirSync(RUN_HISTORY_DIR, { recursive: true });
	fs.writeFileSync(
		STRATEGY_LIBRARY_FILE,
		`${JSON.stringify(records.slice(0, STRATEGY_LIBRARY_LIMIT), null, 2)}\n`,
		'utf8',
	);
}

function createRunId(): string {
	return `run_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
}

function createStrategyId(): string {
	return `strategy_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
}

function normalizeStrategyText(input: string): string {
	return input
		.replace(/\r/g, ' ')
		.replace(/\n+/g, ' ')
		.replace(/[\t]+/g, ' ')
		.replace(/\s+/g, ' ')
		.trim();
}

function toLowerStrategyText(input: string): string {
	return normalizeStrategyText(input).toLowerCase();
}

function extractUniqueMatches(input: string, regex: RegExp): string[] {
	const matches = new Set<string>();
	let match: RegExpExecArray | null;
	const flags = regex.flags.includes('g') ? regex.flags : `${regex.flags}g`;
	const scanner = new RegExp(regex.source, flags);
	while ((match = scanner.exec(input)) !== null) {
		const value = match[1] || match[0];
		if (value) {
			matches.add(String(value).toUpperCase());
		}
	}
	return Array.from(matches);
}

function detectBias(text: string): 'long' | 'short' | 'both' | 'neutral' {
	const hasLong = /\b(long|buy|bullish|upside|support)\b/.test(text);
	const hasShort = /\b(short|sell|bearish|downside|resistance)\b/.test(text);
	if (hasLong && hasShort) {
		return 'both';
	}
	if (hasLong) {
		return 'long';
	}
	if (hasShort) {
		return 'short';
	}
	return 'neutral';
}

function detectArchetype(text: string): string {
	if (/\b(news trading|event[-\s]?driven|economic report|economic release|cpi|nfp|fomc|earnings)\b/.test(text)) {
		return 'News Trading';
	}
	if (/\b(gap trading|price gap|opening gap|gap fill|gap continuation|gap reversal)\b/.test(text)) {
		return 'Gap Trading';
	}
	if (/\b(trend trading)\b/.test(text)) {
		return 'Trend Trading';
	}
	if (/\b(range trading)\b/.test(text)) {
		return 'Range Trading';
	}
	if (/\b(breakout trading)\b/.test(text)) {
		return 'Breakout Trading';
	}
	if (/\b(scalping|scalp trading)\b/.test(text)) {
		return 'Scalping';
	}
	if (/\b(swing trading)\b/.test(text)) {
		return 'Swing Trading';
	}
	if (/\b(position trading)\b/.test(text)) {
		return 'Position Trading';
	}
	if (/\b(position trading|long[-\s]?term|multi[-\s]?month|multi[-\s]?year|hold for months|hold for years)\b/.test(text)) {
		return 'Position Trading';
	}
	if (/\b(swing trading|price swings?|multi[-\s]?day|multi[-\s]?week|days or weeks|correction within trend)\b/.test(text)) {
		return 'Swing Trading';
	}
	if (/\b(scalp|scalping|very short[-\s]?term|small frequent profits?)\b/.test(text)) {
		return 'Scalping';
	}
	if (/\b(support and resistance|support\/resistance|s\/r|zone|retest|rejection)\b/.test(text)) {
		return /\b(breakout|break out|break above|break below)\b/.test(text)
			? 'Support / Resistance Breakout'
			: 'Support / Resistance Mean Reversion';
	}
	if (/\b(range trading|consolidat(?:e|ing|ion)|sideways market|market range|channel|range[-\s]?bound)\b/.test(text)) {
		return 'Range Trading';
	}
	if (/\b(breakout trading|breakout|break out|break above|break below|new trend starts?)\b/.test(text)) {
		return 'Breakout Trading';
	}
	if (/\b(trend trading|trend follow(?:ing)?|momentum|continuation|pullback|higher high|higher low|lower high|lower low|moving averages?)\b/.test(text)) {
		return 'Trend Trading';
	}
	if (/\b(mean reversion|revert|overbought|oversold|bounce back|fade)\b/.test(text)) {
		return 'Mean Reversion';
	}
	return 'Rule-Based Strategy';
}

function detectEntryStyle(text: string): string {
	if (/\b(news release|event trigger|post[-\s]?news)\b/.test(text)) {
		return 'Event trigger';
	}
	if (/\b(gap fill|gap continuation|open[-\s]?drive)\b/.test(text)) {
		return 'Gap pattern entry';
	}
	if (/\b(rejection candle|pin bar|wick rejection|rejection close)\b/.test(text)) {
		return 'Rejection candle';
	}
	if (/\b(break and retest|retest)\b/.test(text)) {
		return 'Break and retest';
	}
	if (/\b(momentum close|close above|close below|impulse close)\b/.test(text)) {
		return 'Momentum close';
	}
	if (/\b(crossover|cross over|golden cross|death cross)\b/.test(text)) {
		return 'Crossover';
	}
	if (/\b(pullback|retracement)\b/.test(text)) {
		return 'Pullback entry';
	}
	if (/\b(touch|tap|test of)\b/.test(text)) {
		return 'Level touch';
	}
	return 'Rule confirmation';
}

function detectStopStyle(text: string): string {
	if (/\b(atr|average true range)\b/.test(text)) {
		return 'ATR based';
	}
	if (/\b(swing low|swing high|below swing|above swing)\b/.test(text)) {
		return 'Swing structure';
	}
	if (/\b(zone boundary|beyond zone|outside zone)\b/.test(text)) {
		return 'Beyond zone';
	}
	if (/\b(fixed stop|hard stop|static stop)\b/.test(text)) {
		return 'Fixed stop';
	}
	if (/\b(pip|point)\b/.test(text)) {
		return 'Fixed distance';
	}
	return 'Structural stop';
}

function detectTargetStyle(text: string): string {
	if (/\b(\d+(?:\.\d+)?)\s*r\b/.test(text)) {
		return 'R multiple target';
	}
	if (/\b(next zone|opposite zone|next resistance|next support)\b/.test(text)) {
		return 'Next zone target';
	}
	if (/\b(trail|trailing stop|runner)\b/.test(text)) {
		return 'Trailing target';
	}
	if (/\b(vwap|ema|sma|moving average)\b/.test(text)) {
		return 'Indicator target';
	}
	return 'Fixed profit target';
}

function detectSessions(text: string): string[] {
	const sessions: string[] = [];
	if (/\b(london|london session|uk session)\b/.test(text)) sessions.push('London');
	if (/\b(new york|ny session|us session|nyc)\b/.test(text)) sessions.push('New York');
	if (/\b(asia|asian session|tokyo)\b/.test(text)) sessions.push('Asia');
	if (/\b(frankfurt|european session|eu session)\b/.test(text)) sessions.push('Frankfurt');
	return sessions;
}

function detectIndicators(text: string): string[] {
	const indicators = new Set<string>();
	if (/\b(ema|ema\d+)\b/.test(text)) indicators.add('EMA');
	if (/\b(sma|ma\d+|moving average)\b/.test(text)) indicators.add('Moving Average');
	if (/\b(rsi)\b/.test(text)) indicators.add('RSI');
	if (/\b(macd)\b/.test(text)) indicators.add('MACD');
	if (/\b(vwap)\b/.test(text)) indicators.add('VWAP');
	if (/\b(atr)\b/.test(text)) indicators.add('ATR');
	if (/\b(bollinger|bbands|bollinger bands)\b/.test(text)) indicators.add('Bollinger Bands');
	if (/\b(adx)\b/.test(text)) indicators.add('ADX');
	if (/\b(stochastic|stoch)\b/.test(text)) indicators.add('Stochastic');
	if (/\b(volume|vol)\b/.test(text)) indicators.add('Volume');
	if (/\b(ichimoku)\b/.test(text)) indicators.add('Ichimoku');
	return Array.from(indicators);
}

function detectTimeframes(text: string, primaryTimeframe: string): string[] {
	const timeframes = new Set<string>([primaryTimeframe || 'H1']);
	extractUniqueMatches(text, /\b(M1|M5|M15|M30|H1|H4|D1|W1)\b/).forEach((tf) => timeframes.add(tf));
	if (/\b(1m|5m|15m|30m|1h|4h|1d|daily|weekly)\b/.test(text)) {
		if (/\b1m\b/.test(text)) timeframes.add('M1');
		if (/\b5m\b/.test(text)) timeframes.add('M5');
		if (/\b15m\b/.test(text)) timeframes.add('M15');
		if (/\b30m\b/.test(text)) timeframes.add('M30');
		if (/\b1h\b/.test(text)) timeframes.add('H1');
		if (/\b4h\b/.test(text)) timeframes.add('H4');
		if (/\b1d\b|\bdaily\b/.test(text)) timeframes.add('D1');
		if (/\bweekly\b/.test(text)) timeframes.add('W1');
	}
	return Array.from(timeframes);
}

function inferPrimaryTimeframeFromText(text: string, fallback: string): string {
	const normalized = String(text || '').toUpperCase();
	const matches = [...normalized.matchAll(/\b(M1|M5|M15|M30|H1|H4|D1|W1|MN1|1M|5M|15M|30M|1H|4H|1D|1W|1MO|DAILY|WEEKLY|MONTHLY)\b/g)];
	if (!matches.length) {
		return fallback;
	}

	const normalize = (tf: string): string => {
		if (tf === '1M') return 'M1';
		if (tf === '5M') return 'M5';
		if (tf === '15M') return 'M15';
		if (tf === '30M') return 'M30';
		if (tf === '1H') return 'H1';
		if (tf === '4H') return 'H4';
		if (tf === '1D' || tf === 'DAILY') return 'D1';
		if (tf === '1W' || tf === 'WEEKLY') return 'W1';
		if (tf === '1MO' || tf === 'MONTHLY') return 'MN1';
		return tf;
	};

	const preferredOrder: Record<string, number> = {
		MN1: 1,
		W1: 2,
		D1: 3,
		H4: 4,
		H1: 5,
		M30: 6,
		M15: 7,
		M5: 8,
		M1: 9,
	};

	const normalizedMatches = matches.map((m) => normalize(m[1] || ''));
	normalizedMatches.sort((a, b) => (preferredOrder[a] || 99) - (preferredOrder[b] || 99));
	return normalizedMatches[0] || fallback;
}

function detectMinTouches(text: string, fallback: number): number {
	const matches = [...text.matchAll(/(?:min(?:imum)?\s+)?(?:touch(?:es)?|tests?)\s*(?:of)?\s*(\d+)/gi)];
	if (matches.length) {
		const values = matches.map((m) => Number(m[1])).filter((n) => Number.isFinite(n) && n > 0);
		if (values.length) {
			return Math.max(...values);
		}
	}
	return fallback;
}

function detectRiskMultiple(text: string): number | undefined {
	const match = text.match(/(\d+(?:\.\d+)?)\s*r\b/i);
	if (match) {
		const value = Number(match[1]);
		return Number.isFinite(value) ? value : undefined;
	}
	return undefined;
}

function detectConfidence(metrics: {
	strategyType: string;
	entryStyle: string;
	stopStyle: string;
	targetStyle: string;
	timeframes: string[];
	sessions: string[];
	indicators: string[];
	text: string;
	}): { confidence: number; band: 'low' | 'medium' | 'high'; notes: string[] } {
	let score = 0.5;
	const notes: string[] = ['Converted from plain-language theory into deterministic rule blocks.'];

	if (metrics.strategyType !== 'Rule-Based Strategy') {
		score += 0.14;
		notes.push(`Detected archetype: ${metrics.strategyType}.`);
	}
	if (/\b(trend trading|range trading|breakout trading|scalping|swing trading|position trading|news trading|gap trading)\b/.test(metrics.text)) {
		score += 0.05;
	}
	if (metrics.entryStyle !== 'Rule confirmation') score += 0.08;
	if (metrics.stopStyle !== 'Structural stop') score += 0.06;
	if (metrics.targetStyle !== 'Fixed profit target') score += 0.06;
	if (metrics.timeframes.length > 1) score += 0.06;
	if (metrics.sessions.length) score += 0.04;
	if (metrics.indicators.length) score += Math.min(0.08, metrics.indicators.length * 0.02);
	if (/\b(\d+(?:\.\d+)?)\s*r\b/.test(metrics.text)) score += 0.04;
	if (/\b(\d+(?:\.\d+)?)%\b/.test(metrics.text)) score += 0.03;

	score = Math.max(0.45, Math.min(0.95, score));
	const band: 'low' | 'medium' | 'high' = score >= 0.8 ? 'high' : score >= 0.62 ? 'medium' : 'low';
	return { confidence: score, band, notes };
}

function parseStrategyTemplateText(templateText: string): Record<string, unknown> | null {
	const trimmed = templateText.trim();
	if (!trimmed) {
		return null;
	}

	try {
		const parsed = JSON.parse(trimmed);
		if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
			return parsed as Record<string, unknown>;
		}
	} catch {
		// fall through to text parsing
	}

	return null;
}

function normalizeStrategyInput(input: StrategyRecognitionInput & { templateText?: string }): StrategyRecognitionInput {
	const templateObject = input.templateText ? parseStrategyTemplateText(input.templateText) : null;
	const templateTheory = templateObject
		? String(templateObject.theoryText || templateObject.strategyText || templateObject.description || '').trim()
		: '';
	const theoryText = templateTheory || input.theoryText;
	const fallbackPrimary = String(templateObject?.primaryTimeframe || templateObject?.timeframe || input.primaryTimeframe || 'H4').toUpperCase();
	const inferredPrimary = inferPrimaryTimeframeFromText(theoryText, fallbackPrimary);
	return {
		theoryText,
		templateName: input.templateName,
		market: String(templateObject?.market || input.market || 'BTCUSD').toUpperCase(),
		primaryTimeframe: inferredPrimary,
		riskPerTradePct: toNumber(templateObject?.riskPerTradePct ?? templateObject?.riskPct ?? input.riskPerTradePct, input.riskPerTradePct),
		zoneWidthPct: toNumber(templateObject?.zoneWidthPct ?? input.zoneWidthPct, input.zoneWidthPct),
		minTouches: Math.max(1, parsePositiveInt(templateObject?.minTouches ?? input.minTouches, input.minTouches)),
		confirmation: String(templateObject?.confirmation || input.confirmation || 'Rejection candle'),
		dataFile: String(templateObject?.dataFile || input.dataFile || ''),
	};
}

function getRunSummaryObject(run: StrategyRunRecord): Record<string, unknown> {
	if (!run.summary || typeof run.summary !== 'object') {
		return {};
	}
	return run.summary as Record<string, unknown>;
}

function isStrategyLabRun(run: StrategyRunRecord): boolean {
	const summary = getRunSummaryObject(run);
	return summary.source === 'strategy-lab';
}

function updateRunSummary(runId: string, patch: Record<string, unknown>): boolean {
	const runs = loadRunHistory();
	const idx = runs.findIndex((run) => run.id === runId);
	if (idx === -1) {
		return false;
	}

	const currentSummary = getRunSummaryObject(runs[idx]);
	runs[idx] = {
		...runs[idx],
		summary: {
			...currentSummary,
			...patch,
			updatedAt: new Date().toISOString(),
		},
	};

	saveRunHistory(runs);
	return true;
}

function getStrategyLabRuns(limit = 20): StrategyRunRecord[] {
	const allRuns = loadRunHistory();
	const filtered = allRuns.filter((run) => isStrategyLabRun(run));
	return filtered
		.sort((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt))
		.slice(0, Math.max(1, limit));
}

function getNextQueuedStrategyLabRun(): StrategyRunRecord | null {
	const runs = loadRunHistory().filter((run) => {
		if (!isStrategyLabRun(run)) {
			return false;
		}
		const summary = getRunSummaryObject(run);
		return summary.status === 'queued';
	});

	if (!runs.length) {
		return null;
	}

	runs.sort((a, b) => Date.parse(a.createdAt) - Date.parse(b.createdAt));
	return runs[0] || null;
}

function maybeStartNextQueuedStrategyLabRun(): void {
	if (backtestProc && backtestState.status === 'running') {
		return;
	}

	const nextRun = getNextQueuedStrategyLabRun();
	if (!nextRun) {
		return;
	}

	const summary = getRunSummaryObject(nextRun);
	const symbol = String(summary.market || 'XAUUSD=X');
	const interval = String(summary.interval || '1m');
	const lookbackDays = Math.max(1, parsePositiveInt(summary.lookbackDays, 30));
	const capital = toNumber(summary.capital, 10000);
	const risk = toNumber(summary.risk, 0.01);

	const started = startBacktestExecution({
		symbol,
		interval,
		lookbackDays,
		capital,
		risk,
		skipPlots: false,
		linkedRunId: nextRun.id,
	});

	if (!started.ok) {
		updateRunSummary(nextRun.id, {
			status: 'queued',
			queueReason: started.error || 'Engine busy',
		});
		return;
	}

	pushLog(`Auto-drain started queued strategy-lab run ${nextRun.id}`);
}

function toNumber(input: unknown, fallbackValue: number): number {
	const n = Number(input);
	return Number.isFinite(n) ? n : fallbackValue;
}

function normalizeTheoryText(input: unknown): string {
	if (typeof input !== 'string') {
		return '';
	}
	return input.trim();
}

function detectDatasetTimeframe(input: string): string | null {
	const text = String(input || '').toUpperCase();
	const hasToken = (token: string): boolean => {
		const rx = new RegExp(`(^|[^A-Z0-9])${token}([^A-Z0-9]|$)`);
		return rx.test(text);
	};

	if (hasToken('M1') || hasToken('1M')) return '1m';
	if (hasToken('M5') || hasToken('5M')) return '5m';
	if (hasToken('M15') || hasToken('15M')) return '15m';
	if (hasToken('M30') || hasToken('30M')) return '30m';
	if (hasToken('H1') || hasToken('1H')) return '1h';
	if (hasToken('H4') || hasToken('4H')) return '4h';
	if (hasToken('D1') || hasToken('1D') || hasToken('DAILY')) return '1d';
	if (hasToken('W1') || hasToken('1W') || hasToken('WEEKLY')) return '1w';
	if (hasToken('MN1') || hasToken('1MO') || hasToken('MONTHLY')) return '1mo';
	return null;
}

function normalizeSymbolToken(input: string): string {
	return input
		.replace(/\.(CSV|TXT)$/i, '')
		.replace(/\.(CASH|SPOT|IDX)$/i, '')
		.replace(/[^A-Za-z0-9]/g, '')
		.toUpperCase();
}

function canonicalizeDatasetSymbol(input: string): string {
	let symbol = normalizeSymbolToken(input);
	let guard = 0;
	while (DATASET_SYMBOL_ALIASES[symbol] && guard < 10) {
		symbol = DATASET_SYMBOL_ALIASES[symbol];
		guard += 1;
	}
	return symbol;
}

function guessSymbolFromPath(filePath: string): string {
	const base = path.basename(filePath);
	const baseNoExt = base.replace(/\.[^.]+$/, '');
	const tfMatch = baseNoExt.match(/^(.*?)[._-](M1|M5|M15|M30|H1|H4|D1|W1|MN1|DAILY|WEEKLY|MONTHLY)(?:[^A-Za-z0-9]|$)/i);
	if (tfMatch && tfMatch[1]) {
		const fromName = normalizeSymbolToken(tfMatch[1]);
		if (fromName) {
			return fromName;
		}
	}

	const dirParts = normalizePath(filePath).split(path.sep).filter(Boolean);
	for (let i = dirParts.length - 2; i >= 0; i -= 1) {
		const token = normalizeSymbolToken(dirParts[i]);
		if (token && !detectDatasetTimeframe(token) && token !== 'UPLOADS' && token !== 'DATASETS') {
			return token;
		}
	}

	return '';
}

function walkDatasetFiles(rootDir: string, depth = 0, maxDepth = 6): string[] {
	if (depth > maxDepth || !fileExists(rootDir)) {
		return [];
	}

	const out: string[] = [];
	let entries: fs.Dirent[] = [];
	try {
		entries = fs.readdirSync(rootDir, { withFileTypes: true });
	} catch {
		return out;
	}

	for (const entry of entries) {
		const fullPath = path.join(rootDir, entry.name);
		if (entry.isDirectory()) {
			out.push(...walkDatasetFiles(fullPath, depth + 1, maxDepth));
			continue;
		}
		if (!entry.isFile()) {
			continue;
		}

		if (!detectDatasetTimeframe(entry.name)) {
			continue;
		}
		out.push(fullPath);
	}

	return out;
}

function getMarketDatasets(): MarketDataset[] {
	const uploadsRoot = DATASET_STORAGE_DIR;
	const discoveredFiles = walkDatasetFiles(uploadsRoot);
	const byMarket = new Map<string, Map<string, DatasetFileRef>>();

	for (const filePath of discoveredFiles) {
		const timeframe = detectDatasetTimeframe(path.basename(filePath));
		if (!timeframe) {
			continue;
		}

		const symbol = canonicalizeDatasetSymbol(guessSymbolFromPath(filePath));
		if (!symbol) {
			continue;
		}

		let size = 0;
		try {
			size = fs.statSync(filePath).size;
		} catch {
			continue;
		}

		if (!byMarket.has(symbol)) {
			byMarket.set(symbol, new Map<string, DatasetFileRef>());
		}

		const marketFiles = byMarket.get(symbol) as Map<string, DatasetFileRef>;
		const current = marketFiles.get(timeframe);
		if (!current || size >= current.size) {
			marketFiles.set(timeframe, {
				timeframe,
				filePath: normalizePath(filePath),
				size,
			});
		}
	}

	const timeframeOrder: Record<string, number> = {
		'1m': 1,
		'5m': 2,
		'15m': 3,
		'30m': 4,
		'1h': 5,
		'4h': 6,
		'1d': 7,
		'1w': 8,
		'1mo': 9,
	};

	const markets: MarketDataset[] = [];
	for (const [symbol, filesByTf] of byMarket.entries()) {
		const files = Array.from(filesByTf.values()).sort(
			(a, b) => (timeframeOrder[a.timeframe] || 99) - (timeframeOrder[b.timeframe] || 99),
		);
		const timeframes = files.map((f) => f.timeframe);
		const defaultDataFile = files.find((f) => f.timeframe === '1m')?.filePath || files[0]?.filePath || null;
		markets.push({
			symbol,
			timeframes,
			files,
			defaultDataFile,
		});
	}

	markets.sort((a, b) => a.symbol.localeCompare(b.symbol));
	return markets;
}

function resolveStrategyDataFile(symbolInput: string, requestedFileInput: string): string {
	const symbol = canonicalizeDatasetSymbol(String(symbolInput || ''));
	const requestedFile = String(requestedFileInput || '').trim();

	if (requestedFile) {
		const resolvedRequested = normalizePath(requestedFile);
		if (!isPathInsideDirectory(resolvedRequested, DATASET_STORAGE_DIR)) {
			throw new Error('dataFile must be inside hosted dataset storage');
		}
		if (!fileExists(resolvedRequested)) {
			throw new Error(`Hosted dataFile not found: ${resolvedRequested}`);
		}
		return resolvedRequested;
	}

	const discovered = getMarketDatasets();
	const match = discovered.find((item) => item.symbol === symbol);
	if (match?.defaultDataFile) {
		return match.defaultDataFile;
	}

	const fallback = DEFAULT_DATA_FILES[symbol] || DEFAULT_DATA_FILES.XAUUSD;
	if (!fallback) {
		throw new Error(`No dataset found for symbol ${symbol}`);
	}
	return normalizePath(fallback);
}

function buildRecognition(input: StrategyRecognitionInput): StrategyRecognitionResult {
	const text = normalizeStrategyText(input.theoryText);
	const lower = toLowerStrategyText(text);
	const strategyType = detectArchetype(lower);
	const entryStyle = detectEntryStyle(lower);
	const stopStyle = detectStopStyle(lower);
	const targetStyle = detectTargetStyle(lower);
	const bias = detectBias(lower);
	const sessions = detectSessions(lower);
	const indicators = detectIndicators(lower);
	const timeframes = detectTimeframes(lower, input.primaryTimeframe);
	const minTouches = detectMinTouches(lower, input.minTouches);
	const rrTarget = detectRiskMultiple(lower);
	const confidenceInfo = detectConfidence({
		strategyType,
		entryStyle,
		stopStyle,
		targetStyle,
		timeframes,
		sessions,
		indicators,
		text: lower,
	});

	const hasBreakout = /\b(breakout|break out|break above|break below)\b/.test(lower);
	const hasSupportResistance = strategyType.startsWith('Support / Resistance');
	const name = input.templateName?.trim() || strategyType;
	const objective = rrTarget
		? `Aim for approximately ${rrTarget.toFixed(2)}R per trade while respecting drawdown and stability constraints.`
		: 'Optimize for risk-adjusted return with drawdown and stability constraints.';

	const notes = [
		...confidenceInfo.notes,
		`Entry style: ${entryStyle}.`,
		`Stop model: ${stopStyle}.`,
		`Target model: ${targetStyle}.`,
		bias !== 'neutral' ? `Directional bias: ${bias}.` : 'Directional bias not explicit; treat as neutral unless validated.',
		 sessions.length ? `Trading sessions: ${sessions.join(', ')}.` : 'No session constraint detected.',
		 indicators.length ? `Indicators referenced: ${indicators.join(', ')}.` : 'No indicator dependency detected.',
	];

	if (hasSupportResistance) {
		notes.push(hasBreakout ? 'Structural logic suggests a breakout variant.' : 'Structural logic suggests a mean-reversion zone model.');
	}

	return {
		name,
		strategyType,
		confidence: confidenceInfo.confidence,
		confidenceBand: confidenceInfo.band,
		market: input.market,
		primaryTimeframe: input.primaryTimeframe,
		timeframes,
		sessions,
		indicators,
		entryStyle,
		stopStyle,
		targetStyle,
		bias,
		objective,
		rules: {
			zoneWidthPct: input.zoneWidthPct,
			minTouches,
			confirmation: input.confirmation,
			riskPerTradePct: input.riskPerTradePct,
			entryBias: hasBreakout ? 'trade momentum continuation' : hasSupportResistance ? 'buy support / sell resistance' : bias,
			invalidation: hasSupportResistance ? 'close beyond zone boundary' : 'hard invalidation on rule break',
			positionSizing: 'fixed risk per trade',
			rrTarget: rrTarget ?? null,
			templateName: input.templateName || '',
			parserVersion: 'v2',
			matchedTerms: {
				strategyType,
				entryStyle,
				stopStyle,
				targetStyle,
				sessions,
				indicators,
			},
		},
		notes,
	};
}

function mapTfToEngineInterval(tf: string): string {
	const normalized = String(tf || '').toUpperCase();
	if (normalized === 'M1') return '1m';
	if (normalized === 'M5') return '5m';
	if (normalized === 'M15') return '15m';
	if (normalized === 'M30') return '30m';
	if (normalized === 'H1') return '1h';
	if (normalized === 'H4') return '4h';
	if (normalized === 'D1') return '1d';
	return '1m';
}

function mapUiTfToProofTimeframe(tf: string): string {
	const normalized = String(tf || '').toUpperCase();
	if (normalized === 'M1' || normalized === '1M') return '1m';
	if (normalized === 'M5' || normalized === '5M') return '5m';
	if (normalized === 'M15' || normalized === '15M') return '15m';
	if (normalized === 'M30' || normalized === '30M') return '15m';
	if (normalized === 'H1' || normalized === '1H') return '1h';
	if (normalized === 'H4' || normalized === '4H') return '4h';
	if (normalized === 'D1' || normalized === '1D' || normalized === 'DAILY') return '4h';
	if (normalized === 'W1' || normalized === '1W' || normalized === 'WEEKLY') return '4h';
	if (normalized === 'MN1' || normalized === '1MO' || normalized === 'MONTHLY') return '4h';
	return '15m';
}

function adjustProofTimeframe(baseTimeframe: string, mode: string): string {
	const ladder = ['1m', '5m', '15m', '1h', '4h'];
	const baseIdx = ladder.indexOf(baseTimeframe);
	if (baseIdx < 0) {
		return baseTimeframe;
	}

	const normalizedMode = String(mode || 'base').toLowerCase();
	if (normalizedMode === 'lower') {
		return ladder[Math.max(0, baseIdx - 1)];
	}
	if (normalizedMode === 'higher') {
		return ladder[Math.min(ladder.length - 1, baseIdx + 1)];
	}
	return ladder[baseIdx];
}

function isTrendWindow(candles: CandleRecord[], start: number, end: number, direction: 'up' | 'down'): boolean {
	if (end <= start + 3) {
		return false;
	}
	let impulseBars = 0;
	for (let i = start + 1; i <= end; i += 1) {
		const delta = candles[i].close - candles[i - 1].close;
		if ((direction === 'up' && delta > 0) || (direction === 'down' && delta < 0)) {
			impulseBars += 1;
		}
	}
	return impulseBars / (end - start) >= 0.64;
}

function buildProofWindow(candles: CandleRecord[], centerIndex: number, radius = 36): CandleRecord[] {
	const left = Math.max(0, centerIndex - radius);
	const right = Math.min(candles.length - 1, centerIndex + radius);
	const segment = candles.slice(left, right + 1);
	if (segment.length <= 120) {
		return segment;
	}
	const stride = Math.ceil(segment.length / 120);
	return segment.filter((_, idx) => idx % stride === 0);
}

function clampProbability(value: number): number {
	return Math.max(0.05, Math.min(0.99, value));
}

function pushProofExample(
	out: StrategyProofExample[],
	candles: CandleRecord[],
	idx: number,
	title: string,
	rationale: string,
	confidence: number,
	overlays: StrategyProofExample['overlays'] = [],
): void {
	if (idx < 0 || idx >= candles.length) {
		return;
	}
	const c = candles[idx];
	out.push({
		id: `ex_${c.ts}_${out.length + 1}`,
		title,
		rationale,
		confidence: clampProbability(confidence),
		centerTs: c.ts,
		centerPrice: c.close,
		window: buildProofWindow(candles, idx),
		overlays,
	});
}

function detectStrategyProofExamples(candles: CandleRecord[], strategyType: string, maxExamples: number): StrategyProofExample[] {
	if (candles.length < 40) {
		return [];
	}

	const examples: StrategyProofExample[] = [];
	const ranges = candles.map((c) => Math.max(1e-9, c.high - c.low));
	const avgRange = ranges.reduce((acc, v) => acc + v, 0) / ranges.length;
	const type = String(strategyType || '').toLowerCase();

	if (type.includes('trend')) {
		for (let i = 35; i < candles.length && examples.length < maxExamples; i += 8) {
			const windowStart = Math.max(0, i - 20);
			const windowCandles = candles.slice(windowStart, i + 1);
			const upward = isTrendWindow(candles, windowStart, i, 'up');
			const downward = isTrendWindow(candles, windowStart, i, 'down');
			if (upward || downward) {
				const winBars = windowCandles.filter((c, idx) => idx > 0 && ((upward && c.close > windowCandles[idx - 1].close) || (downward && c.close < windowCandles[idx - 1].close))).length;
				const ratio = winBars / Math.max(1, windowCandles.length - 1);
				const hi = Math.max(...windowCandles.map((c) => c.high));
				const lo = Math.min(...windowCandles.map((c) => c.low));
				const pad = (hi - lo) * 0.18;
				pushProofExample(
					examples,
					candles,
					i,
					'Trend continuation',
					'Sustained directional closes across the lookback window.',
					0.58 + ratio * 0.35,
					[
						{
							kind: 'channel',
							label: 'Trend channel',
							startTs: candles[windowStart].ts,
							endTs: candles[i].ts,
							upperStartPrice: hi,
							upperEndPrice: hi + (upward ? pad : -pad),
							lowerStartPrice: lo,
							lowerEndPrice: lo + (upward ? pad : -pad),
						},
					],
				);
			}
		}
	}

	if (type.includes('range')) {
		for (let i = 28; i < candles.length && examples.length < maxExamples; i += 7) {
			const window = candles.slice(i - 24, i + 1);
			const hi = Math.max(...window.map((c) => c.high));
			const lo = Math.min(...window.map((c) => c.low));
			const width = Math.max(1e-9, hi - lo);
			const narrow = width <= avgRange * 9;
			const touchesHigh = window.filter((c) => c.high >= hi - width * 0.12).length;
			const touchesLow = window.filter((c) => c.low <= lo + width * 0.12).length;
			if (narrow && touchesHigh >= 2 && touchesLow >= 2) {
				const confidence = 0.52 + Math.min(0.42, ((touchesHigh + touchesLow) / 10));
				pushProofExample(
					examples,
					candles,
					i,
					'Range containment',
					'Price repeatedly tests upper and lower boundaries without expansion.',
					confidence,
					[
						{
							kind: 'box',
							label: 'Range box',
							startTs: window[0].ts,
							endTs: window[window.length - 1].ts,
							low: lo,
							high: hi,
						},
					],
				);
			}
		}
	}

	if (type.includes('breakout') || type.includes('support / resistance breakout')) {
		for (let i = 26; i < candles.length && examples.length < maxExamples; i += 5) {
			const prev = candles.slice(i - 20, i);
			const maxPrev = Math.max(...prev.map((c) => c.high));
			const minPrev = Math.min(...prev.map((c) => c.low));
			const breakoutUp = candles[i].close > maxPrev;
			const breakoutDown = candles[i].close < minPrev;
			if (breakoutUp || breakoutDown) {
				const boundary = breakoutUp ? maxPrev : minPrev;
				const impulse = Math.abs(candles[i].close - boundary) / Math.max(1e-9, avgRange);
				pushProofExample(
					examples,
					candles,
					i,
					'Breakout trigger',
					'Close breaches the prior consolidation boundary.',
					0.55 + Math.min(0.38, impulse * 0.12),
					[
						{ kind: 'hline', label: 'Breakout boundary', price: boundary },
						{ kind: 'vline', label: 'Break candle', ts: candles[i].ts },
					],
				);
			}
		}
	}

	if (type.includes('scalp')) {
		for (let i = 5; i < candles.length && examples.length < maxExamples; i += 4) {
			const c = candles[i];
			const body = Math.abs(c.close - c.open);
			const range = Math.max(1e-9, c.high - c.low);
			const nextMove = Math.abs(candles[Math.min(candles.length - 1, i + 1)].close - c.close);
			if (body / range < 0.45 && nextMove > avgRange * 0.55) {
				pushProofExample(
					examples,
					candles,
					i,
					'Scalp micro-move',
					'Short-duration setup with small body and fast follow-through.',
					0.5 + Math.min(0.4, (nextMove / Math.max(1e-9, avgRange)) * 0.08),
				);
			}
		}
	}

	if (type.includes('swing')) {
		for (let i = 8; i < candles.length - 8 && examples.length < maxExamples; i += 5) {
			const lo = candles.slice(i - 3, i + 4).every((c) => candles[i].low <= c.low);
			const hi = candles.slice(i - 3, i + 4).every((c) => candles[i].high >= c.high);
			if (lo || hi) {
				pushProofExample(examples, candles, i, 'Swing pivot', 'Local pivot marks a potential multi-bar correction swing.', 0.66);
			}
		}
	}

	if (type.includes('position')) {
		for (let i = 90; i < candles.length && examples.length < maxExamples; i += 20) {
			const longUp = isTrendWindow(candles, i - 80, i, 'up');
			const longDown = isTrendWindow(candles, i - 80, i, 'down');
			if (longUp || longDown) {
				pushProofExample(examples, candles, i, 'Position trend leg', 'Extended directional leg consistent with position-style holding periods.', 0.72);
			}
		}
	}

	if (type.includes('news')) {
		for (let i = 1; i < candles.length && examples.length < maxExamples; i += 3) {
			const ratio = (candles[i].high - candles[i].low) / Math.max(1e-9, avgRange);
			if (ratio >= 2.8) {
				pushProofExample(examples, candles, i, 'Volatility spike', 'Unusually large expansion bar consistent with event-driven volatility.', 0.56 + Math.min(0.36, ratio * 0.08));
			}
		}
	}

	if (type.includes('gap')) {
		for (let i = 1; i < candles.length && examples.length < maxExamples; i += 2) {
			const gap = Math.abs(candles[i].open - candles[i - 1].close);
			if (gap >= avgRange * 0.8) {
				pushProofExample(
					examples,
					candles,
					i,
					'Gap setup',
					'Session transition opens away from prior close by a significant distance.',
					0.54 + Math.min(0.38, (gap / Math.max(1e-9, avgRange)) * 0.1),
					[
						{ kind: 'vline', label: 'Gap candle', ts: candles[i].ts },
					],
				);
			}
		}
	}

	if ((type.includes('support / resistance') || type.includes('mean reversion')) && examples.length < maxExamples) {
		const zones = buildSupportResistanceZones(candles, 3);
		for (const zone of zones) {
			if (examples.length >= maxExamples) {
				break;
			}
			let bestIdx = -1;
			let bestDist = Number.POSITIVE_INFINITY;
			for (let i = 0; i < candles.length; i += 1) {
				const dist = Math.abs(candles[i].close - zone.center);
				if (dist < bestDist) {
					bestDist = dist;
					bestIdx = i;
				}
			}
			if (bestIdx >= 0) {
				pushProofExample(
					examples,
					candles,
					bestIdx,
					zone.kind === 'support' ? 'Support reaction' : 'Resistance reaction',
					`Price action clusters around a ${zone.kind} zone with strength score ${zone.strength}.`,
					0.5 + Math.min(0.42, zone.strength / 10),
					[
						{ kind: 'hline', label: `${zone.kind} center`, price: zone.center },
						{ kind: 'box', label: `${zone.kind} zone`, startTs: candles[Math.max(0, bestIdx - 20)].ts, endTs: candles[Math.min(candles.length - 1, bestIdx + 20)].ts, low: zone.low, high: zone.high },
					],
				);
			}
		}
	}

	if (!examples.length) {
		pushProofExample(examples, candles, candles.length - 1, 'Recent context', 'No strong pattern sample found; showing latest structure window for review.', 0.45);
	}

	examples.sort((a, b) => b.confidence - a.confidence);
	return examples.slice(0, maxExamples);
}

function buildStrategyConfig(
	input: StrategyRecognitionInput,
	recognition: StrategyRecognitionResult,
): StrategyExecutionConfig {
	const rrValue = Number(recognition.rules?.rrTarget);
	const rrTarget = Number.isFinite(rrValue) ? rrValue : null;
	const parserVersion = String(recognition.rules?.parserVersion || 'v2');
	const confirmation = String(recognition.rules?.confirmation || input.confirmation || 'Rejection candle');
	const invalidation = String(recognition.rules?.invalidation || 'hard invalidation on rule break');
	const minTouches = Math.max(1, parsePositiveInt(recognition.rules?.minTouches, input.minTouches));

	return {
		schemaVersion: '1.0',
		emittedAt: new Date().toISOString(),
		name: recognition.name,
		market: recognition.market,
		execution: {
			primaryTimeframe: recognition.primaryTimeframe,
			engineInterval: mapTfToEngineInterval(recognition.primaryTimeframe),
			timeframes: recognition.timeframes,
			bias: recognition.bias,
			sessions: recognition.sessions,
		},
		risk: {
			riskPerTradePct: input.riskPerTradePct,
			zoneWidthPct: input.zoneWidthPct,
			minTouches,
			rrTarget,
		},
		entry: {
			style: recognition.entryStyle,
			confirmation,
			invalidation,
		},
		exit: {
			targetStyle: recognition.targetStyle,
			objective: recognition.objective,
		},
		indicators: recognition.indicators,
		metadata: {
			strategyType: recognition.strategyType,
			confidence: recognition.confidence,
			confidenceBand: recognition.confidenceBand || 'medium',
			parserVersion,
			templateName: input.templateName || recognition.name,
			dataFile: input.dataFile || '',
		},
		notes: recognition.notes,
	};
}

function listDirectoryEntries(dirPath: string): Array<{ name: string; isDirectory: boolean; size: number; modifiedAt: string | null }> {
	if (!fs.existsSync(dirPath)) {
		return [];
	}

	const entries: Array<{ name: string; isDirectory: boolean; size: number; modifiedAt: string | null }> = [];
	for (const entry of fs.readdirSync(dirPath, { withFileTypes: true })) {
		const fullPath = path.join(dirPath, entry.name);
		try {
			const stat = fs.statSync(fullPath);
			entries.push({
				name: entry.name,
				isDirectory: entry.isDirectory(),
				size: entry.isDirectory() ? 0 : stat.size,
				modifiedAt: stat.mtime.toISOString(),
			});
		} catch {
			// Skip stale or broken entries (for example, dangling links in uploads).
		}
	}

	return entries;
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

function isPathInsideDirectory(targetPath: string, rootPath: string): boolean {
	const target = normalizePath(targetPath);
	const root = normalizePath(rootPath);
	return target === root || target.startsWith(`${root}${path.sep}`);
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

function startBacktestExecution(params: {
	symbol: string;
	interval: string;
	lookbackDays: number;
	capital: number;
	risk: number;
	skipPlots: boolean;
	linkedRunId?: string;
}): { ok: boolean; error?: string; state?: BacktestState } {
	if (backtestProc && backtestState.status === 'running') {
		return { ok: false, error: 'Backtest already running' };
	}

	const {
		symbol,
		interval,
		lookbackDays,
		capital,
		risk,
		skipPlots,
		linkedRunId,
	} = params;

	fs.mkdirSync(ARTIFACT_DIR, { recursive: true });

	backtestState.status = 'running';
	backtestState.startedAt = new Date().toISOString();
	backtestState.endedAt = undefined;
	backtestState.exitCode = undefined;
	backtestState.linkedRunId = linkedRunId;
	backtestState.logs = [];
	backtestState.metrics = {};
	backtestState.artifacts = [];
	activeStrategyLabRunId = linkedRunId || null;

	if (linkedRunId) {
		updateRunSummary(linkedRunId, {
			status: 'running',
			startedAt: backtestState.startedAt,
		});
	}

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

		if (linkedRunId) {
			updateRunSummary(linkedRunId, {
				status: backtestState.status,
				endedAt: backtestState.endedAt,
				exitCode: backtestState.exitCode,
				metrics: backtestState.metrics,
				artifacts: backtestState.artifacts,
			});
		}

		pushLog(`Backtest process exited with code ${backtestState.exitCode}`);
		broadcast('status', backtestState);
		backtestProc = null;
		activeStrategyLabRunId = null;
		backtestState.linkedRunId = undefined;
		maybeStartNextQueuedStrategyLabRun();
	});

	backtestProc.on('error', (err) => {
		backtestState.status = 'failed';
		backtestState.endedAt = new Date().toISOString();
		pushLog(`Failed to start process: ${err.message}`);

		if (linkedRunId) {
			updateRunSummary(linkedRunId, {
				status: 'failed',
				endedAt: backtestState.endedAt,
				error: err.message,
			});
		}

		broadcast('status', backtestState);
		backtestProc = null;
		activeStrategyLabRunId = null;
		backtestState.linkedRunId = undefined;
		maybeStartNextQueuedStrategyLabRun();
	});

	return { ok: true, state: backtestState };
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
		datasetAliasFile: DATASET_ALIAS_FILE,
		datasetSymbolAliases: DATASET_SYMBOL_ALIASES,
		defaultTradesFile: {
			filePath: DEFAULT_TRADES_FILE,
			exists: fileExists(DEFAULT_TRADES_FILE),
		},
		defaultReportFile: {
			filePath: DEFAULT_REPORT_FILE,
			exists: fileExists(DEFAULT_REPORT_FILE),
		},
		supportedTimeframes: ['1m', '5m', '15m', '30m', '1h', '4h', '1d', '1w', '1mo'],
	});
});

app.get('/platform/datasets', (_req: Request, res: Response): void => {
	const markets = getMarketDatasets();
	const allTimeframes = Array.from(new Set(markets.flatMap((market) => market.timeframes)));
	res.json({
		count: markets.length,
		markets,
		allTimeframes,
	});
});

app.post('/platform/strategy-lab/recognize', (req: Request, res: Response): void => {
	try {
		const theoryText = normalizeTheoryText(req.body?.theoryText || req.body?.templateText);
		if (!theoryText) {
			res.status(400).json({ error: 'theoryText is required' });
			return;
		}

		const input = normalizeStrategyInput({
			theoryText,
			templateName: String(req.body?.templateName || 'Structured Rule Strategy'),
			market: String(req.body?.market || 'BTCUSD'),
			primaryTimeframe: String(req.body?.primaryTimeframe || 'H4'),
			riskPerTradePct: toNumber(req.body?.riskPerTradePct, 0.5),
			zoneWidthPct: toNumber(req.body?.zoneWidthPct, 0.18),
			minTouches: Math.max(1, parsePositiveInt(req.body?.minTouches, 2)),
			confirmation: String(req.body?.confirmation || 'Rejection candle'),
			dataFile: String(req.body?.dataFile || ''),
		});

		const recognition = buildRecognition(input);
		const strategyConfig = buildStrategyConfig(input, recognition);
		res.json({
			ok: true,
			input,
			recognition,
			strategyConfig,
		});
	} catch (error) {
		res.status(500).json({ error: (error as Error).message });
	}
});

app.post('/platform/strategy-lab/proof', (req: Request, res: Response): void => {
	try {
		const normalizedInput = normalizeStrategyInput({
			theoryText: String(req.body?.theoryText || ''),
			templateName: String(req.body?.templateName || 'Structured Rule Strategy'),
			market: String(req.body?.market || 'BTCUSD'),
			primaryTimeframe: String(req.body?.primaryTimeframe || 'H1'),
			riskPerTradePct: toNumber(req.body?.riskPerTradePct, 0.5),
			zoneWidthPct: toNumber(req.body?.zoneWidthPct, 0.18),
			minTouches: Math.max(1, parsePositiveInt(req.body?.minTouches, 2)),
			confirmation: String(req.body?.confirmation || 'Rejection candle'),
			dataFile: String(req.body?.dataFile || ''),
			templateText: String(req.body?.templateText || ''),
		});

		const recognition = buildRecognition(normalizedInput);
		const proofTfMode = String(req.body?.proofTfMode || 'base').toLowerCase();
		const proofTimeframeBase = mapUiTfToProofTimeframe(normalizedInput.primaryTimeframe);
		const proofTimeframe = adjustProofTimeframe(proofTimeframeBase, proofTfMode);
		const selectedFile = resolveStrategyDataFile(normalizedInput.market, normalizedInput.dataFile || '');
		const candles = getCandles(selectedFile, proofTimeframe);
		const maxExamples = Math.max(1, Math.min(6, parsePositiveInt(req.body?.maxExamples, 3)));
		const examples = detectStrategyProofExamples(candles, recognition.strategyType, maxExamples);

		res.json({
			ok: true,
			recognition,
			proof: {
				generatedAt: new Date().toISOString(),
				symbol: normalizedInput.market,
				timeframe: proofTimeframe,
				timeframeMode: proofTfMode,
				dataFile: normalizePath(selectedFile),
				parameters: {
					riskPerTradePct: normalizedInput.riskPerTradePct,
					zoneWidthPct: normalizedInput.zoneWidthPct,
					minTouches: normalizedInput.minTouches,
					confirmation: normalizedInput.confirmation,
				},
				exampleCount: examples.length,
				examples,
			},
		});
	} catch (error) {
		res.status(400).json({ error: (error as Error).message });
	}
});

app.get('/platform/strategy-lab/strategies', (_req: Request, res: Response): void => {
	const records = loadStrategyLibrary();
	res.json({
		count: records.length,
		records,
	});
});

app.post('/platform/strategy-lab/confirm', (req: Request, res: Response): void => {
	try {
		const theoryText = normalizeTheoryText(req.body?.theoryText || req.body?.templateText);
		if (!theoryText) {
			res.status(400).json({ error: 'theoryText is required' });
			return;
		}

		const recognitionInput = normalizeStrategyInput({
			theoryText,
			templateName: String(req.body?.templateName || 'Structured Rule Strategy'),
			market: String(req.body?.market || 'BTCUSD'),
			primaryTimeframe: String(req.body?.primaryTimeframe || 'H4'),
			riskPerTradePct: toNumber(req.body?.riskPerTradePct, 0.5),
			zoneWidthPct: toNumber(req.body?.zoneWidthPct, 0.18),
			minTouches: Math.max(1, parsePositiveInt(req.body?.minTouches, 2)),
			confirmation: String(req.body?.confirmation || 'Rejection candle'),
			dataFile: String(req.body?.dataFile || ''),
		});

		const recognition = buildRecognition(recognitionInput);
		const strategyConfig = buildStrategyConfig(recognitionInput, recognition);
		const now = new Date().toISOString();
		const record: StrategyDefinitionRecord = {
			id: createStrategyId(),
			createdAt: now,
			updatedAt: now,
			status: 'confirmed',
			theoryText,
			recognition,
			strategyConfig,
		};

		const records = loadStrategyLibrary();
		records.unshift(record);
		saveStrategyLibrary(records);

		res.status(201).json({ ok: true, record, strategyConfig });
	} catch (error) {
		res.status(500).json({ error: (error as Error).message });
	}
});

app.post('/platform/strategy-lab/backtest-request', (req: Request, res: Response): void => {
	try {
		const strategyId = String(req.body?.strategyId || '').trim();
		if (!strategyId) {
			res.status(400).json({ error: 'strategyId is required' });
			return;
		}

		const records = loadStrategyLibrary();
		const strategy = records.find((record) => record.id === strategyId);
		if (!strategy) {
			res.status(404).json({ error: 'Strategy not found' });
			return;
		}

		const capital = toNumber(req.body?.capital, 10000);
		const risk = toNumber(req.body?.risk, 0.01);
		const interval = String(req.body?.interval || '1m');
		const lookbackDays = Math.max(1, parsePositiveInt(req.body?.lookbackDays ?? req.body?.days, 30));
		const skipPlots = Boolean(req.body?.skipPlots ?? false);
		const autoStart = req.body?.autoStart !== false;

		const queuedRun: StrategyRunRecord = {
			id: createRunId(),
			createdAt: new Date().toISOString(),
			summary: {
				source: 'strategy-lab',
				status: 'queued',
				strategyId: strategy.id,
				strategyName: strategy.recognition.name,
				strategyType: strategy.recognition.strategyType,
				market: strategy.recognition.market,
				primaryTimeframe: strategy.recognition.primaryTimeframe,
				capital,
				risk,
				interval,
				lookbackDays,
			},
		};

		const runs = loadRunHistory();
		runs.unshift(queuedRun);
		saveRunHistory(runs);

		let autoStartResult: Record<string, unknown> = {
			autoStart,
			started: false,
		};

		if (autoStart) {
			const started = startBacktestExecution({
				symbol: strategy.recognition.market,
				interval,
				lookbackDays,
				capital,
				risk,
				skipPlots,
				linkedRunId: queuedRun.id,
			});

			autoStartResult = {
				autoStart,
				started: started.ok,
				error: started.error,
			};

			if (!started.ok) {
				updateRunSummary(queuedRun.id, {
					status: 'queued',
					queueReason: started.error || 'Backtest engine busy',
				});
			}
		}

		res.status(201).json({
			ok: true,
			queuedRun,
			autoStart: autoStartResult,
			next: {
				backtestStartPath: '/backtest/start',
				suggestedPayload: {
					symbol: strategy.recognition.market,
					interval,
					lookbackDays,
					capital,
					risk,
					skipPlots,
				},
			},
		});
	} catch (error) {
		res.status(500).json({ error: (error as Error).message });
	}
});

app.get('/platform/strategy-lab/runs', (req: Request, res: Response): void => {
	const limit = Math.min(200, parsePositiveInt(req.query.limit, 25));
	const records = getStrategyLabRuns(limit).map((run) => {
		const summary = getRunSummaryObject(run);
		const liveStatus = run.id === activeStrategyLabRunId ? backtestState.status : summary.status;
		return {
			id: run.id,
			createdAt: run.createdAt,
			summary,
			status: liveStatus || 'queued',
			isActive: run.id === activeStrategyLabRunId,
		};
	});

	res.json({
		count: records.length,
		runs: records,
		activeRunId: activeStrategyLabRunId,
		backtestState,
	});
});

app.get('/platform/strategy-lab/runs/:id/status', (req: Request, res: Response): void => {
	const runs = loadRunHistory();
	const run = runs.find((entry) => entry.id === req.params.id && isStrategyLabRun(entry));
	if (!run) {
		res.status(404).json({ error: 'Strategy lab run not found' });
		return;
	}

	const summary = getRunSummaryObject(run);
	const isActive = run.id === activeStrategyLabRunId;
	res.json({
		id: run.id,
		createdAt: run.createdAt,
		summary,
		status: isActive ? backtestState.status : (summary.status || 'queued'),
		isActive,
		backtestState: isActive ? backtestState : null,
	});
});

app.post('/platform/strategy-lab/runs/:id/start', (req: Request, res: Response): void => {
	const runs = loadRunHistory();
	const run = runs.find((entry) => entry.id === req.params.id && isStrategyLabRun(entry));
	if (!run) {
		res.status(404).json({ error: 'Strategy lab run not found' });
		return;
	}

	const summary = getRunSummaryObject(run);
	const symbol = String(summary.market || req.body?.symbol || 'XAUUSD=X');
	const interval = String(summary.interval || req.body?.interval || '1m');
	const lookbackDays = Math.max(1, parsePositiveInt(summary.lookbackDays ?? req.body?.lookbackDays, 30));
	const capital = toNumber(summary.capital ?? req.body?.capital, 10000);
	const risk = toNumber(summary.risk ?? req.body?.risk, 0.01);
	const skipPlots = Boolean(req.body?.skipPlots ?? false);

	const started = startBacktestExecution({
		symbol,
		interval,
		lookbackDays,
		capital,
		risk,
		skipPlots,
		linkedRunId: run.id,
	});

	if (!started.ok) {
		res.status(409).json({ error: started.error || 'Unable to start run' });
		return;
	}

	res.json({ ok: true, runId: run.id, state: started.state });
});

app.get('/platform/candles', (req: Request, res: Response): void => {
	try {
		const symbol = String(req.query.symbol || 'XAUUSD').toUpperCase();
		const timeframe = String(req.query.timeframe || '15m');
		const maxPoints = parsePositiveInt(req.query.maxPoints, 5000);

		const userDataFile = typeof req.query.dataFile === 'string' ? req.query.dataFile : '';
		const selectedFile = resolveStrategyDataFile(symbol, userDataFile);

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
		const selectedFile = resolveStrategyDataFile(symbol, userDataFile);

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
	const labRuns = getStrategyLabRuns(12).map((run) => {
		const summary = getRunSummaryObject(run);
		return {
			id: run.id,
			createdAt: run.createdAt,
			summary,
			status: run.id === activeStrategyLabRunId ? backtestState.status : (summary.status || 'queued'),
			isActive: run.id === activeStrategyLabRunId,
		};
	});
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
		labRuns,
		directories,
		defaultDataFiles: DEFAULT_DATA_FILES,
		datasetAliasFile: DATASET_ALIAS_FILE,
		datasetSymbolAliases: DATASET_SYMBOL_ALIASES,
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

app.post('/platform/datasets/upload', datasetUpload.single('dataset'), (req: Request, res: Response): void => {
	try {
		if (!req.file) {
			res.status(400).json({ error: 'dataset file is required' });
			return;
		}

		const symbol = normalizeSymbolToken(String(req.body?.symbol || ''));
		const canonicalSymbol = canonicalizeDatasetSymbol(symbol);
		const timeframe = String(req.body?.timeframe || '').toLowerCase();
		if (!canonicalSymbol || !timeframe) {
			fs.unlinkSync(req.file.path);
			res.status(400).json({ error: 'symbol and timeframe are required' });
			return;
		}

		fs.mkdirSync(DATASET_STORAGE_DIR, { recursive: true });
		const symbolDir = path.join(DATASET_STORAGE_DIR, canonicalSymbol);
		fs.mkdirSync(symbolDir, { recursive: true });

		const originalName = path.basename(req.file.originalname || `${canonicalSymbol}_${timeframe}.csv`);
		const safeName = originalName.replace(/[^A-Za-z0-9._\-]/g, '_');
		const targetPath = path.join(symbolDir, safeName);
		fs.renameSync(req.file.path, targetPath);

		res.status(201).json({
			ok: true,
			symbol: canonicalSymbol,
			timeframe,
			filePath: normalizePath(targetPath),
			datasets: getMarketDatasets(),
		});
	} catch (error) {
		res.status(500).json({ error: (error as Error).message });
	}
});

app.post('/platform/datasets/register-path', (req: Request, res: Response): void => {
	try {
		const sourcePath = String(req.body?.sourcePath || '').trim();
		if (!sourcePath) {
			res.status(400).json({ error: 'sourcePath is required' });
			return;
		}

		const absoluteSource = normalizePath(sourcePath);
		if (!fileExists(absoluteSource)) {
			res.status(404).json({ error: `sourcePath not found: ${absoluteSource}` });
			return;
		}

		let copied = 0;
		const files = walkDatasetFiles(absoluteSource);
		for (const file of files) {
			const symbol = canonicalizeDatasetSymbol(guessSymbolFromPath(file));
			const tf = detectDatasetTimeframe(path.basename(file));
			if (!symbol || !tf) {
				continue;
			}

			const symbolDir = path.join(DATASET_STORAGE_DIR, symbol);
			fs.mkdirSync(symbolDir, { recursive: true });
			const target = path.join(symbolDir, path.basename(file));
			fs.copyFileSync(file, target);
			copied += 1;
		}

		res.json({
			ok: true,
			copied,
			datasets: getMarketDatasets(),
		});
	} catch (error) {
		res.status(500).json({ error: (error as Error).message });
	}
});

app.post('/platform/strategy-lab/import', (req: Request, res: Response): void => {
	try {
		const templateText = normalizeStrategyText(String(req.body?.templateText || ''));
		if (!templateText) {
			res.status(400).json({ error: 'templateText is required' });
			return;
		}

		const parsedTemplate = parseStrategyTemplateText(templateText);
		const normalized = normalizeStrategyInput({
			theoryText: parsedTemplate?.theoryText ? String(parsedTemplate.theoryText) : templateText,
			templateName: String(req.body?.templateName || parsedTemplate?.name || parsedTemplate?.strategyName || 'Imported Strategy'),
			market: String(req.body?.market || parsedTemplate?.market || 'BTCUSD'),
			primaryTimeframe: String(req.body?.primaryTimeframe || parsedTemplate?.primaryTimeframe || parsedTemplate?.timeframe || 'H4'),
			riskPerTradePct: toNumber(req.body?.riskPerTradePct ?? parsedTemplate?.riskPerTradePct ?? parsedTemplate?.riskPct, 0.5),
			zoneWidthPct: toNumber(req.body?.zoneWidthPct ?? parsedTemplate?.zoneWidthPct, 0.18),
			minTouches: Math.max(1, parsePositiveInt(req.body?.minTouches ?? parsedTemplate?.minTouches, 2)),
			confirmation: String(req.body?.confirmation || parsedTemplate?.confirmation || 'Rejection candle'),
			dataFile: String(req.body?.dataFile || parsedTemplate?.dataFile || ''),
			templateText,
		});

		const recognition = buildRecognition(normalized);
		const strategyConfig = buildStrategyConfig(normalized, recognition);
		res.json({
			ok: true,
			normalized,
			recognition,
			strategyConfig,
			parsedTemplate,
		});
	} catch (error) {
		res.status(500).json({ error: (error as Error).message });
	}
});

app.post('/backtest/start', async (req: Request, res: Response): Promise<void> => {
	const symbol = String(req.body?.symbol || 'XAUUSD=X');
	const interval = String(req.body?.interval || '1m');
	const lookbackDays = Number(req.body?.lookbackDays ?? req.body?.days ?? 30);
	const capital = Number(req.body?.capital ?? 3720);
	const risk = Number(req.body?.risk ?? 0.01);
	const skipPlots = Boolean(req.body?.skipPlots ?? false);
	const started = startBacktestExecution({
		symbol,
		interval,
		lookbackDays,
		capital,
		risk,
		skipPlots,
	});

	if (!started.ok) {
		res.status(409).json({ error: started.error || 'Unable to start backtest' });
		return;
	}

	res.json({ ok: true, state: started.state });
});

app.post('/backtest/stop', async (_req: Request, res: Response): Promise<void> => {
	if (!backtestProc || backtestState.status !== 'running') {
		res.status(409).json({ error: 'No running backtest' });
		return;
	}

	if (activeStrategyLabRunId) {
		updateRunSummary(activeStrategyLabRunId, {
			status: 'stop-requested',
			stopRequestedAt: new Date().toISOString(),
		});
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
