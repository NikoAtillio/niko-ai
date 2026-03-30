# PHANTOM v3.1 Backtest Report

- Symbol: XAUUSD
- Interval: 1m
- Capital: $10,000.00
- Base Risk/Trade: 0.0050
- Version: PHANTOM v3.1 (data-driven)

## v3.1 Enhancements

- H4 regime filter (blocks counter-regime trades)
- Blocked hours: [8]
- MAX_CONCURRENT: 1
- Adaptive risk: 0.35%-0.75%
- Trailing stop: 1.5R activate, 0.3R step
- Quality score min: 50
- Cooldown after stop: 15 min
- Regime-relaxed wick ratio: 0.4 (vs 0.55)
- Regime-relaxed volume mult: 1.2 (vs 1.4)

## Summary

- final_capital: $9,989.39
- total_return_pct: -0.11%
- total_trades: 9
- win_rate_pct: 66.67%
- profit_factor: 1.159853602410976
- max_drawdown_pct: -2.40%
- trades_per_day: 0.33
- total_pnl: $-10.61
- total_fees: $155.40
- expectancy: $4.58

## Skip Reasons

- outside_session: 16,699
- no_micro_trap: 9,377
- blocked_hour: 1,200
- max_concurrent: 95
- cooldown_after_stop: 45
- counter_trend_h1: 31
- volume_fail: 19
- momentum_fail: 10
- h4_regime_blocks_long: 8
- h4_regime_blocks_short: 3
