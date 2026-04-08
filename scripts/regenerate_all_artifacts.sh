#!/usr/bin/env bash
set -euo pipefail

cd /Users/niko/Documents/projects/niko-ai

symbols=(BTCUSD EURUSD GBPUSD NZDUSD US100 USDCHF USDJPY XAUUSD)
engines=(p1 p2)

: > /tmp/regenerated_artifacts.tsv

for s in "${symbols[@]}"; do
  for e in "${engines[@]}"; do
    resp=$(curl -sS -X POST http://localhost:3000/platform/phantom-v2/validate \
      -H 'Content-Type: application/json' \
      -d "{\"symbol\":\"$s\",\"scenario\":\"ALL\",\"engineVersion\":\"$e\",\"capital\":5000,\"spreadBps\":0,\"slippageBps\":0,\"commissionPerTrade\":0}")

    ok=$(printf '%s' "$resp" | jq -r '.ok')
    wd=$(printf '%s' "$resp" | jq -r '.workingDir // empty')
    sc=$(printf '%s' "$resp" | jq -r '.summaries|length')
    echo -e "$s\t$e\t$ok\t$sc\t$wd" | tee -a /tmp/regenerated_artifacts.tsv
  done
done
