#!/usr/bin/env bash
set -euo pipefail

BASE="/Users/niko/Documents/projects/niko-ai/backtest_artifacts/branch-competition-us100-20260416"
mkdir -p "$BASE"

PY="/Users/niko/Documents/projects/niko-ai/.venv/bin/python"
P2_BASE="/Users/niko/Documents/projects/niko-ai/phantom/phantom_US100"
M1="/Users/niko/Documents/projects/niko-ai/data/US100/US100.cash_M1_2023.05.24-2026.03.31"
M5="/Users/niko/Documents/projects/niko-ai/data/US100/US100.cash_M5_2021.01.21-2026.03.31"
M15="/Users/niko/Documents/projects/niko-ai/data/US100/US100.cash_M15_2021.01.21-2026.03.31"
H1="/Users/niko/Documents/projects/niko-ai/data/US100/US100.cash_H1_2021.01.21-2026.03.31"
H4="/Users/niko/Documents/projects/niko-ai/data/US100/US100.cash_H4_2021.01.21-2026.03.31"
D="/Users/niko/Documents/projects/niko-ai/data/US100/US100.cash_Daily_2021.01.21-2026.03.31"

for BR in p2_filter_test1 p2_filter_test2 p2_filter_test3; do
  git -C /Users/niko/Documents/projects/niko-ai checkout "$BR"

  for MODE in full policy; do
    OUT="$BASE/$MODE/$BR"
    mkdir -p "$OUT"

    for SC in A B C; do
      case "$SC" in
        A) P2="$P2_BASE/phantom_US100_high.py" ;;
        B) P2="$P2_BASE/phantom_US100_median.py" ;;
        C) P2="$P2_BASE/phantom_US100_low.py" ;;
      esac
      echo "Running $BR $MODE US100 P2$SC"

      if [[ "$MODE" == "policy" ]]; then
        "$PY" "$P2" \
          --instrument US100 \
          --m1 "$M1" --m5 "$M5" --m15 "$M15" --h1 "$H1" --h4 "$H4" --daily "$D" \
          --scenario "p2$SC" \
          --start-date 2022-01-01 \
          --output-dir "$OUT/US100_P2$SC" \
          > "$OUT/US100_P2${SC}.log" 2>&1
      else
        "$PY" "$P2" \
          --instrument US100 \
          --m1 "$M1" --m5 "$M5" --m15 "$M15" --h1 "$H1" --h4 "$H4" --daily "$D" \
          --scenario "p2$SC" \
          --output-dir "$OUT/US100_P2$SC" \
          > "$OUT/US100_P2${SC}.log" 2>&1
      fi
    done
  done
done

echo "DONE_US100_COMPETITION"
