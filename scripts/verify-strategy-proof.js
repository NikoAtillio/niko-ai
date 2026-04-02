const http = require('http');

const examples = [
  ['Trend Trading', 'Trend trading: follow overall market direction using moving averages and pullback continuation entries.'],
  ['Range Trading', 'Range trading strategy in consolidating markets between support and resistance levels for short-term bounces.'],
  ['Breakout Trading', 'Breakout trading: enter when price breaks above or below defined support and resistance to catch a new trend.'],
  ['Scalping', 'Scalping strategy: very short-term trades for small frequent profits on tiny price moves.'],
  ['Swing Trading', 'Swing trading approach targeting price swings and corrections over days or weeks.'],
  ['Position Trading', 'Position trading: long-term positions held for months to capture major market moves.'],
  ['News Trading', 'News trading around economic reports like CPI, NFP and FOMC to exploit sudden volatility spikes.'],
  ['Gap Trading', 'Gap trading strategy based on opening gaps and whether they fill, continue, or reverse.'],
];

function post(path, body) {
  return new Promise((resolve, reject) => {
    const data = JSON.stringify(body);
    const req = http.request(
      {
        hostname: '127.0.0.1',
        port: 3000,
        path,
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Content-Length': Buffer.byteLength(data),
        },
        timeout: 15000,
      },
      (res) => {
        let raw = '';
        res.on('data', (c) => {
          raw += c;
        });
        res.on('end', () => {
          let json = {};
          try {
            json = JSON.parse(raw || '{}');
          } catch {
            json = {};
          }
          resolve({ status: res.statusCode || 0, body: json });
        });
      },
    );

    req.on('error', reject);
    req.on('timeout', () => req.destroy(new Error('timeout')));
    req.write(data);
    req.end();
  });
}

(async () => {
  for (const [label, theoryText] of examples) {
    const common = {
      theoryText,
      market: 'US100',
      primaryTimeframe: 'H1',
      riskPerTradePct: 0.5,
      zoneWidthPct: 0.18,
      minTouches: 2,
      confirmation: 'Break and retest',
    };

    const recog = await post('/platform/strategy-lab/recognize', common);
    const proof = await post('/platform/strategy-lab/proof', common);
    const recognized = recog.body && recog.body.recognition ? recog.body.recognition.strategyType : 'n/a';
    const proofCount = proof.body && proof.body.proof ? proof.body.proof.exampleCount : 0;

    process.stdout.write(
      `${label.padEnd(16)} | recognize:${String(recog.status).padEnd(3)} -> ${recognized.padEnd(32)} | proof:${String(proof.status).padEnd(3)} -> examples:${proofCount}\n`,
    );
  }
})().catch((error) => {
  console.error(error.message || String(error));
  process.exit(1);
});
