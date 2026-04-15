#!/usr/bin/env python3
from pathlib import Path
import glob
import os
import pandas as pd
from typing import Optional

ROOT = Path('/Users/niko/Documents/projects/niko-ai')
ART = ROOT / 'backtest_artifacts'


def metrics_from_csv(path: Path, start_cap: float = 5000.0) -> dict:
    df = pd.read_csv(path)
    if df.empty:
        return {'trades': 0, 'win_rate': 0.0, 'pf': float('nan'), 'net_ret': 0.0, 'max_dd': 0.0}
    pnl = pd.to_numeric(df['pnl'], errors='coerce').fillna(0.0)
    wins = df['win'].astype(bool) if 'win' in df.columns else pd.Series([False] * len(df))
    gross_win = pnl[wins].sum()
    gross_loss = pnl[~wins].sum()
    pf = abs(gross_win / gross_loss) if gross_loss != 0 else float('inf')
    eq = start_cap + pnl.cumsum()
    peak = eq.cummax()
    max_dd = ((eq - peak) / peak).min() * 100 if len(eq) else 0.0
    return {
        'trades': int(len(df)),
        'win_rate': float(wins.mean() * 100),
        'pf': float(pf),
        'net_ret': float((pnl.sum() / start_cap) * 100),
        'max_dd': float(max_dd),
    }


def latest_dir(pattern: str) -> Optional[Path]:
    matches = sorted(glob.glob(str(ART / pattern)), key=os.path.getmtime, reverse=True)
    return Path(matches[0]) if matches else None


# latest p2 manual stamp
p2_latest_any = latest_dir('phantom-*-p2-manual-*')
if p2_latest_any is None:
    raise SystemExit('No p2 manual runs found')
parts = p2_latest_any.name.split('-')
stamp = '-'.join(parts[-2:])

rows = []
for sym, short in [('XAUUSD', 'xau'), ('US100', 'us100'), ('BTCUSD', 'btc')]:
    # p1 latest active validate folder
    p1_dir = latest_dir(f'phantom-{sym.lower()}-p1-validate-*')
    if p1_dir:
        for letter in ['A', 'B', 'C']:
            files = list(p1_dir.glob(f'*_p1_trades_P1{letter}.csv'))
            if not files:
                continue
            m = metrics_from_csv(files[0])
            rows.append({
                'instrument': sym,
                'engine': 'p1',
                'scenario': f'P1{letter}',
                **m,
                'folder': str(p1_dir),
            })

    # Prefer p2 files from the latest artifact folder for each instrument.
    p2_dir = latest_dir(f'phantom-{short}-p2-manual-*')
    key = {'xau': 'XAU', 'us100': 'US100', 'btc': 'BTC'}[short]
    for letter in ['A', 'B', 'C']:
        in_artifacts = p2_dir / f'phantom_p2_trades_{key}_P2{letter}.csv' if p2_dir else None
        in_root = ROOT / f'phantom_p2_trades_{key}_P2{letter}.csv'
        f = in_artifacts if in_artifacts and in_artifacts.exists() else in_root
        if not f.exists():
            continue
        m = metrics_from_csv(f)
        rows.append({
            'instrument': sym,
            'engine': 'p2',
            'scenario': f'P2{letter}',
            **m,
            'folder': str(p2_dir or ROOT),
        })

out = pd.DataFrame(rows).sort_values(['instrument', 'engine', 'scenario'])
out.to_csv('/tmp/p1_p2_compare.csv', index=False)
print(out.to_string(index=False, float_format=lambda x: f'{x:.3f}'))
