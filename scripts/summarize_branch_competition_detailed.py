import pandas as pd
from pathlib import Path

BASE = Path('/Users/niko/Documents/projects/niko-ai/backtest_artifacts/branch-competition-us100-20260416')

monthly = pd.read_csv(BASE / 'detailed_monthly_pnl_equity.csv')
monthly_dd = pd.read_csv(BASE / 'detailed_monthly_drawdowns.csv')
windows = pd.read_csv(BASE / 'detailed_windows.csv')
summary = pd.read_csv(BASE / 'detailed_summary.csv')

rows = []
for (branch, mode), g in monthly.groupby(['branch', 'mode']):
    d = monthly_dd[(monthly_dd['branch'] == branch) & (monthly_dd['mode'] == mode)]
    w = windows[(windows['branch'] == branch) & (windows['mode'] == mode)].iloc[0]
    s = summary[(summary['branch'] == branch) & (summary['mode'] == mode)].iloc[0]

    pos = int((g['monthly_pnl'] > 0).sum())
    neg = int((g['monthly_pnl'] < 0).sum())
    flat = int((g['monthly_pnl'] == 0).sum())

    best = g.loc[g['monthly_pnl'].idxmax()]
    worst = g.loc[g['monthly_pnl'].idxmin()]
    worst_dd = d.loc[d['worst_intramonth_dd_pct'].idxmin()]

    rows.append({
        'branch': branch,
        'mode': mode,
        'start': w['start'],
        'end': w['end'],
        'months': int(len(g)),
        'start_cap': float(s['start_cap']),
        'final_equity': float(s['final_equity']),
        'net_return_pct': float(s['net_return_pct']),
        'max_dd_pct': float(s['max_dd_pct']),
        'max_dd_amt': float(s['max_dd_amt']),
        'positive_months': pos,
        'negative_months': neg,
        'flat_months': flat,
        'positive_month_ratio_pct': round(pos / len(g) * 100, 2),
        'avg_monthly_pnl': round(float(g['monthly_pnl'].mean()), 2),
        'median_monthly_pnl': round(float(g['monthly_pnl'].median()), 2),
        'best_month': str(best['month']),
        'best_month_pnl': round(float(best['monthly_pnl']), 2),
        'worst_month': str(worst['month']),
        'worst_month_pnl': round(float(worst['monthly_pnl']), 2),
        'worst_intramonth_dd_month': str(worst_dd['month']),
        'worst_intramonth_dd_amt': round(float(worst_dd['worst_intramonth_dd_amt']), 2),
        'worst_intramonth_dd_pct': round(float(worst_dd['worst_intramonth_dd_pct']), 3),
    })

out = pd.DataFrame(rows).sort_values(['mode', 'net_return_pct'], ascending=[True, False])
out.to_csv(BASE / 'detailed_comparison_highlights.csv', index=False)
print(out.to_string(index=False))
print('\nWROTE:', BASE / 'detailed_comparison_highlights.csv')
