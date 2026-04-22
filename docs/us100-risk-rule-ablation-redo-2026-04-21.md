# US100 Risk Rule Ablation Redo (2026-04-21)

This is the corrected rule-level analysis requested.

Artifacts:
- /Users/niko/Documents/projects/niko-ai/backtest_artifacts/phantom-risk-ablation-20260421_191931

Setup:
- Instrument: US100
- Scenario: P2B
- Start date: 2022-01-01
- Start capital: £5,000

## Variant Map (Rule Isolation)

### High
- High T1: position sizing only (risk multiplier 2.0)
- High T2: T1 + qty cap 8
- High T3: T1 + qty cap 10 + peak session boost
- High T4: T1 + qty cap 10 only
- High T5: T1 + peak session boost only (no qty cap)

### Low
- Low T1: position sizing only (risk multiplier 0.5)
- Low T2: T1 + strict confidence profile
- Low T3: T2 + exposure caps
- Low T4: T1 + exposure caps only

## Full Results

| Profile | Test | Trades | Win % | PF | Net Return % | Max DD % | Monthly Positive % | Net PnL (£) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Median | Base | 1771 | 56.01% | 2.653 | 1240.59% | -3.25% | 98.04% | 62029.31 |
| High | T1 | 1771 | 56.01% | 2.526 | 16571.92% | -6.43% | 96.08% | 828595.95 |
| High | T2 | 1771 | 56.01% | 2.853 | 7806.13% | -6.43% | 98.04% | 390306.42 |
| High | T3 | 1771 | 56.01% | 2.867 | 10051.94% | -7.43% | 98.04% | 502596.78 |
| High | T4 | 1771 | 56.01% | 2.848 | 9118.91% | -6.43% | 98.04% | 455945.36 |
| High | T5 | 1771 | 56.01% | 2.528 | 27100.43% | -7.50% | 96.08% | 1355021.25 |
| Low | T1 | 1771 | 56.01% | 2.764 | 269.66% | -1.64% | 98.04% | 13483.11 |
| Low | T2 | 1771 | 56.01% | 2.760 | 147.50% | -1.33% | 98.04% | 7375.09 |
| Low | T3 | 1374 | 55.90% | 2.727 | 101.10% | -0.96% | 96.08% | 5055.17 |
| Low | T4 | 1374 | 55.90% | 2.740 | 189.24% | -1.34% | 100.00% | 9461.96 |

## Rule Contribution Analysis

### High side

| Comparison | Isolated Rule Change | Return Delta | DD Delta | Verdict |
|---|---|---:|---:|---|
| T2 vs T1 | Add qty cap 8 | -8765.79 pp | +0.00 pp | Negative for return |
| T4 vs T1 | Add qty cap 10 | -7453.01 pp | +0.00 pp | Negative for return |
| T3 vs T4 | Add peak boost under cap10 | +933.03 pp | -1.00 pp | Positive for return, higher DD |
| T5 vs T1 | Add peak boost without cap | +10528.51 pp | -1.07 pp | Strong positive return impact |

High conclusion:
- You were correct: the negative element was the qty cap layer.
- The positive extra element was the peak session boost.
- Best combined outcome is T5, which is exactly Test1 + positive part of Test3 (peak boost) without the negative cap.

### Low side

| Comparison | Isolated Rule Change | Return Delta | DD Delta | Verdict |
|---|---|---:|---:|---|
| T2 vs T1 | Add strict confidence only | -122.16 pp | +0.31 pp | Mostly negative for return |
| T4 vs T1 | Add exposure caps only | -80.42 pp | +0.30 pp | Better trade-off than strict confidence |
| T3 vs T4 | Add strict confidence on top of caps | -88.14 pp | +0.37 pp | Additional return drag |

Low conclusion:
- Strict confidence was the main negative return contributor.
- Exposure caps are the cleaner defensive control.
- If you want best low return: T1.
- If you want more defensive low while preserving more return than T3: T4.

## Corrected Recommendations

| Objective | Recommendation |
|---|---|
| Highest high-profile return | High T5 (size + peak boost, no cap) |
| Safer high profile | High T3 or T4 |
| Highest low-profile return | Low T1 |
| Defensive low profile with better trade-off | Low T4 |
| Maximum low safety regardless of return | Low T3 |

## Direct answer to your request

Yes. After true rule-level ablation:
- High: remove cap rules from the Test3 bundle, keep peak session sizing with the base sizing increase.
- Low: remove strict confidence if return retention is important; keep exposure caps if you want defensive behavior.

That is now configured and tested as:
- High T5
- Low T4
