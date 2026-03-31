# PHANTOM v4.2 Walk-Forward Report

- Data: XAUUSD 5m
- Train/Test: 90d / 30d
- Capital: $10,000.00
- Base risk: 1.00%
- **FIX 1**: No stop_be — single exit at 2R or stop
- **FIX 2**: Max stop size: 0.50% of entry price
- **FIX 3**: ATR regime filter: ATR >= 0.4x 50-bar ATR avg
- **V4.2**: 5M EMA50 trend filter enabled
- **V4.2**: Zone tolerance=0.80% | zone age>=1 bars
- **V4.2**: Session filter disabled | target=2.0R

## Overall Results

- total_trades: 32
- win_rate: 46.9%
- avg_winner: $137.00
- avg_loser: $-90.75
- reward_risk: 1.51:1
- breakeven_wr_needed: 39.8%
- profit_factor: 1.33
- expectancy: $16.01
- total_fees: $277.10
- total_return: 3.74%
- final_capital: $10373.85
- max_drawdown: -5.02%
- windows_tested: 21
- windows_degraded: 52%

## Per-Window Results

| Window | Period | Trades | WR% | PF | PnL | DD% | Degraded |
|----|----|----|----|----|----|----|----|
| 1 | 2024-06-30 → 2024-07-30 | 0 | 0 | 0.0 | $+0.00 | 0.0% | ⚠ |
| 2 | 2024-07-30 → 2024-08-29 | 0 | 0 | 0.0 | $+0.00 | 0.0% | ⚠ |
| 3 | 2024-08-29 → 2024-09-28 | 3 | 66.7 | 3.27 | $+107.95 | -0.62% | ✓ |
| 4 | 2024-09-28 → 2024-10-28 | 3 | 33.3 | 0.86 | $-42.71 | -2.26% | ⚠ |
| 5 | 2024-10-28 → 2024-11-27 | 1 | 0.0 | 0.0 | $-124.74 | -1.24% | ⚠ |
| 6 | 2024-11-27 → 2024-12-27 | 2 | 50.0 | 1.55 | $+52.01 | -1.3% | ✓ |
| 7 | 2024-12-27 → 2025-01-26 | 4 | 50.0 | 1.61 | $+56.87 | -1.22% | ✓ |
| 8 | 2025-01-26 → 2025-02-25 | 0 | 0 | 0.0 | $+0.00 | 0.0% | ⚠ |
| 9 | 2025-02-25 → 2025-03-27 | 3 | 33.3 | 0.83 | $-42.79 | -1.75% | ⚠ |
| 10 | 2025-03-27 → 2025-04-26 | 0 | 0 | 0.0 | $+0.00 | 0.0% | ⚠ |
| 11 | 2025-04-26 → 2025-05-26 | 2 | 50.0 | 1.76 | $+37.64 | -0.56% | ✓ |
| 12 | 2025-05-26 → 2025-06-25 | 2 | 50.0 | 1.71 | $+35.19 | -0.61% | ✓ |
| 13 | 2025-06-25 → 2025-07-25 | 1 | 100.0 | 1.0 | $+181.25 | -0.07% | ✓ |
| 14 | 2025-07-25 → 2025-08-24 | 0 | 0 | 0.0 | $+0.00 | 0.0% | ⚠ |
| 15 | 2025-08-24 → 2025-09-23 | 2 | 50.0 | 1.57 | $+56.00 | -1.36% | ✓ |
| 16 | 2025-09-23 → 2025-10-23 | 2 | 100.0 | 1.0 | $+403.44 | -0.03% | ✓ |
| 17 | 2025-10-23 → 2025-11-22 | 1 | 0.0 | 0.0 | $-114.41 | -1.07% | ⚠ |
| 18 | 2025-11-22 → 2025-12-22 | 3 | 0.0 | 0.0 | $-363.93 | -3.43% | ⚠ |
| 19 | 2025-12-22 → 2026-01-21 | 2 | 50.0 | 1.76 | $+37.53 | -0.58% | ✓ |
| 20 | 2026-01-21 → 2026-02-20 | 1 | 100.0 | 1.0 | $+94.55 | -0.03% | ✓ |
| 21 | 2026-02-20 → 2026-03-22 | 0 | 0 | 0.0 | $+0.00 | 0.0% | ⚠ |

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
- ATR_REGIME_MULT: 0.4
- ATR_REGIME_PERIOD: 50
- EMA5M_TREND_FILTER: False
- EMA5M_PERIOD: 50
- BASE_RISK_PCT: 0.01
- MAX_CONCURRENT: 3
- FEE_PCT_PER_SIDE: 7e-05
- SESSION_START_UTC: 7
- SESSION_END_UTC: 16