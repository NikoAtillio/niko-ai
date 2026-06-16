import pandas as pd
from pathlib import Path
import re

BASE = Path('saved_runs/2026-06-16_6y')
REPORTS = BASE / 'reports'
REPORTS.mkdir(parents=True, exist_ok=True)
START_CAP = 10000.0


def period_stats(df: pd.DataFrame, freq: str) -> pd.DataFrame:
    d = df.copy()
    d['exit_ts'] = pd.to_datetime(d['exit_ts'])
    d = d.sort_values('exit_ts').reset_index(drop=True)
    d['equity'] = START_CAP + d['pnl'].cumsum()
    d['period'] = d['exit_ts'].dt.to_period(freq)

    rows = []
    for p, g in d.groupby('period', sort=True):
        first_idx = int(g.index[0])
        start_equity = START_CAP if first_idx == 0 else float(d.loc[first_idx - 1, 'equity'])
        curve = pd.concat([pd.Series([start_equity]), g['equity'].reset_index(drop=True)], ignore_index=True)
        peak = curve.cummax()
        dd = curve - peak
        dd_pct = (curve / peak - 1.0) * 100.0

        rows.append({
            'period': str(p),
            'trades': int(len(g)),
            'pnl': float(g['pnl'].sum()),
            'end_equity': float(g['equity'].iloc[-1]),
            'max_dd_amount': float(abs(dd.min())),
            'max_dd_pct': float(dd_pct.min()),
        })

    return pd.DataFrame(rows)


def overall_stats(df: pd.DataFrame) -> dict:
    d = df.copy()
    d['entry_ts'] = pd.to_datetime(d['entry_ts'])
    d['exit_ts'] = pd.to_datetime(d['exit_ts'])
    d = d.sort_values('exit_ts').reset_index(drop=True)
    d['equity'] = START_CAP + d['pnl'].cumsum()
    peak = d['equity'].cummax()
    dd_amt = d['equity'] - peak
    dd_pct = (d['equity'] / peak - 1.0) * 100.0

    return {
        'trades': int(len(d)),
        'start_equity': START_CAP,
        'end_equity': float(d['equity'].iloc[-1]),
        'net_pnl': float(d['pnl'].sum()),
        'max_dd_amount': float(abs(dd_amt.min())),
        'max_dd_pct': float(dd_pct.min()),
        'first_trade': str(d['entry_ts'].min()),
        'last_trade': str(d['exit_ts'].max()),
    }


modes = {
    'cash': BASE / 'cash' / 'phantom_p2_ftmo_v2_trades_US100_P2_FTMO_V2B.csv',
    'ftmo': BASE / 'ftmo' / 'phantom_p2_ftmo_v2_trades_US100_P2_FTMO_V2B.csv',
}

summary_lines = []
for mode, path in modes.items():
    df = pd.read_csv(path)
    m = period_stats(df, 'M')
    y = period_stats(df, 'Y')
    ov = overall_stats(df)

    m.to_csv(REPORTS / f'{mode}_monthly_metrics.csv', index=False)
    y.to_csv(REPORTS / f'{mode}_yearly_metrics.csv', index=False)

    summary_lines.append(f'[{mode.upper()}]')
    for k, v in ov.items():
        summary_lines.append(f'{k}: {v}')
    summary_lines.append('')

log_text = (BASE / 'ftmo' / 'run.log').read_text(encoding='utf-8', errors='ignore')
patterns = {
    'hard_stop_triggered': r'\[ftmo\] hard-stop TRIGGERED',
    'hard_stop_pause_until': r'\[ftmo\] hard-stop PAUSE-UNTIL',
    'hard_stop_auto_resume': r'\[ftmo\] hard-stop AUTO-RESUME',
    'daily_soft_stop_active': r'\[ftmo\] daily soft-stop active',
    'daily_soft_force_close': r'\[ftmo\] DAILY-SOFT FORCE-CLOSE',
    'total_soft_stop_active': r'\[ftmo\] total soft-stop active',
    'manual_resume_detected': r'\[ftmo\] manual resume detected',
    'daily_hard_reset': r'\[ftmo\] daily hard-stop RESET',
}
counts = {k: len(re.findall(v, log_text)) for k, v in patterns.items()}
reasons = re.findall(r'hard-stop TRIGGERED .*?reason=([^|]+)\s*\|', log_text)
reason_counts = {}
for r in reasons:
    reason_counts[r] = reason_counts.get(r, 0) + 1

(REPORTS / 'summary.txt').write_text('\n'.join(summary_lines), encoding='utf-8')
with (REPORTS / 'ftmo_event_summary.txt').open('w', encoding='utf-8') as f:
    f.write('FTMO Event Counts\n')
    for k, v in counts.items():
        f.write(f'{k}: {v}\n')
    f.write('\nHard-Stop Reasons\n')
    for k, v in sorted(reason_counts.items()):
        f.write(f'{k}: {v}\n')

print('ok')
for p in sorted(REPORTS.glob('*')):
    print(p.as_posix())
