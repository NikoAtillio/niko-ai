#!/usr/bin/env bash
set -euo pipefail

BASE="/Users/niko/Documents/projects/niko-ai/backtest_artifacts/branch-competition-us100-20260416"
PY="/Users/niko/Documents/projects/niko-ai/.venv/bin/python"
P2_BASE="/Users/niko/Documents/projects/niko-ai/phantom/phantom_US100"

M1="/Users/niko/Documents/projects/niko-ai/data/US100/US100.cash_M1_2023.05.24-2026.03.31"
M5_FULL="/Users/niko/Documents/projects/niko-ai/data/US100/US100.cash_M5_2021.01.21-2026.03.31"
M15_FULL="/Users/niko/Documents/projects/niko-ai/data/US100/US100.cash_M15_2021.01.21-2026.03.31"
H1_FULL="/Users/niko/Documents/projects/niko-ai/data/US100/US100.cash_H1_2021.01.21-2026.03.31"
H4_FULL="/Users/niko/Documents/projects/niko-ai/data/US100/US100.cash_H4_2021.01.21-2026.03.31"
D_FULL="/Users/niko/Documents/projects/niko-ai/data/US100/US100.cash_Daily_2021.01.21-2026.03.31"

POLICY_BASE="/Users/niko/Documents/projects/niko-ai/backtest_artifacts/branch-competition-us100-20260416/policy_data"
M5_POLICY="$POLICY_BASE/US100.cash_M5_2021.01.21-2026.03.31"
M15_POLICY="$POLICY_BASE/US100.cash_M15_2021.01.21-2026.03.31"
H1_POLICY="$POLICY_BASE/US100.cash_H1_2021.01.21-2026.03.31"
H4_POLICY="$POLICY_BASE/US100.cash_H4_2021.01.21-2026.03.31"
D_POLICY="$POLICY_BASE/US100.cash_Daily_2021.01.21-2026.03.31"

run_triplet() {
  local br="$1"
  local mode="$2"
  local m5="$3"
  local m15="$4"
  local h1="$5"
  local h4="$6"
  local d="$7"

  git -C /Users/niko/Documents/projects/niko-ai checkout "$br"
  local out="$BASE/$mode/$br"
  mkdir -p "$out"

  for sc in A B C; do
    case "$sc" in
      A) P2="$P2_BASE/phantom_US100_high.py" ;;
      B) P2="$P2_BASE/phantom_US100_median.py" ;;
      C) P2="$P2_BASE/phantom_US100_low.py" ;;
    esac
    echo "Running $br $mode US100 P2$sc"
    "$PY" "$P2" --instrument US100 --m1 "$M1" --m5 "$m5" --m15 "$m15" --h1 "$h1" --h4 "$h4" --daily "$d" --scenario "p2$sc" --output-dir "$out/US100_P2$sc" > "$out/US100_P2${sc}.log" 2>&1
  done
}

# Missing from existing artifacts:
run_triplet p2_filter_test1 policy "$M5_POLICY" "$M15_POLICY" "$H1_POLICY" "$H4_POLICY" "$D_POLICY"
run_triplet p2_filter_test2 policy "$M5_POLICY" "$M15_POLICY" "$H1_POLICY" "$H4_POLICY" "$D_POLICY"
run_triplet p2_filter_test3 full "$M5_FULL" "$M15_FULL" "$H1_FULL" "$H4_FULL" "$D_FULL"

echo DONE_US100_TARGETED
