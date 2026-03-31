# PHANTOM v4.2 Walk-Forward Report

- Data: US100 5m
- Train/Test: 90d / 30d
- Capital: $10,000.00
- Base risk: 1.00%
- **FIX 1**: No stop_be — single exit at 2R or stop
- **FIX 2**: Max stop size: 0.50% of entry price
- **FIX 3**: ATR regime filter: ATR >= 0.35x 50-bar ATR avg
- **V4.2**: 5M EMA50 trend filter enabled
- **V4.2**: Zone tolerance=0.80% | zone age>=1 bars
- **V4.2**: Session filter disabled | target=2.0R

## Overall Results

- total_trades: 33
- win_rate: 48.5%
- avg_winner: $135.36
- avg_loser: $-79.13
- reward_risk: 1.71:1
- breakeven_wr_needed: 36.9%
- profit_factor: 1.61
- expectancy: $24.87
- total_fees: $307.30
- total_return: 6.67%
- final_capital: $10667.02
- max_drawdown: -5.52%
- windows_tested: 21
- windows_degraded: 52%

## Per-Window Results

| Window | Period | Trades | WR% | PF | PnL | DD% | Degraded |
|----|----|----|----|----|----|----|----|
| 1 | 2024-06-30 → 2024-07-30 | 0 | 0 | 0.0 | $+0.00 | 0.0% | ⚠ |
| 2 | 2024-07-30 → 2024-08-29 | 1 | 100.0 | 1.0 | $+92.69 | -0.02% | ✓ |
| 3 | 2024-08-29 → 2024-09-28 | 1 | 100.0 | 1.0 | $+194.99 | -0.02% | ✓ |
| 4 | 2024-09-28 → 2024-10-28 | 2 | 0.0 | 0.0 | $-230.14 | -2.24% | ⚠ |
| 5 | 2024-10-28 → 2024-11-27 | 2 | 0.0 | 0.0 | $-179.67 | -1.79% | ⚠ |
| 6 | 2024-11-27 → 2024-12-27 | 3 | 33.3 | 0.8 | $-33.92 | -1.25% | ⚠ |
| 7 | 2024-12-27 → 2025-01-26 | 3 | 33.3 | 0.77 | $-37.92 | -1.26% | ⚠ |
| 8 | 2025-01-26 → 2025-02-25 | 3 | 66.7 | 2.67 | $+91.55 | -0.74% | ✓ |
| 9 | 2025-02-25 → 2025-03-27 | 1 | 0.0 | 0.0 | $-56.51 | -0.57% | ⚠ |
| 10 | 2025-03-27 → 2025-04-26 | 0 | 0 | 0.0 | $+0.00 | 0.0% | ⚠ |
| 11 | 2025-04-26 → 2025-05-26 | 0 | 0 | 0.0 | $+0.00 | 0.0% | ⚠ |
| 12 | 2025-05-26 → 2025-06-25 | 4 | 50.0 | 1.72 | $+67.42 | -1.12% | ✓ |
| 13 | 2025-06-25 → 2025-07-25 | 3 | 33.3 | 0.83 | $-41.83 | -0.93% | ⚠ |
| 14 | 2025-07-25 → 2025-08-24 | 1 | 100.0 | 1.0 | $+130.06 | -0.06% | ✓ |
| 15 | 2025-08-24 → 2025-09-23 | 1 | 100.0 | 1.0 | $+172.60 | -0.09% | ✓ |
| 16 | 2025-09-23 → 2025-10-23 | 3 | 66.7 | 3.0 | $+230.96 | -1.39% | ✓ |
| 17 | 2025-10-23 → 2025-11-22 | 2 | 50.0 | 1.7 | $+72.05 | -1.22% | ✓ |
| 18 | 2025-11-22 → 2025-12-22 | 0 | 0 | 0.0 | $+0.00 | 0.0% | ⚠ |
| 19 | 2025-12-22 → 2026-01-21 | 0 | 0 | 0.0 | $+0.00 | 0.0% | ⚠ |
| 20 | 2026-01-21 → 2026-02-20 | 2 | 50.0 | 1.67 | $+51.45 | -0.94% | ✓ |
| 21 | 2026-02-20 → 2026-03-22 | 1 | 100.0 | 1.0 | $+143.23 | -0.05% | ✓ |

## Hyperparameters

- SWING_LOOKBACK: 10
- INTERVAL: 5m
- ZONE_MERGE_PCT: 0.008
- ZONE_MIN_AGE_BARS: 1
- WICK_RATIO_MIN: 0.5
- VOLUME_ZSCORE_MIN: 0.0
- ATR_STOP_MULT: 0.8
- FULL_EXIT_R: 2.0
- PARTIAL_EXIT_ENABLED: False  ← V4.1 fix
- MOVE_STOP_TO_BE: False  ← V4.1 fix
- MAX_STOP_PCT: 0.005  ← V4.1 fix
- ATR_REGIME_FILTER: True  ← V4.1 fix
- ATR_REGIME_MULT: 0.35
- ATR_REGIME_PERIOD: 50
- EMA5M_TREND_FILTER: False
- EMA5M_PERIOD: 50
- BASE_RISK_PCT: 0.01
- MAX_CONCURRENT: 3
- FEE_PCT_PER_SIDE: 5e-05
- SESSION_START_UTC: 7
- SESSION_END_UTC: 16