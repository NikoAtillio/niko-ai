# Python vs v2 US100 FTMO Comparison

Date: 2026-05-24

## Scope

This report compares a fresh Python backtest of `phantom/phantom_US100/phantom_US100_high_ftmo.py` against the MT5 v2 Strategy Tester report `ReportTester-1513448421.html`.

The Python run was executed with:

- Instrument: `US100`
- Capital: `10000`
- Date window: `2025-12-01` to `2026-01-31`
- Output directory: `tmp/python_backtest_fresh_20260524`

The fresh Python trade CSV is `tmp/python_backtest_fresh_20260524/phantom_p2_ftmo_trades_US100_P2_FTMOB.csv`.

## Summary

| Metric | Python | v2 report | Delta |
| --- | ---: | ---: | ---: |
| Trades | 70 | 66 | +4 |
| Win rate | 52.9% | 42.42% | +10.48 pp |
| Net profit | 2456.52 | 1234.41 | +1222.11 |
| Profit factor | 3.397 | 1.89 | +1.507 |
| Max drawdown | -3.17% | 4.28% balance drawdown relative | better in Python |
| Final capital / balance | 12456.52 | 11234.41 | +1222.11 |

## Run Details

Python backtest output:

- Entry timeframe: `M5`
- Test span: `2025-12-05 20:00:00` to `2026-01-31 00:00:00`
- Monthly PnL: `2025-12-31 = 1579.15`, `2026-01-31 = 877.36`
- Breakeven triggers: `30.0%`
- Timeout exits: `0.0%`

MT5 v2 report output:

- Report period label: `H1 (2025.12.01 - 2026.01.31)`
- First visible trade: `2025.12.01 08:10:00`
- Total deals: `132`
- Profit trades: `28`
- Loss trades: `38`
- Balance drawdown relative: `4.28%`

## Interpretation

The fresh Python run is stronger than the MT5 v2 report on every headline metric that matters for this comparison: higher win rate, higher profit factor, lower drawdown, and roughly double the net profit.

The main caveat is that the two runs are not yet a perfect execution-level match. The Python engine is running its own UTC-normalized data path and its own session/confirmation logic, while the MT5 report is the tester result as recorded by the platform. That means the headline comparison is valid, but it does not yet prove trade-by-trade equivalence.

## Bottom Line

Fresh Python backtest result: better than v2 on profit and risk-adjusted performance.

The next useful step is a trade-by-trade reconciliation between the Python CSV and the MT5 v2 export for the same calendar window.