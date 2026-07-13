# V5-upgrade Full 3-Year Signal Generation Report

- Run timestamp: 2026-07-13 14:50:08
- Strategy: `phantom_us100_v5_fund.py` (V5-upgrade branch)
- Instrument: US100
- Requested window: 2023-01-01 to 2026-01-01
- Output directory: `saved_runs/2026-07-13_145008_v5_upgrade_full3y`

## Command Configuration

- `--start-date 2023-01-01`
- `--end-date 2026-01-01`
- `--cash-trail-max-loss-pct 100`
- `--capital 10000`

## Backtest Summary (from run log)

- Trades: 636
- Win rate: 56.1%
- Profit factor: 2.776
- Net return: 4473.06%
- Max drawdown: -15.05%
- Expectancy: $703.31/trade
- Final capital: $457,306.29
- Test span: 2023-01-06 15:30:00 to 2025-12-31 16:35:00
- Replay validator: PASS (`REPLAY MATCHES INTERNAL BACKTEST`)

## Signal File Verification

File: `signals/phantom_signals.jsonl`

- Total lines: 8406
- First event: 2023-01-06T15:30:00
- Last event: 2025-12-31T16:35:00
- Action counts:
  - meta: 1
  - open: 636
  - modify: 7133
  - close: 636

Confidence and stacking stats on `open` events:

- `conf` min: 0.65
- `conf` max: 6.0
- `conf` average: 2.6722
- `stack_max` distribution:
  - 1: 491
  - 2: 42
  - 3: 37
  - 4: 66

## MT5 Common/Files Sync Verification

- Copied to: `.../Terminal/Common/Files/phantom_signals.jsonl`
- SHA-256 (repo): `04b4f4a85ca91198769b6166035675c89a461e6b1dd55ffc46912c456e860f73`
- SHA-256 (MT5 Common): `04b4f4a85ca91198769b6166035675c89a461e6b1dd55ffc46912c456e860f73`
- Result: exact match

## Generated Artifacts

- Run log: `saved_runs/2026-07-13_145008_v5_upgrade_full3y/run.log`
- Trades CSV: `saved_runs/2026-07-13_145008_v5_upgrade_full3y/phantom_phantom_us100_v5_fund_trades_US100_PHANTOM_US100_V5_FUNDB.csv`
- Report: `saved_runs/2026-07-13_145008_v5_upgrade_full3y/REPORT_FULL3Y.md`
