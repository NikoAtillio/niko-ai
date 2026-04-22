#!/usr/bin/env bash
set -euo pipefail

BASE="/Users/niko/Documents/projects/niko-ai/backtest_artifacts/phantom-risk-ablation-$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BASE"

PY="/Users/niko/Documents/projects/niko-ai/.venv/bin/python"
MEDIAN="/Users/niko/Documents/projects/niko-ai/phantom/phantom_US100/phantom_US100_median.py"
HIGH="/Users/niko/Documents/projects/niko-ai/phantom/phantom_US100/phantom_US100_high_risk_tests.py"
LOW="/Users/niko/Documents/projects/niko-ai/phantom/phantom_US100/phantom_US100_low_risk_tests.py"

M1="/Users/niko/Documents/projects/niko-ai/data/US100/US100.cash_M1_2023.05.24-2026.03.31"
M5="/Users/niko/Documents/projects/niko-ai/data/US100/US100.cash_M5_2021.01.21-2026.03.31"
M15="/Users/niko/Documents/projects/niko-ai/data/US100/US100.cash_M15_2021.01.21-2026.03.31"
H1="/Users/niko/Documents/projects/niko-ai/data/US100/US100.cash_H1_2021.01.21-2026.03.31"
H4="/Users/niko/Documents/projects/niko-ai/data/US100/US100.cash_H4_2021.01.21-2026.03.31"
D="/Users/niko/Documents/projects/niko-ai/data/US100/US100.cash_Daily_2021.01.21-2026.03.31"

SCENARIO="p2B"
START_DATE="2022-01-01"

run_profile() {
  local label="$1"
  local script_path="$2"
  local out_dir="$3"
  local risk_test_arg="$4"

  mkdir -p "$out_dir"
  echo "Running ${label} -> ${out_dir}"

  "$PY" "$script_path" \
    --instrument US100 \
    --m1 "$M1" --m5 "$M5" --m15 "$M15" --h1 "$H1" --h4 "$H4" --daily "$D" \
    --scenario "$SCENARIO" \
    --start-date "$START_DATE" \
    --output-dir "$out_dir" \
    $risk_test_arg \
    > "$out_dir/run.log" 2>&1
}

run_profile "median_base" "$MEDIAN" "$BASE/median" ""

for T in 1 2 3 4 5; do
  run_profile "high_t${T}" "$HIGH" "$BASE/high_t${T}" "--risk-test ${T}"
done

for T in 1 2 3 4; do
  run_profile "low_t${T}" "$LOW" "$BASE/low_t${T}" "--risk-test ${T}"
done

echo "DONE_US100_RISK_ABLATION"
echo "Artifacts: $BASE"
