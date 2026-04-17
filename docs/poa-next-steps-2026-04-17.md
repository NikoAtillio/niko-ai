# Plan Of Action (POA) - Strategy Consolidation and Forward Build (2026-04-17)

## 1) Outcome We Want
- One clean production baseline branch.
- A clear per-instrument strategy family decision (P1 vs P2 vs P3).
- Standardized risk tiers for every active instrument:
  - Conservative (low DD)
  - Balanced (median DD/return)
  - Aggressive (higher DD/higher return)
- A repeatable process to promote new strategy versions without breaking comparability.

## 2) Current Evidence Snapshot
Source references:
- [docs/strategy-instrument-analysis-2026-04-16.txt](docs/strategy-instrument-analysis-2026-04-16.txt)
- [docs/strategy-consolidation-plan-2026-04-16.md](docs/strategy-consolidation-plan-2026-04-16.md)

Summary from latest validated artifacts:
- US100: P3 leads on return and return/DD efficiency.
- XAUUSD: P2 family is strongest overall; P2C is best efficiency.
- BTCUSD: P2 family is strongest overall; P2C is best efficiency.
- FX set (EURUSD, GBPUSD, NZDUSD, USDCHF, USDJPY): P1/P2 outcomes currently identical in latest artifacts, so keep P1 as canonical baseline family for now.

## 3) Strategy Family Decision Matrix (Keep vs Benchmark)

| Instrument | Production Family To Keep | Benchmark Family To Keep | Decision Rationale |
|---|---|---|---|
| US100 | P3 | P2 + P1 | P3 currently best performer and best efficiency in branch-level comparison. |
| XAUUSD | P2 | P1 | P2 provides stronger PF and efficiency across variants. |
| BTCUSD | P2 | P1 | P2 dominates current artifact set. |
| EURUSD | P1 | P2 (monitor only) | No practical edge shown by P2 in current results. |
| GBPUSD | P1 | P2 (monitor only) | No practical edge shown by P2 in current results. |
| NZDUSD | P1 | P2 (monitor only) | No practical edge shown by P2 in current results. |
| USDCHF | P1 | P2 (monitor only) | No practical edge shown by P2 in current results. |
| USDJPY | P1 | P2 (monitor only) | No practical edge shown by P2 in current results. |

Notes:
- This keeps P1 as the foundation benchmark across all instruments.
- P2/P3 are treated as instrument-specialized overlays where evidence supports promotion.

## 4) Risk-Tier Standard (Secondary and Tertiary Versions)

Use one naming model across all strategy families:
- Tier 1 (Conservative): A variant
- Tier 2 (Balanced): C variant
- Tier 3 (Aggressive): B variant

Implementation mapping by instrument:
- US100 (P3 family target):
  - Immediate operational set: P2A/P2C/P2B while P3 full A/C/B parity is finalized.
  - Promotion target: P3A/P3C/P3B once parity artifacts and validation are complete.
- XAUUSD (P2): P2A / P2C / P2B
- BTCUSD (P2): P2A / P2C / P2B
- FX instruments (P1): P1A / P1C / P1B

Tier acceptance thresholds (proposed):
- Conservative: maximize capital protection, lowest DD in family, PF >= 1.05.
- Balanced: highest return/DD efficiency in family, PF >= 1.10.
- Aggressive: highest net return in family, DD capped by instrument policy limit.

## 5) Branch Merge and Cleanup POA
Current branch topology:
- Local: main, p2_filter_test3
- Remote: main, p2_filter_test3, gh-pages

### Merge Sequence
1. Freeze changes on main for merge window.
2. Create integration branch from main:
   - merge/p2_filter_test3-into-main
3. Merge p2_filter_test3 into integration branch.
4. Run mandatory checks:
   - Build
   - Strategy Tests: US100 P3, BTCUSD P2, XAUUSD P2, USDJPY P1/P3 fallback path
   - Comparative Reports load + growth chart responsiveness
5. If pass, merge integration branch into main.
6. Tag baseline release:
   - baseline-consolidation-2026-04-17
7. Delete fully merged branch locally/remotely:
   - p2_filter_test3

### Keep Rules After Merge
- Keep only main and gh-pages as long-lived branches.
- Use short-lived feature branches with ticket-prefixed names.
- Archive branch-level experiment outputs under dated artifact folders, then prune active artifact root.

## 6) Codebase Cleanup POA

### A) Configuration and Labeling
Create a single strategy registry config (next implementation step) that defines:
- instrument -> production family
- family -> tier mapping (Conservative/Balanced/Aggressive)
- baseline benchmark family for comparison

Example target policy:
- US100: productionFamily=P3, baseline=P1, fallbackTierFamily=P2 until P3 parity complete
- XAUUSD: productionFamily=P2, baseline=P1
- BTCUSD: productionFamily=P2, baseline=P1
- FX: productionFamily=P1, baseline=P1

### B) Runtime Behavior
- Strategy Tests should always show:
  - selected production strategy tier result
  - baseline benchmark result (P1 family) for comparison
- For unsupported P2/P3 symbols, keep current safe fallback behavior and label it clearly in UI as execution fallback.

### C) Artifact Hygiene
- Keep latest validated run per instrument/family/tier.
- Move older runs to archive with date stamp.
- Keep dashboard summary JSON files that feed comparative ranking.

## 7) Execution Roadmap (2-Week)

Week 1:
1. Merge branch and stabilize main.
2. Implement strategy registry config and wire Strategy Tests to it.
3. Add explicit UI labels: Production Family, Tier, Baseline Family.
4. Snapshot and archive old artifacts.

Week 2:
1. Create/validate missing US100 P3 parity tiers (P3A/P3C/P3B).
2. Re-run cross-instrument validation matrix.
3. Publish updated recommendation report and lock versioned defaults.

## 8) Validation Matrix Before Sign-Off

Mandatory pass cases:
- US100:
  - P3 selected as production family
  - all enabled tiers produce curve data and recommendation output
- XAUUSD and BTCUSD:
  - P2 tiers render curves and summary correctly
- USDJPY (and one more FX pair):
  - P1 tiers produce expected output
  - P3 request path safely falls back and still returns curve + summary
- Comparative Reports:
  - chart remains responsive and equal visual footprint with Strategy Tests behavior

## 9) Definition Of Done
- Branches merged and cleaned.
- Strategy family policy committed and visible in config.
- Tier mapping active for each instrument.
- Baseline-vs-production comparison visible in Strategy Tests.
- Validation matrix passed and documented.
- Consolidation release tag created.

## 10) Immediate Next Implementation Ticket Set
1. Add strategy registry file and loader.
2. Wire registry into validation endpoint and front-end labels.
3. Add baseline-vs-production summary card to Strategy Tests.
4. Add artifact-prune script (keep latest N per instrument/family/tier).
5. Publish post-merge validation report.
