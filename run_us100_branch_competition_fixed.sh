#!/usr/bin/env bash
set -euo pipefail

BASE="/Users/niko/Documents/projects/niko-ai/backtest_artifacts/branch-competition-us100-20260416"
mkdir -p "$BASE"

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

for BR in p2_filter_test1 p2_filter_test2 p2_filter_test3; do
  git -C /Users/niko/Documents/projects/niko-ai checkout "$BR"

  for MODE in full policy; do
    OUT="$BASE/$MODE/$BR"
    mkdir -p "$OUT"

    if [[ "$MODE" == "policy" ]]; then
      M5="$M5_POLICY"; M15="$M15_POLICY"; H1="$H1_POLICY"; H4="$H4_POLICY"; D="$D_POLICY"
    else
      M5="$M5_FULL"; M15="$M15_FULL"; H1="$H1_FULL"; H4="$H4_FULL"; D="$D_FULL"
    fi

    for SC in A B C; do
      case "$SC" in
        A) P2="$P2_BASE/phantom_US100_high.py" ;;
        B) P2="$P2_BASE/phantom_US100_median.py" ;;
        C) P2="$P2_BASE/phantom_US100_low.py" ;;
      esac
      echo "Running $BR $MODE US100 P2$SC"
      "$PY" "$P2" \
        --instrument US100 \
        --m1 "$M1" --m5 "$M5" --m15 "$M15" --h1 "$H1" --h4 "$H4" --daily "$D" \
        --scenario "p2$SC" \
        --output-dir "$OUT/US100_P2$SC" \
        > "$OUT/US100_P2${SC}.log" 2>&1
    done
  done
done

echo "DONE_US100_COMPETITION"
