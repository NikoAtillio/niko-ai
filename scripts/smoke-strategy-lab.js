const http = require('http');

function requestJson(method, path, body) {
  return new Promise((resolve, reject) => {
    const payload = body ? JSON.stringify(body) : null;
    const req = http.request(
      {
        hostname: process.env.SMOKE_HOST || '127.0.0.1',
        port: Number(process.env.SMOKE_PORT || 3000),
        path,
        method,
        headers: payload
          ? {
              'Content-Type': 'application/json',
              'Content-Length': Buffer.byteLength(payload),
            }
          : {},
        timeout: 10000,
      },
      (res) => {
        let raw = '';
        res.on('data', (chunk) => {
          raw += chunk;
        });
        res.on('end', () => {
          let json = null;
          try {
            json = raw ? JSON.parse(raw) : null;
          } catch {
            json = raw;
          }
          resolve({ status: res.statusCode || 0, body: json });
        });
      },
    );

    req.on('error', reject);
    req.on('timeout', () => {
      req.destroy(new Error('Request timeout'));
    });

    if (payload) {
      req.write(payload);
    }
    req.end();
  });
}

function assertOk(name, result) {
  if (result.status < 200 || result.status >= 300) {
    throw new Error(`${name} failed with HTTP ${result.status}: ${JSON.stringify(result.body)}`);
  }
}

async function run() {
  const report = [];

  const config = await requestJson('GET', '/platform/config');
  assertOk('GET /platform/config', config);
  report.push(['GET /platform/config', config.status]);

  const admin = await requestJson('GET', '/platform/admin/overview');
  assertOk('GET /platform/admin/overview', admin);
  report.push(['GET /platform/admin/overview', admin.status]);

  const recognize = await requestJson('POST', '/platform/strategy-lab/recognize', {
    theoryText: 'Support and resistance breakout retest on H1 with ATR stop and 2R target in London session.',
    market: 'US100',
    primaryTimeframe: 'H1',
    riskPerTradePct: 0.4,
    zoneWidthPct: 0.15,
    minTouches: 3,
    confirmation: 'Break and retest',
  });
  assertOk('POST /platform/strategy-lab/recognize', recognize);
  report.push(['POST /platform/strategy-lab/recognize', recognize.status]);

  const imported = await requestJson('POST', '/platform/strategy-lab/import', {
    templateName: 'smoke-template.json',
    templateText: JSON.stringify({
      name: 'Smoke Strategy',
      description: 'Support resistance breakout on H1 with retest entry and ATR stop, target 2R',
      market: 'US100',
      primaryTimeframe: 'H1',
      riskPerTradePct: 0.4,
      zoneWidthPct: 0.15,
      minTouches: 3,
      confirmation: 'Break and retest',
    }),
  });
  assertOk('POST /platform/strategy-lab/import', imported);
  report.push(['POST /platform/strategy-lab/import', imported.status]);

  const confirm = await requestJson('POST', '/platform/strategy-lab/confirm', {
    theoryText: 'Support and resistance breakout retest on H1 with ATR stop and 2R target in London session.',
    market: 'US100',
    primaryTimeframe: 'H1',
    riskPerTradePct: 0.4,
    zoneWidthPct: 0.15,
    minTouches: 3,
    confirmation: 'Break and retest',
  });
  assertOk('POST /platform/strategy-lab/confirm', confirm);
  report.push(['POST /platform/strategy-lab/confirm', confirm.status]);

  const strategyId = confirm.body && confirm.body.record && confirm.body.record.id;
  if (!strategyId) {
    throw new Error('Missing strategy id from confirm response');
  }

  const queue = await requestJson('POST', '/platform/strategy-lab/backtest-request', {
    strategyId,
    interval: '1h',
    capital: 10000,
    risk: 0.01,
    lookbackDays: 10,
    autoStart: false,
  });
  assertOk('POST /platform/strategy-lab/backtest-request', queue);
  report.push(['POST /platform/strategy-lab/backtest-request', queue.status]);

  const runs = await requestJson('GET', '/platform/strategy-lab/runs?limit=5');
  assertOk('GET /platform/strategy-lab/runs', runs);
  report.push(['GET /platform/strategy-lab/runs', runs.status]);

  const strategies = await requestJson('GET', '/platform/strategy-lab/strategies');
  assertOk('GET /platform/strategy-lab/strategies', strategies);
  report.push(['GET /platform/strategy-lab/strategies', strategies.status]);

  const badRecognize = await requestJson('POST', '/platform/strategy-lab/recognize', {
    market: 'US100',
  });
  if (badRecognize.status !== 400) {
    throw new Error(`Expected 400 for invalid recognize payload, got ${badRecognize.status}`);
  }
  report.push(['POST /platform/strategy-lab/recognize invalid payload', badRecognize.status]);

  console.log('Smoke test passed.');
  for (const [name, status] of report) {
    console.log(`${status} ${name}`);
  }
}

run().catch((err) => {
  console.error('Smoke test failed:', err.message);
  process.exit(1);
});
