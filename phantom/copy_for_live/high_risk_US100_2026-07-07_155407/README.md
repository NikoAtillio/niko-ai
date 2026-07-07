# high_risk_US100_2026-07-07_155407 (696k baseline)

This folder is a frozen copy of the high-risk US100 run lineage that reproduced the 696k result.

Source commit snapshot:
- 0fa63cfa3e2a2d829e8557f85c70b30f59cab80d

Artifacts:
- signals_696k_10676.jsonl
- phantom_US100_high_ftmo_EA_v2.py
- PhantomBridge_v5.mq5
- SHA256SUMS.txt

Signal identity:
- line count: 10676
- meta engine: p2_ftmo_v2
- first line:
  {"v": 1, "action": "meta", "engine": "p2_ftmo_v2", "instrument": "US100", "signal_account_size": 10000.0, "ftmo": false, "ftmo_daily_dd_pct": 9999.0, "atr_trail_mult": 0.8}

How to use safely:
1. Copy this signal file to MT5 Common Files as phantom_signals.jsonl.
2. Compile/deploy PhantomBridge_v5.mq5.
3. Verify hashes with SHA256SUMS.txt before running.

Note:
- This is the preserved 696k tuple with v5 bridge + p2_ftmo_v2 signal lineage.
- If you generate a new tuple from phantom_us100_v5_fund.py, store it as a separate run-labeled file in this folder or a sibling profile folder.
