#!/usr/bin/env bash
set -euo pipefail

BASE="/Users/niko/Documents/projects/niko-ai/backtest_artifacts/phantom-risk-tests-$(date +%Y%m%d_%H%M%S)"
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

run_strategy () {
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

for TEST in 1 2 3; do
  TEST_DIR="$BASE/test${TEST}"
  mkdir -p "$TEST_DIR"

  # Median baseline is repeated per test folder for side-by-side reporting.
  run_strategy "median" "$MEDIAN" "$TEST_DIR/median" ""
  run_strategy "high_test${TEST}" "$HIGH" "$TEST_DIR/high" "--risk-test ${TEST}"
  run_strategy "low_test${TEST}" "$LOW" "$TEST_DIR/low" "--risk-test ${TEST}"
done

echo "DONE_US100_RISK_PROFILE_TESTS"
echo "Artifacts: $BASE"
