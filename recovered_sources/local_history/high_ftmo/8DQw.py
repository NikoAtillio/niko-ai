"""
PHANTOM p2 - Multi-Timeframe Backtest Engine
=============================================
Improvements over p1:
  1. Instrument config objects  — per-instrument session windows, ATR multipliers, TP targets
  2. Adaptive TP                — 1.3R (XAU/US100) or 1.5R (BTC) instead of fixed 2R
  3. Session gate               — hard block outside high-liquidity hours (instrument-specific)
  4. Cluster cap                — max 3 concurrent entries per 4h window
  5. Zone confirmation delay    — require N bars holding zone before entry
  6. Trend regime filter        — Daily EMA50 vs EMA200; counter-trend at 0.5x size
  7. Breakeven at 0.8R          — move stop to entry once trade reaches +0.8R
  8. Circuit breaker            — pause 24h after 5 consecutive losses
  9. Confidence position sizing — 1.5x size when session + cluster + regime all aligned
 10. Instrument ATR multipliers — XAU: 2.0x, US100: 1.5x, BTC: 1.8x

Usage
    python phantom_p2.py --instrument XAU \\
        --m1 path/M1.csv --m5 path/M5.csv --h1 path/H1.csv --h4 path/H4.csv \\
        --daily path/Daily.csv \\
        [--capital 5000]

    Instrument choices: XAU | US100 | BTC
"""

import argparse
import os
import sys
import warnings
from typing import Optional
import numpy as np
import pandas as pd
try:
    import pytz
except ImportError:
    pytz = None

warnings.filterwarnings('ignore')

ENGINE_VERSION = 'p2_ftmo'

# Aligned profile: match MT5 high-risk sizing and peak-hour boost.
HIGH_RISK_PCT_MULT = 2.0
HIGH_PEAK_SESSION_BOOST = 1.2
HIGH_PEAK_HOURS_UTC = {14, 15, 16, 17}

FTMO_CONFIG = {
    'account_size': 70_000.0,
    'profit_target_pct': 10.0,
    'max_loss_pct': 10.0,
    'max_daily_loss_pct': 5.0,
    'min_trading_days': 2,
    'trading_period_days': 0,
    'max_leverage': 30.0,
}

# ══════════════════════════════════════════════════════════════════════════════
# INSTRUMENT CONFIG
# Each instrument gets its own session window, ATR multiplier, TP ratio,
# confirmation bars, and weekend policy.
# ══════════════════════════════════════════════════════════════════════════════
INSTRUMENT_CONFIG = {
    'XAU': dict(
        # Session: tightened to 08:00–19:00 UTC; exclude 11:00 lunch lull
        session_start   = 8,
        session_end     = 19,
        session_exclude_hours = [11],
        allow_weekend   = False,
        weekend_size    = 0.0,
        # TP at 1.3R — daily range ~1.43%, 1.3R is achievable within session
        tp_mult         = 1.3,
        # ATR stop: 2.0x H4 ATR — XAU needs wider stop due to intraday noise
        atr_stop_mult   = 2.0,
        # Confirmation: require 2 H4 bars (8h) holding zone before entry
        min_confirm_bars= 2,
        confirm_tf_mins = 240,   # H4 = 240 min bars
        # Regime: Daily EMA50 vs EMA200
        regime_ema_fast = 50,
        regime_ema_slow = 200,
        # Asian session (03–07 UTC) allowed at reduced size
        soft_session_start = 3,
        soft_session_size  = 0.5,
    ),
    'US100': dict(
        # Session: Pre-market through NY close (13:00–21:00 UTC), weekdays only
        session_start   = 13,
        session_end     = 21,
        allow_weekend   = False,
        weekend_size    = 0.0,
        # TP at 1.3R — daily range ~1.93%, 1.3R is well within reach
        tp_mult         = 1.3,
        # ATR stop: 1.5x H4 ATR — US100 is cleaner, tighter stop works
        atr_stop_mult   = 1.5,
        # Confirmation: require 1 H1 bar (1h) holding zone before entry
        min_confirm_bars= 1,
        confirm_tf_mins = 60,    # H1 = 60 min bars
        regime_ema_fast = 50,
        regime_ema_slow = 200,
        # Phase 2: keep shorts at base score threshold, require stronger longs
        dir_score_offset = {'long': 1, 'short': 0},
        soft_session_start = None,
        soft_session_size  = 0.0,
    ),
    'BTC': dict(
        # Session tightened to 08:00–18:00 UTC; weekends allowed at 0.5x size
        session_start   = 8,
        session_end     = 18,
        allow_weekend   = True,
        weekend_size    = 0.5,   # 50% size on Sat/Sun
        # TP at 1.5R — BTC daily range ~3–5%, 2R is achievable but 1.5R is safer
        tp_mult         = 1.5,
        # ATR stop: 1.8x H4 ATR — keep p1 value, BTC volatility is already priced in
        atr_stop_mult   = 1.8,
        # Confirmation: require 2 H4 bars (8h) holding zone before entry
        min_confirm_bars= 2,
        confirm_tf_mins = 240,
        # Phase 3 test: allow BTC setups more time before stop exits.
        min_hold_hours  = 4,
        regime_ema_fast = 50,
        regime_ema_slow = 200,
        soft_session_start = None,
        soft_session_size  = 0.0,
    ),
}

# ══════════════════════════════════════════════════════════════════════════════
# SCENARIO CONFIG
# ══════════════════════════════════════════════════════════════════════════════
DEFAULTS = {
    'capital'       : 70_000,
    'max_concurrent': 3,
    'cooldown_min'  : 20,
    'lockout_min'   : 60,
    'conf_tol'      : 0.002,     # 0.20% zone proximity
    'h4_pivot_bars' : 2,
    'h4_lookback'   : 50,
    'circuit_breaker_losses': 5, # pause after N consecutive losses
    'circuit_breaker_hours' : 24,
    'breakeven_r'   : 0.8,       # move stop to entry at this R level
    'confidence_mult': 1.5,      # size multiplier when all 3 conditions aligned
    'confidence_min' : 0.5,      # size multiplier when low confidence
    'confidence_mode': 'inverted', # flat | inverted | score
    'confidence_score_min': 7,
}

SCENARIOS = {
    'B': dict(
        entry_tf    = 'm5',
        risk_pct    = 0.007,
        score_min   = 3,
        h4_min      = 1,
        h1_min      = 1,
        ltf_min     = 1,
        ltf_cap     = 3,
        vol_filter  = False,
        timeout_bars= None,
        atr_trail   = 0.8,
    ),
}

ACTIVE_SCENARIO_LETTER = 'B'
ACTIVE_SCENARIO_ID = f"{ENGINE_VERSION.upper()}{ACTIVE_SCENARIO_LETTER}"
ACTIVE_SCENARIO_CFG = SCENARIOS[ACTIVE_SCENARIO_LETTER]

# ══════════════════════════════════════════════════════════════════════════════
# DATA LOADING
# ══════════════════════════════════════════════════════════════════════════════
def load_csv(path: str) -> pd.DataFrame:
    """Load MetaTrader-style tab-separated OHLCV file."""
    df = pd.read_csv(path, sep='\t', header=0)
    df.columns = [c.strip('<>').lower() for c in df.columns]
    if 'date' in df.columns and 'time' in df.columns:
        date_str = df['date'].astype(str).str.strip()
        time_str = df['time'].astype(str).str.strip()
        df['datetime'] = pd.to_datetime(date_str + ' ' + time_str, errors='coerce')
        # CSV times are in NYSE local time (EST/EDT), convert to UTC for session consistency
        if pytz is not None:
            # Use pytz for proper DST handling (EST = UTC-5 in winter, EDT = UTC-4 in summer)
            nyc_tz = pytz.timezone('America/New_York')
            df['datetime'] = (df['datetime']
                              .dt.tz_localize(None)
                              .dt.tz_localize(nyc_tz, ambiguous='NaT', nonexistent='NaT')
                              .dt.tz_convert('UTC'))
        else:
            # Fallback: assume fixed EST (UTC-5) for January testing
            df['datetime'] = df['datetime'] - pd.Timedelta(hours=5)
    elif 'date' in df.columns:
        # Daily exports often omit a separate time column.
        date_str = df['date'].astype(str).str.strip()
        df['datetime'] = pd.to_datetime(date_str, errors='coerce')
    elif 'datetime' in df.columns:
        datetime_str = df['datetime'].astype(str).str.strip()
        df['datetime'] = pd.to_datetime(datetime_str, errors='coerce')
    else:
        raise ValueError(f"Cannot find datetime columns in {path}")
    df = df.dropna(subset=['datetime'])
    df = df.set_index('datetime').sort_index()
    for col in ['open', 'high', 'low', 'close', 'tickvol']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    df.dropna(subset=['open', 'high', 'low', 'close'], inplace=True)
    if 'tickvol' not in df.columns:
        df['tickvol'] = 1.0
    return df

# ══════════════════════════════════════════════════════════════════════════════
# INDICATORS
# ══════════════════════════════════════════════════════════════════════════════
def calc_atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h, l, c = df['high'], df['low'], df['close']
    tr = pd.concat(
        [h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(span=n, adjust=False).mean()

def calc_ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()

def calc_rsi(s: pd.Series, n: int = 14) -> pd.Series:
    d  = s.diff()
    g  = d.clip(lower=0).ewm(span=n, adjust=False).mean()
    ls = (-d).clip(lower=0).ewm(span=n, adjust=False).mean()
    return 100 - 100 / (1 + g / ls.replace(0, np.nan))

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df['atr']    = calc_atr(df)
    df['ema20']  = calc_ema(df['close'], 20)
    df['ema50']  = calc_ema(df['close'], 50)
    df['ema200'] = calc_ema(df['close'], 200)
    df['rsi']    = calc_rsi(df['close'])
    df['vol_ma'] = df['tickvol'].rolling(20).mean()
    return df

def add_daily_regime(daily: pd.DataFrame, inst_cfg: dict) -> pd.DataFrame:
    """Add trend regime to daily bars: 'bull' or 'bear'."""
    daily = daily.copy()
    fast = inst_cfg['regime_ema_fast']
    slow = inst_cfg['regime_ema_slow']
    daily['regime_ema_fast'] = calc_ema(daily['close'], fast)
    daily['regime_ema_slow'] = calc_ema(daily['close'], slow)
    daily['regime'] = np.where(
        daily['regime_ema_fast'] > daily['regime_ema_slow'], 'bull', 'bear'
    )
    return daily

def apply_start_date(df: pd.DataFrame, start_date: Optional[str], end_date: Optional[str] = None) -> pd.DataFrame:
    """Optionally filter a dataframe to rows within a UTC date range."""
    if start_date:
        ts = pd.Timestamp(start_date)
        df = df[df.index >= ts]
    if end_date:
        ts_end = pd.Timestamp(end_date)
        df = df[df.index <= ts_end]
    return df

# ══════════════════════════════════════════════════════════════════════════════
# FAST LOOKUP HELPERS
# ══════════════════════════════════════════════════════════════════════════════
def fast_val(idx_arr: np.ndarray, vals: np.ndarray, ts) -> float:
    i = np.searchsorted(idx_arr, ts, side='right') - 1
    return float(vals[i]) if i >= 0 else np.nan

def score_tf(idx_arr, c_arr, e20_arr, e50_arr, rsi_arr, ts, direction: str) -> int:
    """Score 0–3 for a single timeframe."""
    i = np.searchsorted(idx_arr, ts, side='right') - 1
    if i < 0:
        return 0
    c, e20, e50, rv = c_arr[i], e20_arr[i], e50_arr[i], rsi_arr[i]
    score = 0
    if direction == 'long':
        if c > e20:  score += 1
        if e20 > e50: score += 1
        if rv > 50:  score += 1
    else:
        if c < e20:  score += 1
        if e20 < e50: score += 1
        if rv < 50:  score += 1
    return score

# ══════════════════════════════════════════════════════════════════════════════
# ZONE DETECTION
# ══════════════════════════════════════════════════════════════════════════════
def build_h4_zones(h4: pd.DataFrame, pivot_bars: int = 2, lookback: int = 50):
    """Detect H4 pivot highs/lows as supply/demand zones."""
    highs = h4['high'].values
    lows  = h4['low'].values
    idx   = h4.index.values
    n     = len(h4)
    zone_ts, zone_px, zone_dir = [], [], []

    for i in range(pivot_bars, n - pivot_bars):
        # A pivot is only known after pivot_bars future candles have printed.
        confirmed_at = idx[i + pivot_bars]
        # Pivot high → supply zone (short entry)
        if all(highs[i] >= highs[i - j] for j in range(1, pivot_bars + 1)) and \
           all(highs[i] >= highs[i + j] for j in range(1, pivot_bars + 1)):
            zone_ts.append(confirmed_at)
            zone_px.append(highs[i])
            zone_dir.append('short')
        # Pivot low → demand zone (long entry)
        if all(lows[i] <= lows[i - j] for j in range(1, pivot_bars + 1)) and \
           all(lows[i] <= lows[i + j] for j in range(1, pivot_bars + 1)):
            zone_ts.append(confirmed_at)
            zone_px.append(lows[i])
            zone_dir.append('long')

    return (
        np.array(zone_ts),
        np.array(zone_px, dtype=float),
        np.array(zone_dir),
    )

# ══════════════════════════════════════════════════════════════════════════════
# SESSION & REGIME HELPERS
# ══════════════════════════════════════════════════════════════════════════════
def get_session_size_mult(ts: pd.Timestamp, inst_cfg: dict) -> float:
    """
    Returns a size multiplier based on session rules:
      1.0  = full session
      0.5  = soft session (XAU Asian) or weekend (BTC)
      0.0  = blocked (out of session)
    """
    hour = ts.hour
    dow  = ts.dayofweek  # 0=Mon, 6=Sun

    # Optional hard exclusion list for known weak hours.
    exclude_hours = inst_cfg.get('session_exclude_hours', [])
    if hour in exclude_hours:
        return 0.0

    in_core_session = inst_cfg['session_start'] <= hour < inst_cfg['session_end']

    # Weekend handling
    if dow >= 5:
        if not inst_cfg['allow_weekend']:
            return 0.0
        return inst_cfg['weekend_size'] if in_core_session else 0.0

    # Core session
    if in_core_session:
        return 1.0

    # Soft session (XAU Asian hours)
    soft_start = inst_cfg.get('soft_session_start')
    if soft_start is not None and soft_start <= hour < inst_cfg['session_start']:
        return inst_cfg.get('soft_session_size', 0.0)

    return 0.0

def get_regime(daily_idx, daily_regime, ts) -> str:
    """Look up the daily regime at timestamp ts."""
    i = np.searchsorted(daily_idx, ts, side='right') - 1
    if i < 0:
        return 'bull'  # default to bull if no data yet
    return daily_regime[i]

def get_regime_size_mult(regime: str, direction: str) -> float:
    """
    With-trend: 1.0x size.
    Counter-trend: 0.5x size (don't block, just reduce).
    """
    if regime == 'bull' and direction == 'long':
        return 1.0
    if regime == 'bear' and direction == 'short':
        return 1.0
    return 0.5  # counter-trend

# ══════════════════════════════════════════════════════════════════════════════
# ZONE CONFIRMATION DELAY
# ══════════════════════════════════════════════════════════════════════════════
def zone_is_confirmed(ts: pd.Timestamp, zone_ts_val, inst_cfg: dict) -> bool:
    """
    Returns True if enough time has passed since the zone was formed
    for it to be considered confirmed (price has held the zone for N bars).
    min_confirm_bars * confirm_tf_mins = minimum minutes since zone formation.
    """
    min_minutes = inst_cfg['min_confirm_bars'] * inst_cfg['confirm_tf_mins']
    zone_time = pd.Timestamp(zone_ts_val)
    elapsed = (ts - zone_time).total_seconds() / 60
    return elapsed >= min_minutes

# ══════════════════════════════════════════════════════════════════════════════
# CLUSTER TRACKING
# ══════════════════════════════════════════════════════════════════════════════
class ClusterTracker:
    """Tracks how many trades have been entered in each 4h window."""
    def __init__(self, max_per_window: int = 3):
        self.max_per_window = max_per_window
        self._counts: dict = {}

    def _window_key(self, ts: pd.Timestamp) -> pd.Timestamp:
        return ts.floor('4h')

    def can_enter(self, ts: pd.Timestamp) -> bool:
        key = self._window_key(ts)
        return self._counts.get(key, 0) < self.max_per_window

    def register(self, ts: pd.Timestamp):
        key = self._window_key(ts)
        self._counts[key] = self._counts.get(key, 0) + 1

    def count_in_window(self, ts: pd.Timestamp) -> int:
        return self._counts.get(self._window_key(ts), 0)

# ══════════════════════════════════════════════════════════════════════════════
# CIRCUIT BREAKER
# ══════════════════════════════════════════════════════════════════════════════
class CircuitBreaker:
    """Pauses trading for N hours after M consecutive losses."""
    def __init__(self, max_losses: int = 5, pause_hours: int = 24):
        self.max_losses   = max_losses
        self.pause_hours  = pause_hours
        self._consec      = 0
        self._paused_until: pd.Timestamp = pd.Timestamp.min

    def is_paused(self, ts: pd.Timestamp) -> bool:
        return ts < self._paused_until

    def record(self, win: bool, ts: pd.Timestamp):
        if win:
            self._consec = 0
        else:
            self._consec += 1
            if self._consec >= self.max_losses:
                self._paused_until = ts + pd.Timedelta(hours=self.pause_hours)
                self._consec = 0  # reset after triggering

    @property
    def consecutive_losses(self) -> int:
        return self._consec

# ══════════════════════════════════════════════════════════════════════════════
# EXECUTION ADJUSTMENT
# ══════════════════════════════════════════════════════════════════════════════
def apply_execution_adjustment(
    px: float, direction: str, side: str,
    spread_bps: float, slippage_bps: float
) -> float:
    half_spread = px * (spread_bps / 10_000) / 2
    slip        = px * (slippage_bps / 10_000)
    adj = half_spread + slip
    if side == 'entry':
        return px + adj if direction == 'long' else px - adj
    return px - adj if direction == 'long' else px + adj

# ══════════════════════════════════════════════════════════════════════════════
# BACKTEST ENGINE
# ══════════════════════════════════════════════════════════════════════════════
def run_scenario(
    candles: pd.DataFrame,
    h4_idx, h4_c, h4_e20, h4_e50, h4_rsi, h4_atr_arr,
    h1_idx, h1_c, h1_e20, h1_e50, h1_rsi,
    m15_idx, m15_atr_arr,
    m5_idx, m5_c, m5_e20, m5_e50, m5_rsi, m5_vol, m5_vol_ma,
    m1_idx, m1_c, m1_e20, m1_e50, m1_rsi,
    zone_ts, zone_px, zone_dir,
    daily_idx, daily_regime,
    cfg: dict,
    inst_cfg: dict,
    capital: float,
    max_concurrent: int,
    cooldown_min: int,
    lockout_min: int,
    conf_tol: float,
    spread_bps: float,
    slippage_bps: float,
    commission_per_trade: float,
    label: str,
    zone_lookback_bars: int,
) -> pd.DataFrame:

    start_cap = capital

    risk_pct    = cfg['risk_pct'] * HIGH_RISK_PCT_MULT
    score_min   = cfg['score_min']
    h4_min      = cfg['h4_min']
    h1_min      = cfg['h1_min']
    ltf_min     = cfg['ltf_min']
    ltf_cap     = cfg['ltf_cap']
    vol_filter  = cfg['vol_filter']
    timeout_bars= cfg['timeout_bars']

    # Instrument-specific params
    atr_stop    = inst_cfg['atr_stop_mult']
    tp_mult     = inst_cfg['tp_mult']
    atr_trail   = cfg.get('atr_trail', 0.8)  # Trailing stop multiplier
    breakeven_r = DEFAULTS['breakeven_r']

    # p2 components
    cluster     = ClusterTracker(max_per_window=max_concurrent)
    breaker     = CircuitBreaker(
        max_losses  = DEFAULTS['circuit_breaker_losses'],
        pause_hours = DEFAULTS['circuit_breaker_hours'],
    )

    c_idx = candles.index.values
    c_c   = candles['close'].values
    c_h   = candles['high'].values
    c_l   = candles['low'].values

    positions  = []
    results    = []
    skipped    = {'session': 0, 'cluster': 0, 'confirm': 0, 'circuit': 0,
                  'score': 0, 'concurrent': 0, 'vol': 0, 'chasing': 0,
                  'not_bounce': 0, 'ftmo': 0}
    last_entry = None
    last_loss_exit = None

    ftmo = FTMO_CONFIG
    ftmo['profit_target_cash'] = ftmo['account_size'] * (ftmo['profit_target_pct'] / 100.0)
    ftmo['max_loss_cash'] = ftmo['account_size'] * (ftmo['max_loss_pct'] / 100.0)
    ftmo['max_daily_loss_cash'] = ftmo['account_size'] * (ftmo['max_daily_loss_pct'] / 100.0)

    challenge_start_ts = pd.Timestamp(c_idx[0])
    challenge_end_ts = None
    if ftmo['trading_period_days'] > 0:
        challenge_end_ts = challenge_start_ts + pd.Timedelta(days=ftmo['trading_period_days'])
    daily_anchor = challenge_start_ts.normalize()
    daily_start_equity = capital
    traded_days = set()
    ftmo_hard_stop = False
    target_hit_ts = None
    target_hit_equity = None

    def mark_to_market(open_positions, mark_price):
        unreal = 0.0
        for p in open_positions:
            unreal += (
                (mark_price - p['entry']) * p['qty']
                if p['dir'] == 'long'
                else (p['entry'] - mark_price) * p['qty']
            )
        return unreal

    def close_positions_for_ftmo(open_positions, ts_pd, signal_px):
        nonlocal capital
        closed = []
        for p in open_positions:
            exit_px = apply_execution_adjustment(
                signal_px, p['dir'], 'exit', spread_bps, slippage_bps
            )
            gross_pnl = (
                (exit_px - p['entry']) * p['qty']
                if p['dir'] == 'long'
                else (p['entry'] - exit_px) * p['qty']
            )
            fees = commission_per_trade
            pnl = gross_pnl - fees
            capital += pnl
            risk_cash = max(1e-9, p['initial_risk_price'] * p['qty'])
            closed.append({
                'entry_ts': p['entry_ts'],
                'exit_ts': ts_pd,
                'dir': p['dir'],
                'entry': p['entry'],
                'exit': exit_px,
                'entry_price': p['entry'],
                'exit_price': exit_px,
                'entry_signal_price': p['entry_signal'],
                'exit_signal_price': signal_px,
                'stop_price': p['stop'],
                'stop_price_initial': p['stop_initial'],
                'stop_price_exit': p['stop'],
                'initial_risk_price': p['initial_risk_price'],
                'r_value': pnl / risk_cash,
                'fees': fees,
                'pnl': pnl,
                'win': pnl > 0,
                'exit_reason': 'ftmo_guardrail',
                'qty': p['qty'],
                'be_triggered': p.get('be_triggered', False),
                'confidence_mult': p.get('confidence_mult', 1.0),
                'regime': p.get('regime', 'unknown'),
            })
        return closed

    for bar_i, ts in enumerate(c_idx):
        ts_pd = pd.Timestamp(ts)
        price = c_c[bar_i]
        high  = c_h[bar_i]
        low   = c_l[bar_i]

        # ── manage open positions ─────────────────────────────────────────
        still_open = []
        for p in positions:
            exit_reason = None
            exit_signal_px = None

            # Trailing stop update (CRITICAL: must come before breakeven check)
            atr_h4_v_now = fast_val(h4_idx, h4_atr_arr, ts)
            if not np.isnan(atr_h4_v_now) and atr_h4_v_now > 0:
                trail_dist = atr_trail * p['atr_e']
                if p['dir'] == 'long':
                    new_trail = price - trail_dist
                    p['stop'] = max(p['stop'], new_trail)
                else:
                    new_trail = price + trail_dist
                    p['stop'] = min(p['stop'], new_trail)

            # Breakeven: move stop to entry once +0.8R is reached
            if not p.get('be_triggered', False):
                current_r = (
                    (price - p['entry']) / p['initial_risk_price']
                    if p['dir'] == 'long'
                    else (p['entry'] - price) / p['initial_risk_price']
                )
                if current_r >= breakeven_r:
                    p['stop'] = p['entry']
                    p['be_triggered'] = True

            # Minimum-hold stop filter (instrument-specific, timeframe-aware).
            hold_bars = bar_i - p['entry_bar']
            bar_minutes = 1 if cfg['entry_tf'] == 'm1' else 5
            bars_per_hour = max(1, 60 // bar_minutes)
            min_hold_hours = int(inst_cfg.get('min_hold_hours', 2))
            min_hold_bars = min_hold_hours * bars_per_hour

            # Only exit on stop if hold threshold is met, or trade is at/above breakeven.
            allow_stop_exit = hold_bars >= min_hold_bars
            if not allow_stop_exit:
                # Allow stop exit even under 2h if we're at/past BE or in profit
                current_r = (
                    (price - p['entry']) / p['initial_risk_price']
                    if p['dir'] == 'long'
                    else (p['entry'] - price) / p['initial_risk_price']
                )
                if current_r >= 0.0:  # At or in profit
                    allow_stop_exit = True

            if p['dir'] == 'long':
                if allow_stop_exit and low <= p['stop']:
                    exit_signal_px = p['stop']
                    exit_reason = 'stop'
                elif high >= p['tp']:
                    exit_signal_px = p['tp']
                    exit_reason = 'tp'
            else:
                if allow_stop_exit and high >= p['stop']:
                    exit_signal_px = p['stop']
                    exit_reason = 'stop'
                elif low <= p['tp']:
                    exit_signal_px = p['tp']
                    exit_reason = 'tp'

            # Timeout
            if exit_reason is None and timeout_bars is not None:
                if bar_i - p['entry_bar'] >= timeout_bars:
                    exit_signal_px = price
                    exit_reason = 'timeout'

            if exit_reason:
                exit_px = apply_execution_adjustment(
                    exit_signal_px, p['dir'], 'exit', spread_bps, slippage_bps
                )
                gross_pnl = (
                    (exit_px - p['entry']) * p['qty']
                    if p['dir'] == 'long'
                    else (p['entry'] - exit_px) * p['qty']
                )
                fees = commission_per_trade
                pnl  = gross_pnl - fees
                capital += pnl
                risk_cash = max(1e-9, p['initial_risk_price'] * p['qty'])
                r_value   = pnl / risk_cash
                win       = pnl > 0

                # Update circuit breaker
                breaker.record(win, ts_pd)
                if not win:
                    last_loss_exit = ts_pd

                results.append({
                    'entry_ts'           : p['entry_ts'],
                    'exit_ts'            : ts_pd,
                    'dir'                : p['dir'],
                    'entry'              : p['entry'],
                    'exit'               : exit_px,
                    'entry_price'        : p['entry'],
                    'exit_price'         : exit_px,
                    'entry_signal_price' : p['entry_signal'],
                    'exit_signal_price'  : exit_signal_px,
                    'stop_price'         : p['stop'],
                    'stop_price_initial' : p['stop_initial'],
                    'stop_price_exit'    : p['stop'],
                    'initial_risk_price' : p['initial_risk_price'],
                    'r_value'            : r_value,
                    'fees'               : fees,
                    'pnl'                : pnl,
                    'win'                : win,
                    'exit_reason'        : exit_reason,
                    'qty'                : p['qty'],
                    'be_triggered'       : p.get('be_triggered', False),
                    'confidence_mult'    : p.get('confidence_mult', 1.0),
                    'regime'             : p.get('regime', 'unknown'),
                })
            else:
                still_open.append(p)

        positions = still_open

        # FTMO daily reset (UTC date boundary)
        if ts_pd.normalize() != daily_anchor:
            daily_anchor = ts_pd.normalize()
            daily_start_equity = capital + mark_to_market(positions, price)

        equity_now = capital + mark_to_market(positions, price)
        daily_floor = daily_start_equity - ftmo['max_daily_loss_cash']
        total_floor = start_cap - ftmo['max_loss_cash']
        profit_target_equity = start_cap + ftmo['profit_target_cash']

        if challenge_end_ts is not None and ts_pd >= challenge_end_ts:
            ftmo_hard_stop = True
        if equity_now <= daily_floor or equity_now <= total_floor:
            ftmo_hard_stop = True
        if target_hit_ts is None and equity_now >= profit_target_equity:
            target_hit_ts = ts_pd
            target_hit_equity = equity_now

        if ftmo_hard_stop:
            if positions:
                results.extend(close_positions_for_ftmo(positions, ts_pd, price))
                positions = []
            skipped['ftmo'] += 1
            continue

        # ── entry logic ───────────────────────────────────────────────────
        if len(positions) >= max_concurrent:
            skipped['concurrent'] += 1
            continue

        # Circuit breaker check
        if breaker.is_paused(ts_pd):
            skipped['circuit'] += 1
            continue

        # Lockout after a losing exit to avoid immediate revenge entries.
        if last_loss_exit is not None:
            if (ts_pd - last_loss_exit).total_seconds() / 60 < lockout_min:
                continue

        # Cooldown
        if last_entry is not None:
            if (ts_pd - last_entry).total_seconds() / 60 < cooldown_min:
                continue

        # ── scan zones ────────────────────────────────────────────────────
        atr_h4_v = fast_val(h4_idx, h4_atr_arr, ts)
        if np.isnan(atr_h4_v) or atr_h4_v <= 0:
            continue

        # Only evaluate zones formed in a recent rolling window and before current bar.
        lookback_minutes = max(1, int(zone_lookback_bars)) * 240
        min_zone_ts = ts - np.timedelta64(lookback_minutes, 'm')
        zone_start = np.searchsorted(zone_ts, min_zone_ts, side='left')
        zone_end = np.searchsorted(zone_ts, ts, side='left')

        for z_i in range(zone_start, zone_end):
            z_ts  = zone_ts[z_i]
            z_px  = zone_px[z_i]
            z_dir = zone_dir[z_i]

            # Zone proximity check
            if abs(price - z_px) / z_px > conf_tol:
                continue

            # ── NOT-CHASING FILTER: entry must be within 1.5x M15 ATR of zone ──
            m15_atr_v = fast_val(m15_idx, m15_atr_arr, ts)
            if not np.isnan(m15_atr_v) and m15_atr_v > 0:
                if abs(price - z_px) > 1.5 * m15_atr_v:
                    skipped['chasing'] += 1
                    continue

            # ── BOUNCE-ONLY FILTER: price approaching from opposite side ──────
            # For a long zone (demand), price must be coming from above (bounce into support)
            # For a short zone (supply), price must be coming from below (bounce into resistance)
            if z_dir == 'long' and price < z_px * (1 - conf_tol):
                skipped['not_bounce'] += 1
                continue  # price already broke below — not a bounce
            if z_dir == 'short' and price > z_px * (1 + conf_tol):
                skipped['not_bounce'] += 1
                continue  # price already broke above — not a bounce

            # ── p2 FILTER 1: Session gate ─────────────────────────────────
            session_mult = get_session_size_mult(ts_pd, inst_cfg)
            if ts_pd.dayofweek < 5 and ts_pd.hour in HIGH_PEAK_HOURS_UTC:
                session_mult *= HIGH_PEAK_SESSION_BOOST
            if session_mult == 0.0:
                skipped['session'] += 1
                continue

            # ── p2 FILTER 2: Zone confirmation delay ──────────────────────
            if not zone_is_confirmed(ts_pd, z_ts, inst_cfg):
                skipped['confirm'] += 1
                continue

            # ── p2 FILTER 3: Cluster cap ──────────────────────────────────
            if not cluster.can_enter(ts_pd):
                skipped['cluster'] += 1
                continue

            # ── p2 FILTER 4: Trend regime ─────────────────────────────────
            regime = get_regime(daily_idx, daily_regime, ts)
            regime_mult = get_regime_size_mult(regime, z_dir)

            # ── Multi-timeframe score ─────────────────────────────────────
            h4_score = score_tf(h4_idx, h4_c, h4_e20, h4_e50, h4_rsi, ts, z_dir)
            h1_score = score_tf(h1_idx, h1_c, h1_e20, h1_e50, h1_rsi, ts, z_dir)

            if cfg['entry_tf'] == 'm1':
                ltf_score = score_tf(m1_idx, m1_c, m1_e20, m1_e50, m1_rsi, ts, z_dir)
            else:
                ltf_score = score_tf(m5_idx, m5_c, m5_e20, m5_e50, m5_rsi, ts, z_dir)

            if h4_score < h4_min:
                skipped['score'] += 1
                continue
            if h1_score < h1_min:
                skipped['score'] += 1
                continue
            if ltf_score < ltf_min:
                skipped['score'] += 1
                continue

            total_score = h4_score + h1_score + ltf_score
            dir_score_offset = inst_cfg.get('dir_score_offset', {})
            effective_score_min = score_min + int(dir_score_offset.get(z_dir, 0))
            if total_score < effective_score_min:
                skipped['score'] += 1
                continue
            if ltf_score > ltf_cap:
                skipped['score'] += 1
                continue

            # Volume filter (Scenario A only)
            if vol_filter:
                if cfg['entry_tf'] == 'm1':
                    # Align M1 entry timestamp to the latest available M5 bar.
                    i_m5 = np.searchsorted(m5_idx, ts, side='right') - 1
                    vol_ok = (
                        i_m5 >= 0
                        and i_m5 < len(m5_vol)
                        and i_m5 < len(m5_vol_ma)
                        and m5_vol[i_m5] > m5_vol_ma[i_m5]
                    )
                else:
                    i_ltf = np.searchsorted(m5_idx, ts, side='right') - 1
                    vol_ok = (i_ltf >= 0 and
                              m5_vol[i_ltf] > m5_vol_ma[i_ltf])
                if not vol_ok:
                    skipped['vol'] += 1
                    continue

            # ── p2 CONFIDENCE SCORING ─────────────────────────────────────
            # Phase 2 supports configurable confidence modes.
            cluster_count = cluster.count_in_window(ts_pd)
            in_peak_session = (
                inst_cfg['session_start'] <= ts_pd.hour < inst_cfg['session_end']
                and ts_pd.dayofweek < 5
            )
            confidence_mode = DEFAULTS.get('confidence_mode', 'flat')
            confidence_score_min = int(DEFAULTS.get('confidence_score_min', 7))

            if confidence_mode == 'flat':
                conf_mult = 1.0
            elif confidence_mode == 'inverted':
                # True inverted confidence: first cluster touch gets the size premium.
                conf_mult = DEFAULTS['confidence_mult'] if cluster_count == 0 else 1.0
            elif confidence_mode == 'score':
                conf_mult = (
                    DEFAULTS['confidence_mult']
                    if (in_peak_session and total_score >= confidence_score_min)
                    else 1.0
                )
            else:
                conf_mult = 1.0

            # ── Position sizing ───────────────────────────────────────────
            stop_dist  = atr_stop * atr_h4_v
            remaining_daily = max(0.0, equity_now - daily_floor)
            remaining_total = max(0.0, equity_now - total_floor)
            risk_amt = min(capital * risk_pct, remaining_daily, remaining_total)
            if risk_amt <= 0.0:
                skipped['ftmo'] += 1
                continue
            stop_px    = price - stop_dist if z_dir == 'long' else price + stop_dist
            tp_px      = (price + tp_mult * stop_dist if z_dir == 'long'
                          else price - tp_mult * stop_dist)

            entry_exec = apply_execution_adjustment(
                price, z_dir, 'entry', spread_bps, slippage_bps
            )
            initial_risk_price = abs(entry_exec - stop_px)
            if initial_risk_price <= 0:
                initial_risk_price = stop_dist if stop_dist > 0 else 1e-9

            # Apply all size multipliers
            size_mult = session_mult * regime_mult * conf_mult
            qty = (risk_amt / initial_risk_price) * size_mult if initial_risk_price > 0 else 0

            # FTMO leverage cap: max notional <= equity * 30
            max_notional = max(0.0, equity_now * ftmo['max_leverage'])
            if entry_exec > 0 and max_notional > 0:
                qty = min(qty, max_notional / entry_exec)

            if qty <= 0:
                continue

            # Register entry
            cluster.register(ts_pd)
            last_entry = ts_pd
            traded_days.add(ts_pd.normalize())

            positions.append({
                'entry_ts'          : ts_pd,
                'entry_bar'         : bar_i,
                'dir'               : z_dir,
                'entry'             : entry_exec,
                'entry_signal'      : price,
                'stop'              : stop_px,
                'stop_initial'      : stop_px,
                'tp'                : tp_px,
                'initial_risk_price': initial_risk_price,
                'qty'               : qty,
                'be_triggered'      : False,
                'confidence_mult'   : conf_mult,
                'regime'            : regime,
                'atr_e'             : atr_h4_v,  # Store H4 ATR at entry for trailing stop
            })

            # Only take one zone per bar
            break

    # ── close any remaining open positions at last bar ────────────────────
    for p in positions:
        exit_signal_px = c_c[-1]
        exit_px = apply_execution_adjustment(
            exit_signal_px, p['dir'], 'exit', spread_bps, slippage_bps
        )
        gross_pnl = (
            (exit_px - p['entry']) * p['qty']
            if p['dir'] == 'long'
            else (p['entry'] - exit_px) * p['qty']
        )
        fees  = commission_per_trade
        pnl   = gross_pnl - fees
        capital += pnl
        risk_cash = max(1e-9, p['initial_risk_price'] * p['qty'])
        r_value   = pnl / risk_cash
        results.append({
            'entry_ts'           : p['entry_ts'],
            'exit_ts'            : pd.Timestamp(c_idx[-1]),
            'dir'                : p['dir'],
            'entry'              : p['entry'],
            'exit'               : exit_px,
            'entry_price'        : p['entry'],
            'exit_price'         : exit_px,
            'entry_signal_price' : p['entry_signal'],
            'exit_signal_price'  : exit_signal_px,
            'stop_price'         : p['stop'],
            'stop_price_initial' : p['stop_initial'],
            'stop_price_exit'    : p['stop'],
            'initial_risk_price' : p['initial_risk_price'],
            'r_value'            : r_value,
            'fees'               : fees,
            'pnl'                : pnl,
            'win'                : pnl > 0,
            'exit_reason'        : 'eod',
            'qty'                : p['qty'],
            'be_triggered'       : p.get('be_triggered', False),
            'confidence_mult'    : p.get('confidence_mult', 1.0),
            'regime'             : p.get('regime', 'unknown'),
        })

    df_r = pd.DataFrame(results)
    _print_summary(
        df_r,
        label,
        capital,
        skipped,
        start_cap=start_cap,
        target_hit_ts=target_hit_ts,
        target_hit_equity=target_hit_equity,
        target_equity=profit_target_equity,
    )
    return df_r

# ══════════════════════════════════════════════════════════════════════════════
# REPORTING
# ══════════════════════════════════════════════════════════════════════════════
def _print_summary(df_r: pd.DataFrame, label: str, final_cap: float,
                   skipped: dict, start_cap: float = 5_000,
                   target_hit_ts=None, target_hit_equity=None,
                   target_equity: float = None):
    if df_r is None or len(df_r) == 0:
        print(f"\n{label}: 0 trades"); return

    entry_times = pd.to_datetime(df_r['entry_ts'])
    exit_times = pd.to_datetime(df_r['exit_ts'])
    test_start = entry_times.min()
    test_end = exit_times.max()

    trades = len(df_r)
    wr     = df_r['win'].mean() * 100
    gw     = df_r[df_r['win']]['pnl'].sum()
    gl     = df_r[~df_r['win']]['pnl'].sum()
    pf     = abs(gw / gl) if gl != 0 else float('inf')
    net    = df_r['pnl'].sum()
    ret    = net / start_cap * 100
    eq     = start_cap + df_r['pnl'].cumsum()
    peak   = eq.cummax()
    dd     = ((eq - peak) / peak).min() * 100
    exp    = df_r['pnl'].mean()
    t_pct  = (df_r['exit_reason'] == 'timeout').mean() * 100
    be_pct = df_r.get('be_triggered', pd.Series([False]*trades)).mean() * 100

    # Weekly trade count
    df_r['_week'] = pd.to_datetime(df_r['entry_ts']).dt.to_period('W')
    weeks = df_r['_week'].nunique()
    tpw   = trades / weeks if weeks > 0 else 0

    pf_flag  = '✅' if pf  >= 1.5  else ('⚠️' if pf >= 1.2 else '❌')
    dd_flag  = '✅' if dd  >= -8   else '❌'
    wr_flag  = '✅' if wr  >= 50   else ('⚠️' if wr >= 45 else '❌')
    ret_flag = '✅' if ret > 0     else '❌'

    print(f"\n{'='*56}")
    print(f"  {label}")
    print(f"{'='*56}")
    print(f"  Trades      : {trades}  ({tpw:.1f}/week)")
    print(f"  Win %       : {wr:.1f}%   {wr_flag}")
    print(f"  PF          : {pf:.3f}  {pf_flag}")
    print(f"  Net Return  : {ret:.2f}%  {ret_flag}")
    print(f"  Max DD      : {dd:.2f}%  {dd_flag}")
    print(f"  Expectancy  : ${exp:.2f}/trade")
    print(f"  Final Cap   : ${final_cap:,.2f}")
    print(f"  Test Span   : {test_start} → {test_end} ({test_end - test_start})")
    if target_equity is not None:
        if target_hit_ts is not None:
            elapsed = pd.Timestamp(target_hit_ts) - pd.Timestamp(df_r['entry_ts'].min())
            days = elapsed.days
            hours = elapsed.components.hours
            print(f"  10% Target  : hit at {target_hit_ts} ({days}d {hours}h) | equity ${target_hit_equity:,.2f}")
        else:
            print(f"  10% Target  : not reached | target equity ${target_equity:,.2f}")

    monthly = (
        df_r.assign(month=exit_times.dt.to_period('M').dt.to_timestamp('M'))
           .groupby('month', as_index=False)['pnl']
           .sum()
           .sort_values('month')
    )
    monthly['cumulative'] = monthly['pnl'].cumsum()
    print("  Monthly PnL / Cumulative:")
    for _, row in monthly.iterrows():
        month_label = pd.Timestamp(row['month']).date()
        print(f"    {month_label}: pnl ${row['pnl']:,.2f} | cum ${row['cumulative']:,.2f}")

    print(f"  Breakeven % : {be_pct:.1f}%")
    print(f"  Timeout %   : {t_pct:.1f}%")
    print(f"  Skipped     : {skipped}")

# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(description=f'Phantom {ENGINE_VERSION} Backtest')
    parser.add_argument('--instrument',  required=True,
                        choices=['XAU', 'US100', 'BTC'],
                        help='Instrument: XAU | US100 | BTC')
    parser.add_argument('--m1',          required=True,  help='Path to M1 CSV')
    parser.add_argument('--m5',          required=True,  help='Path to M5 CSV')
    parser.add_argument('--h1',          required=True,  help='Path to H1 CSV')
    parser.add_argument('--h4',          required=True,  help='Path to H4 CSV')
    parser.add_argument('--daily',       required=True,  help='Path to Daily CSV (for regime filter)')
    parser.add_argument('--m15',         required=True,  help='Path to M15 CSV (for not-chasing filter)')
    parser.add_argument('--capital',     type=float, default=70_000)
    parser.add_argument('--output-dir',  default='.',
                        help='Directory to save trade CSV outputs')
    parser.add_argument('--spread-bps',  type=float, default=0.0,
                        help='Round-trip spread in bps')
    parser.add_argument('--slippage-bps',type=float, default=0.0,
                        help='Adverse slippage per side in bps')
    parser.add_argument('--commission-per-trade', type=float, default=0.0,
                        help='Fixed commission per closed trade')
    parser.add_argument('--start-date', default=None,
                        help='Optional start date filter (YYYY-MM-DD) applied to all timeframes')
    parser.add_argument('--end-date', default=None,
                        help='Optional end date filter (YYYY-MM-DD) applied to all timeframes')
    parser.add_argument('--disable-ftmo', action='store_true',
                        help='Run without FTMO guardrails (for comparison)')
    args = parser.parse_args()

    output_dir = args.output_dir or '.'
    os.makedirs(output_dir, exist_ok=True)

    inst_cfg = INSTRUMENT_CONFIG[args.instrument]

    # Optionally disable FTMO guardrails for comparison runs
    if getattr(args, 'disable_ftmo', False):
        FTMO_CONFIG['profit_target_pct'] = 999999.0
        FTMO_CONFIG['max_loss_pct'] = 999999.0
        FTMO_CONFIG['max_daily_loss_pct'] = 999999.0
        FTMO_CONFIG['min_trading_days'] = 0
    print(f"\nPhantom {ENGINE_VERSION.upper()} | Instrument: {args.instrument}")
    print(
        f"  Session: {inst_cfg['session_start']:02d}:00–{inst_cfg['session_end']:02d}:00 UTC"
        f"  | TP: {inst_cfg['tp_mult']}R"
        f"  | ATR stop: {inst_cfg['atr_stop_mult']}x"
        f"  | Confirm: {inst_cfg['min_confirm_bars']} bars"
    )
    print(
        f"  FTMO: Target {FTMO_CONFIG['profit_target_pct']:.1f}% | "
        f"Max Daily Loss {FTMO_CONFIG['max_daily_loss_pct']:.1f}% | "
        f"Max Loss {FTMO_CONFIG['max_loss_pct']:.1f}% | "
        f"Leverage 1:{int(FTMO_CONFIG['max_leverage'])}"
    )

    print("\nLoading data...")
    m1    = apply_start_date(add_indicators(load_csv(args.m1)), args.start_date, args.end_date)
    m5    = apply_start_date(add_indicators(load_csv(args.m5)), args.start_date, args.end_date)
    h1    = apply_start_date(add_indicators(load_csv(args.h1)), args.start_date, args.end_date)
    h4    = apply_start_date(add_indicators(load_csv(args.h4)), args.start_date, args.end_date)
    m15   = apply_start_date(add_indicators(load_csv(args.m15)), args.start_date, args.end_date)
    daily = apply_start_date(add_indicators(load_csv(args.daily)), args.start_date, args.end_date)
    daily = add_daily_regime(daily, inst_cfg)
    print(f"  M1:{len(m1)}  M5:{len(m5)}  M15:{len(m15)}  H1:{len(h1)}  H4:{len(h4)}  Daily:{len(daily)}")

    print("\nBuilding H4 pivot zones...")
    zone_ts, zone_px, zone_dir = build_h4_zones(
        h4,
        pivot_bars=DEFAULTS['h4_pivot_bars'],
        lookback=DEFAULTS['h4_lookback'],
    )
    print(f"  {len(zone_ts)} zones found")

    # Regime arrays
    daily_idx    = daily.index.values
    daily_regime = daily['regime'].values

    # Cache numpy arrays
    arrays = dict(
        h4_idx=h4.index.values,   h4_c=h4['close'].values,
        h4_e20=h4['ema20'].values, h4_e50=h4['ema50'].values,
        h4_rsi=h4['rsi'].values,   h4_atr_arr=h4['atr'].values,
        h1_idx=h1.index.values,   h1_c=h1['close'].values,
        h1_e20=h1['ema20'].values, h1_e50=h1['ema50'].values,
        h1_rsi=h1['rsi'].values,
        m15_idx=m15.index.values,  m15_atr_arr=m15['atr'].values,
        m5_idx=m5.index.values,   m5_c=m5['close'].values,
        m5_e20=m5['ema20'].values, m5_e50=m5['ema50'].values,
        m5_rsi=m5['rsi'].values,
        m5_vol=m5['tickvol'].values, m5_vol_ma=m5['vol_ma'].values,
        m1_idx=m1.index.values,   m1_c=m1['close'].values,
        m1_e20=m1['ema20'].values, m1_e50=m1['ema50'].values,
        m1_rsi=m1['rsi'].values,
    )

    cfg = ACTIVE_SCENARIO_CFG
    sc_id = ACTIVE_SCENARIO_ID
    candles = m1 if cfg['entry_tf'] == 'm1' else m5
    # Show which timeframe is used for entries and the actual candle ranges
    print(f"\n  Entry TF: {cfg['entry_tf'].upper()} | Candles Range: {candles.index[0]} → {candles.index[-1]}")
    # Also print M1 range to highlight any mismatch between M1 and the entry timeframe
    print(f"  M1 Range: {m1.index[0]} → {m1.index[-1]}")
    print(f"\nRunning Scenario {sc_id}...")
    df_r = run_scenario(
        candles=candles,
        zone_ts=zone_ts, zone_px=zone_px, zone_dir=zone_dir,
        daily_idx=daily_idx, daily_regime=daily_regime,
        cfg=cfg,
        inst_cfg=inst_cfg,
        capital=args.capital,
        max_concurrent=DEFAULTS['max_concurrent'],
        cooldown_min=DEFAULTS['cooldown_min'],
        lockout_min=DEFAULTS['lockout_min'],
        conf_tol=DEFAULTS['conf_tol'],
        spread_bps=args.spread_bps,
        slippage_bps=args.slippage_bps,
        commission_per_trade=args.commission_per_trade,
        zone_lookback_bars=DEFAULTS['h4_lookback'],
        label=(f"Scenario {sc_id} | {args.instrument} | "
             f"{cfg['entry_tf'].upper()} entry | risk={(cfg['risk_pct'] * HIGH_RISK_PCT_MULT)*100:.2f}%"),
        **arrays,
    )
    if df_r is not None and len(df_r):
        out = os.path.join(output_dir, f'phantom_{ENGINE_VERSION}_trades_{args.instrument}_{sc_id}.csv')
        df_r.to_csv(out, index=False)
        print(f"  Trades saved → {out}")

    print("\nDone.")


if __name__ == '__main__':
    main()