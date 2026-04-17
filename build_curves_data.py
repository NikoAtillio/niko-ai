import json
from pathlib import Path

import pandas as pd

root = Path('/Users/niko/Documents/projects/niko-ai')
start_capital = 10000.0


def load_curve(path, label, version, scenario, max_points=280):
    df = pd.read_csv(path)
    if 'pnl' not in df.columns:
        raise ValueError(f'No pnl column in {path}')
    pnl = pd.to_numeric(df['pnl'], errors='coerce').fillna(0.0)

    # Normalize timestamp extraction across script outputs.
    date_col = None
    for c in ('exit_time', 'exit_ts', 'xt', 'entry_time', 'entry_ts'):
        if c in df.columns:
            date_col = c
            break

    if date_col is not None:
        dt = pd.to_datetime(df[date_col], errors='coerce')
    else:
        dt = pd.Series([pd.NaT] * len(df))
    cap = start_capital + pnl.cumsum()
    n = len(cap)
    if n == 0:
        return {
            'label': label,
            'version': version,
            'scenario': scenario,
            'points': [],
            'trades': 0,
            'finalCapital': start_capital,
        }

    step = max(1, n // max_points)
    idxs = list(range(0, n, step))
    if idxs[-1] != n - 1:
        idxs.append(n - 1)

    points = []
    for i in idxs:
        dti = dt.iloc[i]
        points.append(
            {
                'trade': int(i + 1),
                'capital': round(float(cap.iloc[i]), 2),
                'date': None if pd.isna(dti) else pd.Timestamp(dti).isoformat(),
            }
        )

    valid_dates = dt.dropna()
    period_start = None if valid_dates.empty else pd.Timestamp(valid_dates.iloc[0]).isoformat()
    period_end = None if valid_dates.empty else pd.Timestamp(valid_dates.iloc[-1]).isoformat()
    return {
        'label': label,
        'version': version,
        'scenario': scenario,
        'points': points,
        'trades': int(n),
        'finalCapital': round(float(cap.iloc[-1]), 2),
        'periodStart': period_start,
        'periodEnd': period_end,
    }


data = {
    'startCapital': start_capital,
    'periods': {
        '2023-24': [],
        '2024-25': [],
        '2025-26': [],
    },
}

p23 = data['periods']['2023-24']
p23.append(load_curve(root / 'phantom/_archive/v1_runtime/phantom_v4_D_trades_23_24.csv', 'v1 D (pre-fix)', 'v1', 'D'))
p23.append(load_curve(root / 'phantom/_archive/v2_runtime/phantom_v5_1_trades_D_23_24.csv', 'v2 D', 'v2', 'D'))
p23.append(load_curve(root / 'phantom/_archive/v2_runtime/phantom_v5_1_trades_B_23_24.csv', 'v2 B', 'v2', 'B'))
p23.append(load_curve(root / 'phantom/_archive/v2_runtime/phantom_v5_1_trades_A_23_24.csv', 'v2 A', 'v2', 'A'))
p23.append(load_curve(root / 'phantom/_archive/v4/phantom_v5_1_B_trades_23_24.csv', 'v4 B (alt)', 'v4', 'B'))

p24 = data['periods']['2024-25']
p24.append(load_curve(root / 'phantom/_archive/v1_runtime/phantom_v4_D_trades_24_25.csv', 'v1 D (pre-fix)', 'v1', 'D'))
p24.append(load_curve(root / 'phantom/_archive/v2_runtime/phantom_v5_1_trades_D_24_25.csv', 'v2 D', 'v2', 'D'))
p24.append(load_curve(root / 'phantom/_archive/v2_runtime/phantom_v5_1_trades_B_24_25.csv', 'v2 B', 'v2', 'B'))
p24.append(load_curve(root / 'phantom/_archive/v2_runtime/phantom_v5_1_trades_A_24_25.csv', 'v2 A', 'v2', 'A'))
p24.append(load_curve(root / 'phantom/_archive/v4/phantom_v5_1_B_trades_24_25.csv', 'v4 B (alt)', 'v4', 'B'))

p25 = data['periods']['2025-26']
p25.append(load_curve(root / 'phantom/_archive/v1_runtime/phantom_v4_D_trades_25_26.csv', 'v1 D (pre-fix)', 'v1', 'D'))
p25.append(load_curve(root / 'phantom/_archive/v2_runtime/phantom_v5_1_trades_D_25_26.csv', 'v2 D', 'v2', 'D'))
p25.append(load_curve(root / 'phantom/_archive/v2_runtime/phantom_v5_1_trades_B_25_26.csv', 'v2 B', 'v2', 'B'))
p25.append(load_curve(root / 'phantom/_archive/v2_runtime/phantom_v5_1_trades_A_25_26.csv', 'v2 A', 'v2', 'A'))
p25.append(load_curve(root / 'phantom/_archive/v4/phantom_v5_1_B_trades_25_26.csv', 'v4 B (alt)', 'v4', 'B'))

out = root / 'public/phantom-curves.json'
out.write_text(json.dumps(data, indent=2))
print(f'Wrote {out}')
