#!/usr/bin/env python3
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / 'generated_examples'
DATA_ROOT = ROOT / 'data'


@dataclass
class ExampleHit:
    strategy_id: str
    instrument: str
    timeframe: str
    index: int
    direction: str
    confidence: float
    rationale: str
    dataset_path: str


def load_mt_file(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, sep='\t')
    df.columns = [c.strip('<>').lower() for c in df.columns]
    if 'date' not in df.columns or 'time' not in df.columns:
        raise ValueError(f'Unexpected format: {path}')

    df['datetime'] = pd.to_datetime(df['date'].astype(str) + ' ' + df['time'].astype(str), errors='coerce')
    for c in ('open', 'high', 'low', 'close', 'tickvol'):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce')
    df = df.dropna(subset=['datetime', 'open', 'high', 'low', 'close']).sort_values('datetime').reset_index(drop=True)
    if 'tickvol' not in df.columns:
        df['tickvol'] = 0.0
    return df


def infer_tf_label(df: pd.DataFrame) -> str:
    mins = df['datetime'].diff().dt.total_seconds().dropna().to_numpy() / 60.0
    if len(mins) == 0:
        return 'unknown'
    median = float(np.nanmedian(mins))
    mapping = {
        1: 'M1',
        5: 'M5',
        15: 'M15',
        30: 'M30',
        60: 'H1',
        240: 'H4',
        1440: 'D1',
    }
    nearest = min(mapping.keys(), key=lambda k: abs(k - median))
    return mapping[nearest]


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out['ema20'] = out['close'].ewm(span=20, adjust=False).mean()
    out['ema50'] = out['close'].ewm(span=50, adjust=False).mean()

    prev_close = out['close'].shift(1)
    tr = pd.concat([
        out['high'] - out['low'],
        (out['high'] - prev_close).abs(),
        (out['low'] - prev_close).abs(),
    ], axis=1).max(axis=1)
    out['atr14'] = tr.ewm(span=14, adjust=False).mean()

    ma20 = out['close'].rolling(20).mean()
    std20 = out['close'].rolling(20).std()
    out['bb_mid'] = ma20
    out['bb_upper'] = ma20 + 2 * std20
    out['bb_lower'] = ma20 - 2 * std20
    out['bb_width'] = ((out['bb_upper'] - out['bb_lower']) / out['bb_mid']).replace([np.inf, -np.inf], np.nan)

    out['vol_avg20'] = out['tickvol'].rolling(20).mean()
    return out


def body_ratio(row: pd.Series) -> float:
    rng = max(1e-9, float(row['high'] - row['low']))
    return float(abs(row['close'] - row['open']) / rng)


def wick_ratios(row: pd.Series) -> Tuple[float, float]:
    body = max(1e-9, float(abs(row['close'] - row['open'])))
    upper = max(0.0, float(row['high'] - max(row['open'], row['close']))) / body
    lower = max(0.0, float(min(row['open'], row['close']) - row['low'])) / body
    return upper, lower


def find_trend_pullback(df: pd.DataFrame, instrument: str, tf: str, dataset: str) -> Optional[ExampleHit]:
    for i in range(80, len(df) - 2):
        row = df.iloc[i]
        if not np.isfinite(row['ema20']) or not np.isfinite(row['ema50']) or not np.isfinite(row['atr14']):
            continue
        if row['ema20'] <= row['ema50']:
            continue
        # Pullback into EMA20/EMA50 zone with bullish rejection and confirmation
        if row['low'] > max(row['ema20'], row['ema50']) + row['atr14'] * 0.05:
            continue
        up, low = wick_ratios(row)
        if low < 1.2 or row['close'] <= row['open']:
            continue
        if df.iloc[i + 1]['close'] <= row['close']:
            continue
        return ExampleHit('TREND_PULLBACK', instrument, tf, i, 'long', 0.78,
                          'Uptrend EMA alignment, pullback touch, bullish rejection and confirmation close.', dataset)
    return None


def find_breakout_confirm(df: pd.DataFrame, instrument: str, tf: str, dataset: str) -> Optional[ExampleHit]:
    for i in range(60, len(df) - 2):
        row = df.iloc[i]
        prev = df.iloc[i - 20:i]
        if len(prev) < 20 or not np.isfinite(row['atr14']) or row['atr14'] <= 0:
            continue
        r_hi = float(prev['high'].max())
        r_lo = float(prev['low'].min())
        range_w = r_hi - r_lo
        if range_w > row['atr14'] * 2.8:
            continue
        if row['close'] <= r_hi + row['atr14'] * 0.1:
            continue
        if body_ratio(row) < 0.6:
            continue
        if row['tickvol'] < row['vol_avg20'] * 1.4:
            continue
        if df.iloc[i + 1]['close'] < r_hi:
            continue
        return ExampleHit('BREAKOUT_CONFIRM', instrument, tf, i, 'long', 0.80,
                          '20-bar consolidation, high-body breakout candle, volume expansion, hold above level.', dataset)
    return None


def find_range_reversion(df: pd.DataFrame, instrument: str, tf: str, dataset: str) -> Optional[ExampleHit]:
    slope = (df['ema20'] - df['ema20'].shift(8)).abs()
    for i in range(80, len(df) - 2):
        row = df.iloc[i]
        prev = df.iloc[i - 40:i]
        if len(prev) < 40:
            continue
        if not np.isfinite(row['atr14']) or row['atr14'] <= 0:
            continue
        if slope.iloc[i] > row['atr14'] * 0.5:
            continue
        r_hi = float(prev['high'].max())
        # Sell near resistance with bearish rejection back into range
        if abs(row['high'] - r_hi) > row['atr14'] * 0.35:
            continue
        up, low = wick_ratios(row)
        if up < 1.3 or row['close'] >= row['open']:
            continue
        if df.iloc[i + 1]['close'] >= row['close']:
            continue
        return ExampleHit('RANGE_REVERSION', instrument, tf, i, 'short', 0.74,
                          'Flat regime, resistance touch, bearish rejection wick and follow-through candle.', dataset)
    return None


def find_mean_revert_band(df: pd.DataFrame, instrument: str, tf: str, dataset: str) -> Optional[ExampleHit]:
    for i in range(50, len(df) - 2):
        row = df.iloc[i]
        prev = df.iloc[i - 1]
        if not np.isfinite(row['bb_upper']) or not np.isfinite(row['bb_mid']) or not np.isfinite(row['atr14']):
            continue
        # prior candle outside upper band, current closes back inside with bearish body
        if prev['close'] <= prev['bb_upper']:
            continue
        if row['close'] >= row['bb_upper']:
            continue
        if row['close'] >= row['open']:
            continue
        if df.iloc[i + 1]['close'] >= row['close']:
            continue
        return ExampleHit('MEAN_REVERT_BAND', instrument, tf, i, 'short', 0.73,
                          'Price stretched above 2SD band then closed back inside with bearish continuation.', dataset)
    return None


def find_vol_squeeze(df: pd.DataFrame, instrument: str, tf: str, dataset: str) -> Optional[ExampleHit]:
    bbw_low = df['bb_width'].rolling(120).min()
    for i in range(140, len(df) - 2):
        row = df.iloc[i]
        if not np.isfinite(row['bb_width']) or not np.isfinite(df.iloc[i - 1]['bb_width']) or not np.isfinite(row['atr14']):
            continue
        if row['bb_width'] > bbw_low.iloc[i - 1] * 1.3:
            continue
        # look ahead one bar for expansion breakout
        nxt = df.iloc[i + 1]
        prior_hi = float(df.iloc[i - 10:i]['high'].max())
        if not np.isfinite(nxt['bb_width']) or not np.isfinite(nxt['vol_avg20']):
            continue
        if nxt['bb_width'] < row['bb_width'] * 1.6:
            continue
        if nxt['close'] <= prior_hi:
            continue
        if body_ratio(nxt) < 0.55:
            continue
        if nxt['tickvol'] < nxt['vol_avg20'] * 1.3:
            continue
        return ExampleHit('VOL_SQUEEZE', instrument, tf, i + 1, 'long', 0.79,
                          'Low BB width squeeze followed by expansion candle with breakout and higher volume.', dataset)
    return None


def find_orb(df: pd.DataFrame, instrument: str, tf: str, dataset: str) -> Optional[ExampleHit]:
    # Generic day-open ORB: first 30 bars from each day in M1
    if tf != 'M1':
        return None
    d = df.copy()
    d['date_key'] = d['datetime'].dt.date
    grouped = d.groupby('date_key')
    for _day, g in grouped:
        if len(g) < 140:
            continue
        orb = g.iloc[:30]
        orb_hi = float(orb['high'].max())
        orb_lo = float(orb['low'].min())
        orb_w = orb_hi - orb_lo
        if orb_w <= 0:
            continue
        after = g.iloc[30:140]
        for idx, row in after.iterrows():
            if row['close'] > orb_hi and body_ratio(row) >= 0.5:
                return ExampleHit('ORB', instrument, tf, int(idx), 'long', 0.77,
                                  'Opening range defined from first 30 bars; breakout close above OR high with momentum body.', dataset)
    return None


def find_momentum_cont(df: pd.DataFrame, instrument: str, tf: str, dataset: str) -> Optional[ExampleHit]:
    for i in range(60, len(df) - 2):
        # impulse: 5-bar strong up move
        impulse = df.iloc[i - 12:i - 7]
        pause = df.iloc[i - 7:i]
        if len(impulse) < 5 or len(pause) < 7:
            continue
        imp_move = float(impulse['close'].iloc[-1] - impulse['open'].iloc[0])
        atr = float(df.iloc[i]['atr14']) if np.isfinite(df.iloc[i]['atr14']) else np.nan
        if not np.isfinite(atr) or atr <= 0:
            continue
        if imp_move < atr * 2.0:
            continue
        pullback = float(impulse['high'].max() - pause['low'].min())
        if pullback > abs(imp_move) * 0.5:
            continue
        p_hi = float(pause['high'].max())
        row = df.iloc[i]
        if row['close'] <= p_hi:
            continue
        if body_ratio(row) < 0.55:
            continue
        return ExampleHit('MOMENTUM_CONT', instrument, tf, i, 'long', 0.76,
                          'Strong impulse, shallow flag/pause, then continuation breakout close above pause high.', dataset)
    return None


def plot_candles(df: pd.DataFrame, start: int, end: int, hit: ExampleHit, out_path: Path) -> Dict[str, object]:
    w = df.iloc[start:end].copy().reset_index(drop=True)
    center = hit.index - start
    row = w.iloc[center]
    entry = float(row['close'])
    risk = max(float(row['atr14']) * 0.8, float(entry) * 0.0015)
    sl = entry - risk if hit.direction == 'long' else entry + risk
    tp1 = entry + risk * 1.5 if hit.direction == 'long' else entry - risk * 1.5
    tp2 = entry + risk * 2.5 if hit.direction == 'long' else entry - risk * 2.5

    fig, ax = plt.subplots(figsize=(14, 6), dpi=120)
    x = np.arange(len(w))
    up = w['close'] >= w['open']

    for i in range(len(w)):
        o = float(w.iloc[i]['open'])
        h = float(w.iloc[i]['high'])
        l = float(w.iloc[i]['low'])
        c = float(w.iloc[i]['close'])
        color = '#2ca581' if c >= o else '#d9653f'
        ax.vlines(i, l, h, color=color, linewidth=1.0, alpha=0.9)
        lower = min(o, c)
        height = max(1e-9, abs(c - o))
        ax.add_patch(Rectangle((i - 0.35, lower), 0.7, height, facecolor=color, edgecolor=color, linewidth=0.8))

    ax.axvline(center, color='#888', linestyle='--', linewidth=1)
    ax.axhline(entry, color='#1a8f5a', linestyle='--', linewidth=1.2, label='Entry')
    ax.axhline(sl, color='#b11e2f', linestyle='--', linewidth=1.0, label='SL')
    ax.axhline(tp1, color='#1f78b4', linestyle='--', linewidth=1.0, label='TP1')
    ax.axhline(tp2, color='#45a5ff', linestyle=':', linewidth=1.0, label='TP2')

    left = max(0, center - 14)
    right = min(len(w) - 1, center + 2)
    zone_low = float(w.iloc[left:right + 1]['low'].min())
    zone_high = float(w.iloc[left:right + 1]['high'].max())
    ax.fill_between([left, right], zone_low, zone_high, color='#f1c40f', alpha=0.12)

    ax.set_title(f"{hit.strategy_id} | {hit.instrument} {hit.timeframe} | {hit.direction.upper()} | conf {int(hit.confidence * 100)}%")
    ax.set_xlabel('Bars in sampled window')
    ax.set_ylabel('Price')
    ax.legend(loc='upper left', fontsize=8)
    ax.grid(True, alpha=0.2)

    # sparse x tick labels from datetime
    tick_idx = np.linspace(0, len(w) - 1, 6, dtype=int)
    tick_labels = [w.iloc[t]['datetime'].strftime('%Y-%m-%d %H:%M') for t in tick_idx]
    ax.set_xticks(tick_idx)
    ax.set_xticklabels(tick_labels, rotation=20, ha='right', fontsize=8)

    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)

    return {
        'sample_timeframe': f"{w.iloc[0]['datetime'].strftime('%A %d %b %Y %H:%M')} GMT - {w.iloc[-1]['datetime'].strftime('%A %d %b %Y %H:%M')} GMT",
        'center_ohlc': {
            'open': round(float(row['open']), 4),
            'high': round(float(row['high']), 4),
            'low': round(float(row['low']), 4),
            'close': round(float(row['close']), 4),
        },
        'entry': round(entry, 4),
        'sl': round(sl, 4),
        'tp1': round(tp1, 4),
        'tp2': round(tp2, 4),
    }


def run() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    datasets = [
        ('US100', DATA_ROOT / 'US100/US100.cash_M1_2023.05.24-2026.03.31'),
        ('US100', DATA_ROOT / 'US100/US100.cash_H1_2021.01.21-2026.03.31'),
        ('EURUSD', DATA_ROOT / 'EURUSD/EURUSD_M5_2012.07.27-2026.03.31'),
        ('BTCUSD', DATA_ROOT / 'BTCUSD/BTCUSD_M1_2024.04.06-2026.03.31'),
        ('XAUUSD', DATA_ROOT / 'XAUUSD/XAUUSD_M1_2023.03.13-2026.03.31'),
    ]

    scanners: List[Tuple[str, Callable[[pd.DataFrame, str, str, str], Optional[ExampleHit]]]] = [
        ('TREND_PULLBACK', find_trend_pullback),
        ('BREAKOUT_CONFIRM', find_breakout_confirm),
        ('RANGE_REVERSION', find_range_reversion),
        ('MEAN_REVERT_BAND', find_mean_revert_band),
        ('VOL_SQUEEZE', find_vol_squeeze),
        ('ORB', find_orb),
        ('MOMENTUM_CONT', find_momentum_cont),
    ]

    found: Dict[str, Dict[str, object]] = {}

    loaded: List[Tuple[str, str, str, pd.DataFrame]] = []
    for instrument, path in datasets:
        if not path.exists():
            continue
        try:
            df = load_mt_file(path)
            df = add_indicators(df)
            tf = infer_tf_label(df)
            loaded.append((instrument, tf, str(path.relative_to(ROOT)), df))
        except Exception as exc:
            print(f'WARN: failed loading {path}: {exc}')

    for strategy_id, scanner in scanners:
        hit: Optional[ExampleHit] = None
        for instrument, tf, rel_path, df in loaded:
            candidate = scanner(df, instrument, tf, rel_path)
            if candidate is not None:
                hit = candidate
                break
        if hit is None:
            print(f'WARN: no hit for {strategy_id}')
            continue

        instrument, tf, rel_path, df = next((i, t, p, d) for i, t, p, d in loaded if p == hit.dataset_path)
        start = max(0, hit.index - 40)
        end = min(len(df), hit.index + 40)
        img_path = OUT_DIR / f"{strategy_id}_GOOD_1.png"
        level_info = plot_candles(df, start, end, hit, img_path)

        meta = {
            'strategy_id': strategy_id,
            'example_type': 'GOOD',
            'instrument': hit.instrument,
            'timeframe': hit.timeframe,
            'dataset': hit.dataset_path,
            'center_timestamp': str(df.iloc[hit.index]['datetime']),
            'confidence': round(hit.confidence, 2),
            'description': hit.rationale,
            **level_info,
        }
        (OUT_DIR / f"{strategy_id}_GOOD_1.json").write_text(json.dumps(meta, indent=2))
        found[strategy_id] = meta
        print(f'OK: {strategy_id} -> {img_path.name} ({hit.instrument} {hit.timeframe})')

    summary = {
        'generated_count': len(found),
        'strategies': sorted(found.keys()),
        'output_dir': str(OUT_DIR.relative_to(ROOT)),
    }
    (OUT_DIR / 'summary.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    run()
