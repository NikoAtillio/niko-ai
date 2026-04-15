#!/usr/bin/env bash
set -euo pipefail

cd /Users/niko/Documents/projects/niko-ai
PY=/Users/niko/Documents/projects/niko-ai/.venv/bin/python
STAMP=$(date +%Y%m%d-%H%M%S)

run_one() {
  local inst="$1" m1="$2" m5="$3" h1="$4" h4="$5" d1="$6"
  local inst_lc
  inst_lc=$(printf '%s' "$inst" | tr '[:upper:]' '[:lower:]')
  local outdir="backtest_artifacts/phantom-${inst_lc}-p2-manual-${STAMP}"
  mkdir -p "$outdir"
  "$PY" phantom/v2/phantom_p2.py \
    --instrument "$inst" \
    --m1 "$m1" --m5 "$m5" --h1 "$h1" --h4 "$h4" --daily "$d1" \
    --scenario ALL --capital 5000 --output-dir "$outdir" \
    > "$outdir/run.log" 2>&1
  echo "$inst|$outdir"
}

run_one XAU \
  data/XAUUSD/XAUUSD_M1_2023.03.13-2026.03.31 \
  data/XAUUSD/XAUUSD_M5_2011.09.08-2026.03.31 \
  data/XAUUSD/XAUUSD_H1_2010.01.04-2026.03.31 \
  data/XAUUSD/XAUUSD_H4_2010.01.04-2026.03.31 \
  data/XAUUSD/XAUUSD_Daily_2010.01.04-2026.03.31

run_one US100 \
  data/US100/US100.cash_M1_2023.05.24-2026.03.31 \
  data/US100/US100.cash_M5_2021.01.21-2026.03.31 \
  data/US100/US100.cash_H1_2021.01.21-2026.03.31 \
  data/US100/US100.cash_H4_2021.01.21-2026.03.31 \
  data/US100/US100.cash_Daily_2021.01.21-2026.03.31

run_one BTC \
  data/BTCUSD/BTCUSD_M1_2024.04.06-2026.03.31 \
  data/BTCUSD/BTCUSD_M5_2017.01.16-2026.03.31 \
  data/BTCUSD/BTCUSD_H1_2017.01.16-2026.03.31 \
  data/BTCUSD/BTCUSD_H4_2017.01.16-2026.03.31 \
  data/BTCUSD/BTCUSD_Daily_2017.01.16-2026.03.31
