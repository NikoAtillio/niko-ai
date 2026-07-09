# US100 Cash/Vantage High-Risk 696k Lock Pack

Created: 2026-07-07
Bundle folder: `saved_runs/2026-07-07_155407_us100_cash_vantage_highrisk_696k_lock`

## What This Preserves
- Exact MT5 report exported from the successful rerun.
- Exact Python generator, MQL5 bridge source, compiled EX5, and signal stream used for parity.
- MT5 runtime signal snapshot from Common Files.
- MT5 tester config and `.set` file snapshot.
- Git branch/commit/status context from the repo at archive time.

## Key Identity Values
- Python (`repo_files/phantom_US100_high_ftmo_EA_v2.py`) SHA256: `c31794350c2d85407203f013b792b005eb81954d1205d60ae491a6bc08003273`
- MQL5 (`repo_files/PhantomBridge_v2.mq5`) SHA256: `2903c1691198849482868a0c4040e24bd83bcc16d2ead2384b8dd2af5a4262c6`
- Signal repo (`repo_files/phantom_signals_a3c0f7e_10676.jsonl`) SHA256: `df690eb6308916ec0f18bb3e196783a21108b6b97c5a59f04272860b5824770f`
- Signal runtime (`mt5_runtime/phantom_signals_common_runtime.jsonl`) SHA256: `df690eb6308916ec0f18bb3e196783a21108b6b97c5a59f04272860b5824770f`
- Signal line count: `10676` (repo and runtime)
- EX5 (`mt5_runtime/PhantomBridge_v2.ex5`) SHA256: `1be762055f1d7575ed7a95950c1cca298745c2606695044359bee381079b0b0e`
- Main report (`outputs/ReportTester-PhantomBridgeHigh.html`) SHA256: `8900e4594317bb4b17428395fbc0b0d8520eb128b89bf3cd9522fc5b25dbefa5`

## Git Provenance Snapshot
- Branch: `v5-tester`
- Commit: `0fa63cfa3e2a2d829e8557f85c70b30f59cab80d`
- Full status snapshot: `GIT_STATUS_SHORT.txt`

## Folder Contents
- `repo_files/`
	- `phantom_US100_high_ftmo_EA_v2.py`
	- `PhantomBridge_v2.mq5`
	- `phantom_signals_a3c0f7e_10676.jsonl`
- `mt5_runtime/`
	- `PhantomBridge_v2.ex5`
	- `phantom_signals_common_runtime.jsonl`
	- `tester.ini` (UTF-16 from MT5)
	- `tester.ini.utf8.txt` (readable copy)
	- `copilot_parity_on.set`
- `outputs/`
	- `ReportTester-PhantomBridgeHigh.html`
	- `ReportTester-PhantomBridgeHigh.png`
	- `ReportTester-PhantomBridgeHigh-holding.png`
	- `ReportTester-PhantomBridgeHigh-hst.png`
	- `ReportTester-PhantomBridgeHigh-mfemae.png`
- `SHA256SUMS.txt`
- `GIT_BRANCH.txt`
- `GIT_COMMIT.txt`
- `GIT_STATUS_SHORT.txt`

## Rerun Procedure (High-Risk Reference)
1. Use `repo_files/phantom_US100_high_ftmo_EA_v2.py` as the generator reference.
2. Compile `repo_files/PhantomBridge_v2.mq5` and ensure resulting EX5 hash matches this bundle (or use bundled `mt5_runtime/PhantomBridge_v2.ex5`).
3. Copy `repo_files/phantom_signals_a3c0f7e_10676.jsonl` to MT5 Common Files as `phantom_signals.jsonl`.
4. Confirm runtime signal hash equals `df690eb6308916ec0f18bb3e196783a21108b6b97c5a59f04272860b5824770f`.
5. Load the corresponding tester settings (`copilot_parity_on.set` plus any UI parameters used in the successful run) and export a new report for comparison.

## Important Note
`tester.ini` is archived as runtime evidence only. MT5 can keep UI-selected tester settings that do not always mirror this file at export time, so treat the report and tuple hashes as the primary source of truth.
