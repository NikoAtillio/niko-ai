import pandas as pd
from pathlib import Path

START_CAP = 5000.0
BASE = Path('/Users/niko/Documents/projects/niko-ai')

BRANCHES = {
    'p2_filter_test1': BASE / 'backtest_artifacts/phantom-p2-fixed-20260415_181252',
    'p2_filter_test2': BASE / 'backtest_artifacts/phantom-p2-fixed-20260416_164644',
    'p2_filter_test3': BASE / 'backtest_artifacts/phantom-p2-fixed-20260416_174332',
}

US100_COMP = BASE / 'backtest_artifacts/branch-competition-us100-20260416'
SCENARIOS = ['A', 'B', 'C']
INSTRUMENTS = ['BTC', 'XAU', 'US100']


def load_trade_file(path: Path, branch: str, mode: str, instrument: str, scenario: str):
    if not path.exists():
        return None
    df = pd.read_csv(path)
    if df.empty:
        return None
    df['entry_ts'] = pd.to_datetime(df['entry_ts'])
    df['exit_ts'] = pd.to_datetime(df['exit_ts'])
    df['branch'] = branch
    df['mode'] = mode
    df['instrument'] = instrument
    df['scenario'] = scenario
    return df


def collect_all_trades() -> pd.DataFrame:
    chunks = []

    # Full mode: all instrument/scenario files from each branch root.
    for branch, root in BRANCHES.items():
        for inst in INSTRUMENTS:
            for sc in SCENARIOS:
                path = root / f'{inst}_P2{sc}' / f'phantom_p2_trades_{inst}_P2{sc}.csv'
                df = load_trade_file(path, branch, 'full', inst, f'P2{sc}')
                if df is not None:
                    chunks.append(df)

    # Policy mode: US100 only from normalized competition artifacts.
    for branch, root in BRANCHES.items():
        for sc in SCENARIOS:
            path = US100_COMP / 'policy' / branch / f'US100_P2{sc}' / f'phantom_p2_trades_US100_P2{sc}.csv'
            if not path.exists():
                # Fallback to branch root (branch3 policy-like run).
                path = root / f'US100_P2{sc}' / f'phantom_p2_trades_US100_P2{sc}.csv'
            df = load_trade_file(path, branch, 'policy', 'US100', f'P2{sc}')
            if df is not None:
                chunks.append(df)

    if not chunks:
        raise SystemExit('No trade files found for detailed analysis')

    return pd.concat(chunks, ignore_index=True)


def build_windows(trades: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (branch, mode), g in trades.groupby(['branch', 'mode']):
        start = g['entry_ts'].min()
        end = g['exit_ts'].max()
        days = (end - start).total_seconds() / 86400.0
        rows.append({
            'branch': branch,
            'mode': mode,
            'start': start,
            'end': end,
            'days': round(days, 1),
            'months': round(days / 30.44, 2),
            'trades': len(g),
            'files': g[['instrument', 'scenario']].drop_duplicates().shape[0],
        })
    return pd.DataFrame(rows).sort_values(['mode', 'branch'])


def build_mode_stats(trades: pd.DataFrame):
    # Synthetic mode baskets:
    # full mode has 9 files => 45k notional start, policy has 3 files => 15k.
    starts = {'full': 9 * START_CAP, 'policy': 3 * START_CAP}

    summary_rows = []
    monthly_rows = []
    monthly_dd_rows = []

    for (branch, mode), g in trades.groupby(['branch', 'mode']):
        g = g.sort_values('exit_ts').copy()
        start_cap = starts[mode]

        g['eq'] = start_cap + g['pnl'].cumsum()
        g['peak'] = g['eq'].cummax()
        g['dd_amt'] = g['eq'] - g['peak']
        g['dd_pct'] = (g['eq'] - g['peak']) / g['peak'] * 100
        g['month'] = g['exit_ts'].dt.to_period('M').astype(str)

        final_eq = float(g['eq'].iloc[-1])
        net = final_eq - start_cap
        ret = net / start_cap * 100

        summary_rows.append({
            'branch': branch,
            'mode': mode,
            'start_cap': round(start_cap, 2),
            'final_equity': round(final_eq, 2),
            'net_pnl': round(net, 2),
            'net_return_pct': round(ret, 2),
            'max_dd_amt': round(float(g['dd_amt'].min()), 2),
            'max_dd_pct': round(float(g['dd_pct'].min()), 3),
            'win_rate_pct': round(float(g['win'].mean() * 100), 2),
            'trades': int(len(g)),
        })

        for month, m in g.groupby('month'):
            m_end_eq = float(m['eq'].iloc[-1])
            m_pnl = float(m['pnl'].sum())
            monthly_rows.append({
                'branch': branch,
                'mode': mode,
                'month': month,
                'monthly_pnl': round(m_pnl, 2),
                'monthly_return_on_mode_start_pct': round(m_pnl / start_cap * 100, 3),
                'month_end_equity': round(m_end_eq, 2),
                'month_end_drawdown_amt': round(float(m['dd_amt'].iloc[-1]), 2),
                'month_end_drawdown_pct': round(float(m['dd_pct'].iloc[-1]), 3),
            })
            monthly_dd_rows.append({
                'branch': branch,
                'mode': mode,
                'month': month,
                'worst_intramonth_dd_amt': round(float(m['dd_amt'].min()), 2),
                'worst_intramonth_dd_pct': round(float(m['dd_pct'].min()), 3),
            })

    summary = pd.DataFrame(summary_rows).sort_values(
        ['mode', 'net_return_pct'], ascending=[True, False]
    )
    monthly = pd.DataFrame(monthly_rows).sort_values(['mode', 'branch', 'month'])
    monthly_dd = pd.DataFrame(monthly_dd_rows).sort_values(['mode', 'branch', 'month'])
    return summary, monthly, monthly_dd


def main():
    trades = collect_all_trades()
    windows = build_windows(trades)
    summary, monthly, monthly_dd = build_mode_stats(trades)

    out_dir = US100_COMP
    out_dir.mkdir(parents=True, exist_ok=True)

    windows.to_csv(out_dir / 'detailed_windows.csv', index=False)
    summary.to_csv(out_dir / 'detailed_summary.csv', index=False)
    monthly.to_csv(out_dir / 'detailed_monthly_pnl_equity.csv', index=False)
    monthly_dd.to_csv(out_dir / 'detailed_monthly_drawdowns.csv', index=False)

    print('=== WINDOW SUMMARY ===')
    print(windows.to_string(index=False))
    print('\n=== MODE SUMMARY ===')
    print(summary.to_string(index=False))
    print('\n=== MONTHLY PNL+EQUITY (first 60 rows) ===')
    print(monthly.head(60).to_string(index=False))
    print('\n=== MONTHLY DRAWDOWNS (first 60 rows) ===')
    print(monthly_dd.head(60).to_string(index=False))
    print('\nWROTE FILES:')
    print(out_dir / 'detailed_windows.csv')
    print(out_dir / 'detailed_summary.csv')
    print(out_dir / 'detailed_monthly_pnl_equity.csv')
    print(out_dir / 'detailed_monthly_drawdowns.csv')


if __name__ == '__main__':
    main()
