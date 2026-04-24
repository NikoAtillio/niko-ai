import importlib.util
import os
import pandas as pd

ROOT = '/Users/niko/Documents/projects/niko-ai'
SCRIPT_PATH = os.path.join(ROOT, 'phantom', 'phantom_XAU', 'phantom_XAU_median.py')
OUT_DIR = os.path.join(ROOT, 'tmp', 'analysis_xau', 'sensitivity_runs')
os.makedirs(OUT_DIR, exist_ok=True)

spec = importlib.util.spec_from_file_location('xau_median', SCRIPT_PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

# Load data once
m1 = mod.apply_start_date(mod.add_indicators(mod.load_csv(os.path.join(ROOT, 'data', 'XAUUSD', 'XAUUSD_M1_2023.03.13-2026.03.31'))), '2021-01-14')
m5 = mod.apply_start_date(mod.add_indicators(mod.load_csv(os.path.join(ROOT, 'data', 'XAUUSD', 'XAUUSD_M5_2011.09.08-2026.03.31'))), '2021-01-14')
h1 = mod.apply_start_date(mod.add_indicators(mod.load_csv(os.path.join(ROOT, 'data', 'XAUUSD', 'XAUUSD_H1_2010.01.04-2026.03.31'))), '2021-01-14')
h4 = mod.apply_start_date(mod.add_indicators(mod.load_csv(os.path.join(ROOT, 'data', 'XAUUSD', 'XAUUSD_H4_2010.01.04-2026.03.31'))), '2021-01-14')
m15 = mod.apply_start_date(mod.add_indicators(mod.load_csv(os.path.join(ROOT, 'data', 'XAUUSD', 'XAUUSD_M15_2010.01.04-2026.03.31'))), '2021-01-14')
daily = mod.apply_start_date(mod.add_indicators(mod.load_csv(os.path.join(ROOT, 'data', 'XAUUSD', 'XAUUSD_Daily_2010.01.04-2026.03.31'))), '2021-01-14')
daily = mod.add_daily_regime(daily, mod.INSTRUMENT_CONFIG['XAU'])

zone_ts, zone_px, zone_dir = mod.build_h4_zones(
    h4,
    pivot_bars=mod.DEFAULTS['h4_pivot_bars'],
    lookback=mod.DEFAULTS['h4_lookback'],
)

arrays = dict(
    h4_idx=h4.index.values, h4_c=h4['close'].values,
    h4_e20=h4['ema20'].values, h4_e50=h4['ema50'].values,
    h4_rsi=h4['rsi'].values, h4_atr_arr=h4['atr'].values,
    h1_idx=h1.index.values, h1_c=h1['close'].values,
    h1_e20=h1['ema20'].values, h1_e50=h1['ema50'].values,
    h1_rsi=h1['rsi'].values,
    m15_idx=m15.index.values, m15_atr_arr=m15['atr'].values,
    m5_idx=m5.index.values, m5_c=m5['close'].values,
    m5_e20=m5['ema20'].values, m5_e50=m5['ema50'].values,
    m5_rsi=m5['rsi'].values,
    m5_vol=m5['tickvol'].values, m5_vol_ma=m5['vol_ma'].values,
    m1_idx=m1.index.values, m1_c=m1['close'].values,
    m1_e20=m1['ema20'].values, m1_e50=m1['ema50'].values,
    m1_rsi=m1['rsi'].values,
)

daily_idx = daily.index.values
daily_regime = daily['regime'].values

base_cfg = dict(mod.SCENARIOS['B'])
base_defaults = dict(mod.DEFAULTS)
base_tp = mod.INSTRUMENT_CONFIG['XAU']['tp_mult']

tests = [
    dict(name='Baseline', trail_atr=0.5, be_trigger=0.4, tp=1.0, entry_gate='yes', cooldown_min=5),
    dict(name='Test 1', trail_atr=0.8, be_trigger=0.4, tp=1.0, entry_gate='yes', cooldown_min=5),
    dict(name='Test 2', trail_atr=0.5, be_trigger=0.8, tp=1.0, entry_gate='yes', cooldown_min=5),
    dict(name='Test 3', trail_atr=0.8, be_trigger=0.6, tp=0.9, entry_gate='yes', cooldown_min=5),
    dict(name='Test 4', trail_atr=0.5, be_trigger=0.4, tp=1.0, entry_gate='no', cooldown_min=0),
]

rows = []

for t in tests:
    mod.SCENARIOS['B'] = dict(base_cfg)
    mod.SCENARIOS['B']['atr_trail'] = t['trail_atr']

    mod.DEFAULTS.update(base_defaults)
    mod.DEFAULTS['breakeven_r'] = t['be_trigger']
    mod.DEFAULTS['cooldown_min'] = t['cooldown_min']

    mod.INSTRUMENT_CONFIG['XAU']['tp_mult'] = t['tp']

    df_r = mod.run_scenario(
        candles=m5,
        zone_ts=zone_ts,
        zone_px=zone_px,
        zone_dir=zone_dir,
        daily_idx=daily_idx,
        daily_regime=daily_regime,
        cfg=mod.SCENARIOS['B'],
        inst_cfg=mod.INSTRUMENT_CONFIG['XAU'],
        capital=5000,
        max_concurrent=mod.DEFAULTS['max_concurrent'],
        cooldown_min=mod.DEFAULTS['cooldown_min'],
        lockout_min=mod.DEFAULTS['lockout_min'],
        conf_tol=mod.DEFAULTS['conf_tol'],
        spread_bps=0.0,
        slippage_bps=0.0,
        commission_per_trade=0.0,
        zone_lookback_bars=mod.DEFAULTS['h4_lookback'],
        label=f"{t['name']} | trail={t['trail_atr']} be={t['be_trigger']} tp={t['tp']}",
        **arrays,
    )

    out_csv = os.path.join(OUT_DIR, f"{t['name'].lower().replace(' ', '_')}.csv")
    df_r.to_csv(out_csv, index=False)

    trades = len(df_r)
    wins = (df_r['pnl'] > 0).sum()
    win_rate = (wins / trades * 100) if trades else 0.0
    gross_win = df_r.loc[df_r['pnl'] > 0, 'pnl'].sum()
    gross_loss = df_r.loc[df_r['pnl'] <= 0, 'pnl'].sum()
    pf = abs(gross_win / gross_loss) if gross_loss != 0 else float('inf')

    eq = 5000 + df_r['pnl'].cumsum() if trades else pd.Series([5000])
    peak = eq.cummax()
    dd_pct = ((eq - peak) / peak).min() * 100 if len(eq) else 0.0
    final_cap = float(eq.iloc[-1]) if len(eq) else 5000.0
    ret = (final_cap / 5000 - 1) * 100

    ex_vc = df_r['exit_reason'].value_counts(normalize=True) * 100 if 'exit_reason' in df_r.columns and trades else pd.Series(dtype=float)

    rows.append({
        'config': t['name'],
        'trail_atr': t['trail_atr'],
        'be_trigger_r': t['be_trigger'],
        'tp_r': t['tp'],
        'entry_gate': t['entry_gate'],
        'cooldown_min': t['cooldown_min'],
        'trades': trades,
        'win_pct': round(win_rate, 2),
        'pf': round(float(pf), 3),
        'ret_pct': round(float(ret), 2),
        'max_dd_pct': round(float(dd_pct), 2),
        'final_cap': round(float(final_cap), 2),
        'expectancy': round(float(df_r['pnl'].mean()) if trades else 0.0, 2),
        'tp_pct': round(float(ex_vc.get('tp', 0.0)), 2),
        'stop_pct': round(float(ex_vc.get('stop', 0.0)), 2),
        'timeout_pct': round(float(ex_vc.get('timeout', 0.0)), 2),
    })

# restore
mod.SCENARIOS['B'] = base_cfg
mod.DEFAULTS.update(base_defaults)
mod.INSTRUMENT_CONFIG['XAU']['tp_mult'] = base_tp

result_df = pd.DataFrame(rows)
out_table = os.path.join(ROOT, 'tmp', 'analysis_xau', 'sensitivity_summary.csv')
result_df.to_csv(out_table, index=False)
print(result_df.to_string(index=False))
print(f"\nSaved summary -> {out_table}")
print(f"Saved run CSVs -> {OUT_DIR}")