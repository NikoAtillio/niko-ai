#!/usr/bin/env python3
from __future__ import annotations

"""
PHANTOM Strategy Backtest — XAUUSD 1M
======================================
P.H.A.N.T.O.M — Price Hunting After Micro Trap On Momentum

5-Layer Confluence System:
  Layer 1: H1 EMA21 trend bias (context filter)
  Layer 2: Micro-trap detection — sweep of 8-candle swing high/low on 1M
  Layer 3: Volume confirmation — trap candle volume >= 1.4x 20-bar average
  Layer 4: Momentum confirmation — follow-through candle closes in reversal direction
  Layer 5: Session gate — London/NY overlap only (07:00–16:00 UTC)

Risk Management:
  - ATR-based stop loss (beyond trap wick + 1 tick)
  - Partial exit at 1R (50% of position)
  - Move stop to break-even after partial exit
  - Remaining 50% targets 2R
  - Max 3 concurrent positions
  - Daily loss circuit breaker at -2%

Author: PHANTOM Strategy Engine v1.0
"""

import os
import sys
import argparse
import requests
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timezone, timedelta
from collections import defaultdict
import warnings
warnings.filterwarnings('ignore')

# ============================================================
# CONFIGURATION — tune these parameters
# ============================================================

# Capital
STARTING_CAPITAL     = 10_000.0   # USD (or GBP — just a unit)
RISK_PER_TRADE_PCT   = 0.005      # 0.5% risk per trade

# Layer 2 — Micro Trap
SWING_LOOKBACK       = 8          # candles to define swing high/low
SWEEP_TICK_MIN       = 0.10       # min sweep beyond swing (USD for Gold)
SWEEP_TICK_MAX       = 15.0        # max sweep — larger = messy, not a trap
WICK_RATIO_MIN       = 0.48       # wick must be >= 55% of candle range

# Layer 3 — Volume
VOLUME_MULT          = 1.15        # trap candle volume >= 1.4x 20-bar avg

# Layer 4 — Momentum
# Follow-through candle must close in reversal direction (boolean check)

# Layer 5 — Session (UTC hours, inclusive)
SESSION_START_UTC    = 7          # London open
SESSION_END_UTC      = 16         # NY afternoon

# Stop & Target
ATR_PERIOD           = 14         # ATR for stop sizing
ATR_STOP_MULT        = 0.5        # stop = wick_extreme + ATR * mult
PARTIAL_EXIT_R       = 1.0        # take 50% off at 1R
PARTIAL_FRACTION     = 0.5        # fraction to close at partial
FULL_EXIT_R          = 2.0        # close remainder at 2R
MOVE_STOP_TO_BE      = True       # move stop to entry after partial

# Position limits
MAX_CONCURRENT       = 3
DAILY_LOSS_LIMIT_PCT = 0.02       # circuit breaker: stop trading if -2% on day

# Fees
TAKER_FEE_PCT        = 0.00007   # 0.007% per side (raw spread account Gold)

# Data
SYMBOL               = "XAUUSD"
INTERVAL             = "1m"
LOOKBACK_DAYS        = 30         # days of 1M data to fetch

# H1 bias EMA
H1_EMA_PERIOD        = 21

# ============================================================
# ARGUMENT PARSER
# ============================================================

def parse_args():
    p = argparse.ArgumentParser(description="PHANTOM XAUUSD 1M Backtest")
    p.add_argument("--days",      type=int,   default=LOOKBACK_DAYS,    help="Lookback days")
    p.add_argument("--capital",   type=float, default=STARTING_CAPITAL, help="Starting capital")
    p.add_argument("--risk",      type=float, default=RISK_PER_TRADE_PCT,help="Risk per trade (0.005 = 0.5%%)")
    p.add_argument("--outdir",    type=str,   default=".",              help="Output directory")
    p.add_argument("--skip-plots",action="store_true",                  help="Skip chart generation")
    p.add_argument("--symbol",    type=str,   default=SYMBOL,           help="Symbol (default XAUUSD)")
    return p.parse_args()

# ============================================================
# DATA FETCHING — Binance (XAUUSDT proxy) or yfinance fallback
# ============================================================

def fetch_1m_data_yfinance(symbol: str, days: int) -> pd.DataFrame:
    """Fetch 1M OHLCV data via yfinance (max 7 days per call, loop for more)."""
    try:
        import yfinance as yf
    except ImportError:
        print("Installing yfinance...")
        os.system(f"{sys.executable} -m pip install yfinance -q")
        import yfinance as yf

    ticker_map = {
        "XAUUSD": "GC=F",   # Gold futures
        "EURUSD": "EURUSD=X",
        "GBPUSD": "GBPUSD=X",
        "BTCUSD": "BTC-USD",
    }
    ticker = ticker_map.get(symbol.upper(), symbol)

    # yfinance 1m max 7 days per request — chunk it
    all_frames = []
    end = datetime.now(timezone.utc)
    chunk_days = 7
    fetched = 0

    while fetched < days:
        fetch_n = min(chunk_days, days - fetched)
        start = end - timedelta(days=fetch_n)
        print(f"  Fetching {ticker} 1m: {start.date()} → {end.date()}")
        df_chunk = yf.download(ticker, start=start, end=end, interval="1m",
                               progress=False, auto_adjust=True)
        if df_chunk.empty:
            break
        all_frames.append(df_chunk)
        end = start
        fetched += fetch_n

    if not all_frames:
        raise ValueError(f"No data returned for {symbol}")

    df = pd.concat(all_frames).sort_index()
    df = df[~df.index.duplicated(keep='first')]

    # Flatten MultiIndex columns if present
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.rename(columns={
        "Open": "open", "High": "high", "Low": "low",
        "Close": "close", "Volume": "volume"
    })
    df.index = pd.to_datetime(df.index, utc=True)
    df = df[["open", "high", "low", "close", "volume"]].dropna()
    print(f"  Loaded {len(df):,} 1M candles for {symbol}")
    return df


def fetch_data(symbol: str, days: int) -> pd.DataFrame:
    print(f"\nFetching {days}-day 1M data for {symbol}...")
    return fetch_1m_data_yfinance(symbol, days)


# ============================================================
# INDICATOR HELPERS
# ============================================================

def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h, l, c = df['high'], df['low'], df['close']
    prev_c = c.shift(1)
    tr = pd.concat([h - l, (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def compute_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def resample_to_h1(df_1m: pd.DataFrame) -> pd.DataFrame:
    """Resample 1M data to H1 for trend bias."""
    df_h1 = df_1m.resample('1h').agg({
        'open':   'first',
        'high':   'max',
        'low':    'min',
        'close':  'last',
        'volume': 'sum'
    }).dropna()
    df_h1['ema21'] = compute_ema(df_h1['close'], H1_EMA_PERIOD)
    return df_h1


# ============================================================
# LAYER 2 — MICRO TRAP DETECTION
# ============================================================

def detect_trap(df: pd.DataFrame, i: int) -> dict | None:
    """
    Detect a micro-trap at candle i.
    A bullish trap: price sweeps BELOW the 8-candle swing low, then closes ABOVE it.
    A bearish trap: price sweeps ABOVE the 8-candle swing high, then closes BELOW it.

    Returns dict with trap info or None.
    """
    if i < SWING_LOOKBACK + 1:
        return None

    candle = df.iloc[i]
    lookback = df.iloc[i - SWING_LOOKBACK: i]  # last 8 candles (not including current)

    swing_low  = lookback['low'].min()
    swing_high = lookback['high'].max()

    candle_range = candle['high'] - candle['low']
    if candle_range < 1e-6:
        return None

    # --- Bullish trap: wick sweeps below swing_low, body closes above it ---
    body_low  = min(candle['open'], candle['close'])
    body_high = max(candle['open'], candle['close'])

    sweep_below = swing_low - candle['low']   # how far below swing_low the wick went
    if (SWEEP_TICK_MIN <= sweep_below <= SWEEP_TICK_MAX and
            body_low >= swing_low and                          # body closes above swing_low
            candle['close'] > candle['open']):                 # bullish close
        wick_size = swing_low - candle['low']
        wick_ratio = wick_size / candle_range
        if wick_ratio >= WICK_RATIO_MIN:
            return {
                'direction': 'long',
                'trap_low':  candle['low'],
                'swing_ref': swing_low,
                'sweep':     sweep_below,
                'wick_ratio': wick_ratio,
            }

    # --- Bearish trap: wick sweeps above swing_high, body closes below it ---
    sweep_above = candle['high'] - swing_high
    if (SWEEP_TICK_MIN <= sweep_above <= SWEEP_TICK_MAX and
            body_high <= swing_high and                        # body closes below swing_high
            candle['close'] < candle['open']):                 # bearish close
        wick_size = candle['high'] - swing_high
        wick_ratio = wick_size / candle_range
        if wick_ratio >= WICK_RATIO_MIN:
            return {
                'direction': 'short',
                'trap_high': candle['high'],
                'swing_ref': swing_high,
                'sweep':     sweep_above,
                'wick_ratio': wick_ratio,
            }

    return None


# ============================================================
# TRADE CLASS
# ============================================================

class PhantomTrade:
    _id_counter = 0

    def __init__(self, direction, entry_price, entry_time, stop_loss,
                 target1, target2, risk_usd, position_size):
        PhantomTrade._id_counter += 1
        self.trade_id      = PhantomTrade._id_counter
        self.direction     = direction       # 'long' | 'short'
        self.entry_price   = entry_price
        self.entry_time    = entry_time
        self.stop_loss     = stop_loss
        self.target1       = target1         # 1R — partial exit
        self.target2       = target2         # 2R — full exit
        self.risk_usd      = risk_usd        # dollar risk on full position
        self.position_size = position_size   # units (oz for Gold)
        self.remaining     = position_size

        self.partial_done  = False
        self.be_moved      = False
        self.status        = 'open'          # open | closed
        self.exit_price    = None
        self.exit_time     = None
        self.exit_reason   = None
        self.realised_pnl  = 0.0
        self.fees_paid     = 0.0

    def check_and_update(self, candle, capital):
        """
        Process one candle. Returns list of (pnl, fee, close_fraction, reason) events.
        """
        events = []
        h, l = candle['high'], candle['low']

        if self.direction == 'long':
            # Stop hit
            if l <= self.stop_loss:
                pnl, fee = self._close(self.remaining, self.stop_loss)
                events.append((pnl, fee, 1.0, 'stop_loss'))
                return events

            # Target 1 — partial
            if not self.partial_done and h >= self.target1:
                close_qty = self.remaining * PARTIAL_FRACTION
                pnl, fee = self._close(close_qty, self.target1)
                self.partial_done = True
                events.append((pnl, fee, PARTIAL_FRACTION, 'target1'))
                if MOVE_STOP_TO_BE:
                    self.stop_loss = self.entry_price
                    self.be_moved  = True

            # Target 2 — full
            if self.partial_done and h >= self.target2:
                pnl, fee = self._close(self.remaining, self.target2)
                events.append((pnl, fee, 1.0, 'target2'))

        else:  # short
            # Stop hit
            if h >= self.stop_loss:
                pnl, fee = self._close(self.remaining, self.stop_loss)
                events.append((pnl, fee, 1.0, 'stop_loss'))
                return events

            # Target 1 — partial
            if not self.partial_done and l <= self.target1:
                close_qty = self.remaining * PARTIAL_FRACTION
                pnl, fee = self._close(close_qty, self.target1)
                self.partial_done = True
                events.append((pnl, fee, PARTIAL_FRACTION, 'target1'))
                if MOVE_STOP_TO_BE:
                    self.stop_loss = self.entry_price
                    self.be_moved  = True

            # Target 2 — full
            if self.partial_done and l <= self.target2:
                pnl, fee = self._close(self.remaining, self.target2)
                events.append((pnl, fee, 1.0, 'target2'))

        return events

    def _close(self, qty, price):
        if self.direction == 'long':
            pnl = (price - self.entry_price) * qty
        else:
            pnl = (self.entry_price - price) * qty

        fee = (self.entry_price + price) * qty * TAKER_FEE_PCT
        self.remaining     -= qty
        self.realised_pnl  += pnl - fee
        self.fees_paid     += fee

        if self.remaining <= 1e-9:
            self.status      = 'closed'
            self.exit_price  = price
            self.exit_time   = None   # set by caller
        return pnl, fee

    def force_close(self, price, time, reason='end_of_data'):
        pnl, fee = self._close(self.remaining, price)
        self.exit_time   = time
        self.exit_reason = reason
        return pnl, fee


# ============================================================
# BACKTEST ENGINE
# ============================================================

def run_backtest(df_1m: pd.DataFrame, df_h1: pd.DataFrame,
                 starting_capital: float, risk_pct: float,
                 skip_plots: bool, outdir: str, symbol: str):

    print("\n" + "="*70)
    print("  PHANTOM STRATEGY BACKTEST — " + symbol + " 1M")
    print("="*70)

    # Pre-compute indicators on 1M
    df_1m = df_1m.copy()
    df_1m['atr']        = compute_atr(df_1m, ATR_PERIOD)
    df_1m['vol_ma20']   = df_1m['volume'].rolling(20).mean()
    df_1m['hour_utc']   = df_1m.index.hour

    # Build H1 EMA lookup: for each 1M candle, find the H1 EMA21 value
    # Map each 1M timestamp to its H1 bar
    h1_ema_series = df_h1['ema21']

    def get_h1_ema(ts):
        """Get H1 EMA21 at or before timestamp ts."""
        idx = h1_ema_series.index.searchsorted(ts, side='right') - 1
        if idx < 0:
            return None
        return h1_ema_series.iloc[idx]

    # State
    capital        = starting_capital
    peak_capital   = capital
    day_start_cap  = capital
    current_day    = None
    day_halted     = False

    open_trades    = []
    closed_trades  = []
    equity_curve   = []

    skip_reasons   = defaultdict(int)
    total_fees     = 0.0

    # Reset trade ID counter
    PhantomTrade._id_counter = 0

    print(f"\n  Starting capital : {capital:,.2f}")
    print(f"  Risk per trade   : {risk_pct*100:.2f}%  =  {capital*risk_pct:.2f} per trade")
    print(f"  Session          : {SESSION_START_UTC:02d}:00 – {SESSION_END_UTC:02d}:00 UTC")
    print(f"  Data range       : {df_1m.index[0].date()} → {df_1m.index[-1].date()}")
    print(f"  Total 1M candles : {len(df_1m):,}\n")

    for i in range(SWING_LOOKBACK + 2, len(df_1m)):
        candle     = df_1m.iloc[i]
        ts         = df_1m.index[i]
        close      = candle['close']

        # Daily reset
        day = ts.date()
        if day != current_day:
            current_day    = day
            day_start_cap  = capital
            day_halted     = False

        # ---- Process exits on open trades ----
        trades_to_close = []
        for trade in open_trades:
            events = trade.check_and_update(candle, capital)
            for pnl, fee, fraction, reason in events:
                capital    += pnl - fee
                total_fees += fee
                if trade.remaining <= 1e-9:
                    trade.exit_time   = ts
                    trade.exit_reason = reason
                    trades_to_close.append(trade)

        for t in trades_to_close:
            open_trades.remove(t)
            closed_trades.append(t)

        # Equity snapshot (cash basis — no MTM distortion)
        equity_curve.append({'ts': ts, 'equity': capital})
        if capital > peak_capital:
            peak_capital = capital

        # ---- Daily circuit breaker ----
        daily_loss = (capital - day_start_cap) / day_start_cap
        if daily_loss <= -DAILY_LOSS_LIMIT_PCT:
            day_halted = True

        if day_halted:
            skip_reasons['daily_loss_limit'] += 1
            continue

        # ---- Layer 5: Session gate ----
        hour = candle['hour_utc']
        if not (SESSION_START_UTC <= hour < SESSION_END_UTC):
            skip_reasons['outside_session'] += 1
            continue

        # ---- Max concurrent positions ----
        if len(open_trades) >= MAX_CONCURRENT:
            skip_reasons['max_concurrent'] += 1
            continue

        # ---- Layer 2: Micro trap detection ----
        trap = detect_trap(df_1m, i)
        if trap is None:
            continue   # no trap — don't count as skip, just no signal

        direction = trap['direction']

        # ---- Layer 1: H1 EMA21 trend bias ----
        h1_ema = get_h1_ema(ts)
        if h1_ema is None:
            skip_reasons['no_h1_ema'] += 1
            continue

        if direction == 'long'  and close < h1_ema:
            skip_reasons['against_h1_trend'] += 1
            continue
        if direction == 'short' and close > h1_ema:
            skip_reasons['against_h1_trend'] += 1
            continue

        # ---- Layer 3: Volume confirmation ----
        vol_ma = candle['vol_ma20']
        if pd.isna(vol_ma) or vol_ma == 0:
            skip_reasons['no_volume_data'] += 1
            continue
        if candle['volume'] < VOLUME_MULT * vol_ma:
            skip_reasons['low_volume'] += 1
            continue

        # ---- Layer 4: Momentum confirmation (next candle) ----
        if i + 1 >= len(df_1m):
            skip_reasons['no_next_candle'] += 1
            continue

        next_candle = df_1m.iloc[i + 1]
        if direction == 'long'  and next_candle['close'] <= next_candle['open']:
            skip_reasons['no_momentum_confirm'] += 1
            continue
        if direction == 'short' and next_candle['close'] >= next_candle['open']:
            skip_reasons['no_momentum_confirm'] += 1
            continue

        # ---- All layers passed — calculate entry ----
        entry_price = next_candle['open']   # enter at open of confirmation candle
        entry_time  = df_1m.index[i + 1]
        atr         = candle['atr']
        if pd.isna(atr) or atr == 0:
            skip_reasons['no_atr'] += 1
            continue

        if direction == 'long':
            stop_loss  = trap['trap_low'] - atr * ATR_STOP_MULT
            risk_price = entry_price - stop_loss
        else:
            stop_loss  = trap['trap_high'] + atr * ATR_STOP_MULT
            risk_price = stop_loss - entry_price

        if risk_price <= 0:
            skip_reasons['invalid_risk'] += 1
            continue

        # Position sizing: risk_usd / risk_price = position size (oz)
        risk_usd      = capital * risk_pct
        position_size = risk_usd / risk_price

        target1 = entry_price + risk_price * PARTIAL_EXIT_R  if direction == 'long' \
             else entry_price - risk_price * PARTIAL_EXIT_R
        target2 = entry_price + risk_price * FULL_EXIT_R     if direction == 'long' \
             else entry_price - risk_price * FULL_EXIT_R

        # Entry fee
        entry_fee  = entry_price * position_size * TAKER_FEE_PCT
        capital   -= entry_fee
        total_fees += entry_fee

        trade = PhantomTrade(
            direction     = direction,
            entry_price   = entry_price,
            entry_time    = entry_time,
            stop_loss     = stop_loss,
            target1       = target1,
            target2       = target2,
            risk_usd      = risk_usd,
            position_size = position_size,
        )
        open_trades.append(trade)

    # ---- Force-close any remaining open trades ----
    final_price = df_1m.iloc[-1]['close']
    final_time  = df_1m.index[-1]
    for trade in open_trades:
        pnl, fee = trade.force_close(final_price, final_time, 'end_of_data')
        capital    += pnl - fee
        total_fees += fee
        closed_trades.append(trade)

    return closed_trades, equity_curve, skip_reasons, capital, total_fees


# ============================================================
# RESULTS ANALYSIS
# ============================================================

def analyse_results(closed_trades, equity_curve, skip_reasons,
                    final_capital, total_fees, starting_capital,
                    symbol, outdir, skip_plots):

    eq_df = pd.DataFrame(equity_curve).set_index('ts')

    # ---- Trade stats ----
    wins   = [t for t in closed_trades if t.realised_pnl > 0]
    losses = [t for t in closed_trades if t.realised_pnl <= 0]
    n      = len(closed_trades)
    n_win  = len(wins)
    n_loss = len(losses)

    win_rate     = n_win / n * 100 if n > 0 else 0
    avg_win      = np.mean([t.realised_pnl for t in wins])   if wins   else 0
    avg_loss     = np.mean([t.realised_pnl for t in losses]) if losses else 0
    gross_profit = sum(t.realised_pnl for t in wins)
    gross_loss   = abs(sum(t.realised_pnl for t in losses))
    profit_factor= gross_profit / gross_loss if gross_loss > 0 else float('inf')
    net_pnl      = final_capital - starting_capital
    ret_pct      = net_pnl / starting_capital * 100
    expectancy   = np.mean([t.realised_pnl for t in closed_trades]) if closed_trades else 0

    # Drawdown
    eq_df['peak'] = eq_df['equity'].cummax()
    eq_df['dd']   = (eq_df['equity'] - eq_df['peak']) / eq_df['peak'] * 100
    max_dd        = eq_df['dd'].min()

    # Consecutive losses
    results = [1 if t.realised_pnl > 0 else 0 for t in closed_trades]
    max_consec_loss = 0
    cur = 0
    for r in results:
        if r == 0:
            cur += 1
            max_consec_loss = max(max_consec_loss, cur)
        else:
            cur = 0

    # Exit reason breakdown
    exit_reasons = defaultdict(int)
    for t in closed_trades:
        exit_reasons[t.exit_reason] += 1

    # Direction breakdown
    longs  = [t for t in closed_trades if t.direction == 'long']
    shorts = [t for t in closed_trades if t.direction == 'short']

    # ---- Print summary ----
    print("\n" + "="*70)
    print("  PHANTOM BACKTEST RESULTS")
    print("="*70)
    print(f"\n  Symbol          : {symbol}")
    print(f"  Starting capital: {starting_capital:>12,.2f}")
    print(f"  Final capital   : {final_capital:>12,.2f}")
    print(f"  Net P&L         : {net_pnl:>+12,.2f}  ({ret_pct:+.2f}%)")
    print(f"  Total fees      : {total_fees:>12,.2f}")
    print(f"\n  Total trades    : {n}")
    print(f"  Wins            : {n_win}  ({win_rate:.1f}%)")
    print(f"  Losses          : {n_loss}  ({100-win_rate:.1f}%)")
    print(f"  Avg win         : {avg_win:>+10,.2f}")
    print(f"  Avg loss        : {avg_loss:>+10,.2f}")
    print(f"  Profit factor   : {profit_factor:.3f}")
    print(f"  Expectancy/trade: {expectancy:>+10,.2f}")
    print(f"  Max drawdown    : {max_dd:.2f}%")
    print(f"  Max consec loss : {max_consec_loss}")

    print(f"\n  Direction breakdown:")
    if longs:
        lw = sum(1 for t in longs if t.realised_pnl > 0)
        print(f"    Long  : {len(longs)} trades, {lw/len(longs)*100:.1f}% win rate, P&L {sum(t.realised_pnl for t in longs):+,.2f}")
    if shorts:
        sw = sum(1 for t in shorts if t.realised_pnl > 0)
        print(f"    Short : {len(shorts)} trades, {sw/len(shorts)*100:.1f}% win rate, P&L {sum(t.realised_pnl for t in shorts):+,.2f}")

    print(f"\n  Exit reasons:")
    for reason, count in sorted(exit_reasons.items(), key=lambda x: -x[1]):
        print(f"    {reason:<25}: {count}")

    print(f"\n  Skip reasons (signals filtered out):")
    for reason, count in sorted(skip_reasons.items(), key=lambda x: -x[1]):
        print(f"    {reason:<30}: {count:,}")

    # ---- Save trade log ----
    os.makedirs(outdir, exist_ok=True)
    trade_rows = []
    for t in closed_trades:
        trade_rows.append({
            'trade_id':      t.trade_id,
            'direction':     t.direction,
            'entry_time':    t.entry_time,
            'entry_price':   t.entry_price,
            'exit_time':     t.exit_time,
            'exit_price':    t.exit_price,
            'stop_loss':     t.stop_loss,
            'target1':       t.target1,
            'target2':       t.target2,
            'position_size': t.position_size,
            'realised_pnl':  t.realised_pnl,
            'fees_paid':     t.fees_paid,
            'exit_reason':   t.exit_reason,
            'partial_done':  t.partial_done,
        })
    trade_df = pd.DataFrame(trade_rows)
    csv_path = os.path.join(outdir, "phantom_trades.csv")
    trade_df.to_csv(csv_path, index=False)
    print(f"\n  Trade log saved : {csv_path}")

    # ---- Plots ----
    if not skip_plots and len(eq_df) > 0:
        fig, axes = plt.subplots(3, 2, figsize=(18, 14))
        fig.suptitle(f"PHANTOM Strategy — {symbol} 1M Backtest", fontsize=15, fontweight='bold')

        # 1. Equity curve
        ax = axes[0, 0]
        ax.plot(eq_df.index, eq_df['equity'], color='#2E86AB', lw=1.5, label='Equity')
        ax.axhline(starting_capital, color='gray', ls='--', alpha=0.6, label='Start')
        ax.fill_between(eq_df.index, starting_capital, eq_df['equity'],
                        where=eq_df['equity'] >= starting_capital, alpha=0.2, color='green')
        ax.fill_between(eq_df.index, starting_capital, eq_df['equity'],
                        where=eq_df['equity'] < starting_capital, alpha=0.2, color='red')
        ax.set_title('Equity Curve (Cash Basis)')
        ax.set_ylabel('Capital')
        ax.legend(fontsize=9)
        ax.grid(alpha=0.3)
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
        ax.tick_params(axis='x', rotation=30)

        # 2. Drawdown
        ax = axes[0, 1]
        ax.fill_between(eq_df.index, 0, eq_df['dd'], color='red', alpha=0.4)
        ax.plot(eq_df.index, eq_df['dd'], color='darkred', lw=1)
        ax.set_title(f'Drawdown (Max: {max_dd:.2f}%)')
        ax.set_ylabel('Drawdown %')
        ax.grid(alpha=0.3)
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
        ax.tick_params(axis='x', rotation=30)

        # 3. Trade P&L bar chart
        ax = axes[1, 0]
        if len(trade_df) > 0:
            colors = ['#1D9E75' if p > 0 else '#D85A30' for p in trade_df['realised_pnl']]
            ax.bar(range(len(trade_df)), trade_df['realised_pnl'], color=colors, alpha=0.7)
            ax.axhline(0, color='black', lw=0.8)
            ax.set_title('Individual Trade P&L')
            ax.set_xlabel('Trade #')
            ax.set_ylabel('P&L')
            ax.grid(alpha=0.3, axis='y')

        # 4. Win/Loss pie
        ax = axes[1, 1]
        if n > 0:
            ax.pie([n_win, n_loss], labels=[f'Wins\n{n_win}', f'Losses\n{n_loss}'],
                   colors=['#1D9E75', '#D85A30'], autopct='%1.1f%%',
                   startangle=90, textprops={'fontsize': 11})
            ax.set_title(f'Win Rate: {win_rate:.1f}%')

        # 5. Exit reason breakdown
        ax = axes[2, 0]
        if exit_reasons:
            er_labels = list(exit_reasons.keys())
            er_vals   = list(exit_reasons.values())
            bar_colors = ['#1D9E75' if 'target' in l else '#D85A30' if 'stop' in l else '#7F77DD'
                          for l in er_labels]
            ax.barh(er_labels, er_vals, color=bar_colors, alpha=0.8)
            ax.set_title('Exit Reason Breakdown')
            ax.set_xlabel('Count')
            ax.grid(alpha=0.3, axis='x')

        # 6. Cumulative P&L
        ax = axes[2, 1]
        if len(trade_df) > 0:
            cum_pnl = trade_df['realised_pnl'].cumsum()
            ax.plot(cum_pnl.values, color='#7F77DD', lw=1.5)
            ax.axhline(0, color='gray', ls='--', alpha=0.5)
            ax.fill_between(range(len(cum_pnl)), 0, cum_pnl.values,
                            where=cum_pnl.values >= 0, alpha=0.2, color='green')
            ax.fill_between(range(len(cum_pnl)), 0, cum_pnl.values,
                            where=cum_pnl.values < 0, alpha=0.2, color='red')
            ax.set_title('Cumulative P&L')
            ax.set_xlabel('Trade #')
            ax.set_ylabel('Cumulative P&L')
            ax.grid(alpha=0.3)

        plt.tight_layout()
        plot_path = os.path.join(outdir, "phantom_backtest_results.png")
        plt.savefig(plot_path, dpi=150, bbox_inches='tight')
        plt.close()
        print(f"  Chart saved     : {plot_path}")

    # ---- Summary dict ----
    return {
        'n_trades':      n,
        'win_rate':      win_rate,
        'net_pnl':       net_pnl,
        'return_pct':    ret_pct,
        'profit_factor': profit_factor,
        'expectancy':    expectancy,
        'max_drawdown':  max_dd,
        'total_fees':    total_fees,
        'max_consec_loss': max_consec_loss,
    }


# ============================================================
# MAIN
# ============================================================

def main():
    args = parse_args()

    # Override globals from args
    global STARTING_CAPITAL, RISK_PER_TRADE_PCT, LOOKBACK_DAYS, SYMBOL
    STARTING_CAPITAL  = args.capital
    RISK_PER_TRADE_PCT= args.risk
    LOOKBACK_DAYS     = args.days
    SYMBOL            = args.symbol

    # Fetch data
    df_1m = fetch_data(args.symbol, args.days)

    # Build H1 data for trend bias
    print("  Building H1 EMA21 trend bias...")
    df_h1 = resample_to_h1(df_1m)

    # Run backtest
    closed_trades, equity_curve, skip_reasons, final_capital, total_fees = run_backtest(
        df_1m            = df_1m,
        df_h1            = df_h1,
        starting_capital = args.capital,
        risk_pct         = args.risk,
        skip_plots       = args.skip_plots,
        outdir           = args.outdir,
        symbol           = args.symbol,
    )

    # Analyse & report
    summary = analyse_results(
        closed_trades    = closed_trades,
        equity_curve     = equity_curve,
        skip_reasons     = skip_reasons,
        final_capital    = final_capital,
        total_fees       = total_fees,
        starting_capital = args.capital,
        symbol           = args.symbol,
        outdir           = args.outdir,
        skip_plots       = args.skip_plots,
    )

    print("\n" + "="*70)
    print("  DONE")
    print("="*70 + "\n")
    return summary


if __name__ == "__main__":
    main()
