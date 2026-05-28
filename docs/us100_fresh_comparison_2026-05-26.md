# US100 Fresh Backtest Comparison

Date: 2026-05-26

## Scope

Fresh comparison run on the same US100 period using newly sliced input data for:
- 2025-12-01 through 2026-01-31
- `data/US100` source files copied into `tmp/us100_fresh_compare_20260526`

## Results

| Engine | Trades | Win % | Net Return | Max DD | Final Capital |
| --- | ---: | ---: | ---: | ---: | ---: |
| high | 98 | 42.9% | 7.29% | -3.70% | 10,729.05 |
| high2 | 17 | 35.3% | 6.01% | -3.05% | 10,601.20 |
| high_ftmo | 70 | 52.9% | 24.49% | -3.17% | 12,449.44 |

## Output Files

- `tmp/us100_fresh_compare_outputs_20260526/high/phantom_p2_trades_US100_P2B.csv`
- `tmp/us100_fresh_compare_outputs_20260526/high2/phantom_p2_trades_US100_P2B.csv`
- `tmp/us100_fresh_compare_outputs_20260526/ftmo/phantom_p2_ftmo_trades_US100_P2_FTMOB.csv`

## Notes

- `high_ftmo` delivered the strongest headline performance in this fresh run.
- `high2` remained the most restrictive and produced the fewest trades.
- The `high_ftmo` run uses its own FTMO guardrails and an internally reported effective test span ending at 2026-01-31.
