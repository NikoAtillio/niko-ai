# PHANTOM v4.2 Walk-Forward Report

- Data: XAUUSD 5m
- Train/Test: 90d / 30d
- Capital: $10,000.00
- Base risk: 1.00%
- **FIX 1**: No stop_be — single exit at 2R or stop
- **FIX 2**: Max stop size: 0.35% of entry price
- **FIX 3**: ATR regime filter: ATR >= 0.6x 50-bar ATR avg
- **V4.2**: 5M EMA50 trend filter enabled
- **V4.2**: Zone tolerance=1.00% | zone age>=3 bars
- **V4.2**: Session filter disabled | target=2.5R

## Overall Results

- total_trades: 6
- win_rate: 50.0%
- avg_winner: $159.45
- avg_loser: $-94.52
- reward_risk: 1.69:1
- breakeven_wr_needed: 37.2%
- profit_factor: 1.69
- expectancy: $32.47
- total_fees: $51.74
- total_return: 1.69%
- final_capital: $10168.93
- max_drawdown: -2.83%
- windows_tested: 21
- windows_degraded: 90%

## Per-Window Results

| Window | Period | Trades | WR% | PF | PnL | DD% | Degraded |
|----|----|----|----|----|----|----|----|
| 1 | 2024-06-30 → 2024-07-30 | 0 | 0 | 0.0 | $+0.00 | 0.0% | ⚠ |
| 2 | 2024-07-30 → 2024-08-29 | 0 | 0 | 0.0 | $+0.00 | 0.0% | ⚠ |
| 3 | 2024-08-29 → 2024-09-28 | 0 | 0 | 0.0 | $+0.00 | 0.0% | ⚠ |
| 4 | 2024-09-28 → 2024-10-28 | 0 | 0 | 0.0 | $+0.00 | 0.0% | ⚠ |
| 5 | 2024-10-28 → 2024-11-27 | 0 | 0 | 0.0 | $+0.00 | 0.0% | ⚠ |
| 6 | 2024-11-27 → 2024-12-27 | 0 | 0 | 0.0 | $+0.00 | 0.0% | ⚠ |
| 7 | 2024-12-27 → 2025-01-26 | 2 | 100.0 | 1.0 | $+230.84 | -0.06% | ✓ |
| 8 | 2025-01-26 → 2025-02-25 | 1 | 100.0 | 1.0 | $+233.83 | -0.07% | ✓ |
| 9 | 2025-02-25 → 2025-03-27 | 1 | 0.0 | 0.0 | $-122.33 | -1.17% | ⚠ |
| 10 | 2025-03-27 → 2025-04-26 | 1 | 0.0 | 0.0 | $-117.87 | -1.14% | ⚠ |
| 11 | 2025-04-26 → 2025-05-26 | 0 | 0 | 0.0 | $+0.00 | 0.0% | ⚠ |
| 12 | 2025-05-26 → 2025-06-25 | 0 | 0 | 0.0 | $+0.00 | 0.0% | ⚠ |
| 13 | 2025-06-25 → 2025-07-25 | 0 | 0 | 0.0 | $+0.00 | 0.0% | ⚠ |
| 14 | 2025-07-25 → 2025-08-24 | 0 | 0 | 0.0 | $+0.00 | 0.0% | ⚠ |
| 15 | 2025-08-24 → 2025-09-23 | 0 | 0 | 0.0 | $+0.00 | 0.0% | ⚠ |
| 16 | 2025-09-23 → 2025-10-23 | 0 | 0 | 0.0 | $+0.00 | 0.0% | ⚠ |
| 17 | 2025-10-23 → 2025-11-22 | 1 | 0.0 | 0.0 | $-55.54 | -0.54% | ⚠ |
| 18 | 2025-11-22 → 2025-12-22 | 0 | 0 | 0.0 | $+0.00 | 0.0% | ⚠ |
| 19 | 2025-12-22 → 2026-01-21 | 0 | 0 | 0.0 | $+0.00 | 0.0% | ⚠ |
| 20 | 2026-01-21 → 2026-02-20 | 0 | 0 | 0.0 | $+0.00 | 0.0% | ⚠ |
| 21 | 2026-02-20 → 2026-03-22 | 0 | 0 | 0.0 | $+0.00 | 0.0% | ⚠ |

## Hyperparameters

- SWING_LOOKBACK: 20
- INTERVAL: 5m
- ZONE_MERGE_PCT: 0.01
- ZONE_MIN_AGE_BARS: 3
- WICK_RATIO_MIN: 0.5
- VOLUME_ZSCORE_MIN: 0.0
- ATR_STOP_MULT: 0.8
- FULL_EXIT_R: 2.5
- PARTIAL_EXIT_ENABLED: False  ← V4.1 fix
- MOVE_STOP_TO_BE: False  ← V4.1 fix
- MAX_STOP_PCT: 0.0035  ← V4.1 fix
- ATR_REGIME_FILTER: True  ← V4.1 fix
- ATR_REGIME_MULT: 0.6
- ATR_REGIME_PERIOD: 50
- EMA5M_TREND_FILTER: True
- EMA5M_PERIOD: 50
- BASE_RISK_PCT: 0.01
- MAX_CONCURRENT: 2
- FEE_PCT_PER_SIDE: 7e-05
- SESSION_START_UTC: 7
- SESSION_END_UTC: 16