# US100 Fresh Trade Reconciliation

Date: 2026-05-26

This compares the three fresh US100 runs on the same sliced period: 2025-12-01 through 2026-01-31.

## Summary

| Engine | Trades | Win % | Net PnL | Final Capital |
| --- | ---: | ---: | ---: | ---: |
| high | 98 | 42.86% | 729.05 | 10,729.05 |
| high2 | 17 | 35.29% | 601.20 | 10,601.20 |
| high_ftmo | 70 | 52.86% | 2,449.44 | 12,449.44 |

## Overlap Analysis

Trades were matched by exact entry timestamp plus direction.

- `high` vs `high2`: 3 common trades
- `high` vs `high_ftmo`: 11 common trades
- `high2` vs `high_ftmo`: 0 common trades
- Triple overlap across all three: 0 trades

## Common-Trade PnL

### high vs high2

- Common trade PnL: `high = 287.81`, `high2 = 270.27`
- Difference on common trades: `+17.53` in favor of `high`

### high vs high_ftmo

- Common trade PnL: `high = -64.67`, `high_ftmo = 727.41`
- Difference on common trades: `-792.09` when subtracting `high_ftmo - high`

## Notes

- `high_ftmo` takes a much different trade set from the other two runs, so its edge is not just a sizing difference.
- `high2` is the most restrictive and barely overlaps with `high`, and does not overlap with `high_ftmo` on exact entry timestamp + direction.
- A fuller reconciliation would need looser matching rules if you want to compare near-miss setups that fire a few bars apart.

## Saved Artifact

- [trade_reconciliation_summary.csv](../tmp/us100_fresh_compare_outputs_20260526/trade_reconciliation_summary.csv)
