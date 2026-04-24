import pandas as pd
import numpy as np

p = 'tmp/analysis_xau/phantom_p2_trades_XAU_P2B.csv'
df = pd.read_csv(p)

wins = df[df['pnl'] > 0]
losses = df[df['pnl'] <= 0]

print(f"CSV: {p}")
print(f"Total trades: {len(df)}")
print(f"Avg win: £{wins['pnl'].mean():.2f}")
print(f"Avg loss: £{losses['pnl'].mean():.2f}")
if len(losses) > 0 and losses['pnl'].mean() != 0:
    print(f"Avg win/loss ratio: {abs(wins['pnl'].mean() / losses['pnl'].mean()):.2f}")
print(f"Largest win: £{wins['pnl'].max():.2f}")
print(f"Largest loss: £{losses['pnl'].min():.2f}")

if 'reason' in df.columns:
    vc = df['reason'].value_counts(dropna=False)
    pct = (vc / len(df) * 100).round(2)
    print("\nExit reasons (count | %):")
    for reason, count in vc.items():
        print(f"{reason}: {count} | {pct.loc[reason]:.2f}%")

r_cols = [c for c in df.columns if c.lower() in {'r_value', 'r', 'r_multiple', 'r_mult'}]
if r_cols:
    rcol = r_cols[    rcol = r_cols[    rcol = r_cols[    rcol = r_cols[    rcol = r_cols[    rcol = r_cols[   (losses): {losses[rco    rcol = r_}")
elselselselselselselselselselselselselselselselselsels}
elselselselselselsbseelselselselselselsb
        risk_per_unit = (df['entry_price'] - df['sl']).abs()
        risk_amt = risk_per_unit * df['size'].replace(0, np.nan)
                                                                                                        oc                                                                                es, inferred): {df.loc[df['pnl'] <= 0, 'r_inferred'].mean():.2f}")
        print(f"Avg R-multiple (all, inferred): {df['r_inferred'].mean():.2f}")
    else:
        print("\nAvg R-multiple: not available")

print("\nColumns:", ', '.join(df.columns))
