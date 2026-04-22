# US100 Risk Profile Tests Results (2026-04-21)

Artifacts base:
- /Users/niko/Documents/projects/niko-ai/backtest_artifacts/phantom-risk-tests-20260421_171409

Setup used:
- Instrument: US100
- Scenario: P2B (median baseline strategy logic)
- Start date: 2022-01-01
- Start capital: 5000
- Comparisons: median vs high and low for test 1, test 2, test 3

## Results Table

| Test | Profile | Trades | Win % | PF | Net Return % | Max DD % | Monthly Positive % | Net PnL |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | median | 1771 | 56.01 | 2.653 | 1240.59 | -3.25 | 98.04 | 62029.31 |
| 1 | high | 1771 | 56.01 | 2.526 | 16571.92 | -6.43 | 96.08 | 828595.95 |
| 1 | low | 1771 | 56.01 | 2.764 | 269.66 | -1.64 | 98.04 | 13483.11 |
| 2 | median | 1771 | 56.01 | 2.653 | 1240.59 | -3.25 | 98.04 | 62029.31 |
| 2 | high | 1771 | 56.01 | 2.853 | 7806.13 | -6.43 | 98.04 | 390306.42 |
| 2 | low | 1771 | 56.01 | 2.760 | 147.50 | -1.33 | 98.04 | 7375.09 |
| 3 | median | 1771 | 56.01 | 2.653 | 1240.59 | -3.25 | 98.04 | 62029.31 |
| 3 | high | 1771 | 56.01 | 2.867 | 10051.94 | -7.43 | 98.04 | 502596.78 |
| 3 | low | 1374 | 55.90 | 2.727 | 101.10 | -0.96 | 96.08 | 5055.17 |

## Delta vs Median

### Test 1
- High: return +15331.33 pp, drawdown -3.17 pp (deeper), PF -0.127, monthly positive -1.96 pp
- Low: return -970.92 pp, drawdown +1.62 pp (shallower), PF +0.111, monthly positive +0.00 pp

### Test 2
- High: return +6565.54 pp, drawdown -3.17 pp (deeper), PF +0.200, monthly positive +0.00 pp
- Low: return -1093.08 pp, drawdown +1.93 pp (shallower), PF +0.107, monthly positive +0.00 pp

### Test 3
- High: return +8811.35 pp, drawdown -4.18 pp (deeper), PF +0.214, monthly positive +0.00 pp
- Low: return -1139.48 pp, drawdown +2.29 pp (shallower), PF +0.074, monthly positive -1.96 pp

## Quick Interpretation

- High profile materially increases growth but also increases drawdown in all tests.
- Low profile materially reduces drawdown and keeps PF strong, but sharply reduces total return.
- Test 3 low adds exposure caps and reduces trade count (1374 vs 1771), indicating the portfolio constraints are actively filtering entries.
- Test 2 and Test 3 high are more controlled than Test 1 high due to additional controls and structure, while still significantly outperforming median on return.
