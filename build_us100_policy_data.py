from pathlib import Path
import pandas as pd

src = Path('/Users/niko/Documents/projects/niko-ai/data/US100')
out = Path('/Users/niko/Documents/projects/niko-ai/backtest_artifacts/branch-competition-us100-20260416/policy_data')
out.mkdir(parents=True, exist_ok=True)

files = [
    'US100.cash_M5_2021.01.21-2026.03.31',
    'US100.cash_M15_2021.01.21-2026.03.31',
    'US100.cash_H1_2021.01.21-2026.03.31',
    'US100.cash_H4_2021.01.21-2026.03.31',
    'US100.cash_Daily_2021.01.21-2026.03.31',
]

for fn in files:
    p = src / fn
    df = pd.read_csv(p, sep='\t', header=0)
    original_cols = list(df.columns)
    cols = [c.strip('<>').lower() for c in original_cols]
    df.columns = cols

    if 'time' in df.columns:
        dt = pd.to_datetime(df['date'].astype(str).str.strip() + ' ' + df['time'].astype(str).str.strip(), errors='coerce')
    else:
        dt = pd.to_datetime(df['date'].astype(str).str.strip(), errors='coerce')

    keep = dt >= pd.Timestamp('2022-01-01')
    out_df = df.loc[keep].copy()

    out_df.columns = original_cols
    out_df.to_csv(out / fn, sep='\t', index=False)

print('POLICY_DATA_READY')
