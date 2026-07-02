#!/usr/bin/env bash
set -euo pipefail

OUT_BASE="/Users/niko/Documents/projects/niko-ai/saved_runs"
OUT_DIR="${OUT_BASE}/$(date +%Y-%m-%d)_us100_cash_high_risk"
mkdir -p "$OUT_DIR"

PY="/Users/niko/Documents/projects/niko-ai/.venv/bin/python"
SCRIPT="/Users/niko/Documents/projects/niko-ai/phantom/phantom_US100/phantom_us100_cash_high_risk.py"

M1="/Users/niko/Documents/projects/niko-ai/data/US100/US100.cash_M1_2023.05.24-2026.03.31"
M5="/Users/niko/Documents/projects/niko-ai/data/US100/US100.cash_M5_2021.01.21-2026.03.31"
M15="/Users/niko/Documents/projects/niko-ai/data/US100/US100.cash_M15_2021.01.21-2026.03.31"
H1="/Users/niko/Documents/projects/niko-ai/data/US100/US100.cash_H1_2021.01.21-2026.03.31"
H4="/Users/niko/Documents/projects/niko-ai/data/US100/US100.cash_H4_2021.01.21-2026.03.31"
D="/Users/niko/Documents/projects/niko-ai/data/US100/US100.cash_Daily_2021.01.21-2026.03.31"
W="/Users/niko/Documents/projects/niko-ai/data/US100/US100.cash_Weekly_2021.01.17-2026.03.31"

echo "Running high-risk US100 cash signal generation"
echo "Output directory: $OUT_DIR"

"$PY" "$SCRIPT" \
  --instrument US100 \
  --m1 "$M1" --m5 "$M5" --m15 "$M15" --h1 "$H1" --h4 "$H4" --daily "$D" --weekly "$W" \
  --capital 10000 \
  --start-date 2023-01-01 \
  --end-date 2026-01-01 \
  --cash-trail-max-loss-pct 100 \
  --output-dir "$OUT_DIR/cash" \
  | tee "$OUT_DIR/run.log"

echo "Done."
echo "Signals: /Users/niko/Documents/projects/niko-ai/signals/phantom_signals.jsonl"
echo "Trades CSV: $OUT_DIR/cash/phantom_p2_cash_v3_high_risk_trades_US100_P2_CASH_V3B.csv"
