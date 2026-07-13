# V5-upgrade Full 3-Year Signal Generation Report

- Run timestamp: 2026-07-13 17:30:00
- Strategy: `phantom_us100_v5_fund.py` (V5-upgrade branch)
- Instrument: US100
- Requested window: 2023-01-01 to 2026-01-01
- Output directory: `saved_runs/2026-07-13_173000_v5_upgrade_full3y`

## Command Configuration

- `--start-date 2023-01-01`
- `--end-date 2026-01-01`
- `--cash-trail-max-loss-pct 100`
- `--capital 10000`

## Backtest Summary

- Trades: 632
- Win rate: 55.7%
- Profit factor: 2.763
- Net return: 5317.89%
- Max drawdown: -18.67%
- Expectancy: $841.44/trade
- Final capital: $541,789.24
- Test span: 2023-01-06 15:30:00 to 2025-12-31 16:35:00
- Replay validator: PASS (`REPLAY MATCHES INTERNAL BACKTEST`)

## Signal File Verification

File: `signals/signals_phantom_us100_v5_fund_us100_20230101_20260101.jsonl`

- Total lines: 8350
- First open event: 2023-01-06T15:30:00
- Last open event: 2025-12-31T15:00:00
- Action counts:
  - meta: 1
  - open: 632
  - modify: 7085
  - close: 632

Confidence and stacking stats on `open` events:

- `conf` min: 0.96
- `conf` max: 9.0
- `conf` average: 4.8916
- `stack_max` distribution:
  - 1: 487
  - 2: 7
  - 3: 70
  - 4: 68

## MT5 Common/Files Sync Verification

- Copied to: `.../Terminal/Common/Files/signals_phantom_us100_v5_fund_us100_20230101_20260101.jsonl`
- SHA-256 (repo): `39140b017d893da28246b0fd2d3ac0b6f46f4de6b41dd65f2cd51608879c40ba`
- SHA-256 (MT5 Common): `39140b017d893da28246b0fd2d3ac0b6f46f4de6b41dd65f2cd51608879c40ba`
- Result: exact match

## MT5 Wiring

- Bridge source default: `phantom/mql5/PhantomBridge.mq5`
- Run profile: `phantom/mql5/profiles/bridge_v5_upgrade_full3y.set`
- Signal filename: `signals_phantom_us100_v5_fund_us100_20230101_20260101.jsonl`

## Generated Artifacts

- Run log: `saved_runs/2026-07-13_173000_v5_upgrade_full3y/run.log`
- Trades CSV: `saved_runs/2026-07-13_173000_v5_upgrade_full3y/phantom_phantom_us100_v5_fund_trades_US100_PHANTOM_US100_V5_FUNDB.csv`
- Report: `saved_runs/2026-07-13_173000_v5_upgrade_full3y/REPORT_FULL3Y.md`