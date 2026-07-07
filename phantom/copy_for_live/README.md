# copy_for_live

Purpose: immutable, run-labeled bundles for live deployment and reruns.

Signal naming convention (required):
- phantom_signals_<profile>_<instrument>_<result_or_tag>_<YYYY-MM-DD>_<engine>_<event_count>.jsonl

Examples:
- phantom_signals_high_risk_US100_696k_2026-07-07_p2_ftmo_v2_10676.jsonl
- phantom_signals_high_risk_US100_v5fund_trial_2026-07-07_phantom_us100_v5_fund_XXXXX.jsonl

Rules:
1. Never run MT5 from a generic signals/phantom_signals.jsonl without first copying a run-labeled file into place.
2. Keep signal + python + mql together in one profile folder.
3. Always write SHA256SUMS.txt after creating a bundle.
4. Preserve the signal meta header line (engine, instrument, account size) for provenance.
