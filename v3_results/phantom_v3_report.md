# PHANTOM v3 Backtest Report

- Symbol: GC=F
- Interval: 1m
- Days: 30
- Capital: $10,000.00
- Base Risk/Trade: 0.0050
- Version: PHANTOM v3 (data-driven upgrade)

## v3 Enhancements Active

- H4 regime filter (blocks counter-regime trades)
- Blocked hours: [8, 12]
- R-value gate: 4.5–28.0
- Adaptive risk: 0.35%–0.75%
- Trailing stop: activates at 1.5R, steps 0.5R
- Quality score minimum: 60
- Cooldown after stop: 15 min

## Summary

- final_capital: $10,098.11
- total_return_pct: 0.98%
- total_trades: 8
- win_rate_pct: 62.50%
- profit_factor: 1.384490331516153
- max_drawdown_pct: -2.20%
- trades_per_day: 0.26666666666666666
- total_pnl: $98.11
- total_fees: $49.20
- expectancy: $12.26

## Skip Reasons

- outside_session: 13,345
- no_micro_trap: 6,313
- blocked_hour: 1,920
- volume_fail: 249
- momentum_fail: 71
- counter_trend_h1: 32
- cooldown_after_stop: 30
- h4_regime_bearish_blocks_long: 7
- low_quality_score: 7
