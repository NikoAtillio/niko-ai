# US100 Risk Profile Production Recommendation (2026-04-21)

This document converts the risk-profile test results into a practical production recommendation for the Phantom US100 P2B strategy.

Artifacts analyzed:
- /Users/niko/Documents/projects/niko-ai/backtest_artifacts/phantom-risk-tests-20260421_171409

Setup:
- Instrument: US100
- Scenario: P2B
- Start date: 2022-01-01
- Starting capital: £5,000

## Recommendation Summary

| Profile | Recommended Test | Why | Keep / Drop |
|---|---|---|---|
| High | Test 3 | Highest return, best PF of the high variants, uses peak-hour size expansion effectively | Keep peak-hour boost and larger cap; drop anything that does not change sizing |
| Low | Test 2 | Best balance of reduced drawdown and less trade suppression than test 3 | Keep lower size and stricter confidence; avoid over-tight exposure caps unless you want maximum safety |

## Full Comparison

| Test | Profile | Trades | Win % | PF | Net Return % | Max DD % | Monthly Positive % | Net PnL (£) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | Median | 1,771 | 56.01% | 2.653 | 1,240.59% | -3.25% | 98.04% | £62,029.31 |
| 1 | High | 1,771 | 56.01% | 2.526 | 16,571.92% | -6.43% | 96.08% | £828,595.95 |
| 1 | Low | 1,771 | 56.01% | 2.764 | 269.66% | -1.64% | 98.04% | £13,483.11 |
| 2 | Median | 1,771 | 56.01% | 2.653 | 1,240.59% | -3.25% | 98.04% | £62,029.31 |
| 2 | High | 1,771 | 56.01% | 2.853 | 7,806.13% | -6.43% | 98.04% | £390,306.42 |
| 2 | Low | 1,771 | 56.01% | 2.760 | 147.50% | -1.33% | 98.04% | £7,375.09 |
| 3 | Median | 1,771 | 56.01% | 2.653 | 1,240.59% | -3.25% | 98.04% | £62,029.31 |
| 3 | High | 1,771 | 56.01% | 2.867 | 10,051.94% | -7.43% | 98.04% | £502,596.78 |
| 3 | Low | 1,374 | 55.90% | 2.727 | 101.10% | -0.96% | 96.08% | £5,055.17 |

## Rule-Level Conclusion

| Rule | High Side | Low Side | Verdict |
|---|---|---|---|
| Base position sizing increase | Major positive effect | Major negative effect on return, positive effect on drawdown | Keep as core lever |
| Peak-hour session boost | Positive effect on high returns | Not used in low | Keep for high |
| Qty cap / exposure cap | Safety control only | Safety control only | Keep only if you want to limit tail risk |
| Stricter confidence sizing | Not the main driver of high returns | Helps reduce drawdown but cuts return | Keep for low, optional for high |

## Why Test 3 High Wins

Test 3 high outperforms test 2 high because it increases size more often and more aggressively in the hours where the strategy already produces the most PnL.

| Measure | Test 2 High | Test 3 High | Delta |
|---|---|---:|---:|
| Mean Qty | 5.386252 | 6.887035 | +27.86% |
| Net PnL | £390,306.42 | £502,596.78 | +£112,290.36 |
| Drawdown | -6.43% | -7.43% | -1.00 pp |
| Win Rate | 56.01% | 56.01% | 0.00 pp |

That means the extra rules did not improve signal quality. They improved or reduced performance only through how much size was applied.

## Why Test 2 Low Is the Better Low Variant

Test 3 low is the safest, but it is also the most restrictive and cuts the trade count materially.

| Measure | Test 2 Low | Test 3 Low | Delta |
|---|---|---:|---:|
| Trades | 1,771 | 1,374 | -397 |
| Net PnL | £7,375.09 | £5,055.17 | -£2,319.92 |
| Drawdown | -1.33% | -0.96% | +0.37 pp |
| Win Rate | 56.01% | 55.90% | -0.12 pp |

So test 3 low is best if your primary objective is capital preservation. Test 2 low is better if you want a cleaner low-risk profile without suppressing as many trades.

## Final Production Suggestion

| Role | Suggested Variant | Rationale |
|---|---|---|
| High growth profile | Test 3 High | Best absolute return, strongest use of peak-session sizing |
| Defensive profile | Test 2 Low | Better balance of drawdown reduction and trade flow than test 3 low |

## Keep / Drop List

| Rule | Recommendation | Reason |
|---|---|---|
| Initial sizing increase | Keep | Clear positive benefit in the high profile |
| Peak-hour sizing boost | Keep for high | This is the main extra rule that improved delta on the high side |
| Qty cap expansion | Keep as a limiter only | Useful as a guardrail, not as a source of edge |
| Stricter confidence sizing | Keep for low | Helps control losses, but not a return driver |
| Exposure cap | Keep only for defensive mode | Reduces drawdown but also reduces opportunity |

## Bottom Line

- The high side is best understood as a **sizing strategy**, not a new signal strategy.
- The low side is best understood as a **risk containment strategy**, not a return-improvement strategy.
- If you want maximum returns, use **Test 3 High**.
- If you want the best low-risk compromise, use **Test 2 Low**.
