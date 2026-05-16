#!/usr/bin/env python3
import csv
from collections import Counter

python_file = "backtest_artifacts/high-vs-high2-20260429_154936/high/phantom_p2_trades_US100_P2B.csv"

with open(python_file, 'r') as f:
    reader = csv.DictReader(f)
    rows = list(reader)
    
# Get all column names
print("Python CSV Columns:", list(rows[0].keys()))
print("\nSample first row:")
for k, v in list(rows[0].items())[:10]:
    print(f"  {k}: {v}")

# Look for regime column
regime_col = next((k for k in rows[0].keys() if 'regime' in k.lower()), None)
if regime_col:
    print(f"\nRegime column found: {regime_col}")
    regimes = Counter(r.get(regime_col, 'unknown') for r in rows)
    print(f"\nPython Regime Distribution:")
    for regime, count in regimes.most_common():
        print(f"  {regime}: {count} trades ({100*count/len(rows):.1f}%)")

# Check exit reason
exit_col = next((k for k in rows[0].keys() if 'exit' in k.lower() or 'reason' in k.lower()), None)
if exit_col:
    print(f"\nExit reason column: {exit_col}")
    exits = Counter(r.get(exit_col, 'unknown') for r in rows)
    print(f"\nPython Exit Distribution:")
    for exit, count in exits.most_common(5):
        print(f"  {exit}: {count} trades ({100*count/len(rows):.1f}%)")
