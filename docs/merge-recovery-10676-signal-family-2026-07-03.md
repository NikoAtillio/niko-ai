# Merge Recovery: 10676-Event Signal Family

Date: 2026-07-03

## What Was Missing

The current branch kept the newer main replay stream at [signals/phantom_signals.jsonl](signals/phantom_signals.jsonl), which is:

- 16443 lines
- SHA-256 `ab1a6829f11f87d90405fd009d42e8b5fce2c0bc0dc56ca3a5cbce305f511756`

But MT5 bridge log evidence showed a distinct historical run family with:

- `LOAD_EVENTS;count=10676`
- first trade sizing log `lots_raw=2.5108`
- first open `lots=2.50`

That historical signal family was no longer present as an explicit artifact on the current branch.

## Source Commit

Recovered from commit `a3c0f7e2decee694e7e1530593f93d99a78f092b` on branch family `feature/us100-dd-bias-stacking`.

Recovered main signal snapshot:

- [signals/phantom_signals_a3c0f7e_10676.jsonl](signals/phantom_signals_a3c0f7e_10676.jsonl)
- 10676 lines
- SHA-256 `df690eb6308916ec0f18bb3e196783a21108b6b97c5a59f04272860b5824770f`

## Restored Artifacts

Restored into current tree from `a3c0f7e`:

- [signals/phantom_signals_a3c0f7e_10676.jsonl](signals/phantom_signals_a3c0f7e_10676.jsonl)
- [saved_runs/2026-06-16_6y_biasstack/cash/phantom_signals_cash.jsonl](saved_runs/2026-06-16_6y_biasstack/cash/phantom_signals_cash.jsonl)
- [saved_runs/2026-06-16_6y_biasstack/cash/phantom_p2_ftmo_v2_trades_US100_P2_FTMO_V2B.csv](saved_runs/2026-06-16_6y_biasstack/cash/phantom_p2_ftmo_v2_trades_US100_P2_FTMO_V2B.csv)
- [saved_runs/2026-06-16_6y_biasstack/ftmo/phantom_signals_ftmo.jsonl](saved_runs/2026-06-16_6y_biasstack/ftmo/phantom_signals_ftmo.jsonl)
- [saved_runs/2026-06-16_6y_biasstack/ftmo/phantom_p2_ftmo_v2_trades_US100_P2_FTMO_V2B.csv](saved_runs/2026-06-16_6y_biasstack/ftmo/phantom_p2_ftmo_v2_trades_US100_P2_FTMO_V2B.csv)
- [saved_runs/2026-06-16_6y_biasstack/reports/summary.txt](saved_runs/2026-06-16_6y_biasstack/reports/summary.txt)
- [saved_runs/2026-06-16_6y_biasstack_cap400/cash/phantom_signals_cash.jsonl](saved_runs/2026-06-16_6y_biasstack_cap400/cash/phantom_signals_cash.jsonl)
- [saved_runs/2026-06-16_6y_cashlev200/cash/phantom_signals_cash.jsonl](saved_runs/2026-06-16_6y_cashlev200/cash/phantom_signals_cash.jsonl)

Additional reports and companion CSVs from the same commit were also restored under those `saved_runs` directories.

## Important Distinction

This recovery restores the missing historical signal family into the repository, but it does not overwrite the current main replay stream.

- Current main stream remains [signals/phantom_signals.jsonl](signals/phantom_signals.jsonl)
- Historical recovered stream is [signals/phantom_signals_a3c0f7e_10676.jsonl](signals/phantom_signals_a3c0f7e_10676.jsonl)

If a rerun needs to target the historical 2.5-lot first-trade family, it should use the recovered `a3c0f7e` artifact explicitly rather than the current main signal file.