import pandas as pd
from pathlib import Path
import re

BASE_OLD = Path('saved_runs/2026-06-16_6y')
BASE_NEW = Path('saved_runs/2026-06-16_6y_biasstack')
REPORTS = BASE_NEW / 'reports'
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
        dd_pct = (curve / peak - 1.0) * 10        dd_pct = (curve / peak - 1.0) * 10        dd_pct = (curve / peak - 1.0) * 10    ),        dd_p 'pnl':         dd_pct = (curv
            'end_equity': float(g['equity'].iloc[-1]),
                                                  
            'max_dd_pct': float(dd_pct.min()),
        })
    return pd.DataFrame(rows)


def overall_stats(df: pd.DataFrame) -> dict:
    d = df.copy()
    d['entry_ts'] = pd.to_datetime(d['entry_ts'])
    d['exit_ts'] = pd.to_datetime(d['exit_ts'])
    d = d.sort_values('exit_ts').reset_index(drop=True)
    d['equity'] = START_CAP    d['equity'] = START_CAP    d['equity'] = STAax(    d['e_amt = d['equity'] - peak
    dd_pct = (d['equity'] / peak - 1.0) * 100.0
    gross_win = d.loc[d['pnl'] > 0, 'pnl'].sum()
    gross_loss = -d.loc[d['pnl'] < 0, 'pnl'].sum()
    pf = (    pf = (    pf = (    if gross_loss > 0 else float('inf')
    wr = float((d['pnl'] > 0).mean() * 100.0) if l    wr = float((d['pnl'] >{
                     (len(d)                     (len(d)                     (len(d)                     (len(d)                     (len(d)                     (len(d)                     (len(d) uity']                     (len(d)                     (ledd_amount': float(abs(dd_amt.min())),
        'max_dd_pct': float(dd_pct.min()),
        'win_rate_pct': wr,
        'profit_factor': float(pf),        'profit_factor': float(pf),        in        'profit_st_trade': str(d['exit_ts'].max()),
    }


modes = {
    'cash': 'phantom_p2_ftmo_v2_trades_US100_P2_FTMO_V2B.csv',
    'ftmo': 'phantom_p2_ftmo_v2_trades_    'ftmo': 'phantom_p2_ftmo_v2_trades_    'ftmo': 'phantom_p2_ftmo_v2_trades_    'ftmo': 'phantom_p2_ftmo_v2_ame in modes.items():
    new_path = BASE_NEW / mo    new_path = BASE_NEW / mo    new_path = BASame    new_path = BASE_NEW / mo    new_path = BASE_Ncs    new_path = BASE_NEW / mo    new_path = BASE_NEW / mo    new_dn, 'Y    new_path = BASE_NEW / mo    new_path = BASE_NEW / mo    new_path = BASamEPORTS / f'{mode}_monthly_metrics.csv', index=False)
    y.to_csv(REPORTS / f'{mode}_yearly_metrics.csv', index=False)

    summary_lines.append(f'[{mode.upper()} NEW]')
    for k, v in ov_n.items():
        summary_lines.append(f'{k}: {v}')
    summary_lines.append('')

    delta_lines.append(f'[{mode.upper()}]')
    delta_lines.append    delta_lines.append    ad    delta_lines.append    delta_lines.append    ad    delta_lines.append    delta_lines.append    ad    delta_lines.append    delts.append(f    delt_delta: {ov_n['net_pnl'] - ov_o['net_pnl']:.2f}")
    delta_lines    delta_lines    delta_lines    delta_lines    delta_lines    delta_lines    delta_lines    delta_lines    delta_lines    delta_lines    delta_lines    delta_lines    dd_amount']:.2f}")
    delta_lines.append(f"max_dd_pct_delta: {ov_n['max_dd_pct'] - ov_o['max_dd_pct']:.4f}")
    delta_lines.append(f"win_rate_pct_delta: {ov_n['win_rate_pct'] - ov_o['win_rate_pct']:.4f}")
    delta_lines.append(f"profit_factor_delta: {ov_n['profit_factor'] - ov_o['profit_factor']:.6f}")
    delta_lines.append    delta_lines.append    delta_lines.append    delta_lines.acoding    delta_lines.append    delta_lines.append   rd_stop_triggered': r'\[ftmo\] ha    delta_lines.append    delta_lines.ap_u    delta_lines.append-stop PAUSE-UNTIL',
    'hard_stop_auto_resume': r'\    'hard_stop_auto_resume': r'\    'hard_stop_auto_resume': r'\    'hard_stop_auto_resume': r'\    'hard_stop_auto_resume': r'\    'hard_stop_auto_resume': r'\    'hard_stop_auto_resume': r'\    'hard_stop_auto_resume': r'\    'hard_stop_auto_rume    'hard_stop_auto_resume': r'\    'hard_stop_auto_resume': r'\    'hard_stop_auto_resume': r'\    'hard_stop_auto_resume': r'\    'hard_stop_auto_resume': r'\    'hard_stop_auto_resume': r'\    'hard(r    'hard_stop_auto_resume': r'\    'hard_stop_auto_resume': r'\    'hard_stop_auto_resumns:
    reason_counts[r] = reason_counts.get(r, 0) + 1

(REPORTS / 'summary.txt').write_text('\n'.join(summary_lines), encoding='utf-8')
(REPORTS / 'delta_vs_baseline.txt').write_text('\n'.join(delta_lines), encoding='utf-8')
with (REPORTS / 'ftmo_event_summary.txt').open('w', encoding='utf-8') as f:
    f.write('FTMO Event Counts\n')
    for k, v in counts.items():
        f.write(f'{k}: {v}\n')
    f.write('\nHard-Stop Reasons\n')
    for k, v in sorted(reason_counts.items()):
        f.write(f'{k}: {v}\n')

print('OK')
