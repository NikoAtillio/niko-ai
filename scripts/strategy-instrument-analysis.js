const fs = require('fs');
const path = require('path');

const ROOT = path.join(process.cwd(), 'backtest_artifacts');
const START_CAPITAL = 10000;

function walk(dir, out = []) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      walk(p, out);
      continue;
    }
    if (entry.isFile() && /trades_.*\.csv$/i.test(entry.name)) {
      out.push(p);
    }
  }
  return out;
}

function walkDashboards(dir, out = []) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      walkDashboards(p, out);
      continue;
    }
    if (entry.isFile() && /^dashboard_data_phantom_p[123]\.json$/i.test(entry.name)) {
      out.push(p);
    }
  }
  return out;
}

function instrumentFromPath(filePath) {
  const up = filePath.toUpperCase();
  const candidates = ['XAUUSD', 'BTCUSD', 'US100', 'EURUSD', 'GBPUSD', 'USDCHF', 'USDJPY', 'NZDUSD', 'EURGBP', 'XAU', 'BTC'];
  for (const token of candidates) {
    if (up.includes(token)) {
      if (token === 'XAU') return 'XAUUSD';
      if (token === 'BTC') return 'BTCUSD';
      return token;
    }
  }
  return 'UNKNOWN';
}

function strategyFromName(name) {
  const up = name.toUpperCase();
  const match = up.match(/P([123])([ABC])/);
  if (!match) return 'UNKNOWN';
  return `P${match[1]}${match[2]}`;
}

function strategyFromBranchName(name) {
  const up = String(name || '').toUpperCase();
  const match = up.match(/PHANTOM[_-]?P([123])/);
  if (!match) return 'UNKNOWN';
  return `P${match[1]}`;
}

function parseDashboardSummaryMetrics(filePath) {
  try {
    const raw = fs.readFileSync(filePath, 'utf8').replace(/^\uFEFF/, '').trim();
    if (!raw) return null;
    const payload = JSON.parse(raw);
    const summary = Array.isArray(payload.summary)
      ? payload.summary.find((row) => String(row.mode || '').toLowerCase() === 'full') || payload.summary[0]
      : null;
    if (!summary) return null;

    const strategy = strategyFromBranchName(summary.branch || payload?.meta?.strategyLabel || '');
    if (strategy === 'UNKNOWN') return null;

    const net = Number(summary.net_pnl_gbp);
    const retPct = Number(summary.net_return_pct);
    const maxDdRaw = Number(summary.max_dd_amt_gbp);
    if (!Number.isFinite(net) || !Number.isFinite(retPct) || !Number.isFinite(maxDdRaw)) return null;

    return {
      strategy,
      net,
      retPct,
      maxDrawdown: Math.abs(maxDdRaw),
      trades: Number(summary.months) || 0,
      wins: 0,
      losses: 0,
      profitFactor: Number.NaN,
    };
  } catch {
    return null;
  }
}

function parseMetrics(filePath) {
  const raw = fs.readFileSync(filePath, 'utf8').replace(/^\uFEFF/, '').trim();
  if (!raw) return null;

  const lines = raw.split(/\r?\n/);
  if (lines.length < 2) return null;

  const header = lines[0].split(',').map((h) => h.trim().toLowerCase());
  const pnlIdx = header.indexOf('pnl');
  if (pnlIdx < 0) return null;

  let trades = 0;
  let wins = 0;
  let losses = 0;
  let grossProfit = 0;
  let grossLoss = 0;
  let net = 0;

  let equity = START_CAPITAL;
  let peak = START_CAPITAL;
  let maxDrawdown = 0;

  for (let i = 1; i < lines.length; i += 1) {
    const cols = lines[i].split(',');
    const pnl = Number(cols[pnlIdx]);
    if (!Number.isFinite(pnl)) continue;

    trades += 1;
    net += pnl;

    if (pnl > 0) {
      wins += 1;
      grossProfit += pnl;
    } else if (pnl < 0) {
      losses += 1;
      grossLoss += Math.abs(pnl);
    }

    equity += pnl;
    if (equity > peak) peak = equity;
    const dd = peak - equity;
    if (dd > maxDrawdown) maxDrawdown = dd;
  }

  if (!trades) return null;

  const profitFactor = grossLoss > 0 ? grossProfit / grossLoss : (grossProfit > 0 ? Infinity : 0);

  return {
    trades,
    wins,
    losses,
    net,
    retPct: (net / START_CAPITAL) * 100,
    maxDrawdown,
    profitFactor,
  };
}

function pickBest(arr, scoreFn, wantMax = true) {
  return arr.reduce((best, candidate) => {
    if (!best) return candidate;
    return wantMax
      ? (scoreFn(candidate) > scoreFn(best) ? candidate : best)
      : (scoreFn(candidate) < scoreFn(best) ? candidate : best);
  }, null);
}

function main() {
  if (!fs.existsSync(ROOT)) {
    console.error(`Missing directory: ${ROOT}`);
    process.exit(1);
  }

  const files = walk(ROOT).map((filePath) => ({
    filePath,
    mtimeMs: fs.statSync(filePath).mtimeMs,
  }));
  const dashboardFiles = walkDashboards(ROOT).map((filePath) => ({
    filePath,
    mtimeMs: fs.statSync(filePath).mtimeMs,
  }));

  const latestByInstrumentStrategy = new Map();
  for (const file of files) {
    const instrument = instrumentFromPath(file.filePath);
    const strategy = strategyFromName(path.basename(file.filePath));
    if (instrument === 'UNKNOWN' || strategy === 'UNKNOWN') continue;

    const key = `${instrument}::${strategy}`;
    const prev = latestByInstrumentStrategy.get(key);
    if (!prev || file.mtimeMs > prev.mtimeMs) {
      latestByInstrumentStrategy.set(key, { ...file, instrument, strategy });
    }
  }

  const rows = [];
  for (const item of latestByInstrumentStrategy.values()) {
    const metrics = parseMetrics(item.filePath);
    if (!metrics) continue;
    rows.push({
      instrument: item.instrument,
      strategy: item.strategy,
      filePath: item.filePath,
      ...metrics,
    });
  }

  // Fallback source: branch-comparison dashboard summaries (captures P3 where raw trade CSV naming may differ).
  const latestDashByInstrumentStrategy = new Map();
  for (const file of dashboardFiles) {
    const instrument = instrumentFromPath(file.filePath);
    if (instrument === 'UNKNOWN') continue;
    const metrics = parseDashboardSummaryMetrics(file.filePath);
    if (!metrics) continue;
    const key = `${instrument}::${metrics.strategy}`;
    const prev = latestDashByInstrumentStrategy.get(key);
    if (!prev || file.mtimeMs > prev.mtimeMs) {
      latestDashByInstrumentStrategy.set(key, { instrument, filePath: file.filePath, ...metrics });
    }
  }

  const existingKeys = new Set(rows.map((row) => `${row.instrument}::${row.strategy}`));
  for (const row of latestDashByInstrumentStrategy.values()) {
    const key = `${row.instrument}::${row.strategy}`;
    if (existingKeys.has(key)) continue;
    rows.push(row);
    existingKeys.add(key);
  }

  rows.sort((a, b) => a.instrument.localeCompare(b.instrument) || a.strategy.localeCompare(b.strategy));

  const grouped = new Map();
  for (const row of rows) {
    if (!grouped.has(row.instrument)) grouped.set(row.instrument, []);
    grouped.get(row.instrument).push(row);
  }

  console.log('INSTRUMENT SUMMARY (latest run per strategy variant)');

  for (const instrument of Array.from(grouped.keys()).sort()) {
    const set = grouped.get(instrument);
    const bestReturn = pickBest(set, (x) => x.retPct, true);
    const lowestDd = pickBest(set, (x) => x.maxDrawdown, false);
    const bestNet = pickBest(set, (x) => x.net, true);
    const bestEfficiency = pickBest(set, (x) => (x.maxDrawdown > 0 ? x.net / x.maxDrawdown : Number.POSITIVE_INFINITY), true);

    console.log(`\n${instrument} (${set.length} variants)`);
    console.log(`  Highest return: ${bestReturn.strategy} | return=${bestReturn.retPct.toFixed(2)}% net=${bestReturn.net.toFixed(2)} maxDD=${bestReturn.maxDrawdown.toFixed(2)} PF=${Number.isFinite(bestReturn.profitFactor) ? bestReturn.profitFactor.toFixed(2) : 'Inf'} trades=${bestReturn.trades}`);
    console.log(`  Lowest drawdown: ${lowestDd.strategy} | maxDD=${lowestDd.maxDrawdown.toFixed(2)} return=${lowestDd.retPct.toFixed(2)}% net=${lowestDd.net.toFixed(2)} PF=${Number.isFinite(lowestDd.profitFactor) ? lowestDd.profitFactor.toFixed(2) : 'Inf'} trades=${lowestDd.trades}`);
    console.log(`  Highest net PnL: ${bestNet.strategy} | net=${bestNet.net.toFixed(2)} return=${bestNet.retPct.toFixed(2)}% maxDD=${bestNet.maxDrawdown.toFixed(2)} PF=${Number.isFinite(bestNet.profitFactor) ? bestNet.profitFactor.toFixed(2) : 'Inf'} trades=${bestNet.trades}`);
    console.log(`  Best return/DD efficiency: ${bestEfficiency.strategy} | net/maxDD=${(bestEfficiency.maxDrawdown > 0 ? bestEfficiency.net / bestEfficiency.maxDrawdown : Number.POSITIVE_INFINITY).toFixed(2)} return=${bestEfficiency.retPct.toFixed(2)}% maxDD=${bestEfficiency.maxDrawdown.toFixed(2)} trades=${bestEfficiency.trades}`);
  }

  console.log('\nDETAIL CSV');
  console.log('instrument,strategy,trades,wins,losses,net,retPct,maxDD,profitFactor,filePath');
  for (const row of rows.sort((a, b) => a.instrument.localeCompare(b.instrument) || b.retPct - a.retPct)) {
    console.log([
      row.instrument,
      row.strategy,
      row.trades,
      row.wins,
      row.losses,
      row.net.toFixed(2),
      row.retPct.toFixed(2),
      row.maxDrawdown.toFixed(2),
      Number.isFinite(row.profitFactor) ? row.profitFactor.toFixed(3) : 'Inf',
      row.filePath,
    ].join(','));
  }
}

main();
