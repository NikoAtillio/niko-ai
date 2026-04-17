# Strategy Consolidation Plan (2026-04-16)

## Scope
- Data source: latest trade CSV for each instrument and strategy variant found under `backtest_artifacts`.
- Dashboard fallback included: `dashboard_data_phantom_p*.json` branch summaries (used where variant CSV naming/availability differs, notably `P3`).
- Variants compared per instrument: `P1A`, `P1B`, `P1C`, `P2A`, `P2B`, `P2C`, plus branch-level `P1/P2/P3` summaries where available.
- Return model assumption: baseline capital = GBP 10,000.
- Metrics used:
  - Net PnL and Return %
  - Max Drawdown (currency)
  - Profit Factor
  - Efficiency score = Net PnL / Max Drawdown

Full raw output: `docs/strategy-instrument-analysis-2026-04-16.txt`

## Earmarked Core Strategy Per Instrument
Core strategy is chosen by best return/drawdown efficiency (not merely highest return):

- BTCUSD: `P2C` (best efficiency, strong return, controlled DD)
- US100: `P3` (highest return, highest net PnL, and best return/DD efficiency in branch-comparison dashboard)
- XAUUSD: `P2C` (best efficiency, strong return, controlled DD)
- EURUSD: `P1C` (best efficiency vs P1A/P1B)
- GBPUSD: `P1C` (best efficiency vs P1A/P1B)
- NZDUSD: `P1C` (best efficiency vs P1A/P1B)
- USDCHF: `P1C` (best efficiency vs P1A/P1B)
- USDJPY: `P1C` (best efficiency vs P1A/P1B)

## Risk Profile Variants Per Instrument
Use one core strategy with three risk profiles:

- Conservative profile: `A` variant (lowest drawdown)
- Balanced profile: `C` variant (best return/DD efficiency)
- Aggressive profile: `B` variant (highest return / highest PnL)

Practical mapping:
- For BTCUSD/XAUUSD, use `P2A/P2C/P2B`.
- For US100, keep `P2A/P2C/P2B` as operational risk-profile presets until full `P3A/P3B/P3C` artifact parity is published; use `P3` as default strategy family in Strategy Tests.
- For EURUSD/GBPUSD/NZDUSD/USDCHF/USDJPY, use `P1A/P1C/P1B`.

## Observations
- FX instruments currently show identical outcomes between `P1*` and `P2*` in the latest artifacts, suggesting no meaningful regime split for those datasets yet.
- BTCUSD/US100/XAUUSD show clear performance separation where `P2*` dominates.
- US100 branch-level comparative dashboard now shows `P3` outperforming `P2` and `P1` on return and return/DD efficiency across the full window.
- `B` variants deliver the highest returns but materially larger drawdowns.

## Branch Cleanup Status
- Deleted merged local branches:
  - `p2_filter_test1`
  - `p2_filter_test2`
- Retained local `p2_filter_test3` because it is ahead of its remote branch by one commit and not considered fully merged relative to upstream tracking.

## File Cleanup Priorities (Storage)
Largest folders currently:
- `uploads` ~ 1.3G
- `node_modules` ~ 849M
- `backtest_artifacts` ~ 244M
- `backtest_artifacts_archive` ~ 223M
- `_docs_archive` ~ 109M
- `backtest_artifacts_legacy` ~ 52M

Recommended cleanup order:
1. Prune old datasets in `uploads` not used by active runs.
2. Remove/regenerate `node_modules` when needed (`npm ci`).
3. Keep only latest run per instrument/variant in `backtest_artifacts`; move the rest to archive storage.
4. Compress or externalize `_docs_archive` and legacy artifacts.

## Next Operational Step
- Promote the selected per-instrument cores into runtime defaults:
  - BTCUSD/XAUUSD -> `P2C`
  - US100 -> `P3`
  - EURUSD/GBPUSD/NZDUSD/USDCHF/USDJPY -> `P1C`
- Expose risk profile selector with `Conservative(A) / Balanced(C) / Aggressive(B)` mapped to the same chosen strategy family.
