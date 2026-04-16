import json
from pathlib import Path

import pandas as pd

BASE = Path('/Users/niko/Documents/projects/niko-ai')
ART = BASE / 'backtest_artifacts' / 'branch-competition-us100-20260416'
OUT = ART / 'dashboard_2021_10k'
OUT.mkdir(parents=True, exist_ok=True)

START_DATE = pd.Timestamp('2021-01-01')
TARGET_START_CAP = 10_000.0  # GBP notional baseline

BRANCHES = ['p2_filter_test1', 'p2_filter_test2', 'p2_filter_test3']
MODES = ['full', 'policy']

# These start caps are from the previously aggregated baskets.
ORIG_START_CAP_BY_MODE = {
    'full': 45_000.0,   # 9 files x 5k
    'policy': 15_000.0, # 3 files x 5k
}


def build_monthly_and_summary():
    monthly_path = ART / 'detailed_monthly_pnl_equity.csv'
    dd_path = ART / 'detailed_monthly_drawdowns.csv'
    windows_path = ART / 'detailed_windows.csv'

    monthly = pd.read_csv(monthly_path)
    dd = pd.read_csv(dd_path)
    windows = pd.read_csv(windows_path)

    monthly['month_ts'] = pd.to_datetime(monthly['month'] + '-01')
    monthly = monthly[monthly['month_ts'] >= START_DATE].copy()

    out_monthly_rows = []
    out_summary_rows = []
    out_highlight_rows = []

    for mode in MODES:
        mode_monthly = monthly[monthly['mode'] == mode]
        if mode_monthly.empty:
            continue

        scale = TARGET_START_CAP / ORIG_START_CAP_BY_MODE[mode]

        for branch in BRANCHES:
            g = mode_monthly[mode_monthly['branch'] == branch].sort_values('month_ts').copy()
            if g.empty:
                continue

            # Scale monthly pnl and recompute equity from 10k baseline.
            g['monthly_pnl_scaled'] = g['monthly_pnl'] * scale
            g['equity_scaled'] = TARGET_START_CAP + g['monthly_pnl_scaled'].cumsum()
            g['peak_scaled'] = g['equity_scaled'].cummax()
            g['month_end_dd_amt_scaled'] = g['equity_scaled'] - g['peak_scaled']
            g['month_end_dd_pct_scaled'] = (g['month_end_dd_amt_scaled'] / g['peak_scaled']) * 100

            # Monthly worst intramonth DD is also scaled linearly in amount,
            # while percentage remains unchanged.
            gdd = dd[(dd['mode'] == mode) & (dd['branch'] == branch)].copy()
            gdd['month_ts'] = pd.to_datetime(gdd['month'] + '-01')
            gdd = gdd[gdd['month_ts'] >= START_DATE]
            dd_map = {
                row['month']: (
                    float(row['worst_intramonth_dd_amt']) * scale,
                    float(row['worst_intramonth_dd_pct']),
                )
                for _, row in gdd.iterrows()
            }

            for _, row in g.iterrows():
                m = row['month']
                worst_amt, worst_pct = dd_map.get(m, (0.0, 0.0))
                out_monthly_rows.append({
                    'branch': branch,
                    'mode': mode,
                    'month': m,
                    'monthly_pnl_gbp': round(float(row['monthly_pnl_scaled']), 2),
                    'month_end_equity_gbp': round(float(row['equity_scaled']), 2),
                    'month_end_drawdown_amt_gbp': round(float(row['month_end_dd_amt_scaled']), 2),
                    'month_end_drawdown_pct': round(float(row['month_end_dd_pct_scaled']), 3),
                    'worst_intramonth_dd_amt_gbp': round(float(worst_amt), 2),
                    'worst_intramonth_dd_pct': round(float(worst_pct), 3),
                })

            final_equity = float(g['equity_scaled'].iloc[-1])
            net_pnl = final_equity - TARGET_START_CAP
            net_return_pct = (net_pnl / TARGET_START_CAP) * 100
            max_dd_amt = float((g['equity_scaled'] - g['peak_scaled']).min())
            max_dd_pct = float(((g['equity_scaled'] - g['peak_scaled']) / g['peak_scaled']).min() * 100)

            pos = int((g['monthly_pnl_scaled'] > 0).sum())
            neg = int((g['monthly_pnl_scaled'] < 0).sum())
            flat = int((g['monthly_pnl_scaled'] == 0).sum())

            best_idx = g['monthly_pnl_scaled'].idxmax()
            worst_idx = g['monthly_pnl_scaled'].idxmin()
            best_month = str(g.loc[best_idx, 'month'])
            worst_month = str(g.loc[worst_idx, 'month'])
            best_month_pnl = float(g.loc[best_idx, 'monthly_pnl_scaled'])
            worst_month_pnl = float(g.loc[worst_idx, 'monthly_pnl_scaled'])

            out_summary_rows.append({
                'branch': branch,
                'mode': mode,
                'start_cap_gbp': TARGET_START_CAP,
                'final_equity_gbp': round(final_equity, 2),
                'net_pnl_gbp': round(net_pnl, 2),
                'net_return_pct': round(net_return_pct, 2),
                'max_dd_amt_gbp': round(max_dd_amt, 2),
                'max_dd_pct': round(max_dd_pct, 3),
                'months': int(len(g)),
            })

            out_highlight_rows.append({
                'branch': branch,
                'mode': mode,
                'months': int(len(g)),
                'start_cap_gbp': TARGET_START_CAP,
                'final_equity_gbp': round(final_equity, 2),
                'net_return_pct': round(net_return_pct, 2),
                'max_dd_pct': round(max_dd_pct, 3),
                'max_dd_amt_gbp': round(max_dd_amt, 2),
                'positive_months': pos,
                'negative_months': neg,
                'flat_months': flat,
                'positive_month_ratio_pct': round((pos / len(g)) * 100, 2),
                'avg_monthly_pnl_gbp': round(float(g['monthly_pnl_scaled'].mean()), 2),
                'median_monthly_pnl_gbp': round(float(g['monthly_pnl_scaled'].median()), 2),
                'best_month': best_month,
                'best_month_pnl_gbp': round(best_month_pnl, 2),
                'worst_month': worst_month,
                'worst_month_pnl_gbp': round(worst_month_pnl, 2),
            })

    monthly_out = pd.DataFrame(out_monthly_rows).sort_values(['mode', 'branch', 'month'])
    summary_out = pd.DataFrame(out_summary_rows).sort_values(['mode', 'net_return_pct'], ascending=[True, False])
    highlights_out = pd.DataFrame(out_highlight_rows).sort_values(['mode', 'net_return_pct'], ascending=[True, False])

    # Window metadata clipped at 2021 start.
    win_rows = []
    for mode in MODES:
        mode_rows = monthly_out[monthly_out['mode'] == mode]
        if mode_rows.empty:
            continue
        start = mode_rows['month'].min() + '-01'
        end_month = pd.to_datetime(mode_rows['month'].max() + '-01')
        end = (end_month + pd.offsets.MonthEnd(1)).strftime('%Y-%m-%d')
        win_rows.append({
            'mode': mode,
            'start_date': start,
            'end_date': end,
            'timescale_months': int(mode_rows['month'].nunique()),
            'start_cap_gbp': TARGET_START_CAP,
        })
    windows_out = pd.DataFrame(win_rows)

    return monthly_out, summary_out, highlights_out, windows_out


def build_dashboard_json(summary_df, highlights_df, monthly_df, windows_df):
    data = {
        'meta': {
            'currency': 'GBP',
            'start_cap_gbp': TARGET_START_CAP,
            'start_filter': '2021-01-01',
            'notes': [
                'Monthly values are exact month-by-month values from trade outputs, not sampled January points.',
                'PnL/equity amounts are normalized from original basket starts (full=45k, policy=15k) to 10k using linear scaling.',
            ],
        },
        'windows': windows_df.to_dict(orient='records'),
        'summary': summary_df.to_dict(orient='records'),
        'highlights': highlights_df.to_dict(orient='records'),
        'monthly': {},
    }

    for mode in MODES:
        data['monthly'][mode] = {}
        mode_df = monthly_df[monthly_df['mode'] == mode]
        for branch in BRANCHES:
            g = mode_df[mode_df['branch'] == branch]
            data['monthly'][mode][branch] = g[
                [
                    'month',
                    'monthly_pnl_gbp',
                    'month_end_equity_gbp',
                    'month_end_drawdown_amt_gbp',
                    'month_end_drawdown_pct',
                    'worst_intramonth_dd_amt_gbp',
                    'worst_intramonth_dd_pct',
                ]
            ].to_dict(orient='records')

    return data


def main():
    monthly_df, summary_df, highlights_df, windows_df = build_monthly_and_summary()

    monthly_df.to_csv(OUT / 'monthly_2021_10k.csv', index=False)
    summary_df.to_csv(OUT / 'summary_2021_10k.csv', index=False)
    highlights_df.to_csv(OUT / 'highlights_2021_10k.csv', index=False)
    windows_df.to_csv(OUT / 'windows_2021_10k.csv', index=False)

    dashboard_json = build_dashboard_json(summary_df, highlights_df, monthly_df, windows_df)
    with open(OUT / 'dashboard_data_2021_10k.json', 'w', encoding='utf-8') as f:
        json.dump(dashboard_json, f, indent=2)

    print('WROTE:')
    print(OUT / 'monthly_2021_10k.csv')
    print(OUT / 'summary_2021_10k.csv')
    print(OUT / 'highlights_2021_10k.csv')
    print(OUT / 'windows_2021_10k.csv')
    print(OUT / 'dashboard_data_2021_10k.json')

    print('\nSUMMARY PREVIEW:')
    print(summary_df.to_string(index=False))


if __name__ == '__main__':
    main()
