# POA - Phase 1 Front-End QA + High/Low Discussion Prep (2026-04-19)

## Agreed Direction
- Keep current runtime routing behavior as-is.
- Keep front-end prepared for high/low selections.
- Treat median as the effective base strategy until high/low filters are designed and approved.
- Do not implement high/low filter divergence before discussion sign-off.

## Phase 1 Objective
Validate the front end thoroughly using the current baseline behavior so we can separate UI/flow defects from future strategy-logic changes.

## Progress Against Original POA

### Phase 1 - Front-End Test Hardening (No strategy logic changes)
- [x] Keep current runtime routing behavior as-is.
- [x] Keep front-end prepared for high/low selections while median remains baseline.
- [x] Core tab/page loading validated for Strategy Lab, Strategy Tests, Comparative Reports, My Profile, Data.
- [x] Live validation request baseline verified for all supported symbols.
- [x] Date range handling and start-date passthrough wired on Strategy Tests flow.
- [x] Comparative naming normalization verified (no legacy P1/P2/P3 labels in primary UI paths).
- [ ] Mobile rendering sanity pass still pending.
- [ ] Explicit browser-console clean sweep still pending.

### Phase 2 - Test Matrix and Runbook
- [x] Front-end checklist by tab and feature is documented.
- [x] Symbol matrix covered: XAUUSD, US100, BTCUSD, EURUSD, GBPUSD, NZDUSD, USDCHF, USDJPY, EURGBP.
- [x] Standard QA scenario baseline defined (2021-01-01, capital 5000, median).
- [x] Manual QA runbook created for repeatable execution.
- [x] Bug triage template added (below).
- [ ] Exit gate not reached yet: critical/high findings closure still open until manual console/mobile passes complete.

### Phase 3 - High/Low Discussion Pack (Pre-implementation)
- [x] Parameter proposal worksheet scaffold created for phantom_XAU, phantom_US100, phantom_BTC, phantom_fx.
- [x] Discussion guardrails captured (hypothesis-first, limited variable changes, rollback criteria).
- [ ] Parameter values and rationale still TBD pending workshop sign-off.

### Phase 4 - Controlled Experiment Plan (Post sign-off)
- [ ] Not started by design.
- [ ] Remains blocked until Phase 3 values are agreed and approved.

## Phase 1 QA Checklist

| Area | Test | Status | Evidence / Notes |
|---|---|---|---|
| Navigation | All main tabs load and can be reached from nav: Strategy Lab, Strategy Tests, Comparative Reports, My Profile, Data | Passed | Loaded successfully via app on port 3113. |
| Strategy Lab | Recognize -> Confirm -> Backtest request flow returns success and records run state | Passed | smoke-strategy-lab.js: recognize/import/confirm/backtest-request all succeeded. |
| Strategy Lab | Invalid payload returns friendly validation error (400 path) | Passed | smoke-strategy-lab.js returned expected 400 on invalid recognize payload. |
| Strategy Tests | Preloaded instrument selection works for all available symbols | In Progress | Backend validation matrix passed 9/9 symbols; direct UI click-through sweep still pending. |
| Strategy Tests | Date/capital/risk controls update modeled output without UI errors | Passed | Added `startDate` passthrough from UI validation request; endpoint checks for risk/capital/startDate all returned 200. |
| Strategy Tests | Strategy selector can be changed (even if output currently equivalent) without breaking flow | In Progress | High/median/low requests all returned 200 with stable strategy output (median baseline). |
| Comparative Reports | Report list loads and tabs render (Overview/Growth/Monthly/Drawdown/Comparison) | Passed | Page and report sections loaded; comparison content rendered. |
| Comparative Reports | Normalized naming displays correctly (no legacy Phantom P1/P2/P3 labels) | Passed | Visible labels normalized to Phantom Median Strategy + Variant naming. |
| My Profile | Saved runs table, filters, and exports are reachable and responsive | In Progress | Page/table render confirmed; export endpoints return 200 (CSV/JSON); manual filter click sweep still pending. |
| Data | Page loads and all static sections render without errors | Passed | Data page sections render correctly on load. |
| API Integration | Validation endpoint works for all known symbols from 2021-01-01 with capital 5000 | Passed | 9/9 symbols OK (XAUUSD, US100, BTCUSD, EURUSD, GBPUSD, NZDUSD, USDCHF, USDJPY, EURGBP). |
| Browser Stability | No blocking runtime errors in console during core flows | In Progress | Functional flows pass, but explicit browser console capture via interactive devtools is still pending. |

## Phase 1 Execution Notes
- Standard validation baseline for this phase:
  - startDate: 2021-01-01
  - capital: 5000
  - riskProfile: median
- Initial execution log:
  - App server booted on port 3113.
  - Strategy Lab smoke script passed all happy-path endpoints and one expected 400 invalid case.
  - All main tabs loaded successfully via browser fetch.
  - Validation matrix completed 9/9 symbols successfully at baseline settings.
  - Profile exports verified: `/platform/admin/export/runs.csv` and `/platform/admin/export/runs.json` both 200.
  - Strategy control variation check verified successful responses for risk/capital/startDate variations.
  - Strategy Tests UI wiring fix applied so selected `From Date` now passes to `/platform/phantom-v2/validate` as `startDate`.

## Automated Verification Snapshot (2026-04-20)
- Server on port 3113 confirmed active during checks.
- Core page route health checks all returned HTTP 200:
  - /strategy-test.html
  - /comparative-reports.html
  - /profile.html
  - /data.html
  - /strategy-lab.html
- Profile export endpoint checks returned HTTP 200:
  - /platform/admin/export/runs.csv
  - /platform/admin/export/runs.json
- Strategy Lab smoke test passed against active port:
  - Command context: SMOKE_PORT=3113 npm run -s test:smoke
  - Key results: config/admin/recognize/import/confirm/backtest/runs/strategies all successful, invalid recognize payload returned expected 400.
- Validation matrix rerun completed 9/9 symbols at baseline (2021-01-01, capital 5000, median), all HTTP 200:
  - XAUUSD, US100, BTCUSD, EURUSD, GBPUSD, NZDUSD, USDCHF, USDJPY, EURGBP.

## Fixes Applied This Session
- Restored Comparative Reports navigation in Profile and verified Data already exposed the Comparative Reports menu item.
- Replaced placeholder per-row export actions in Profile and Lab Runs with real `/platform/runs/:id` links.
- Marked static comparative reports as selectable so they are not treated as missing data in the checklist.
- Added a fallback mode resolver in Comparative Reports so blank views can fall back to the first available mode instead of stopping at "No summary rows found for this mode.".

## High/Low Discussion Worksheet (Review Before Any Implementation)
Use this table to discuss and approve changes first. Keep one row per parameter family.

| Stem | Parameter / Filter Family | Current Median Value | Proposed Low (Conservative) | Proposed High (Aggressive) | Expected Effect | Risks / Tradeoffs | Owner | Decision |
|---|---|---|---|---|---|---|---|---|
| phantom_XAU | Score threshold | TBD | TBD | TBD | Trade frequency / quality balance | Missed moves vs overtrading | | Pending |
| phantom_XAU | Session window | TBD | TBD | TBD | Lower noise vs fewer opportunities | Time-based bias | | Pending |
| phantom_XAU | Confirmation bars | TBD | TBD | TBD | Signal quality | Late entries | | Pending |
| phantom_XAU | ATR stop multiplier | TBD | TBD | TBD | DD profile / stopout rate | Stop too wide/narrow | | Pending |
| phantom_XAU | TP multiple | TBD | TBD | TBD | Win rate vs payoff ratio | Lower PF if mis-set | | Pending |
| phantom_US100 | Score threshold | TBD | TBD | TBD | Trade frequency / quality balance | Missed moves vs overtrading | | Pending |
| phantom_US100 | Session window | TBD | TBD | TBD | Lower noise vs fewer opportunities | Time-based bias | | Pending |
| phantom_US100 | Confirmation bars | TBD | TBD | TBD | Signal quality | Late entries | | Pending |
| phantom_US100 | ATR stop multiplier | TBD | TBD | TBD | DD profile / stopout rate | Stop too wide/narrow | | Pending |
| phantom_US100 | TP multiple | TBD | TBD | TBD | Win rate vs payoff ratio | Lower PF if mis-set | | Pending |
| phantom_BTC | Score threshold | TBD | TBD | TBD | Trade frequency / quality balance | Missed moves vs overtrading | | Pending |
| phantom_BTC | Session / weekend policy | TBD | TBD | TBD | Volatility capture / risk containment | Weekend gap exposure | | Pending |
| phantom_BTC | Confirmation bars | TBD | TBD | TBD | Signal quality | Late entries | | Pending |
| phantom_BTC | ATR stop multiplier | TBD | TBD | TBD | DD profile / stopout rate | Stop too wide/narrow | | Pending |
| phantom_BTC | TP multiple | TBD | TBD | TBD | Win rate vs payoff ratio | Lower PF if mis-set | | Pending |
| phantom_fx | Score threshold | TBD | TBD | TBD | Trade frequency / quality balance | Missed moves vs overtrading | | Pending |
| phantom_fx | Session window | TBD | TBD | TBD | Lower noise vs fewer opportunities | Session mismatch by pair | | Pending |
| phantom_fx | Confirmation bars | TBD | TBD | TBD | Signal quality | Late entries | | Pending |
| phantom_fx | ATR stop multiplier | TBD | TBD | TBD | DD profile / stopout rate | Stop too wide/narrow | | Pending |
| phantom_fx | TP multiple | TBD | TBD | TBD | Win rate vs payoff ratio | Lower PF if mis-set | | Pending |

## Discussion Guardrails
- No high/low code implementation until worksheet rows are reviewed and marked Approved.
- Change one to two parameter families per experiment batch only.
- Define expected KPI movement before each trial (return, PF, DD, trade count).
- Keep rollback criteria explicit before each test run.

## Phase 1 Manual QA Runbook (User Execution)

### Preconditions
- App server running on port 3113.
- Use one browser profile/session for all checks.
- Keep browser devtools open on Console tab for the full run.

### Test A - Strategy Tests: Instrument + Risk Selector Stability
1. Open `/strategy-test.html`.
2. Confirm page renders Strategy Results and Recommended Strategy sections.
3. Run three passes with the same symbol but different risk profile selections:
  - median
  - high
  - low
4. For each pass, click Validate/Run (same action used in your current workflow).
5. Confirm each pass completes and no UI freeze or blocking error appears.

Expected:
- All three runs complete.
- No hard error banner.
- No uncaught exception in browser console.

### Test B - Strategy Tests: Date + Capital + Risk Controls
1. Stay on `/strategy-test.html`.
2. Set From Date to `2021-01-01`.
3. Set To Date to a valid later date.
4. Set Starting Capital to `5000` and run once.
5. Change Starting Capital to `8000` and run once.
6. Change Starting Capital to `12000` and run once.
7. Set Risk Multiplier to three values (for example `0.8`, `1.0`, `1.2`) and run each.

Expected:
- Every run request completes.
- Results area refreshes each time.
- No blocking console error during control changes or run completion.

### Test C - My Profile: Filters + Reset + Exports
1. Open `/profile.html`.
2. In Saved Runs:
  - Change Market filter from All Markets to a specific market.
  - Enter a strategy keyword in Strategy filter.
  - Set From and To date filters.
  - Set Return >= filter.
3. Confirm row count and table rows update after each change.
4. Click Reset.
5. Confirm filters return to default and table repopulates.
6. Click Download Runs CSV and Download Runs JSON.

Expected:
- Filters are responsive and deterministic.
- Reset restores baseline view.
- Both export downloads succeed without error page.
- No blocking console error.

### Test D - Comparative Reports: Rendering + Naming
1. Open `/comparative-reports.html`.
2. Open each tab/section available in the page (Overview, Growth, Monthly, Drawdown, Comparison).
3. Confirm report labels use normalized naming and do not show legacy P1/P2/P3 naming.

Expected:
- All sections render and are navigable.
- Naming remains normalized.
- No blocking console error.

### Test E - Browser Console Stability Sweep
1. With devtools Console open, repeat one full happy-path cycle:
  - Strategy Tests run
  - Comparative Reports tab switching
  - My Profile filter and export actions
2. Capture any red error lines exactly as shown.

Expected:
- No uncaught runtime exception that blocks feature usage.
- Warnings are acceptable if non-blocking and known.

### Evidence Log Template

| Test ID | Result (Pass/Fail) | Evidence (short) | Console Errors (if any) |
|---|---|---|---|
| A | In Progress | Automated backend baseline: 9/9 symbol validate calls returned 200; Strategy selector UI click-through still pending manual pass. | Not captured yet (manual devtools run pending). |
| B | In Progress | Automated baseline confirms validate endpoint healthy at required QA defaults; manual date/capital/risk control interaction still pending. | Not captured yet (manual devtools run pending). |
| C | In Progress | Export endpoints CSV/JSON returned 200 in this session; filter/reset interaction remains manual pending. | Not captured yet (manual devtools run pending). |
| D | In Progress | Comparative Reports route returns 200 and prior naming normalization checks remain valid; per-tab manual rendering sweep still pending. | Not captured yet (manual devtools run pending). |
| E | In Progress | Functional automation passed (smoke + route + matrix), but explicit browser console sweep not executed yet. | Pending capture. |

### Bug Triage Template

| Field | Value |
|---|---|
| Severity | Critical / High / Medium / Low |
| Reproducibility | Always / Intermittent / Once |
| Tab or Page | strategy-test / strategy-lab / comparative-reports / profile / data |
| Request Payload | Request body or query used at failure time |
| Expected Behavior | What should have happened |
| Actual Behavior | What happened instead |
| Evidence | Screenshot path + console excerpt + timestamp |
| Owner | Assignee |
| Target Fix Date | YYYY-MM-DD |

### Failure Handling
- If any test fails, record exact UI step, timestamp, and visible error text.
- If console shows stack traces, copy the first error line and top frame path.
- Do not change code yet; collect all failures first, then patch in one focused fix pass.

## Next Steps To Continue Now
1. Re-test Strategy Tests with median-only instrument runs and record the high/low limitation as an expected constraint.
2. Re-test My Profile navigation plus row export/download actions and confirm Comparative Reports remains visible.
3. Re-test Comparative Reports with the static report sets and verify Growth/Monthly/Drawdown populate from full/policy modes.
4. Run the browser-console sweep again after those UI checks.
5. Run the mobile viewport sanity pass on Strategy Tests, Comparative Reports, and Profile.
6. Close Phase 1 with explicit pass/fail entries in Evidence Log Template, then move to Phase 3 parameter workshop.
