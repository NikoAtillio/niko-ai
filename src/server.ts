import express, { Request, Response } from 'express';
import multer from 'multer';
import path from 'path';
import fs from 'fs';
import PDFDocument from 'pdfkit';
import { spawn, ChildProcessWithoutNullStreams } from 'child_process';
import { ChartAIAnalyzer } from './services/ChartAIAnalyzer';

const app = express();

const upload = multer({ dest: 'uploads/' });
const datasetUpload = multer({ dest: path.join('uploads', '_incoming') });
const chartAnalyzer = new ChartAIAnalyzer();

const WORKSPACE_ROOT = process.cwd();
const DATA_ROOT = process.env.NIKO_DATA_ROOT
	? path.resolve(process.env.NIKO_DATA_ROOT)
	: WORKSPACE_ROOT;
const UPLOADS_DIR = path.join(DATA_ROOT, 'uploads');
const DATASET_STORAGE_DIR = path.join(UPLOADS_DIR, 'datasets');
const DATASET_ALIAS_FILE = path.join(DATA_ROOT, 'config', 'dataset-symbol-aliases.json');
const APP_DATASET_ALIAS_FILE = path.join(WORKSPACE_ROOT, 'config', 'dataset-symbol-aliases.json');
const ARTIFACT_DIR = path.join(DATA_ROOT, 'backtest_artifacts');
const RUN_HISTORY_DIR = path.join(DATA_ROOT, 'saved_runs');
const RUN_HISTORY_FILE = path.join(RUN_HISTORY_DIR, 'strategy_runs.json');
const STRATEGY_LIBRARY_FILE = path.join(RUN_HISTORY_DIR, 'strategy_library.json');
const COMPARATIVE_REPORTS_FILE = path.join(DATA_ROOT, 'config', 'comparative-reports.json');
const APP_COMPARATIVE_REPORTS_FILE = path.join(WORKSPACE_ROOT, 'config', 'comparative-reports.json');
const COMPARATIVE_PROFILE_SETS_FILE = path.join(RUN_HISTORY_DIR, 'comparative_profile_sets.json');
const RUN_HISTORY_LIMIT = 100;
const STRATEGY_LIBRARY_LIMIT = 250;
const ARCHIVE_ARTIFACT_DIR = path.join(DATA_ROOT, 'backtest_artifacts_archive');
const ADMIN_SCAN_DIRS = [
	UPLOADS_DIR,
	ARTIFACT_DIR,
	ARCHIVE_ARTIFACT_DIR,
	RUN_HISTORY_DIR,
];

const DEFAULT_DATA_FILES: Record<string, string> = {
	XAUUSD: '/Users/niko/Downloads/XAUUSD_M1_202404010105_202603302033.csv',
	NAS100: '/Users/niko/Downloads/NAS100_M1_202404010105_202603302033.csv',
};

fs.mkdirSync(ARTIFACT_DIR, { recursive: true });

const DEFAULT_DATASET_SYMBOL_ALIASES: Record<string, string> = {
	BTC: 'BTCUSD',
	XAU: 'XAUUSD',
	US1002324: 'US100',
	US1002425: 'US100',
	US1002526: 'US100',
};

function loadDatasetSymbolAliases(): Record<string, string> {
	try {
		const aliasFile = fileExists(DATASET_ALIAS_FILE)
			? DATASET_ALIAS_FILE
			: APP_DATASET_ALIAS_FILE;
		if (!fileExists(aliasFile)) {
			return { ...DEFAULT_DATASET_SYMBOL_ALIASES };
		}

		const raw = fs.readFileSync(aliasFile, 'utf8');
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
	tradeHorizonTimeframe: string;
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
	tradeHorizonTimeframe: string;
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
		entryTimeframe: string;
		primaryTimeframe: string;
		tradeHorizonTimeframe: string;
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
	direction?: 'long' | 'short';
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

interface ComparativeReportRecord {
	id: string;
	title: string;
	description?: string;
	generatedAt?: string;
	windowStart?: string;
	windowEnd?: string;
	dataFile: string;
}

interface ComparativeReportManifest {
	reports: ComparativeReportRecord[];
}

interface ComparativeProfileSetRecord {
	id: string;
	name: string;
	reportIds: string[];
	windowStart?: string;
	windowEnd?: string;
	createdAt: string;
	updatedAt: string;
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
const volatileRunHistory = new Map<string, StrategyRunRecord>();

const dataCache = new Map<string, DataCacheEntry>();
const tradesCache = new Map<string, TradeRecord[]>();
const reportCache = new Map<string, Record<string, string>>();
const comparativeDataCache = new Map<string, Record<string, unknown> | null>();

function loadRunHistory(): StrategyRunRecord[] {
	try {
		const combined = new Map<string, StrategyRunRecord>();

		if (fs.existsSync(RUN_HISTORY_FILE)) {
			const text = fs.readFileSync(RUN_HISTORY_FILE, 'utf8');
			const parsed = JSON.parse(text);
			if (Array.isArray(parsed)) {
				for (const run of parsed as StrategyRunRecord[]) {
					if (run && typeof run === 'object' && typeof run.id === 'string') {
						combined.set(run.id, run);
					}
				}
			}
		}

		for (const [runId, run] of volatileRunHistory.entries()) {
			combined.set(runId, run);
		}

		return Array.from(combined.values());
	} catch {
		return Array.from(volatileRunHistory.values());
	}
}

function saveRunHistory(runs: StrategyRunRecord[]): void {
	fs.mkdirSync(RUN_HISTORY_DIR, { recursive: true });
	const persistentRuns = runs.filter((run) => !isStrategyLabRun(run));
	fs.writeFileSync(RUN_HISTORY_FILE, `${JSON.stringify(persistentRuns.slice(0, RUN_HISTORY_LIMIT), null, 2)}\n`, 'utf8');
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
	const fallbackPrimary = String(templateObject?.primaryTimeframe || templateObject?.entryTimeframe || templateObject?.timeframe || input.primaryTimeframe || 'H4').toUpperCase();
	const selectedPrimary = String(input.primaryTimeframe || fallbackPrimary || 'H4').toUpperCase();
	const fallbackHorizon = String(
		templateObject?.tradeHorizonTimeframe
		|| templateObject?.executionTimeframe
		|| input.tradeHorizonTimeframe
		|| selectedPrimary,
	).toUpperCase();
	return {
		theoryText,
		templateName: input.templateName,
		market: String(templateObject?.market || input.market || 'BTCUSD').toUpperCase(),
		primaryTimeframe: selectedPrimary,
		tradeHorizonTimeframe: fallbackHorizon,
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
	if (volatileRunHistory.has(runId)) {
		const current = volatileRunHistory.get(runId) as StrategyRunRecord;
		volatileRunHistory.set(runId, {
			...current,
			summary: {
				...getRunSummaryObject(current),
				...patch,
				updatedAt: new Date().toISOString(),
			},
		});
		return true;
	}

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

function mapSymbolToPhantomInstrumentCode(symbolInput: string): 'XAU' | 'US100' | 'BTC' | 'FX' {
	const symbol = canonicalizeDatasetSymbol(symbolInput);
	if (symbol.startsWith('XAU')) return 'XAU';
	if (symbol.startsWith('US100') || symbol.startsWith('NAS100')) return 'US100';
	if (symbol.startsWith('BTC')) return 'BTC';
	return 'FX';
}

function supportsPhantomExecution(symbolInput: string): boolean {
	const stem = mapSymbolToPhantomStem(symbolInput);
	return ['XAU', 'US100', 'BTC', 'fx'].includes(stem);
}

function mapScenarioOrRiskToRiskProfile(inputValue: string): 'high' | 'median' | 'low' {
	const normalized = String(inputValue || 'B').trim().toUpperCase();
	if (normalized === 'A' || normalized === 'P2A' || normalized === 'P3A' || normalized === 'HIGH' || normalized === 'AGGRESSIVE') return 'high';
	if (normalized === 'C' || normalized === 'P2C' || normalized === 'P3C' || normalized === 'LOW' || normalized === 'CONSERVATIVE') return 'low';
	return 'median';
}

function mapRiskProfileToScenarioKey(riskProfile: 'high' | 'median' | 'low'): 'A' | 'B' | 'C' {
	if (riskProfile === 'high') return 'A';
	if (riskProfile === 'low') return 'C';
	return 'B';
}

function mapSymbolToPhantomStem(symbolInput: string): 'XAU' | 'US100' | 'BTC' | 'fx' {
	const symbol = canonicalizeDatasetSymbol(symbolInput);
	if (symbol.startsWith('BTC')) return 'BTC';
	if (symbol.startsWith('US100') || symbol.startsWith('NAS100')) return 'US100';
	if (symbol.startsWith('XAU')) return 'XAU';
	return 'fx';
}

function resolvePhantomScriptCandidates(symbolInput: string, riskProfileInput: string): string[] {
	const stem = mapSymbolToPhantomStem(symbolInput);
	const riskProfile = mapScenarioOrRiskToRiskProfile(riskProfileInput);
	const stemFolder = `phantom_${stem}`;
	const stemFile = `phantom_${stem}_${riskProfile}.py`;

	return [
		path.join(WORKSPACE_ROOT, 'phantom', stemFolder, stemFile),
		path.join(WORKSPACE_ROOT, 'phantom', '_archive', 'v2_runtime', 'phantom_p2.py'),
		path.join(WORKSPACE_ROOT, 'phantom', '_archive', 'v3_runtime', 'phantom_p3.py'),
	];
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
	const datasetRoots = [DATASET_STORAGE_DIR, path.join(WORKSPACE_ROOT, 'data')];
	const discoveredFiles = datasetRoots.flatMap((rootDir) => walkDatasetFiles(rootDir));
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

function resolveMarketTimeframeFile(symbolInput: string, timeframeInput: string): string {
	const symbol = canonicalizeDatasetSymbol(String(symbolInput || ''));
	const timeframe = String(timeframeInput || '').toLowerCase();
	const discovered = getMarketDatasets();
	const match = discovered.find((item) => item.symbol === symbol);
	if (match) {
		const exact = match.files.find((file) => file.timeframe === timeframe);
		if (exact?.filePath) {
			return exact.filePath;
		}
		if (match.defaultDataFile) {
			return match.defaultDataFile;
		}
	}
	return resolveStrategyDataFile(symbol, '');
}

interface PhantomV2ScenarioSummary {
	version: string;
	scenarioKey: string;
	scenario: string;
	label: string;
	trades: number;
	winRatePct: number;
	profitFactor: number;
	netReturnPct: number;
	maxDrawdownPct: number;
	expectancy: number;
	finalCapital: number;
	timeoutPct: number;
}

interface PhantomV2ValidationResult {
	symbol: string;
	capital: number;
	scenario: string;
	dataFiles: Record<string, string>;
	summaries: PhantomV2ScenarioSummary[];
	best: PhantomV2ScenarioSummary | null;
	stdout: string;
}

function normalizePhantomScenario(rawScenario: string): { version: string; scenarioKey: string; scenario: string } {
	const version = 'phantom';
	let token = String(rawScenario || '').trim().toUpperCase().replace(/[^A-Z0-9]/g, '');
	token = token.replace(/^P[123]/, '');
	if (token === 'D') token = 'C';
	if (!['A', 'B', 'C'].includes(token)) token = 'B';
	return {
		version,
		scenarioKey: token,
		scenario: `${version}${token}`,
	};
}

function parsePhantomV2ValidationOutput(stdout: string): PhantomV2ScenarioSummary[] {
	const blocks = [...stdout.matchAll(/=+\n\s*(.+?)\n=+\n([\s\S]*?)(?=\n=+\n\s*.+?\n=+|\n\n=== v5\.0 → v5\.1 COMPARISON ===|$)/g)];
	return blocks.map((match) => {
		const label = match[1].trim();
		const body = match[2];
		const getNumber = (pattern: RegExp): number => {
			const found = body.match(pattern)?.[1];
			if (!found) return Number.NaN;
			return Number(String(found).replace(/,/g, ''));
		};
		const rawScenario = label.match(/Scenario\s+([A-Za-z0-9.]+)/i)?.[1] || '';
		const normalizedScenario = normalizePhantomScenario(rawScenario);
		return {
			version: normalizedScenario.version,
			scenarioKey: normalizedScenario.scenarioKey,
			scenario: normalizedScenario.scenario,
			label: normalizedScenario.scenario.toUpperCase(),
			trades: getNumber(/Trades\s*:\s*(\d+)/),
			winRatePct: getNumber(/Win %\s*:\s*([\d.]+)%/),
			profitFactor: getNumber(/PF\s*:\s*([\d.]+)/),
			netReturnPct: getNumber(/Net Return\s*:\s*([\-\d.]+)%/),
			maxDrawdownPct: getNumber(/Max DD\s*:\s*([\-\d.]+)%/),
			expectancy: getNumber(/Expectancy\s*:\s*\$([\-\d.]+)\/trade/),
			finalCapital: getNumber(/Final Cap\s*:\s*\$([\d,.-]+)/),
			timeoutPct: getNumber(/Timeout %\s*:\s*([\d.]+)%/),
		};
	}).filter((summary) => Number.isFinite(summary.trades));
}

function bucketStartYearFromDate(dateText: string): number | null {
	const date = new Date(dateText);
	if (!Number.isFinite(date.getTime())) return null;
	const month = date.getUTCMonth() + 1;
	const year = date.getUTCFullYear();
	return month >= 4 ? year : year - 1;
}

function bucketLabelFromDate(dateText: string): string {
	const startYear = bucketStartYearFromDate(dateText);
	if (startYear === null) return 'Imported';
	return `${startYear}-${String(startYear + 1).slice(-2)}`;
}

function buildValidationCurveDataFromTradeFiles(symbol: string, capital: number, workingDir: string, summaries: PhantomV2ScenarioSummary[]): Record<string, unknown> {
	const periods: Record<string, Array<Record<string, unknown>>> = {};
	const tradeVersion = 'p2';
	const strategyInstrumentCode = mapSymbolToPhantomInstrumentCode(symbol);

	const symbolToken = strategyInstrumentCode || canonicalizeDatasetSymbol(symbol).replace(/[^A-Z0-9]/g, '');

	for (const summary of summaries) {
		const scenarioTag = String(summary.scenario || '').toUpperCase();
		const scenarioTagP2Compat = scenarioTag.replace(/^P3/, 'P2');
		const preferredCandidates: string[] = [];
		const scenarioToken = `${tradeVersion.toUpperCase()}${summary.scenarioKey}`;
		preferredCandidates.push(path.join(workingDir, `phantom_${tradeVersion}_trades_${scenarioToken}.csv`));
		preferredCandidates.push(path.join(workingDir, `phantom_${tradeVersion}_trades_${symbolToken}_${scenarioToken}.csv`));
		preferredCandidates.push(path.join(workingDir, `phantom_${tradeVersion}_trades_${scenarioTag}.csv`));
		preferredCandidates.push(path.join(workingDir, `phantom_${tradeVersion}_trades_${symbolToken}_${scenarioTag}.csv`));
		if (scenarioTagP2Compat !== scenarioTag) {
			preferredCandidates.push(path.join(workingDir, `phantom_${tradeVersion}_trades_${scenarioTagP2Compat}.csv`));
			preferredCandidates.push(path.join(workingDir, `phantom_${tradeVersion}_trades_${symbolToken}_${scenarioTagP2Compat}.csv`));
		}
		preferredCandidates.push(path.join(workingDir, `${symbolToken}_${tradeVersion}_trades_${scenarioToken}.csv`));
		preferredCandidates.push(path.join(workingDir, `${symbolToken}_${tradeVersion}_trades_${scenarioTag}.csv`));
		if (scenarioTagP2Compat !== scenarioTag) {
			preferredCandidates.push(path.join(workingDir, `${symbolToken}_${tradeVersion}_trades_${scenarioTagP2Compat}.csv`));
		}
		const legacyScenario = summary.scenarioKey === 'C' ? 'D' : summary.scenarioKey;
		const legacyTradeFile = path.join(workingDir, `phantom_v5_1_trades_${legacyScenario}.csv`);
		const preferredTradeFile = preferredCandidates.find((candidate) => fileExists(candidate));
		const tradeFile = preferredTradeFile || legacyTradeFile;
		if (!fileExists(tradeFile)) {
			continue;
		}

		const lines = fs.readFileSync(tradeFile, 'utf8').replace(/^\uFEFF/, '').split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
		if (lines.length < 2) {
			continue;
		}

		const headers = lines[0].split(',').map((header) => header.trim().toLowerCase());
		const iEntryTs = headers.indexOf('entry_ts');
		const iExitTs = headers.indexOf('exit_ts');
		const iPnl = headers.indexOf('pnl');
		if (iPnl < 0 || (iEntryTs < 0 && iExitTs < 0)) {
			continue;
		}

		let cumulativeCapital = capital;
		const groupedPoints = new Map<string, Array<{ trade: number; date: string; capital: number }>>();
		let tradeCount = 0;

		for (let index = 1; index < lines.length; index += 1) {
			const cols = lines[index].split(',');
			const rawDate = (iExitTs >= 0 ? cols[iExitTs] : '') || (iEntryTs >= 0 ? cols[iEntryTs] : '');
			const pnl = Number(cols[iPnl]);
			if (!rawDate || Number.isNaN(pnl)) {
				continue;
			}

			const date = new Date(rawDate);
			if (!Number.isFinite(date.getTime())) {
				continue;
			}

			cumulativeCapital += pnl;
			tradeCount += 1;
			const bucket = bucketLabelFromDate(date.toISOString());
			if (!groupedPoints.has(bucket)) {
				groupedPoints.set(bucket, []);
			}
			groupedPoints.get(bucket)?.push({
				trade: tradeCount,
				date: date.toISOString(),
				capital: cumulativeCapital,
			});
		}

		for (const [bucket, points] of groupedPoints.entries()) {
			periods[bucket] = periods[bucket] || [];
			periods[bucket].push({
				version: summary.version,
				scenario: summary.scenario,
				label: summary.scenario.toUpperCase(),
				trades: points.length,
				points,
			});
		}
	}

	return {
		startCapital: capital,
		market: symbol,
		sourceType: 'live phantom validation',
		timeframe: 'multi-timeframe',
		sourceFile: workingDir,
		periods,
	};
}

function pickBestPhantomV2Summary(summaries: PhantomV2ScenarioSummary[]): PhantomV2ScenarioSummary | null {
	if (!summaries.length) return null;
	return [...summaries].sort((a, b) => {
		if (b.netReturnPct !== a.netReturnPct) return b.netReturnPct - a.netReturnPct;
		if (b.profitFactor !== a.profitFactor) return b.profitFactor - a.profitFactor;
		if (a.maxDrawdownPct !== b.maxDrawdownPct) return b.maxDrawdownPct - a.maxDrawdownPct;
		return b.winRatePct - a.winRatePct;
	})[0];
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
		tradeHorizonTimeframe: input.tradeHorizonTimeframe,
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
	if (normalized === 'M30' || normalized === '30M') return '30m';
	if (normalized === 'H1' || normalized === '1H') return '1h';
	if (normalized === 'H4' || normalized === '4H') return '4h';
	if (normalized === 'D1' || normalized === '1D' || normalized === 'DAILY') return '1d';
	if (normalized === 'W1' || normalized === '1W' || normalized === 'WEEKLY') return '1w';
	if (normalized === 'MN1' || normalized === '1MO' || normalized === 'MONTHLY') return '1mo';
	return '15m';
}

function adjustProofTimeframe(baseTimeframe: string, mode: string): string {
	const ladder = ['1m', '5m', '15m', '30m', '1h', '4h', '1d', '1w', '1mo'];
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

function detectRejectionDirection(candle: CandleRecord): 'long' | 'short' | null {
	const open = Number(candle.open || 0);
	const close = Number(candle.close || 0);
	const high = Number(candle.high || 0);
	const low = Number(candle.low || 0);
	const body = Math.max(1e-9, Math.abs(close - open));
	const range = Math.max(1e-9, high - low);
	const upperWick = Math.max(0, high - Math.max(open, close));
	const lowerWick = Math.max(0, Math.min(open, close) - low);

	const bearishReject = upperWick >= body * 1.2 && upperWick >= range * 0.34;
	const bullishReject = lowerWick >= body * 1.2 && lowerWick >= range * 0.34;
	if (bearishReject && !bullishReject) return 'short';
	if (bullishReject && !bearishReject) return 'long';
	return null;
}

function inferDirectionFromFollowThrough(candles: CandleRecord[], idx: number): 'long' | 'short' {
	const lookahead = Math.min(candles.length - 1, idx + 3);
	const entry = Number(candles[idx].close || 0);
	const later = Number(candles[lookahead].close || entry);
	return later >= entry ? 'long' : 'short';
}

function calculateEntrySlTpOverlays(
	entryPrice: number,
	zoneWidthPct: number,
	direction: 'long' | 'short',
): StrategyProofExample['overlays'] {
	const zoneWidth = entryPrice * (zoneWidthPct / 100);
	const slPrice = direction === 'long' ? (entryPrice - zoneWidth) : (entryPrice + zoneWidth);
	const tpPrice = direction === 'long' ? (entryPrice + zoneWidth * 2) : (entryPrice - zoneWidth * 2);
	
	return [
		{ kind: 'hline' as const, label: `Entry (${direction.toUpperCase()})`, price: entryPrice },
		{ kind: 'hline' as const, label: 'Stop Loss', price: slPrice },
		{ kind: 'hline' as const, label: 'Take Profit', price: tpPrice },
	];
}

function pushProofExample(
	out: StrategyProofExample[],
	candles: CandleRecord[],
	idx: number,
	title: string,
	rationale: string,
	confidence: number,
	direction: 'long' | 'short',
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
		direction,
		centerTs: c.ts,
		centerPrice: c.close,
		window: buildProofWindow(candles, idx),
		overlays,
	});
}

function detectStrategyProofExamples(
	candles: CandleRecord[],
	strategyType: string,
	maxExamples: number,
	zoneWidthPct: number = 0.18,
	confirmation: string = '',
): StrategyProofExample[] {
	if (candles.length < 40) {
		return [];
	}

	const examples: StrategyProofExample[] = [];
	const ranges = candles.map((c) => Math.max(1e-9, c.high - c.low));
	const avgRange = ranges.reduce((acc, v) => acc + v, 0) / ranges.length;
	const type = String(strategyType || '').toLowerCase();
	const confirmationLower = String(confirmation || '').toLowerCase();
	const requireRejection = confirmationLower.includes('rejection');

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
				const centerPrice = candles[i].close;
				const direction: 'long' | 'short' = upward ? 'long' : 'short';
				const baseOverlays = [
					{
						kind: 'channel' as const,
						label: 'Trend channel',
						startTs: candles[windowStart].ts,
						endTs: candles[i].ts,
						upperStartPrice: hi,
						upperEndPrice: hi + (upward ? pad : -pad),
						lowerStartPrice: lo,
						lowerEndPrice: lo + (upward ? pad : -pad),
					},
				];
				const slTpOverlays = calculateEntrySlTpOverlays(centerPrice, zoneWidthPct, direction);
				pushProofExample(
					examples,
					candles,
					i,
					'Trend continuation',
					`Sustained directional closes across the lookback window (${direction}).`,
					0.58 + ratio * 0.35,
					direction,
					[...baseOverlays, ...slTpOverlays],
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
				const centerPrice = candles[i].close;
				const rejectionDir = detectRejectionDirection(candles[i]);
				if (requireRejection && !rejectionDir) {
					continue;
				}
				const distToHigh = Math.abs(candles[i].close - hi);
				const distToLow = Math.abs(candles[i].close - lo);
				const direction: 'long' | 'short' = rejectionDir || (distToHigh < distToLow ? 'short' : 'long');
				const baseOverlays = [
					{
						kind: 'box' as const,
						label: 'Range box',
						startTs: window[0].ts,
						endTs: window[window.length - 1].ts,
						low: lo,
						high: hi,
					},
				];
				const slTpOverlays = calculateEntrySlTpOverlays(centerPrice, zoneWidthPct, direction);
				pushProofExample(
					examples,
					candles,
					i,
					'Range containment',
					`Price repeatedly tests boundaries and aligns with ${direction} rejection context.`,
					confidence,
					direction,
					[...baseOverlays, ...slTpOverlays],
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
				const centerPrice = candles[i].close;
				const direction: 'long' | 'short' = breakoutUp ? 'long' : 'short';
				const baseOverlays = [
					{ kind: 'hline' as const, label: 'Breakout boundary', price: boundary },
					{ kind: 'vline' as const, label: 'Break candle', ts: candles[i].ts },
				];
				const slTpOverlays = calculateEntrySlTpOverlays(centerPrice, zoneWidthPct, direction);
				pushProofExample(
					examples,
					candles,
					i,
					'Breakout trigger',
					`Close breaches the prior consolidation boundary (${direction} breakout).`,
					0.55 + Math.min(0.38, impulse * 0.12),
					direction,
					[...baseOverlays, ...slTpOverlays],
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
				const centerPrice = candles[i].close;
				const rejectionDir = detectRejectionDirection(candles[i]);
				if (requireRejection && !rejectionDir) {
					continue;
				}
				const direction: 'long' | 'short' = rejectionDir || inferDirectionFromFollowThrough(candles, i);
				const slTpOverlays = calculateEntrySlTpOverlays(centerPrice, zoneWidthPct, direction);
				pushProofExample(
					examples,
					candles,
					i,
					'Scalp micro-move',
					requireRejection
						? `Rejection candle confirms a ${direction} scalp setup with follow-through.`
						: `Short-duration setup with ${direction} follow-through.`,
					0.5 + Math.min(0.4, (nextMove / Math.max(1e-9, avgRange)) * 0.08),
					direction,
					slTpOverlays,
				);
			}
		}
	}

	if (type.includes('swing')) {
		for (let i = 8; i < candles.length - 8 && examples.length < maxExamples; i += 5) {
			const lo = candles.slice(i - 3, i + 4).every((c) => candles[i].low <= c.low);
			const hi = candles.slice(i - 3, i + 4).every((c) => candles[i].high >= c.high);
			if (lo || hi) {
				const centerPrice = candles[i].close;
				const direction: 'long' | 'short' = lo ? 'long' : 'short';
				const slTpOverlays = calculateEntrySlTpOverlays(centerPrice, zoneWidthPct, direction);
				pushProofExample(examples, candles, i, 'Swing pivot', `Local pivot marks a potential ${direction} swing correction.`, 0.66, direction, slTpOverlays);
			}
		}
	}

	if (type.includes('position')) {
		for (let i = 90; i < candles.length && examples.length < maxExamples; i += 20) {
			const longUp = isTrendWindow(candles, i - 80, i, 'up');
			const longDown = isTrendWindow(candles, i - 80, i, 'down');
			if (longUp || longDown) {
				const centerPrice = candles[i].close;
				const direction: 'long' | 'short' = longUp ? 'long' : 'short';
				const slTpOverlays = calculateEntrySlTpOverlays(centerPrice, zoneWidthPct, direction);
				pushProofExample(examples, candles, i, 'Position trend leg', `Extended ${direction} leg consistent with position holding periods.`, 0.72, direction, slTpOverlays);
			}
		}
	}

	if (type.includes('news')) {
		for (let i = 1; i < candles.length && examples.length < maxExamples; i += 3) {
			const ratio = (candles[i].high - candles[i].low) / Math.max(1e-9, avgRange);
			if (ratio >= 2.8) {
				const centerPrice = candles[i].close;
				const direction: 'long' | 'short' = Number(candles[i].close) >= Number(candles[i].open) ? 'long' : 'short';
				const slTpOverlays = calculateEntrySlTpOverlays(centerPrice, zoneWidthPct, direction);
				pushProofExample(examples, candles, i, 'Volatility spike', `Expansion bar consistent with event-driven ${direction} volatility.`, 0.56 + Math.min(0.36, ratio * 0.08), direction, slTpOverlays);
			}
		}
	}

	if (type.includes('gap')) {
		for (let i = 1; i < candles.length && examples.length < maxExamples; i += 2) {
			const gap = Math.abs(candles[i].open - candles[i - 1].close);
			if (gap >= avgRange * 0.8) {
				const centerPrice = candles[i].close;
				const direction: 'long' | 'short' = Number(candles[i].open) >= Number(candles[i - 1].close) ? 'long' : 'short';
				const baseOverlays = [
					{ kind: 'vline' as const, label: 'Gap candle', ts: candles[i].ts },
				];
				const slTpOverlays = calculateEntrySlTpOverlays(centerPrice, zoneWidthPct, direction);
				pushProofExample(
					examples,
					candles,
					i,
					'Gap setup',
					`Session transition opens away from prior close, favoring ${direction} continuation.`,
					0.54 + Math.min(0.38, (gap / Math.max(1e-9, avgRange)) * 0.1),
					direction,
					[...baseOverlays, ...slTpOverlays],
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
				const proximity = 1 - Math.min(1, bestDist / Math.max(1e-9, avgRange * 4));
				const strengthScore = Math.min(0.30, zone.strength / 25);
				const confidence = 0.48 + strengthScore + proximity * 0.20;
				const centerPrice = candles[bestIdx].close;
				const direction: 'long' | 'short' = zone.kind === 'support' ? 'long' : 'short';
				const baseOverlays = [
					{ kind: 'hline' as const, label: `${zone.kind} center`, price: zone.center },
					{ kind: 'box' as const, label: `${zone.kind} zone`, startTs: candles[Math.max(0, bestIdx - 20)].ts, endTs: candles[Math.min(candles.length - 1, bestIdx + 20)].ts, low: zone.low, high: zone.high },
				];
				const slTpOverlays = calculateEntrySlTpOverlays(centerPrice, zoneWidthPct, direction);
				pushProofExample(
					examples,
					candles,
					bestIdx,
					zone.kind === 'support' ? 'Support reaction' : 'Resistance reaction',
					`Price clusters around a ${zone.kind} zone, supporting a ${direction} reaction setup.`,
					confidence,
					direction,
					[...baseOverlays, ...slTpOverlays],
				);
			}
		}
	}

	if (!examples.length) {
		const lastCandle = candles[candles.length - 1];
		const centerPrice = lastCandle.close;
		const direction: 'long' | 'short' = Number(lastCandle.close) >= Number(lastCandle.open) ? 'long' : 'short';
		const slTpOverlays = calculateEntrySlTpOverlays(centerPrice, zoneWidthPct, direction);
		pushProofExample(examples, candles, candles.length - 1, 'Recent context', 'No strong pattern sample found; showing latest structure window for review.', 0.45, direction, slTpOverlays);
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
			entryTimeframe: recognition.primaryTimeframe,
			primaryTimeframe: recognition.primaryTimeframe,
			tradeHorizonTimeframe: recognition.tradeHorizonTimeframe,
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

function toFiniteNumber(value: unknown, fallback = 0): number {
	const parsed = Number(value);
	return Number.isFinite(parsed) ? parsed : fallback;
}

function getRunPresentationData(run: StrategyRunRecord): {
	title: string;
	market: string;
	scenario: string;
	periodKey: string;
	createdAt: string;
	startCapital: number;
	finalCapital: number;
	returnPct: number;
	profitFactor: number;
	winRatePct: number;
	maxDrawdownPct: number;
	tradeCount: number;
	note: string;
} {
	const summary = (run.summary && typeof run.summary === 'object') ? run.summary as Record<string, unknown> : {};
	const best = (summary.best && typeof summary.best === 'object') ? summary.best as Record<string, unknown> : {};
	const title = String(
		summary.strategy
			|| summary.strategyName
			|| best.label
			|| summary.periodKey
			|| 'Untitled',
	).trim();
	const market = String(summary.market || 'N/A').trim() || 'N/A';
	const scenario = String(summary.scenario || summary.riskProfile || 'N/A').trim() || 'N/A';
	const periodKey = String(summary.periodKey || '').trim();
	const startCapital = toFiniteNumber(summary.startCapital, 0);
	const finalCapital = toFiniteNumber(best.compounded ?? best.finalCapital, startCapital);
	const netPnl = finalCapital - startCapital;
	const returnPct = toFiniteNumber(
		summary.return ?? best.avgRet ?? summary.avgReturnPct,
		startCapital > 0 ? (netPnl / startCapital) * 100 : 0,
	);
	const profitFactor = toFiniteNumber(summary.profitFactor ?? best.avgPf, 1);
	const winRatePct = toFiniteNumber(summary.winRate ?? best.avgWin, 0);
	const maxDrawdownPct = toFiniteNumber(summary.maxDrawdownPct ?? best.worstDD, 0);
	const tradeCount = parsePositiveInt(summary.tradeCount ?? best.trades, 0);
	const note = String(summary.note || '').trim();

	return {
		title,
		market,
		scenario,
		periodKey,
		createdAt: run.createdAt,
		startCapital,
		finalCapital,
		returnPct,
		profitFactor,
		winRatePct,
		maxDrawdownPct,
		tradeCount,
		note,
	};
}

function writeRunPdf(doc: PDFKit.PDFDocument, run: StrategyRunRecord): void {
	const data = getRunPresentationData(run);
	const netPnl = data.finalCapital - data.startCapital;
	const generatedAt = new Date().toISOString();

	doc.fontSize(20).text('Strategy Run Report', { align: 'left' });
	doc.moveDown(0.2);
	doc.fontSize(11).fillColor('#4b5563').text(`Run ID: ${run.id}`);
	doc.text(`Generated: ${generatedAt}`);
	doc.text(`Created: ${data.createdAt}`);
	doc.moveDown(0.8);

	doc.fillColor('#111827').fontSize(14).text('Overview');
	doc.moveDown(0.3);
	doc.fontSize(11);
	doc.text(`Strategy: ${data.title}`);
	doc.text(`Market: ${data.market}`);
	doc.text(`Scenario: ${data.scenario}`);
	if (data.periodKey) {
		doc.text(`Period Key: ${data.periodKey}`);
	}
	doc.moveDown(0.8);

	doc.fontSize(14).text('Performance');
	doc.moveDown(0.3);
	doc.fontSize(11);
	doc.text(`Start Capital: £${data.startCapital.toLocaleString('en-GB', { maximumFractionDigits: 2 })}`);
	doc.text(`Final Capital: £${data.finalCapital.toLocaleString('en-GB', { maximumFractionDigits: 2 })}`);
	doc.text(`Net P&L: £${netPnl.toLocaleString('en-GB', { maximumFractionDigits: 2 })}`);
	doc.text(`Return: ${data.returnPct.toFixed(2)}%`);
	doc.text(`Profit Factor: ${data.profitFactor.toFixed(2)}`);
	doc.text(`Win Rate: ${data.winRatePct.toFixed(2)}%`);
	doc.text(`Max Drawdown: ${data.maxDrawdownPct.toFixed(2)}%`);
	doc.text(`Trades: ${data.tradeCount}`);

	if (data.note) {
		doc.moveDown(0.8);
		doc.fontSize(14).text('Notes');
		doc.moveDown(0.3);
		doc.fontSize(11).text(data.note, { width: 500 });
	}
}

function writeRunsOverviewPdf(doc: PDFKit.PDFDocument, runs: StrategyRunRecord[]): void {
	doc.fontSize(20).text('Strategy Runs Export');
	doc.moveDown(0.2);
	doc.fontSize(11).fillColor('#4b5563').text(`Generated: ${new Date().toISOString()}`);
	doc.text(`Runs: ${runs.length}`);
	doc.moveDown(0.8);
	doc.fillColor('#111827').fontSize(12).text('Summary');
	doc.moveDown(0.3);

	runs.forEach((run, index) => {
		const data = getRunPresentationData(run);
		doc.fontSize(10).fillColor('#111827').text(
			`${index + 1}. ${data.title} | ${data.market} | Return ${data.returnPct.toFixed(2)}% | PF ${data.profitFactor.toFixed(2)} | ${new Date(data.createdAt).toLocaleDateString('en-GB')}`,
			{ width: 510 },
		);
		doc.moveDown(0.2);
	});
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

function loadComparativeReportManifest(): ComparativeReportRecord[] {
	const fallback: ComparativeReportRecord[] = [
		{
			id: 'phantom-p2-branch-competition-2021-gbp10k',
			title: 'Phantom P2 Branch Competition',
			description: 'p2_filter_test1 vs p2_filter_test2 vs p2_filter_test3 with 2021+ window and GBP 10,000 baseline.',
			generatedAt: '2026-04-16T00:00:00Z',
			windowStart: '2021-01-01',
			windowEnd: '2026-03-31',
			dataFile: 'backtest_artifacts/branch-competition-us100-20260416/dashboard_2021_10k/dashboard_data_2021_10k.json',
		},
	];

	try {
		const manifestFile = fileExists(COMPARATIVE_REPORTS_FILE)
			? COMPARATIVE_REPORTS_FILE
			: APP_COMPARATIVE_REPORTS_FILE;
		if (!fileExists(manifestFile)) {
			return fallback;
		}

		const raw = fs.readFileSync(manifestFile, 'utf8');
		const parsed = JSON.parse(raw) as Partial<ComparativeReportManifest>;
		if (!parsed || !Array.isArray(parsed.reports)) {
			return fallback;
		}

		const reports = parsed.reports
			.map((report): ComparativeReportRecord | null => {
				if (!report || typeof report !== 'object') {
					return null;
				}
				const id = String(report.id || '').trim();
				const title = String(report.title || '').trim();
				const dataFile = String(report.dataFile || '').trim();
				if (!id || !title || !dataFile) {
					return null;
				}
				return {
					id,
					title,
					description: String(report.description || '').trim() || undefined,
					generatedAt: String(report.generatedAt || '').trim() || undefined,
					windowStart: String(report.windowStart || '').trim() || undefined,
					windowEnd: String(report.windowEnd || '').trim() || undefined,
					dataFile,
				};
			})
			.filter((report): report is ComparativeReportRecord => Boolean(report));

		return reports.length ? reports : fallback;
	} catch {
		return fallback;
	}
}

function saveComparativeReportManifest(reports: ComparativeReportRecord[]): void {
	const payload: ComparativeReportManifest = { reports };
	fs.mkdirSync(path.dirname(COMPARATIVE_REPORTS_FILE), { recursive: true });
	fs.writeFileSync(COMPARATIVE_REPORTS_FILE, `${JSON.stringify(payload, null, 2)}\n`, 'utf8');
}

function normalizeComparativeReportId(value: string): string {
	const token = String(value || '')
		.trim()
		.toLowerCase()
		.replace(/[^a-z0-9\-_\s]+/g, '')
		.replace(/\s+/g, '-')
		.replace(/-+/g, '-');
	return token.replace(/^-+|-+$/g, '');
}

function resolveComparativeReportDataPath(dataFile: string): string {
	const candidate = path.isAbsolute(dataFile)
		? normalizePath(dataFile)
		: normalizePath(path.join(WORKSPACE_ROOT, dataFile));

	if (!isPathInsideDirectory(candidate, WORKSPACE_ROOT)) {
		throw new Error('Comparative report data path must be inside the workspace root');
	}

	return candidate;
}

function readComparativeReportData(report: ComparativeReportRecord): unknown {
	const absPath = resolveComparativeReportDataPath(report.dataFile);
	if (!fileExists(absPath)) {
		throw new Error(`Comparative report data file missing: ${absPath}`);
	}

	const raw = fs.readFileSync(absPath, 'utf8');
	return JSON.parse(raw);
}

function normalizeReportTitle(title: string): string {
	const value = String(title || '').trim();
	const lowered = value.toLowerCase();
	if (lowered.includes('phantom p1')) return 'Phantom Median Strategy A';
	if (lowered.includes('phantom p2')) return 'Phantom Median Strategy B';
	if (lowered.includes('phantom p3')) return 'Phantom Median Strategy C';
	if (lowered.includes('branch competition')) return 'Phantom Variant Comparison';
	return value;
}

function normalizeComparativeBranchKey(branchKey: string): string {
	const upper = String(branchKey || '').trim().toUpperCase();
	if (upper === 'PHANTOM_P1' || upper === 'P1' || upper === 'V1') return 'variant_a';
	if (upper === 'PHANTOM_P2' || upper === 'P2' || upper === 'V2') return 'variant_b';
	if (upper === 'PHANTOM_P3' || upper === 'P3' || upper === 'V3') return 'variant_c';
	return String(branchKey || '');
}

function normalizeComparativeReportData(rawData: unknown): unknown {
	if (!rawData || typeof rawData !== 'object' || Array.isArray(rawData)) {
		return rawData;
	}

	const data = JSON.parse(JSON.stringify(rawData)) as Record<string, unknown>;
	if (typeof data.title === 'string') {
		data.title = normalizeReportTitle(data.title);
	}
	if (typeof data.reportTitle === 'string') {
		data.reportTitle = normalizeReportTitle(data.reportTitle);
	}
	if (data.meta && typeof data.meta === 'object' && !Array.isArray(data.meta)) {
		const meta = data.meta as Record<string, unknown>;
		if (typeof meta.strategyLabel === 'string') {
			meta.strategyLabel = normalizeReportTitle(meta.strategyLabel);
		}
		if (typeof meta.title === 'string') {
			meta.title = normalizeReportTitle(meta.title);
		}
		if (typeof meta.sourceBranch === 'string') {
			meta.sourceBranch = normalizeComparativeBranchKey(meta.sourceBranch);
		}
	}

	if (data.summary && Array.isArray(data.summary)) {
		data.summary = data.summary.map((row) => {
			if (!row || typeof row !== 'object' || Array.isArray(row)) return row;
			const item = { ...(row as Record<string, unknown>) };
			if (typeof item.branch === 'string') {
				item.branch = normalizeComparativeBranchKey(item.branch);
			}
			return item;
		});
	}

	if (data.highlights && Array.isArray(data.highlights)) {
		data.highlights = data.highlights.map((row) => {
			if (!row || typeof row !== 'object' || Array.isArray(row)) return row;
			const item = { ...(row as Record<string, unknown>) };
			if (typeof item.branch === 'string') {
				item.branch = normalizeComparativeBranchKey(item.branch);
			}
			return item;
		});
	}

	if (data.monthly && typeof data.monthly === 'object' && !Array.isArray(data.monthly)) {
		const monthly = data.monthly as Record<string, unknown>;
		for (const [mode, modeValue] of Object.entries(monthly)) {
			if (!modeValue || typeof modeValue !== 'object' || Array.isArray(modeValue)) continue;
			const modeRows = modeValue as Record<string, unknown>;
			const normalizedRows: Record<string, unknown> = {};
			for (const [branchKey, rows] of Object.entries(modeRows)) {
				normalizedRows[normalizeComparativeBranchKey(branchKey)] = rows;
			}
			monthly[mode] = normalizedRows;
		}
	}

	return data;
}

function loadComparativeProfileSets(): ComparativeProfileSetRecord[] {
	try {
		if (!fileExists(COMPARATIVE_PROFILE_SETS_FILE)) {
			return [];
		}

		const raw = fs.readFileSync(COMPARATIVE_PROFILE_SETS_FILE, 'utf8');
		const parsed = JSON.parse(raw);
		if (!Array.isArray(parsed)) {
			return [];
		}

		const out: ComparativeProfileSetRecord[] = [];
		for (const item of parsed) {
			if (!item || typeof item !== 'object') {
				continue;
			}

			const id = normalizeComparativeReportId(String((item as { id?: unknown }).id || ''));
			const name = String((item as { name?: unknown }).name || '').trim();
			const reportIds = Array.isArray((item as { reportIds?: unknown }).reportIds)
				? ((item as { reportIds?: unknown[] }).reportIds || [])
					.map((value) => normalizeComparativeReportId(String(value || '')))
					.filter((value) => Boolean(value))
				: [];
			if (!id || !name || !reportIds.length) {
				continue;
			}

			out.push({
				id,
				name,
				reportIds: Array.from(new Set(reportIds)),
				windowStart: String((item as { windowStart?: unknown }).windowStart || '').trim() || undefined,
				windowEnd: String((item as { windowEnd?: unknown }).windowEnd || '').trim() || undefined,
				createdAt: String((item as { createdAt?: unknown }).createdAt || '').trim() || new Date().toISOString(),
				updatedAt: String((item as { updatedAt?: unknown }).updatedAt || '').trim() || new Date().toISOString(),
			});
		}

		return out;
	} catch {
		return [];
	}
}

function saveComparativeProfileSets(sets: ComparativeProfileSetRecord[]): void {
	fs.mkdirSync(path.dirname(COMPARATIVE_PROFILE_SETS_FILE), { recursive: true });
	fs.writeFileSync(COMPARATIVE_PROFILE_SETS_FILE, `${JSON.stringify(sets, null, 2)}\n`, 'utf8');
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
	if (tf === '30m') {
		return 30;
	}
	if (tf === '1h') {
		return 60;
	}
	if (tf === '4h') {
		return 240;
	}
	if (tf === '1d') {
		return 1440;
	}
	if (tf === '1w') {
		return 10080;
	}
	if (tf === '1mo') {
		return 43200;
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
		direction: r.direction || r.dir || '',
		entry_time: r.entry_time || r.entry_ts || r.entry || '',
		entry_price: Number(r.entry_price || 0),
		exit_time: r.exit_time || r.exit_ts || r.exit || '',
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

function findLatestTradesFileForMarket(marketInput: string): string | null {
	const market = canonicalizeDatasetSymbol(String(marketInput || '')).toUpperCase();
	const instrumentCode = mapSymbolToPhantomInstrumentCode(market);
	const tokenVariants = Array.from(new Set([
		instrumentCode,
		market,
		market.replace(/USD$/i, ''),
	])).filter(Boolean);
	const candidateRoots = [
		ARTIFACT_DIR,
		ARCHIVE_ARTIFACT_DIR,
		path.join(WORKSPACE_ROOT, '_docs_archive', 'backtest_artifacts'),
	];

	let bestPath: string | null = null;
	let bestMtime = -1;

	for (const root of candidateRoots) {
		if (!fs.existsSync(root)) {
			continue;
		}

		const stack = [root];
		while (stack.length) {
			const dirPath = stack.pop();
			if (!dirPath) continue;

			let entries: fs.Dirent[] = [];
			try {
				entries = fs.readdirSync(dirPath, { withFileTypes: true });
			} catch {
				continue;
			}

			for (const entry of entries) {
				const fullPath = path.join(dirPath, entry.name);
				if (entry.isDirectory()) {
					stack.push(fullPath);
					continue;
				}

				const upperName = entry.name.toUpperCase();
				if (!upperName.includes('TRADE') || !upperName.endsWith('.CSV')) {
					continue;
				}

				const matchesMarket = tokenVariants.some((token) => token && upperName.includes(String(token).toUpperCase()));
				if (!matchesMarket) {
					continue;
				}

				try {
					const stat = fs.statSync(fullPath);
					if (stat.mtimeMs > bestMtime) {
						bestMtime = stat.mtimeMs;
						bestPath = fullPath;
					}
				} catch {
					// Skip files that disappear mid-scan.
				}
			}
		}
	}

	return bestPath;
}

function inferRiskProfileFromRunSummary(summary: Record<string, unknown>): 'high' | 'median' | 'low' {
	const best = summary.best && typeof summary.best === 'object' ? (summary.best as Record<string, unknown>) : {};
	const haystack = `${String(summary.riskProfile || '')} ${String(summary.periodKey || '')} ${String(best.label || '')}`.toLowerCase();
	if (haystack.includes('high')) return 'high';
	if (haystack.includes('low')) return 'low';
	return 'median';
}

function findNearestTradesFileForRun(run: StrategyRunRecord, marketInput: string, riskProfile: 'high' | 'median' | 'low'): string | null {
	const market = canonicalizeDatasetSymbol(String(marketInput || '')).toUpperCase();
	const instrumentCode = mapSymbolToPhantomInstrumentCode(market);
	const tokenVariants = Array.from(new Set([
		instrumentCode,
		market,
		market.replace(/USD$/i, ''),
	])).filter(Boolean);
	const candidateRoots = [
		ARTIFACT_DIR,
		ARCHIVE_ARTIFACT_DIR,
		path.join(WORKSPACE_ROOT, '_docs_archive', 'backtest_artifacts'),
	];
	const createdAtMs = Number.isFinite(Date.parse(String(run.createdAt || '')))
		? Date.parse(String(run.createdAt || ''))
		: null;

	let bestPath: string | null = null;
	let bestScore = Number.POSITIVE_INFINITY;
	let bestMtime = -1;

	for (const root of candidateRoots) {
		if (!fs.existsSync(root)) {
			continue;
		}

		const stack = [root];
		while (stack.length) {
			const dirPath = stack.pop();
			if (!dirPath) continue;

			let entries: fs.Dirent[] = [];
			try {
				entries = fs.readdirSync(dirPath, { withFileTypes: true });
			} catch {
				continue;
			}

			for (const entry of entries) {
				const fullPath = path.join(dirPath, entry.name);
				if (entry.isDirectory()) {
					stack.push(fullPath);
					continue;
				}

				const upperName = entry.name.toUpperCase();
				if (!upperName.includes('TRADE') || !upperName.endsWith('.CSV')) {
					continue;
				}

				const upperPath = fullPath.toUpperCase();
				const matchesMarket = tokenVariants.some((token) => token && upperPath.includes(String(token).toUpperCase()));
				if (!matchesMarket) {
					continue;
				}

				const profileTag = `-${riskProfile.toUpperCase()}-VALIDATE-`;
				const matchesProfile = upperPath.includes(profileTag);
				if (!matchesProfile) {
					continue;
				}

				try {
					const stat = fs.statSync(fullPath);
					const score = createdAtMs === null
						? -stat.mtimeMs
						: Math.abs(stat.mtimeMs - createdAtMs);
					if (score < bestScore || (score === bestScore && stat.mtimeMs > bestMtime)) {
						bestScore = score;
						bestMtime = stat.mtimeMs;
						bestPath = fullPath;
					}
				} catch {
					// Skip files that disappear mid-scan.
				}
			}
		}
	}

	return bestPath;
}

function buildMonthlyComparativeDataFromTrades(trades: TradeRecord[], startCapital: number): Record<string, unknown> | null {
	const ordered = trades
		.map((trade) => ({
			...trade,
			tradeTime: trade.exit_time || trade.entry_time || '',
		}))
		.filter((trade) => Boolean(trade.tradeTime) && Number.isFinite(Date.parse(trade.tradeTime)) && Number.isFinite(Number(trade.pnl)))
		.sort((a, b) => Date.parse(a.tradeTime) - Date.parse(b.tradeTime));

	if (!ordered.length) {
		return null;
	}

	let equity = startCapital;
	let rollingPeak = startCapital;
	const monthStats = new Map<string, {
		monthlyPnl: number;
		monthEndEquity: number;
		monthEndPeak: number;
		monthEndDrawdownAmt: number;
		monthEndDrawdownPct: number;
		worstIntramonthDdAmt: number;
		worstIntramonthDdPct: number;
	}>();

	for (const trade of ordered) {
		const tradeDate = new Date(trade.tradeTime);
		if (Number.isNaN(tradeDate.getTime())) {
			continue;
		}

		equity += Number(trade.pnl || 0);
		rollingPeak = Math.max(rollingPeak, equity);
		const month = tradeDate.toISOString().slice(0, 7);
		const ddAmt = equity - rollingPeak;
		const ddPct = rollingPeak ? (ddAmt / rollingPeak) * 100 : 0;
		const current = monthStats.get(month) || {
			monthlyPnl: 0,
			monthEndEquity: startCapital,
			monthEndPeak: startCapital,
			monthEndDrawdownAmt: 0,
			monthEndDrawdownPct: 0,
			worstIntramonthDdAmt: 0,
			worstIntramonthDdPct: 0,
		};

		current.monthlyPnl += Number(trade.pnl || 0);
		current.monthEndEquity = equity;
		current.monthEndPeak = rollingPeak;
		current.monthEndDrawdownAmt = ddAmt;
		current.monthEndDrawdownPct = ddPct;
		if (ddAmt < current.worstIntramonthDdAmt) {
			current.worstIntramonthDdAmt = ddAmt;
			current.worstIntramonthDdPct = ddPct;
		}

		monthStats.set(month, current);
	}

	const months = Array.from(monthStats.keys()).sort();
	if (!months.length) {
		return null;
	}

	const rows = months.map((month) => {
		const current = monthStats.get(month);
		if (!current) {
			return null;
		}

		return {
			month,
			monthly_pnl_gbp: Number(current.monthlyPnl.toFixed(2)),
			month_end_equity_gbp: Number(current.monthEndEquity.toFixed(2)),
			month_end_drawdown_amt_gbp: Number(current.monthEndDrawdownAmt.toFixed(2)),
			month_end_drawdown_pct: Number(current.monthEndDrawdownPct.toFixed(3)),
			worst_intramonth_dd_amt_gbp: Number(current.worstIntramonthDdAmt.toFixed(2)),
			worst_intramonth_dd_pct: Number(current.worstIntramonthDdPct.toFixed(3)),
		};
	}).filter((row): row is {
		month: string;
		monthly_pnl_gbp: number;
		month_end_equity_gbp: number;
		month_end_drawdown_amt_gbp: number;
		month_end_drawdown_pct: number;
		worst_intramonth_dd_amt_gbp: number;
		worst_intramonth_dd_pct: number;
	} => Boolean(row));

	const monthPnls = rows.map((row) => Number(row.monthly_pnl_gbp));
	const bestMonth = rows.reduce((best, row) => (Number(row.monthly_pnl_gbp) > Number(best.monthly_pnl_gbp) ? row : best), rows[0]);
	const worstMonth = rows.reduce((worst, row) => (Number(row.monthly_pnl_gbp) < Number(worst.monthly_pnl_gbp) ? row : worst), rows[0]);
	const positiveMonths = monthPnls.filter((value) => value > 0).length;
	const negativeMonths = monthPnls.filter((value) => value < 0).length;
	const flatMonths = monthPnls.length - positiveMonths - negativeMonths;
	const worstDdAmt = rows.reduce((min, row) => Math.min(min, Number(row.worst_intramonth_dd_amt_gbp)), 0);
	const worstDdPct = rows.reduce((min, row) => Math.min(min, Number(row.worst_intramonth_dd_pct)), 0);
	const lastRow = rows[rows.length - 1];
	const netPnl = Number((lastRow.month_end_equity_gbp - startCapital).toFixed(2));
	const returnPct = startCapital ? Number(((netPnl / startCapital) * 100).toFixed(2)) : 0;

	return {
		windows: [{
			mode: 'full',
			start_date: `${months[0]}-01`,
			end_date: `${months[months.length - 1]}-01`,
			timescale_months: months.length,
		}],
		summary: [{
			branch: 'variant_b',
			mode: 'full',
			start_cap_gbp: Number(startCapital.toFixed(2)),
			final_equity_gbp: Number(lastRow.month_end_equity_gbp.toFixed(2)),
			net_pnl_gbp: netPnl,
			net_return_pct: returnPct,
			max_dd_amt_gbp: Number(worstDdAmt.toFixed(2)),
			max_dd_pct: Number(worstDdPct.toFixed(3)),
			months: months.length,
		}],
		highlights: [{
			branch: 'variant_b',
			mode: 'full',
			positive_month_ratio_pct: Number(((positiveMonths / months.length) * 100).toFixed(1)),
			best_month_pnl_gbp: Number(bestMonth.monthly_pnl_gbp.toFixed(2)),
			worst_month_pnl_gbp: Number(worstMonth.monthly_pnl_gbp.toFixed(2)),
			positive_months: positiveMonths,
			negative_months: negativeMonths,
			flat_months: flatMonths,
		}],
		monthly: {
			full: {
				variant_b: rows,
			},
		},
	};
}

function buildComparativeDataForRun(run: StrategyRunRecord): Record<string, unknown> | null {
	const summary = getRunSummaryObject(run);
	if (summary.comparativeData && typeof summary.comparativeData === 'object' && !Array.isArray(summary.comparativeData)) {
		return summary.comparativeData as Record<string, unknown>;
	}

	const market = String(summary.market || '').trim();
	if (!market) {
		return null;
	}

	const startCapital = toNumber(summary.startCapital, 5000);
	const riskProfile = inferRiskProfileFromRunSummary(summary);
	const cacheKey = String(run.id || `${market.toUpperCase()}::${riskProfile}::${startCapital}`);
	if (comparativeDataCache.has(cacheKey)) {
		return comparativeDataCache.get(cacheKey) || null;
	}

	const tradesFile = findNearestTradesFileForRun(run, market, riskProfile) || findLatestTradesFileForMarket(market);
	if (!tradesFile) {
		comparativeDataCache.set(cacheKey, null);
		return null;
	}

	const trades = getOrLoadTrades(tradesFile);
	const comparativeData = buildMonthlyComparativeDataFromTrades(trades, startCapital);
	if (comparativeData) {
		(comparativeData as Record<string, unknown>).tradesFile = normalizePath(tradesFile);
	}
	comparativeDataCache.set(cacheKey, comparativeData);
	return comparativeData;
}

function enrichRunForComparativeReports(run: StrategyRunRecord): StrategyRunRecord {
	const comparativeData = buildComparativeDataForRun(run);
	if (!comparativeData) {
		return run;
	}

	const summary = getRunSummaryObject(run);
	return {
		...run,
		summary: {
			...summary,
			comparativeData,
		},
	};
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

function resolvePhantomBacktestCommand(symbolInput: string, capital: number): {
	pythonExec: string;
	scriptPath: string;
	args: string[];
	instrumentCode: 'XAU' | 'US100' | 'BTC' | 'FX';
	scenarioKey: 'A' | 'B' | 'C';
	riskProfile: 'high' | 'median' | 'low';
	periodKey: string;
	strategyLabel: string;
} {
	const symbol = canonicalizeDatasetSymbol(String(symbolInput || ''));
	const riskProfile: 'high' | 'median' | 'low' = 'median';
	const instrumentCode = mapSymbolToPhantomInstrumentCode(symbol);
	const stem = mapSymbolToPhantomStem(symbol);
	const scriptCandidates = resolvePhantomScriptCandidates(symbol, riskProfile);
	const scriptPath = scriptCandidates.find((candidate) => fileExists(candidate));

	if (!scriptPath) {
		throw new Error(`No phantom runtime script found for ${symbol} (${riskProfile})`);
	}

	const m1 = resolveMarketTimeframeFile(symbol, '1m');
	const m5 = resolveMarketTimeframeFile(symbol, '5m');
	const m15 = resolveMarketTimeframeFile(symbol, '15m');
	const h1 = resolveMarketTimeframeFile(symbol, '1h');
	const h4 = resolveMarketTimeframeFile(symbol, '4h');
	const daily = resolveMarketTimeframeFile(symbol, '1d');

	const pythonExec = path.join(WORKSPACE_ROOT, '.venv', 'bin', 'python');
	const args = [
		'-u',
		scriptPath,
		'--instrument', instrumentCode,
		'--m1', m1,
		'--m5', m5,
		'--m15', m15,
		'--h1', h1,
		'--h4', h4,
		'--daily', daily,
		'--capital', String(capital),
		'--output-dir', ARTIFACT_DIR,
	];

	if (instrumentCode === 'US100') {
		args.push('--start-date', '2021-01-01');
	}

	const scenarioKey: 'A' | 'B' | 'C' = 'B';

	return {
		pythonExec,
		scriptPath,
		args,
		instrumentCode,
		scenarioKey,
		riskProfile,
		periodKey: `LIVE PHANTOM_${stem.toUpperCase()}_MEDIAN VALIDATION`,
		strategyLabel: `phantom_${stem.toLowerCase()}_median • Scenario ${scenarioKey}`,
	};
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

	let command: ReturnType<typeof resolvePhantomBacktestCommand>;
	try {
		command = resolvePhantomBacktestCommand(symbol, capital);
	} catch (error) {
		const message = (error as Error).message || 'Failed to resolve phantom runtime command';
		pushLog(message);
		backtestState.status = 'failed';
		backtestState.endedAt = new Date().toISOString();
		if (linkedRunId) {
			updateRunSummary(linkedRunId, {
				status: 'failed',
				endedAt: backtestState.endedAt,
				error: message,
			});
		}
		broadcast('status', backtestState);
		return { ok: false, error: message };
	}

	const { pythonExec, args } = command;

	backtestProc = spawn(pythonExec, args, {
		cwd: WORKSPACE_ROOT,
		env: { ...process.env, PYTHONUNBUFFERED: '1' },
	});
	pushLog(`Started backtest: ${pythonExec} ${args.join(' ')}`);
	let outputBuffer = '';

	backtestProc.stdout.on('data', (chunk: Buffer) => {
		outputBuffer += chunk.toString();
		handleOutputChunk(chunk);
	});
	backtestProc.stderr.on('data', (chunk: Buffer) => {
		outputBuffer += chunk.toString();
		handleOutputChunk(chunk);
	});

	backtestProc.on('close', (code) => {
		backtestState.exitCode = code ?? -1;
		backtestState.status = code === 0 ? 'completed' : 'failed';
		backtestState.endedAt = new Date().toISOString();

		if (code === 0) {
			const parsedSummaries = parsePhantomV2ValidationOutput(outputBuffer);
			const bestSummary = pickBestPhantomV2Summary(parsedSummaries);
			if (bestSummary) {
				backtestState.metrics = {
					...backtestState.metrics,
					finalCapital: bestSummary.finalCapital,
					totalReturnPct: bestSummary.netReturnPct,
					totalTrades: bestSummary.trades,
					winRatePct: bestSummary.winRatePct,
					maxDrawdownPct: bestSummary.maxDrawdownPct,
				};
				broadcast('metrics', backtestState.metrics);
			}
		}

		addArtifactIfExists('phantom_backtest_trades.csv');
		addArtifactIfExists('phantom_backtest_report.md');
		addArtifactIfExists('phantom_backtest_results.png');
		addArtifactIfExists('phantom_backtest_zones.png');

		if (linkedRunId) {
			const parsedSummaries = parsePhantomV2ValidationOutput(outputBuffer);
			const bestSummary = pickBestPhantomV2Summary(parsedSummaries);
			const summaryPatch: Record<string, unknown> = {
				status: backtestState.status,
				endedAt: backtestState.endedAt,
				exitCode: backtestState.exitCode,
				metrics: backtestState.metrics,
				artifacts: backtestState.artifacts,
			};

			if (bestSummary) {
				summaryPatch.periodKey = command.periodKey;
				summaryPatch.riskProfile = command.riskProfile;
				summaryPatch.scenario = bestSummary.scenarioKey;
				summaryPatch.startCapital = capital;
				summaryPatch.market = symbol;
				summaryPatch.best = {
					label: command.strategyLabel,
					avgRet: bestSummary.netReturnPct,
					avgPf: bestSummary.profitFactor,
					avgWin: bestSummary.winRatePct,
					worstDD: bestSummary.maxDrawdownPct,
					compounded: bestSummary.finalCapital,
					finalCapital: bestSummary.finalCapital,
					trades: bestSummary.trades,
				};
			}

			updateRunSummary(linkedRunId, {
				...summaryPatch,
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

app.use((req: Request, res: Response, next) => {
	const origin = String(req.headers.origin || '');
	const allowLocal = /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/i.test(origin);

	if (allowLocal) {
		res.header('Access-Control-Allow-Origin', origin);
		res.header('Vary', 'Origin');
	} else {
		res.header('Access-Control-Allow-Origin', '*');
	}

	res.header('Access-Control-Allow-Methods', 'GET,POST,PUT,PATCH,DELETE,OPTIONS');
	res.header('Access-Control-Allow-Headers', 'Content-Type, Authorization');

	if (req.method === 'OPTIONS') {
		res.status(204).end();
		return;
	}

	next();
});

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
		dataRoot: DATA_ROOT,
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

app.get('/platform/comparative-reports', (_req: Request, res: Response): void => {
	const reports = loadComparativeReportManifest().map((report) => {
		let hasData = false;
		try {
			const absPath = resolveComparativeReportDataPath(report.dataFile);
			hasData = fileExists(absPath);
		} catch {
			hasData = false;
		}

		return {
			id: report.id,
			title: report.title,
			description: report.description,
			generatedAt: report.generatedAt,
			windowStart: report.windowStart,
			windowEnd: report.windowEnd,
			hasData,
		};
	});

	res.json({
		count: reports.length,
		reports,
	});
});

app.get('/platform/comparative-reports/:id', (req: Request, res: Response): void => {
	const id = String(req.params.id || '').trim();
	if (!id) {
		res.status(400).json({ error: 'report id is required' });
		return;
	}

	const report = loadComparativeReportManifest().find((item) => item.id === id);
	if (!report) {
		res.status(404).json({ error: `Comparative report not found: ${id}` });
		return;
	}

	try {
		const data = normalizeComparativeReportData(readComparativeReportData(report));
		res.json({
			report: {
				id: report.id,
				title: normalizeReportTitle(report.title),
				description: report.description,
				generatedAt: report.generatedAt,
				windowStart: report.windowStart,
				windowEnd: report.windowEnd,
			},
			data,
		});
	} catch (error) {
		res.status(500).json({ error: (error as Error).message });
	}
});

app.post('/platform/comparative-reports', (req: Request, res: Response): void => {
	try {
		const title = String(req.body?.title || '').trim();
		const dataFile = String(req.body?.dataFile || '').trim();
		const description = String(req.body?.description || '').trim();
		const generatedAt = String(req.body?.generatedAt || '').trim();
		const windowStart = String(req.body?.windowStart || '').trim();
		const windowEnd = String(req.body?.windowEnd || '').trim();

		if (!title) {
			res.status(400).json({ error: 'title is required' });
			return;
		}
		if (!dataFile) {
			res.status(400).json({ error: 'dataFile is required' });
			return;
		}

		const requestedId = String(req.body?.id || '').trim();
		const id = normalizeComparativeReportId(requestedId || title);
		if (!id || id.length < 3) {
			res.status(400).json({ error: 'id is invalid; use at least 3 letters/numbers' });
			return;
		}

		const reports = loadComparativeReportManifest();
		if (reports.some((report) => report.id === id)) {
			res.status(409).json({ error: `report id already exists: ${id}` });
			return;
		}

		const absPath = resolveComparativeReportDataPath(dataFile);
		if (!fileExists(absPath)) {
			res.status(404).json({ error: `report data file not found: ${absPath}` });
			return;
		}

		// Validate JSON shape at a basic level before saving.
		const raw = fs.readFileSync(absPath, 'utf8');
		JSON.parse(raw);

		const record: ComparativeReportRecord = {
			id,
			title,
			description: description || undefined,
			generatedAt: generatedAt || undefined,
			windowStart: windowStart || undefined,
			windowEnd: windowEnd || undefined,
			dataFile,
		};

		reports.unshift(record);
		saveComparativeReportManifest(reports);

		res.status(201).json({
			ok: true,
			report: {
				id: record.id,
				title: record.title,
				description: record.description,
				generatedAt: record.generatedAt,
				windowStart: record.windowStart,
				windowEnd: record.windowEnd,
				hasData: true,
			},
		});
	} catch (error) {
		res.status(500).json({ error: (error as Error).message });
	}
});

app.get('/platform/comparative-profile/sets', (_req: Request, res: Response): void => {
	const sets = loadComparativeProfileSets();
	res.json({
		count: sets.length,
		sets,
	});
});

app.post('/platform/comparative-profile/sets', (req: Request, res: Response): void => {
	try {
		const reportIds = Array.isArray(req.body?.reportIds)
			? (req.body.reportIds as unknown[])
				.map((value) => normalizeComparativeReportId(String(value || '')))
				.filter((value) => Boolean(value))
			: [];

		if (!reportIds.length) {
			res.status(400).json({ error: 'reportIds is required and must contain at least one report id' });
			return;
		}

		const availableReports = loadComparativeReportManifest();
		const availableIds = new Set(availableReports.map((report) => report.id));
		for (const reportId of reportIds) {
			if (!availableIds.has(reportId)) {
				res.status(404).json({ error: `Unknown report id: ${reportId}` });
				return;
			}
		}

		const incomingId = normalizeComparativeReportId(String(req.body?.id || ''));
		const incomingName = String(req.body?.name || '').trim();
		const fallbackName = reportIds
			.map((reportId) => availableReports.find((item) => item.id === reportId)?.title || reportId)
			.join(' + ');
		const setName = incomingName || fallbackName;
		if (!setName) {
			res.status(400).json({ error: 'name is required when report titles cannot be resolved' });
			return;
		}

		const nowIso = new Date().toISOString();
		const sets = loadComparativeProfileSets();
		const existingIndex = incomingId ? sets.findIndex((set) => set.id === incomingId) : -1;
		const id = incomingId || normalizeComparativeReportId(setName) || `set-${Date.now()}`;
		const payload: ComparativeProfileSetRecord = {
			id,
			name: setName,
			reportIds: Array.from(new Set(reportIds)),
			windowStart: String(req.body?.windowStart || '').trim() || undefined,
			windowEnd: String(req.body?.windowEnd || '').trim() || undefined,
			createdAt: existingIndex >= 0 ? sets[existingIndex].createdAt : nowIso,
			updatedAt: nowIso,
		};

		if (existingIndex >= 0) {
			sets[existingIndex] = payload;
		} else {
			if (sets.some((set) => set.id === id)) {
				res.status(409).json({ error: `profile set id already exists: ${id}` });
				return;
			}
			sets.unshift(payload);
		}

		saveComparativeProfileSets(sets);
		res.status(existingIndex >= 0 ? 200 : 201).json({ ok: true, set: payload });
	} catch (error) {
		res.status(500).json({ error: (error as Error).message });
	}
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
			tradeHorizonTimeframe: String(req.body?.tradeHorizonTimeframe || req.body?.primaryTimeframe || 'H4'),
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
			tradeHorizonTimeframe: String(req.body?.tradeHorizonTimeframe || req.body?.primaryTimeframe || 'H1'),
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
		const examples = detectStrategyProofExamples(
			candles,
			recognition.strategyType,
			maxExamples,
			normalizedInput.zoneWidthPct || 0.18,
			normalizedInput.confirmation,
		);

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
					tradeHorizonTimeframe: normalizedInput.tradeHorizonTimeframe,
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
			tradeHorizonTimeframe: String(req.body?.tradeHorizonTimeframe || req.body?.primaryTimeframe || 'H4'),
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
				entryTimeframe: strategy.recognition.primaryTimeframe,
				tradeHorizonTimeframe: strategy.recognition.tradeHorizonTimeframe || strategy.recognition.primaryTimeframe,
				capital,
				risk,
				interval,
				lookbackDays,
			},
		};

		volatileRunHistory.set(queuedRun.id, queuedRun);

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
					entryTimeframe: strategy.recognition.primaryTimeframe,
					tradeHorizonTimeframe: strategy.recognition.tradeHorizonTimeframe || strategy.recognition.primaryTimeframe,
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
		const timeframe = String(req.query.timeframe || '15m').toLowerCase();
		const maxPoints = parsePositiveInt(req.query.maxPoints, 5000);

		const userDataFile = typeof req.query.dataFile === 'string' ? req.query.dataFile : '';
		const selectedFile = userDataFile
			? resolveStrategyDataFile(symbol, userDataFile)
			: resolveMarketTimeframeFile(symbol, timeframe);

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

app.post('/platform/phantom-v2/validate', async (req: Request, res: Response): Promise<void> => {
	try {
		const symbol = canonicalizeDatasetSymbol(String(req.body?.symbol || 'XAUUSD'));
		const capital = toNumber(req.body?.capital, 5_000);
		const startDate = String(req.body?.startDate || req.body?.start_date || '2021-01-01').trim();
		const riskProfileInput = String(req.body?.riskProfile || 'median');
		const riskProfile = mapScenarioOrRiskToRiskProfile(riskProfileInput);
		const scenario: 'A' | 'B' | 'C' = 'B';
		if (!supportsPhantomExecution(symbol)) {
			throw new Error(`Unsupported symbol for Phantom routing: ${symbol}`);
		}
		const spreadBps = Math.max(0, toNumber(req.body?.spreadBps, 0));
		const slippageBps = Math.max(0, toNumber(req.body?.slippageBps, 0));
		const commissionPerTrade = Math.max(0, toNumber(req.body?.commissionPerTrade, 0));

		const dataFiles = {
			m1: resolveMarketTimeframeFile(symbol, '1m'),
			m5: resolveMarketTimeframeFile(symbol, '5m'),
			m15: resolveMarketTimeframeFile(symbol, '15m'),
			h1: resolveMarketTimeframeFile(symbol, '1h'),
			h4: resolveMarketTimeframeFile(symbol, '4h'),
			daily: resolveMarketTimeframeFile(symbol, '1d'),
		};
		const strategyInstrumentCode = mapSymbolToPhantomInstrumentCode(symbol);
		const strategyStem = mapSymbolToPhantomStem(symbol);

		const pythonExec = path.join(WORKSPACE_ROOT, '.venv', 'bin', 'python');
		const scriptCandidates = resolvePhantomScriptCandidates(symbol, riskProfile);
		const scriptPath = scriptCandidates.find((candidate) => fileExists(candidate)) || scriptCandidates[0];
		const artifactPrefix = `phantom-${symbol.toLowerCase()}-${riskProfile}-validate-`;
		const workingDir = fs.mkdtempSync(path.join(ARTIFACT_DIR, artifactPrefix));

		const args = [
			'-u',
			scriptPath,
			'--m1', dataFiles.m1,
			'--m5', dataFiles.m5,
			'--h1', dataFiles.h1,
			'--h4', dataFiles.h4,
			'--start-date', startDate,
			'--capital', String(capital),
			'--spread-bps', String(spreadBps),
			'--slippage-bps', String(slippageBps),
			'--commission-per-trade', String(commissionPerTrade),
		];

		if (strategyInstrumentCode) {
			args.push('--instrument', strategyInstrumentCode, '--daily', dataFiles.daily, '--m15', dataFiles.m15);
		}

		const usedTimeframes = [
			{ flag: '--m1', label: 'M1' },
			{ flag: '--m5', label: 'M5' },
			{ flag: '--m15', label: 'M15' },
			{ flag: '--h1', label: 'H1' },
			{ flag: '--h4', label: 'H4' },
			{ flag: '--daily', label: '1D' },
		]
			.filter((item) => args.includes(item.flag))
			.map((item) => item.label);

		const stdout = await new Promise<string>((resolve, reject) => {
			const proc = spawn(pythonExec, args, {
				cwd: workingDir,
				env: { ...process.env, PYTHONUNBUFFERED: '1' },
			});
			const validationTimeoutMs = 180_000;

			let output = '';
			let errorOutput = '';
			let timedOut = false;
			const timeoutHandle = setTimeout(() => {
				timedOut = true;
				proc.kill('SIGTERM');
			}, validationTimeoutMs);

			proc.stdout.on('data', (chunk) => {
				output += chunk.toString();
			});
			proc.stderr.on('data', (chunk) => {
				errorOutput += chunk.toString();
			});
			proc.on('error', reject);
			proc.on('close', (code) => {
				clearTimeout(timeoutHandle);
				if (timedOut) {
					reject(new Error('Validation timed out after 180 seconds. Try a single scenario or retry.'));
					return;
				}
				if (code !== 0) {
					reject(new Error(errorOutput || output || `PHANTOM v2 validation exited with code ${code}`));
					return;
				}
				resolve(`${output}\n${errorOutput}`.trim());
			});
		});

		const summaries = parsePhantomV2ValidationOutput(stdout);
		const best = pickBestPhantomV2Summary(summaries);
		const curveData = buildValidationCurveDataFromTradeFiles(symbol, capital, workingDir, summaries);

		res.json({
			ok: true,
			symbol,
			capital,
			spreadBps,
			slippageBps,
			commissionPerTrade,
			strategy: `phantom_${strategyStem}_${riskProfile}`,
			riskProfile,
			scenario,
			dataFiles,
			usedTimeframes,
			workingDir,
			summaries,
			best,
			curveData,
			stdout,
		});
	} catch (error) {
		res.status(500).json({ error: (error as Error).message });
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
	const runs = loadRunHistory().map((run) => enrichRunForComparativeReports(run));
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
	res.json(enrichRunForComparativeReports(run));
});

app.get('/platform/runs/:id/pdf', (req: Request, res: Response): void => {
	const runs = loadRunHistory();
	const run = runs.find((entry) => entry.id === req.params.id);
	if (!run) {
		res.status(404).json({ error: 'Run not found' });
		return;
	}

	const safeRunId = String(run.id || 'run').replace(/[^a-zA-Z0-9._-]+/g, '_');
	res.setHeader('Content-Type', 'application/pdf');
	res.setHeader('Content-Disposition', `attachment; filename="${safeRunId}.pdf"`);

	const doc = new PDFDocument({ margin: 48, size: 'A4' });
	doc.pipe(res);
	writeRunPdf(doc, run);
	doc.end();
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

app.get('/platform/admin/export/runs.pdf', (_req: Request, res: Response): void => {
	const runs = loadRunHistory();
	res.setHeader('Content-Type', 'application/pdf');
	res.setHeader('Content-Disposition', 'attachment; filename="strategy-runs.pdf"');

	const doc = new PDFDocument({ margin: 48, size: 'A4' });
	doc.pipe(res);
	writeRunsOverviewPdf(doc, runs);
	doc.end();
});

app.get('/admin', (_req: Request, res: Response): void => {
	res.sendFile(path.join(WORKSPACE_ROOT, 'public', 'admin.html'));
});

app.get('/strategy-lab', (_req: Request, res: Response): void => {
	res.sendFile(path.join(WORKSPACE_ROOT, 'public', 'strategy-lab.html'));
});

app.get('/comparative-reports', (_req: Request, res: Response): void => {
	res.sendFile(path.join(WORKSPACE_ROOT, 'public', 'comparative-reports.html'));
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
			tradeHorizonTimeframe: String(req.body?.tradeHorizonTimeframe || parsedTemplate?.tradeHorizonTimeframe || parsedTemplate?.executionTimeframe || parsedTemplate?.primaryTimeframe || parsedTemplate?.timeframe || 'H4'),
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
