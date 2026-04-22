# US100 Risk Rule Decomposition (2026-04-21)

This note answers which added rules actually improved the high/low variants versus the median US100 P2B baseline.

Artifacts analyzed:
- /Users/niko/Documents/projects/niko-ai/backtest_artifacts/phantom-risk-tests-20260421_171409

Setup:
- Instrument: US100
- Scenario: P2B
- Start date: 2022-01-01
- Start capital: £5,000

## High Profile: Test 2 vs Test 3

| Metric | Test 2 High | Test 3 High | Delta |
|---|---:|---:|---:|
| Trades | 1,771 | 1,771 | 0 |
| Win Rate | 56.01% | 56.01% | 0.00 pp |
| Profit Factor | 2.853 | 2.867 | +0.014 |
| Net PnL | £390,306.42 | £502,596.78 | +£112,290.36 |
| Net Return | 7,806.13% | 10,051.94% | +2,245.81 pp |
| Max Drawdown | -6.43% | -7.43% | -1.00 pp |
| Mean Qty | 5.386252 | 6.887035 | +27.86% |

### High-side rule interpretation

| Added rule | Effect | Verdict |
|---|---|---|
| Higher qty cap | Lets larger trades through when sizing is already elevated | Supportive, but not the source of edge |
| Peak session boost | Raises size during 14:00-17:00 UTC, where PnL concentration is highest | Positive contributor |
| Same base risk multiplier | Present in both test 2 and test 3 | Not a differentiator between the two |

### High-side conclusion

The improvement from test 2 high to test 3 high is driven by **more aggressive sizing in peak hours**. The qty cap does not create edge; it only prevents runaway size. The trade quality itself did not improve because win rate stayed identical.

## Low Profile: Test 2 vs Test 3

| Metric | Test 2 Low | Test 3 Low | Delta |
|---|---:|---:|---:|
| Trades | 1,771 | 1,374 | -397 |
| Win Rate | 56.01% | 55.90% | -0.12 pp |
| Profit Factor | 2.760 | 2.727 | -0.033 |
| Net PnL | £7,375.09 | £5,055.17 | -£2,319.92 |
| Net Return | 147.50% | 101.10% | -46.40 pp |
| Max Drawdown | -1.33% | -0.96% | +0.37 pp |
| Mean Qty | 0.118170 | 0.105743 | -10.52% |

### Low-side rule interpretation

| Added rule | Effect | Verdict |
|---|---|---|
| Stricter confidence sizing | Reduces size unless score quality is stronger | Risk-reducing, but not a return driver |
| Exposure cap | Reduces concurrent risk and trade count | Helps drawdown, hurts total return |
| Same base risk multiplier | Present in both test 2 and test 3 | Not a differentiator between the two |

### Low-side conclusion

Test 3 low is safer, but it does **not** improve absolute return. The extra rules mainly lower exposure and cut trade count. That is why return falls even though drawdown improves.

## Bottom Line

| Profile | Rule That Helped Most | Rule That Did Not Improve Delta |
|---|---|---|
| High | Peak-session sizing boost | Qty cap only constrained risk; it did not add edge |
| Low | None on return; only risk control improved | Exposure cap and stricter confidence reduced return |

## Answer to the main question

Yes, your interpretation is basically correct:

- The high profile’s gain comes primarily from **larger sizing**, especially during peak hours.
- The extra rules in test 3 high did **not** improve trade quality; they only changed how much size got applied to already-good trades.
- On the low side, the extra rules improved **safety** more than performance. They reduced drawdown, but they did not improve return.

So if the goal is maximizing delta versus median, the only rule that clearly helped is the **peak-hour sizing increase** on the high side. For low, the added controls are risk-management improvements, not return improvements.
