# Python Strategy Tester Report
FTMO-Demo (Python, US100, same period as MT5 reference)

## Settings
Expert:  phantom_US100_high_ftmo.py
Symbol:  US100.cash
Period:  M5 (2025.12.01 - 2026.01.31)
Source CSV:  phantom_p2_ftmo_trades_US100_P2_FTMOB.csv

Inputs:
InpPivotBars=2
InpZoneLookback=50
InpZoneTolerance=0.002
InpChaseFilterATR=1.5
InpSessionStart=13
InpSessionEnd=21
InpPeakSessionBoost=true
InpMinConfirmBars=1
InpConfirmTF=16385
InpScoreMin=3
InpH4ScoreMin=1
InpH1ScoreMin=1
InpLTFScoreMin=1
InpLTFScoreCap=3
InpLongScoreOffset=1
InpRiskPercent=0.7
InpRiskMultiplier=2.0
InpATRStopMult=1.5
InpTPMult=1.3
InpTrailATRMult=0.8
InpBreakevenR=0.8
InpMaxConcurrent=3
InpCooldownMin=20
InpEnableDebugLogs=true
InpLockoutMin=60
InpCircuitBreakerLosses=5
InpCircuitBreakerHours=24
InpEnableFTMOGuardrails=false
InpFTMOAccountSize=70000.0
InpFTMOProfitTargetPct=5.0
InpFTMOMaxLossPct=10.0
InpFTMOMaxDailyLossPct=5.0
InpFTMOTradingPeriodDays=0
InpFTMOMinTradingDays=2
InpFTMOMaxLeverage=30.0
InpConfidenceMult=1.5
InpSessionSoftMult=0.5
InpCounterTrendMult=0.5
InpSpreadBPS=0.0
InpSlippageBPS=0.0
InpMagicNumber=202406
InpComment=Phantom P2 US100 B
InpAutoDetectUTC=false
InpManualUTCOffset=-5
InpEWMATRPeriod=14
InpPythonExpectedATR=103.76
InpEnableDebugPrint=true
InpEnableVisuals=true
InpShowOnlyActiveZones=true
InpShowZoneOrigins=true
InpShowInactiveZoneMarkers=true
InpShowZoneTimeframe=true

## Results
History Quality: 100%
Bars: 11639    Ticks: 11337960    Symbols: 1
Total Net Profit: 2,449.44
Balance Drawdown Absolute: 404.66
Equity Drawdown Absolute: 404.66
Gross Profit: 3,474.57
Balance Drawdown Maximal: 404.66 (3.17%)
Equity Drawdown Maximal: 404.66 (3.17%)
Gross Loss: -1,025.13
Balance Drawdown Relative: 3.17%
Equity Drawdown Relative: 3.17%
Profit Factor: 3.39
Expected Payoff: 34.99
Margin Level: n/a
Recovery Factor: n/a
Sharpe Ratio: n/a
Z-Score: n/a
AHPR: n/a
LR Correlation: n/a
OnTester result: n/a
GHPR: n/a
LR Standard Error: n/a
Total Trades: 70
Short Trades (won %): 34 (44.12%)
Long Trades (won %): 36 (61.11%)
Total Deals: 140
Profit Trades (% of total): 37 (52.86%)
Loss Trades (% of total): 33 (47.14%)
Largest profit trade: 352.23
Largest loss trade: -99.06
Average profit trade: 93.91
Average loss trade: -31.06
Maximum consecutive wins ($): 7
Maximum consecutive losses ($): 10
Minimal position holding time: 0 days 00:50:00
Maximal position holding time: 2 days 16:05:00
Average position holding time: 0 days 08:18:08.571428571

## Trades
Times below are from the Python FTMO export and are sorted by entry time.

| # | Entry Time | Exit Time | Dir | Entry | Exit | Exit Reason | Qty | PnL | Win | Conf | Regime |
|---:|---|---|---|---:|---:|---|---:|---:|---|---:|---|
| 1 | 2025-12-05 20:00:00 | 2025-12-05 21:25:00 | short | 25665.15 | 25630.056792 | stop | 0.66 | 23.31 | Yes | 1.5 | bull |
| 2 | 2025-12-05 20:20:00 | 2025-12-05 21:25:00 | short | 25642.35 | 25630.056792 | stop | 0.44 | 5.44 | Yes | 1.0 | bull |
| 3 | 2025-12-05 20:50:00 | 2025-12-05 22:50:00 | short | 25578.85 | 25656.056792 | stop | 0.44 | -34.19 | No | 1.0 | bull |
| 4 | 2025-12-09 13:00:00 | 2025-12-09 22:00:00 | short | 25621.55 | 25622.730084 | stop | 0.73 | -0.86 | No | 1.5 | bull |
| 5 | 2025-12-09 13:20:00 | 2025-12-09 22:00:00 | short | 25617.25 | 25622.730084 | stop | 0.49 | -2.67 | No | 1.0 | bull |
| 6 | 2025-12-09 13:40:00 | 2025-12-09 22:00:00 | short | 25646.55 | 25622.730084 | stop | 0.49 | 11.59 | Yes | 1.0 | bull |
| 7 | 2025-12-10 17:05:00 | 2025-12-10 20:25:00 | short | 25674.65 | 25671.738937 | stop | 0.94 | 2.74 | Yes | 1.5 | bull |
| 8 | 2025-12-10 17:25:00 | 2025-12-10 20:25:00 | short | 25600.35 | 25673.438937 | stop | 0.63 | -45.88 | No | 1.0 | bull |
| 9 | 2025-12-10 17:45:00 | 2025-12-10 20:25:00 | short | 25623.55 | 25673.438937 | stop | 0.63 | -31.32 | No | 1.0 | bull |
| 10 | 2025-12-11 16:00:00 | 2025-12-11 21:30:00 | long | 25514.25 | 25552.066838 | stop | 1.15 | 43.54 | Yes | 1.5 | bull |
| 11 | 2025-12-11 16:20:00 | 2025-12-11 21:30:00 | long | 25562.05 | 25552.066838 | stop | 0.77 | -7.66 | No | 1.0 | bull |
| 12 | 2025-12-11 16:40:00 | 2025-12-11 21:30:00 | long | 25561.55 | 25552.066838 | stop | 0.77 | -7.28 | No | 1.0 | bull |
| 13 | 2025-12-12 15:00:00 | 2025-12-12 22:25:00 | short | 25650.55 | 25346.941760 | tp | 0.54 | 163.09 | Yes | 1.5 | bull |
| 14 | 2025-12-12 15:20:00 | 2025-12-12 22:25:00 | short | 25650.45 | 25346.841760 | tp | 0.36 | 108.73 | Yes | 1.0 | bull |
| 15 | 2025-12-12 15:40:00 | 2025-12-12 22:25:00 | short | 25644.45 | 25340.841760 | tp | 0.36 | 108.73 | Yes | 1.0 | bull |
| 16 | 2025-12-17 13:00:00 | 2025-12-17 21:35:00 | long | 25115.75 | 25124.227592 | stop | 0.91 | 7.69 | Yes | 1.5 | bull |
| 17 | 2025-12-17 13:30:00 | 2025-12-17 21:35:00 | long | 25143.45 | 25124.227592 | stop | 0.60 | -11.63 | No | 1.0 | bull |
| 18 | 2025-12-17 14:00:00 | 2025-12-17 21:35:00 | long | 25144.75 | 25124.227592 | stop | 0.73 | -14.89 | No | 1.0 | bull |
| 19 | 2025-12-18 17:05:00 | 2025-12-19 00:05:00 | long | 24846.45 | 25029.825950 | stop | 1.00 | 183.78 | Yes | 1.5 | bull |
| 20 | 2025-12-18 17:35:00 | 2025-12-19 00:05:00 | long | 24841.55 | 25029.825950 | stop | 0.67 | 125.80 | Yes | 1.0 | bull |
| 21 | 2025-12-18 17:55:00 | 2025-12-19 00:05:00 | long | 24844.65 | 25029.825950 | stop | 0.67 | 123.72 | Yes | 1.0 | bull |
| 22 | 2025-12-19 14:00:00 | 2025-12-22 06:05:00 | long | 25098.35 | 25401.139151 | tp | 1.16 | 352.23 | Yes | 1.5 | bull |
| 23 | 2025-12-19 14:20:00 | 2025-12-22 06:05:00 | long | 25113.25 | 25416.039151 | tp | 0.78 | 234.82 | Yes | 1.0 | bull |
| 24 | 2025-12-19 14:40:00 | 2025-12-22 06:05:00 | long | 25098.15 | 25400.939151 | tp | 0.78 | 234.82 | Yes | 1.0 | bull |
| 25 | 2025-12-29 13:00:00 | 2025-12-29 20:45:00 | short | 25599.15 | 25469.177799 | tp | 1.22 | 157.98 | Yes | 1.5 | bull |
| 26 | 2025-12-29 13:20:00 | 2025-12-29 15:20:00 | long | 25624.65 | 25567.928071 | stop | 1.62 | -91.93 | No | 1.0 | bull |
| 27 | 2025-12-29 13:40:00 | 2025-12-29 20:45:00 | short | 25607.65 | 25516.571929 | stop | 0.81 | 73.80 | Yes | 1.0 | bull |
| 28 | 2025-12-29 16:20:00 | 2025-12-29 21:35:00 | short | 25547.85 | 25517.571929 | stop | 1.45 | 43.81 | Yes | 1.5 | bull |
| 29 | 2025-12-29 20:45:00 | 2025-12-29 22:45:00 | short | 25463.25 | 25521.443005 | stop | 1.12 | -65.20 | No | 1.5 | bull |
| 30 | 2025-12-30 13:05:00 | 2025-12-30 16:25:00 | short | 25519.45 | 25534.613310 | stop | 1.07 | -16.29 | No | 1.5 | bull |
| 31 | 2025-12-30 13:25:00 | 2025-12-30 16:25:00 | short | 25503.05 | 25534.613310 | stop | 0.72 | -22.60 | No | 1.0 | bull |
| 32 | 2025-12-30 13:45:00 | 2025-12-30 16:25:00 | short | 25516.35 | 25534.613310 | stop | 0.72 | -13.08 | No | 1.0 | bull |
| 33 | 2025-12-30 17:35:00 | 2025-12-30 21:50:00 | short | 25520.75 | 25536.519535 | stop | 1.33 | -21.02 | No | 1.5 | bull |
| 34 | 2025-12-30 17:55:00 | 2025-12-30 21:50:00 | short | 25514.85 | 25536.519535 | stop | 0.89 | -19.26 | No | 1.0 | bull |
| 35 | 2025-12-30 18:15:00 | 2025-12-30 21:50:00 | short | 25499.65 | 25536.519535 | stop | 0.74 | -27.31 | No | 1.0 | bull |
| 36 | 2026-01-02 13:00:00 | 2026-01-02 21:40:00 | long | 25432.25 | 25441.788197 | stop | 1.49 | 14.20 | Yes | 1.5 | bull |
| 37 | 2026-01-02 13:20:00 | 2026-01-02 21:40:00 | long | 25432.95 | 25441.788197 | stop | 0.99 | 8.77 | Yes | 1.0 | bull |
| 38 | 2026-01-02 13:40:00 | 2026-01-02 21:40:00 | long | 25438.45 | 25441.788197 | stop | 0.99 | 3.31 | Yes | 1.0 | bull |
| 39 | 2026-01-06 15:00:00 | 2026-01-06 22:55:00 | long | 25444.35 | 25499.803856 | stop | 1.73 | 95.68 | Yes | 1.5 | bull |
| 40 | 2026-01-06 16:40:00 | 2026-01-06 22:55:00 | long | 25406.45 | 25499.803856 | stop | 1.73 | 161.08 | Yes | 1.5 | bull |
| 41 | 2026-01-06 17:05:00 | 2026-01-06 22:55:00 | long | 25400.95 | 25503.562008 | stop | 1.20 | 123.16 | Yes | 1.0 | bull |
| 42 | 2026-01-08 14:05:00 | 2026-01-08 21:30:00 | long | 25528.15 | 25538.696473 | stop | 1.83 | 19.35 | Yes | 1.5 | bull |
| 43 | 2026-01-08 14:25:00 | 2026-01-08 21:30:00 | long | 25580.05 | 25538.696473 | stop | 1.22 | -50.58 | No | 1.0 | bull |
| 44 | 2026-01-08 14:45:00 | 2026-01-08 21:30:00 | long | 25583.95 | 25538.696473 | stop | 1.22 | -55.35 | No | 1.0 | bull |
| 45 | 2026-01-09 13:00:00 | 2026-01-09 21:20:00 | long | 25516.95 | 25549.489746 | stop | 1.56 | 50.71 | Yes | 1.5 | bull |
| 46 | 2026-01-09 13:20:00 | 2026-01-09 18:25:00 | short | 25503.15 | 25566.610254 | stop | 0.52 | -32.97 | No | 1.0 | bull |
| 47 | 2026-01-09 13:40:00 | 2026-01-09 21:20:00 | long | 25517.75 | 25549.489746 | stop | 1.04 | 32.98 | Yes | 1.0 | bull |
| 48 | 2026-01-09 19:25:00 | 2026-01-09 21:20:00 | long | 25549.85 | 25550.943113 | stop | 1.58 | 1.73 | Yes | 1.5 | bull |
| 49 | 2026-01-12 13:00:00 | 2026-01-12 19:30:00 | short | 25538.65 | 25573.427546 | stop | 0.64 | -22.10 | No | 1.5 | bull |
| 50 | 2026-01-12 13:20:00 | 2026-01-12 19:30:00 | short | 25540.65 | 25573.427546 | stop | 0.42 | -13.88 | No | 1.0 | bull |
| 51 | 2026-01-12 13:40:00 | 2026-01-12 19:30:00 | short | 25543.83 | 25573.427546 | stop | 0.42 | -12.54 | No | 1.0 | bull |
| 52 | 2026-01-12 20:40:00 | 2026-01-12 21:30:00 | long | 25574.95 | 25587.114793 | stop | 1.34 | 16.32 | Yes | 1.5 | bull |
| 53 | 2026-01-14 13:35:00 | 2026-01-14 21:40:00 | short | 25681.25 | 25479.844159 | tp | 0.81 | 162.60 | Yes | 1.5 | bull |
| 54 | 2026-01-14 15:45:00 | 2026-01-14 21:40:00 | short | 25680.95 | 25479.544159 | tp | 0.65 | 130.08 | Yes | 1.0 | bull |
| 55 | 2026-01-14 16:45:00 | 2026-01-14 21:35:00 | short | 25686.23 | 25616.258037 | stop | 0.97 | 67.79 | Yes | 1.5 | bull |
| 56 | 2026-01-15 13:00:00 | 2026-01-15 20:45:00 | long | 25464.65 | 25750.661465 | tp | 1.17 | 335.05 | Yes | 1.5 | bull |
| 57 | 2026-01-15 13:20:00 | 2026-01-15 22:45:00 | long | 25552.55 | 25659.211963 | stop | 0.78 | 83.30 | Yes | 1.0 | bull |
| 58 | 2026-01-15 13:40:00 | 2026-01-15 22:45:00 | long | 25560.15 | 25659.211963 | stop | 0.78 | 77.36 | Yes | 1.0 | bull |
| 59 | 2026-01-16 13:00:00 | 2026-01-16 21:55:00 | long | 25650.43 | 25614.728677 | stop | 1.46 | -52.07 | No | 1.5 | bull |
| 60 | 2026-01-16 13:25:00 | 2026-01-16 21:55:00 | long | 25656.78 | 25614.728677 | stop | 0.97 | -40.89 | No | 1.0 | bull |
| 61 | 2026-01-16 14:30:00 | 2026-01-16 21:55:00 | long | 25655.25 | 25614.728677 | stop | 1.17 | -47.28 | No | 1.0 | bull |
| 62 | 2026-01-22 15:00:00 | 2026-01-22 21:45:00 | long | 25468.65 | 25436.859759 | stop | 1.08 | -34.33 | No | 1.5 | bull |
| 63 | 2026-01-22 15:20:00 | 2026-01-22 21:45:00 | long | 25499.35 | 25436.859759 | stop | 0.72 | -44.98 | No | 1.0 | bull |
| 64 | 2026-01-22 15:40:00 | 2026-01-22 21:45:00 | long | 25524.15 | 25436.859759 | stop | 0.72 | -62.83 | No | 1.0 | bull |
| 65 | 2026-01-30 13:00:00 | 2026-01-30 18:30:00 | short | 25695.05 | 25702.493197 | stop | 0.43 | -3.21 | No | 1.5 | bull |
| 66 | 2026-01-30 13:20:00 | 2026-01-30 18:30:00 | short | 25668.75 | 25702.493197 | stop | 0.29 | -9.71 | No | 1.0 | bull |
| 67 | 2026-01-30 13:40:00 | 2026-01-30 18:30:00 | short | 25666.75 | 25702.493197 | stop | 0.29 | -10.29 | No | 1.0 | bull |
| 68 | 2026-01-30 19:30:00 | 2026-01-30 23:20:00 | long | 25749.85 | 25634.283230 | stop | 0.86 | -99.06 | No | 1.5 | bull |
| 69 | 2026-01-30 19:50:00 | 2026-01-31 00:00:00 | short | 25711.15 | 25598.730000 | eod | 0.29 | 32.12 | Yes | 1.0 | bull |
| 70 | 2026-01-30 20:20:00 | 2026-01-31 00:00:00 | short | 25723.15 | 25598.730000 | eod | 0.43 | 53.32 | Yes | 1.5 | bull |

## Notes
- The first trade in this period is on 2025-12-05 20:00:00, so there were no Python FTMO entries on Dec 1-4.
- This report is built from the fresh Python FTMO trade export used in the latest US100 comparison.
- If you want the raw CSV version of this report, it is the source file above.
