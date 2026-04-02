const http = require('http');

function post(body) {
  return new Promise((resolve, reject) => {
    const data = JSON.stringify(body);
    const req = http.request(
      {
        hostname: '127.0.0.1',
        port: 3000,
        path: '/platform/strategy-lab/proof',
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Content-Length': Buffer.byteLength(data),
        },
        timeout: 15000,
      },
      (res) => {
        let raw = '';
        res.on('data', (chunk) => {
          raw += chunk;
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
  for (const mode of ['lower', 'base', 'higher']) {
    const result = await post({
      theoryText: 'Breakout trading: enter when price breaks above resistance and continue with momentum.',
      market: 'US100',
      primaryTimeframe: 'H1',
      riskPerTradePct: 0.5,
      zoneWidthPct: 0.18,
      minTouches: 2,
      confirmation: 'Break and retest',
      proofTfMode: mode,
      maxExamples: 3,
    });

    const proof = (result.body && result.body.proof) || {};
    const first = (Array.isArray(proof.examples) && proof.examples[0]) || {};
    const overlays = Array.isArray(first.overlays) ? first.overlays.length : 0;
    process.stdout.write(
      `${mode} | HTTP ${result.status} | tf ${proof.timeframe || 'n/a'} | mode ${proof.timeframeMode || 'n/a'} | examples ${proof.exampleCount || 0} | confidence ${Number(first.confidence || 0).toFixed(2)} | overlays ${overlays}\n`,
    );
  }
})().catch((error) => {
  console.error(error.message || String(error));
  process.exit(1);
});
