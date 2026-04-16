import pandas as pd
from pathlib import Path

START_CAP = 5000.0

branches = {
    'p2_filter_test1': Path('/Users/niko/Documents/projects/niko-ai/backtest_artifacts/phantom-p2-fixed-20260415_181252'),
    'p2_filter_test2': Path('/Users/niko/Documents/projects/niko-ai/backtest_artifacts/phantom-p2-fixed-20260416_164644'),
    'p2_filter_test3': Path('/Users/niko/Documents/projects/niko-ai/backtest_artifacts/phantom-p2-fixed-20260416_174332'),
}

us100_comp = Path('/Users/niko/Documents/projects/niko-ai/backtest_artifacts/branch-competition-us100-20260416')

instruments = ['BTC', 'XAU', 'US100']
scenarios = ['A', 'B', 'C']


def metrics(csv_path: Path):
    df = pd.read_csv(csv_path)
    trades = len(df)
    wr = float(df['win'].mean() * 100)
    wins = df[df['win']]['pnl'].sum()
    losses = df[~df['win']]['pnl'].sum()
    pf = abs(wins / losses) if losses != 0 else float('inf')
    ret = float(df['pnl'].sum() / START_CAP * 100)
    eq = START_CAP + df['pnl'].cumsum()
    peak = eq.cummax()
    dd = float(((eq - peak) / peak).min() * 100)
    return dict(trades=trades, wr=wr, pf=pf, ret=ret, dd=dd)


rows = []

for br, root in branches.items():
    for inst in ['BTC', 'XAU']:
        for sc in scenarios:
            csv = root / f'{inst}_P2{sc}' / f'phantom_p2_trades_{inst}_P2{sc}.csv'
            if csv.exists():
                m = metrics(csv)
                rows.append(dict(branch=br, mode='full', instrument=inst, scenario=f'P2{sc}', **m))

for br in branches:
    for mode in ['full', 'policy']:
        for sc in scenarios:
            csv = us100_comp / mode / br / f'US100_P2{sc}' / f'phantom_p2_trades_US100_P2{sc}.csv'
            if csv.exists():
                m = metrics(csv)
                rows.append(dict(branch=br, mode=mode, instrument='US100', scenario=f'P2{sc}', **m))

# Fallback: if US100 full is missing from competition folder, use branch baseline artifact.
for br, root in branches.items():
    for sc in scenarios:
        already = any(
            r['branch'] == br and r['mode'] == 'full' and r['instrument'] == 'US100' and r['scenario'] == f'P2{sc}'
            for r in rows
        )
        if already:
            continue
        csv = root / f'US100_P2{sc}' / f'phantom_p2_trades_US100_P2{sc}.csv'
        if csv.exists():
            m = metrics(csv)
            rows.append(dict(branch=br, mode='full', instrument='US100', scenario=f'P2{sc}', **m))

# Fallback: if US100 policy is missing from competition folder, use branch artifact
# (branch3 matrix was executed with policy-style US100 start date).
for br, root in branches.items():
    for sc in scenarios:
        already = any(
            r['branch'] == br and r['mode'] == 'policy' and r['instrument'] == 'US100' and r['scenario'] == f'P2{sc}'
            for r in rows
        )
        if already:
            continue
        csv = root / f'US100_P2{sc}' / f'phantom_p2_trades_US100_P2{sc}.csv'
        if csv.exists():
            m = metrics(csv)
            rows.append(dict(branch=br, mode='policy', instrument='US100', scenario=f'P2{sc}', **m))

out = pd.DataFrame(rows)
if out.empty:
    raise SystemExit('No rows found')

# Rank helpers

def rank_block(df: pd.DataFrame):
    # composite score: maximize ret/wr/pf, minimize |dd|
    t = df.copy()
    t['dd_abs'] = t['dd'].abs()
    t['rank_ret'] = t['ret'].rank(ascending=False, method='min')
    t['rank_wr'] = t['wr'].rank(ascending=False, method='min')
    t['rank_pf'] = t['pf'].rank(ascending=False, method='min')
    t['rank_dd'] = t['dd_abs'].rank(ascending=True, method='min')
    t['composite'] = t[['rank_ret', 'rank_wr', 'rank_pf', 'rank_dd']].mean(axis=1)
    return t.sort_values(['composite', 'rank_dd', 'rank_pf', 'rank_wr', 'rank_ret'])

print('=== RAW RESULTS ===')
print(out.sort_values(['mode','instrument','scenario','branch']).to_string(index=False))

print('\n=== WINNERS BY INSTRUMENT/SCENARIO (FULL) ===')
full = out[out['mode'] == 'full']
for (inst, sc), g in full.groupby(['instrument', 'scenario']):
    r = rank_block(g).iloc[0]
    print(f'{inst} {sc}: {r.branch} | WR={r.wr:.1f}% PF={r.pf:.3f} DD={r.dd:.2f}% RET={r.ret:.2f}%')

print('\n=== WINNERS BY INSTRUMENT/SCENARIO (POLICY US100) ===')
pol = out[(out['mode'] == 'policy') & (out['instrument'] == 'US100')]
for sc, g in pol.groupby('scenario'):
    r = rank_block(g).iloc[0]
    print(f'US100 {sc}: {r.branch} | WR={r.wr:.1f}% PF={r.pf:.3f} DD={r.dd:.2f}% RET={r.ret:.2f}%')

print('\n=== BEST OVERALL BRANCH (FULL, all available instruments/scenarios) ===')
if not full.empty:
    agg = full.groupby('branch').agg(
        avg_wr=('wr','mean'),
        avg_pf=('pf','mean'),
        avg_ret=('ret','mean'),
        avg_dd=('dd',lambda s: s.abs().mean())
    ).reset_index()
    agg['rank'] = (
        agg['avg_wr'].rank(ascending=False, method='min') +
        agg['avg_pf'].rank(ascending=False, method='min') +
        agg['avg_ret'].rank(ascending=False, method='min') +
        agg['avg_dd'].rank(ascending=True, method='min')
    ) / 4.0
    print(agg.sort_values('rank').to_string(index=False))
