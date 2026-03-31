# US100 Strategy Comparison Matrix

Interactive dashboard: [public/phantom-comparison.html](../public/phantom-comparison.html)

## US100 2023-24

### Dataset Scope

| Item | Value |
|---|---|
| Market | US100.cash |
| Primary evaluation window | 2023-05-19 to 2024-03-28 |
| Input timeframes supplied | M1, M5, H1, H4 |
| M1 bars | 301,385 |
| M5 bars | 70,208 |
| H1 bars | 5,917 |
| H4 bars | 1,547 |

### Cross-Referenced Results (v1, v2, v3, v4)

| Version | Scenario | Strategy Label | Entry TF | Zone/HTF Allocation | Session Allocation | Zones Found | Trades | Win Rate % | Profit Factor | Net Return % | Net PnL $ | Max DD % | Expectancy $/trade | Fees $ | Final Capital $ | Status | Source |
|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| v1 | D (pre-fix) | H1+H4 Confluence, risk 0.70%, no timeout | M1 execution loop | H1 + H4 confluence zones | Not explicitly shown in summary output | 61 | 226 | 32.3 | 0.958 | 60.64 | 6064.23 | -5.34 | 26.83 | 427.64 | 16064.23 | Completed | [v1_run.log](v1/v1_run.log) |
| v2 | D | PHANTOM v5.1, M5 entry, risk 0.40% | M5 | H4 pivot zones + H1 + M5 scoring | Not explicitly shown in summary output | 428 (shared build) | 1220 | 43.1 | 1.319 | 28.21 | 2821.39 | -3.03 | 2.31 | N/A | 12821.39 | Completed | [v2_run.log](v2/v2_run.log) |
| v2 | B | PHANTOM v5.1, M5 entry, risk 0.70% | M5 | H4 pivot zones + H1 + M5 scoring | Not explicitly shown in summary output | 428 (shared build) | 1220 | 43.1 | 1.308 | 53.61 | 5361.37 | -5.24 | 4.39 | N/A | 15361.37 | Completed | [v2_run.log](v2/v2_run.log) |
| v2 | A | PHANTOM v5.1, M1 entry, risk 0.35%, volume filter | M1 | H4 pivot zones + H1 + M1 scoring | Not explicitly shown in summary output | 428 (shared build) | 1004 | 43.2 | 1.450 | 41.55 | 4155.23 | -3.79 | 4.14 | N/A | 14155.23 | Completed | [v2_run.log](v2/v2_run.log) |
| v3 | A-style | 1H Zones, score >= 5, volume filter | M1 | H1 zones (script design) | 07-16 UTC in script config | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | Not completed (timeout / no output) | [v3_run.log](v3/v3_run.log) |
| v4 | B (alternate impl) | PHANTOM v5.1 Scenario B alternate implementation | M5 | H4 zones (alternate detector) + HTF filters | 07-16 UTC | 15 | 97 | 4.1 | 0.010 | -40.71 | -5429.35 | -54.29 | -41.97 | 2716.66 | 4570.65 | Completed (poor performance) | [v4_run.log](v4/v4_run.log) |

### Quick Cross-Reference View

| Data Point | v1 | v2 (best = B) | v3 | v4 |
|---|---:|---:|---:|---:|
| Entry timeframe | M1 loop | M5 | M1 | M5 |
| Zone/HTF allocation | H1+H4 confluence | H4 pivots + H1/M5 scoring | H1 zones | H4 zones (alternate) |
| Trades | 226 | 1220 | N/A | 97 |
| Win rate % | 32.3 | 43.1 | N/A | 4.1 |
| Profit factor | 0.958 | 1.308 | N/A | 0.010 |
| Net return % | 60.64 | 53.61 | N/A | -40.71 |
| Max DD % | -5.34 | -5.24 | N/A | -54.29 |
| Expectancy $/trade | 26.83 | 4.39 | N/A | -41.97 |
| Final capital $ | 16064.23 | 15361.37 | N/A | 4570.65 |

---

## US100 2024-25

### Dataset Scope

| Item | Value |
|---|---|
| Market | US100.cash |
| Primary evaluation window | 2024-04-01 to 2025-03-31 |
| Input timeframes supplied | M1, M5, H1, H4 |
| M1 bars | 350,004 |
| M5 bars | 70,006 |
| H1 bars | 5,900 |
| H4 bars | 1,543 |

### Cross-Referenced Results (v1, v2, v3, v4)

| Version | Scenario | Entry TF | Zone/HTF Allocation | Trades | Win Rate % | Profit Factor | Net Return % | Net PnL $ | Max DD % | Expectancy $/trade | Fees $ | Final Capital $ | Status | Source |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| v1 | D (pre-fix) | M1 execution loop | H1 + H4 confluence zones | 289 | 34.9 | 0.798 | 46.38 | 4637.65 | -14.66 | 16.05 | 475.90 | 14637.65 | Completed | [v1_24_25_run.log](v1/v1_24_25_run.log) |
| v2 | D | M5 | H4 pivot zones + H1 + M5 scoring | 1197 | 40.0 | 1.288 | 25.62 | 2562.00 | -4.62 | 2.14 | N/A | 12562.00 | Completed | [v2_24_25_run.log](v2/v2_24_25_run.log) |
| v2 | B | M5 | H4 pivot zones + H1 + M5 scoring | 1197 | 40.0 | 1.289 | 48.07 | 4806.94 | -8.00 | 4.02 | N/A | 14806.94 | Completed | [v2_24_25_run.log](v2/v2_24_25_run.log) |
| v2 | A | M1 | H4 pivot zones + H1 + M1 scoring | 1185 | 40.9 | 1.352 | 39.53 | 3952.54 | -3.24 | 3.34 | N/A | 13952.54 | Completed | [v2_24_25_run.log](v2/v2_24_25_run.log) |
| v3 | A-style | M1 | H1 zones (script design) | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | Not completed (timeout / no output) | [v3_24_25_run.log](v3/v3_24_25_run.log) |
| v4 | B (alternate impl) | M5 | H4 zones (alternate detector) + HTF filters | 82 | 9.8 | 0.059 | -30.91 | -4119.76 | -41.20 | -37.69 | 2057.79 | 5880.24 | Completed (poor performance) | [v4_24_25_run.log](v4/v4_24_25_run.log) |

---

## US100 2025-26

### Dataset Scope

| Item | Value |
|---|---|
| Market | US100.cash |
| Primary evaluation window | 2025-03-31 to 2026-03-31 |
| Input timeframes supplied | M1, M5, H1, H4 |
| M1 bars | 349,844 |
| M5 bars | 69,978 |
| H1 bars | 5,900 |
| H4 bars | 1,544 |

### Cross-Referenced Results (v1, v2, v3, v4)

| Version | Scenario | Entry TF | Zone/HTF Allocation | Trades | Win Rate % | Profit Factor | Net Return % | Net PnL $ | Max DD % | Expectancy $/trade | Fees $ | Final Capital $ | Status | Source |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| v1 | D (pre-fix) | M1 execution loop | H1 + H4 confluence zones | 230 | 22.6 | 0.420 | -10.43 | -1042.78 | -21.11 | -4.53 | 263.83 | 8957.22 | Completed | [v1_25_26_run.log](v1/v1_25_26_run.log) |
| v2 | D | M5 | H4 pivot zones + H1 + M5 scoring | 1194 | 38.3 | 1.135 | 11.70 | 1169.85 | -3.62 | 0.98 | N/A | 11169.85 | Completed | [v2_25_26_run.log](v2/v2_25_26_run.log) |
| v2 | B | M5 | H4 pivot zones + H1 + M5 scoring | 1194 | 38.3 | 1.131 | 20.72 | 2072.08 | -6.26 | 1.74 | N/A | 12072.08 | Completed | [v2_25_26_run.log](v2/v2_25_26_run.log) |
| v2 | A | M1 | H4 pivot zones + H1 + M1 scoring | 1161 | 40.1 | 1.202 | 20.61 | 2061.39 | -3.67 | 1.78 | N/A | 12061.39 | Completed | [v2_25_26_run.log](v2/v2_25_26_run.log) |
| v3 | A-style | M1 | H1 zones (script design) | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | Not completed (timeout / no output) | [v3_25_26_run.log](v3/v3_25_26_run.log) |
| v4 | B (alternate impl) | M5 | H4 zones (alternate detector) + HTF filters | 127 | 11.0 | 0.037 | -36.45 | -4615.54 | -46.16 | -28.70 | 1940.60 | 5384.46 | Completed (poor performance) | [v4_25_26_run.log](v4/v4_25_26_run.log) |

---

## Final Multi-Period Comparison (Template)

Populate this once all three periods are complete.

| Version | Scenario | 2023-24 Return % | 2024-25 Return % | 2025-26 Return % | Avg Return % | Return Std Dev | 2023-24 PF | 2024-25 PF | 2025-26 PF | Avg PF | Worst DD % (all periods) | Notes |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| v1 | D (pre-fix) | 60.64 | 46.38 | -10.43 | 32.20 | 30.70 | 0.958 | 0.798 | 0.420 | 0.725 | -21.11 | Regime-sensitive and unstable; PF < 1 across all periods |
| v2 | D | 28.21 | 25.62 | 11.70 | 21.84 | 7.25 | 1.319 | 1.288 | 1.135 | 1.247 | -4.62 | Most stable drawdown profile of v2 set |
| v2 | B | 53.61 | 48.07 | 20.72 | 40.80 | 14.38 | 1.308 | 1.289 | 1.131 | 1.243 | -8.00 | Best absolute returns, reduced edge in 2025-26 |
| v2 | A | 41.55 | 39.53 | 20.61 | 33.90 | 9.43 | 1.450 | 1.352 | 1.202 | 1.335 | -3.79 | Best risk-adjusted across three periods |
| v3 | A-style | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | Did not complete in any period (timeout) |
| v4 | B (alternate impl) | -40.71 | -30.91 | -36.45 | -36.02 | 4.01 | 0.010 | 0.059 | 0.037 | 0.035 | -54.29 | Consistently broken/negative implementation |