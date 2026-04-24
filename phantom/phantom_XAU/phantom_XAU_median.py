
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

# ============================================
# CONFIGURATION
# ============================================
class Config:
    # Risk
    RISK_PER_TRADE = 0.0025
    COUNTER_RISK_MULT = 0.5
    SESSION_RISK_CAP = 0.02
    PRE_SESSION_RISK_CAP = 0.01

    # Session
    SESSION_START_HOUR = 7
    CORE_SESSION_START = 8
    SESSION_END_HOUR = 16

    # Stops/Targets
    SL_ATR_MULT = 1.2
    TP_R_MULT = 1.0
    BE_TRIGGER_R = 0.4
    TRAIL_TRIGGER_R = 0.8
    TRAIL_ATR_MULT = 0.5
    MAX_HOLD_MINUTES = 30

    # Filters
    MAX_SPREAD_PCT = 0.001   # 0.10%
    MIN_ATR_ABS = 1.0        # $1.0

    # Zones
    ZONE_FRESH_HOURS = 4
    ZONE_LOOKBACK = 20
    PIVOT_BARS = 2
    ZONE_PROX_PCT = 0.0015   # 0.15%

    # Strategy
    ALLOW_COUNTER_TREND = True

    # EMAs
    EMA_FAST = 20
    EMA_SLOW = 50
    EMA_D_FAST = 50
    EMA_D_SLOW = 200

    # Circuit breaker
    MAX_LOSS_STREAK = 3
    COOLDOWN_MINUTES = 15

    # Initial capital
    INITIAL_EQUITY = 10000.0

    # Debug / logging
    DEBUG_MODE = False
    LOG_REJECTIONS = False


# ============================================
# LOGGING HELPERS
# ============================================
def debug_log(msg):
    if Config.DEBUG_MODE:
        print(f"[DEBUG] {msg}")


def log_rejection(reason, t):
    if Config.LOG_REJECTIONS:
        print(f"[REJECTED][{t}] {reason}")


# ============================================
# DATA LOADING
# ============================================
def load_csv(filepath):
    """
    Load MetaTrader-style tab-separated OHLCV file with <DATE> <TIME> columns.
    Handles both MetaTrader exports and standard CSV formats.
    """
    # Read the raw file to detect format
    with open(filepath, 'r') as f:
        first_line = f.readline().strip()
    
    # Detect separator: tab or comma
    sep = '\t' if '\t' in first_line else ','
    
    df = pd.read_csv(filepath, sep=sep)
    
    # Clean column names - remove angle brackets if present
    df.columns = [c.strip().strip('<>').lower() for c in df.columns]
    
    # MetaTrader format: separate <DATE> and <TIME> columns
    if 'date' in df.columns and 'time' in df.columns:
        date_str = df['date'].astype(str).str.strip()
        time_str = df['time'].astype(str).str.strip()
        df['datetime'] = pd.to_datetime(date_str + ' ' + time_str, errors='coerce')
        df = df.drop(columns=['date', 'time'])
    
    # Single datetime column
    elif 'datetime' in df.columns:
        df['datetime'] = pd.to_datetime(df['datetime'], errors='coerce')
    
    elif 'time' in df.columns:
        df['datetime'] = pd.to_datetime(df['time'], errors='coerce')
        df = df.drop(columns=['time'])
    
    else:
        # Try first column as datetime
        first_col = df.columns[0]
        try:
            df['datetime'] = pd.to_datetime(df[first_col], errors='coerce')
            df = df.drop(columns=[first_col])
        except:
            raise ValueError(
                f"Cannot parse datetime from {filepath}. "
                f"Columns found: {list(df.columns)}"
            )
    
    # Drop rows where datetime parsing failed
    df = df.dropna(subset=['datetime'])
    df = df.set_index('datetime').sort_index()
    
    # Normalize OHLCV column names
    col_map = {}
    for col in df.columns:
        lc = col.lower()
        if lc == 'open': col_map[col] = 'open'
        elif lc == 'high': col_map[col] = 'high'
        elif lc == 'low': col_map[col] = 'low'
        elif lc == 'close': col_map[col] = 'close'
        elif lc in ('tickvol', 'tick_vol', 'volume', 'vol'): 
            col_map[col] = 'volume'
        elif lc == 'spread': col_map[col] = 'spread'
    df.rename(columns=col_map, inplace=True)
    
    # Ensure required columns exist
    for req in ['open', 'high', 'low', 'close']:
        if req not in df.columns:
            raise ValueError(f"{filepath} missing required column: {req}. Columns: {list(df.columns)}")
    
    # Convert price columns to numeric
    for col in ['open', 'high', 'low', 'close']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    
    df.dropna(subset=['open', 'high', 'low', 'close'], inplace=True)
    
    # Add volume column if missing
    if 'volume' not in df.columns:
        df['volume'] = 1.0
    
    # Add spread column if missing
    if 'spread' not in df.columns:
        df['spread'] = df['close'] * 0.0005
    
    return df


def load_data():
    data = {}
    paths = {
        'M1':  'data/XAUUSD/XAUUSD_M1_2023.03.13-2026.03.31',
        'M5':  'data/XAUUSD/XAUUSD_M5_2011.09.08-2026.03.31',
        'M30': 'data/XAUUSD/XAUUSD_M30_2010.01.04-2026.03.31',
        'H1':  'data/XAUUSD/XAUUSD_H1_2010.01.04-2026.03.31',
        'H4':  'data/XAUUSD/XAUUSD_H4_2010.01.04-2026.03.31',
        'D1':  'data/XAUUSD/XAUUSD_Daily_2010.01.04-2026.03.31'
    }

    for tf, filepath in paths.items():
        df = load_csv(filepath)
        data[tf] = df
        print(f"Loaded {tf}: {len(df)} rows from {df.index[0]} to {df.index[-1]}")

    return data


# ============================================
# INDICATORS
# ============================================
def calculate_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def calculate_atr(df, period=14):
    high, low, close = df['high'], df['low'], df['close']
    prev_close = close.shift(1)

    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    return tr.rolling(window=period, min_periods=period).mean()


def calculate_all_indicators(data):
    # M5 ATR and EMAs
    m5 = data['M5']
    m5['ATR_14'] = calculate_atr(m5, 14)
    m5['EMA5'] = calculate_ema(m5['close'], 5)
    m5['EMA20'] = calculate_ema(m5['close'], Config.EMA_FAST)
    m5['EMA50'] = calculate_ema(m5['close'], Config.EMA_SLOW)

    # Higher TF EMAs
    for tf in ['M30', 'H1', 'H4']:
        df = data[tf]
        df['EMA20'] = calculate_ema(df['close'], Config.EMA_FAST)
        df['EMA50'] = calculate_ema(df['close'], Config.EMA_SLOW)

    # Daily EMAs
    d1 = data['D1']
    d1['EMA50'] = calculate_ema(d1['close'], Config.EMA_D_FAST)
    d1['EMA200'] = calculate_ema(d1['close'], Config.EMA_D_SLOW)

    return data


# ============================================
# SESSION & FILTERS
# ============================================
def in_session(ts):
    h = ts.hour
    return Config.SESSION_START_HOUR <= h < Config.SESSION_END_HOUR


def is_pre_session(ts):
    h = ts.hour
    return Config.SESSION_START_HOUR <= h < Config.CORE_SESSION_START


def is_weekend(ts):
    return ts.weekday() >= 5


def get_spread_pct(row):
    """
    Calculate spread as percentage of price.
    Handles spread in both points and absolute dollar terms.
    """
    mid = row['close']
    spread = row.get('spread', 0)
    
    # MetaTrader spread is typically in points (1 point = 0.01 for XAUUSD)
    # If spread > 1, it's likely in points, convert to absolute
    if spread > 1.0 and spread / mid < 0.0001:
        # Spread is in points (e.g., 7 means 0.07)
        spread_absolute = spread * 0.01  # Convert points to dollars for XAUUSD
    else:
        spread_absolute = spread
    
    return spread_absolute / mid if mid > 0 else 0.0


# ============================================
# TREND ANALYSIS
# ============================================
def get_daily_bias(d1_df, ts):
    try:
        d1_bars = d1_df[d1_df.index <= ts]
        if len(d1_bars) < Config.EMA_D_SLOW:
            return 0
        last = d1_bars.iloc[-1]
        if pd.isna(last['EMA50']) or pd.isna(last['EMA200']):
            return 0
        if last['EMA50'] > last['EMA200']:
            return 1
        elif last['EMA50'] < last['EMA200']:
            return -1
        return 0
    except Exception:
        return 0


def get_tf_trend(df, ts):
    try:
        bars = df[df.index <= ts]
        if len(bars) < Config.EMA_SLOW + 1:
            return 0
        last = bars.iloc[-1]
        close = last['close']
        ema20 = last['EMA20']
        ema50 = last['EMA50']
        if pd.isna(ema20) or pd.isna(ema50):
            return 0
        if close > ema20 > ema50:
            return 1
        elif close < ema20 < ema50:
            return -1
        return 0
    except Exception:
        return 0


def get_multi_tf_trend(data, ts):
    trends = [
        get_tf_trend(data['H4'], ts),
        get_tf_trend(data['H1'], ts),
        get_tf_trend(data['M30'], ts)
    ]
    bulls = sum(1 for t in trends if t == 1)
    bears = sum(1 for t in trends if t == -1)
    if bulls >= 2:
        return 1
    elif bears >= 2:
        return -1
    return 0


# ============================================
# ZONE DETECTION
# ============================================
def is_swing_high(df, idx_pos):
    if idx_pos < Config.PIVOT_BARS or idx_pos + Config.PIVOT_BARS >= len(df):
        return False
    current_high = df['high'].iloc[idx_pos]
    prev_highs = df['high'].iloc[idx_pos - Config.PIVOT_BARS:idx_pos]
    next_highs = df['high'].iloc[idx_pos + 1:idx_pos + 1 + Config.PIVOT_BARS]
    return (current_high > prev_highs).all() and (current_high > next_highs).all()


def is_swing_low(df, idx_pos):
    if idx_pos < Config.PIVOT_BARS or idx_pos + Config.PIVOT_BARS >= len(df):
        return False
    current_low = df['low'].iloc[idx_pos]
    prev_lows = df['low'].iloc[idx_pos - Config.PIVOT_BARS:idx_pos]
    next_lows = df['low'].iloc[idx_pos + 1:idx_pos + 1 + Config.PIVOT_BARS]
    return (current_low < prev_lows).all() and (current_low < next_lows).all()


def find_zone(m5_df, current_time):
    # Only use closed bars before current_time
    historical = m5_df[m5_df.index < current_time]
    if len(historical) < Config.ZONE_LOOKBACK + Config.PIVOT_BARS + 2:
        return None

    window = historical.iloc[-(Config.ZONE_LOOKBACK + Config.PIVOT_BARS + 2):]

    best_time = None
    best_price = None
    is_support = None

    for i in range(Config.PIVOT_BARS, len(window) - Config.PIVOT_BARS):
        bar_ts = window.index[i]
        idx_full = m5_df.index.get_loc(bar_ts)

        age_sec = (current_time - bar_ts).total_seconds()
        if age_sec > Config.ZONE_FRESH_HOURS * 3600:
            continue

        if is_swing_high(m5_df, idx_full):
            if best_time is None or bar_ts > best_time:
                best_time = bar_ts
                best_price = m5_df['high'].iloc[idx_full]
                is_support = False
        elif is_swing_low(m5_df, idx_full):
            if best_time is None or bar_ts > best_time:
                best_time = bar_ts
                best_price = m5_df['low'].iloc[idx_full]
                is_support = True

    if best_time is None:
        return None

    return {
        'time': best_time,
        'price': best_price,
        'is_support': is_support
    }


def price_near_zone(current_price, zone_price):
    if zone_price <= 0:
        return False
    diff_pct = abs(current_price - zone_price) / zone_price
    return diff_pct <= Config.ZONE_PROX_PCT


# ============================================
# SIGNAL LOGIC
# ============================================
def m5_rejection(m5_df, current_time, is_long):
    closed = m5_df[m5_df.index < current_time]
    if len(closed) < 3:
        return False

    bar = closed.iloc[-1]
    prev = closed.iloc[-2]

    o, c, h, l = bar['open'], bar['close'], bar['high'], bar['low']
    rng = h - l
    if rng <= 0:
        return False

    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l

    if is_long:
        wick_ok = lower_wick >= 0.3 * rng
        close_ok = c > (l + rng / 2.0)
        engulf = (c > prev['open']) and (o < prev['close'])
        return (wick_ok and close_ok) or engulf
    else:
        wick_ok = upper_wick >= 0.3 * rng
        close_ok = c < (l + rng / 2.0)
        engulf = (c < prev['open']) and (o > prev['close'])
        return (wick_ok and close_ok) or engulf


def m1_momentum(m1_df, m5_df, current_time, is_long):
    try:
        m1_bar = m1_df.loc[current_time]
        o, c = m1_bar['open'], m1_bar['close']

        m5_closed = m5_df[m5_df.index < current_time]
        if len(m5_closed) == 0:
            return False
        ema5 = m5_closed['EMA5'].iloc[-1]
        if pd.isna(ema5):
            return False

        if is_long:
            return c > o and c > ema5
        else:
            return c < o and c < ema5
    except Exception:
        return False


# ============================================
# TRADE MANAGEMENT HELPERS
# ============================================
def calculate_position_size(equity, entry_price, sl_price, is_counter_trend):
    risk_pct = Config.RISK_PER_TRADE
    if is_counter_trend:
        risk_pct *= Config.COUNTER_RISK_MULT

    risk_amount = equity * risk_pct
    stop_distance = abs(entry_price - sl_price)
    if stop_distance <= 0:
        return 0.0

    size = risk_amount / stop_distance
    return round(size, 2)


def check_sl_tp_hit(open_trade, high, low, close):
    is_long = open_trade['is_long']
    sl = open_trade['sl']
    tp = open_trade['tp']

    if is_long:
        if low <= sl:
            return True, sl, 'stop_loss'
        elif high >= tp:
            return True, tp, 'take_profit'
    else:
        if high >= sl:
            return True, sl, 'stop_loss'
        elif low <= tp:
            return True, tp, 'take_profit'

    return False, close, None


# ============================================
# BACKTEST ENGINE
# ============================================
def run_backtest(data):
    filter_stats = {
        'total_bars': 0,
        'weekend': 0,
        'out_of_session': 0,
        'in_session': 0,
        'spread_fail': 0,
        'atr_fail': 0,
        'daily_bias_fail': 0,
        'intraday_fail': 0,
        'no_zone': 0,
        'not_near_zone': 0,
        'passed_all': 0
    }
    equity = Config.INITIAL_EQUITY
    session_start_equity = None
    cooldown_until = None
    last_m5_bar_traded = None
    consecutive_losses = 0

    open_trade = None
    trades = []
    equity_curve = []

    m1_times = data['M1'].index
    print(f"\nStarting backtest from {m1_times[0]} to {m1_times[-1]}")
    print(f"Total M1 bars: {len(m1_times)}\n")

    for idx, ts in enumerate(m1_times):
        if idx % 10000 == 0 and idx > 0:
            print(f"  Processing: {ts} | Equity: ${equity:,.2f} | Trades: {len(trades)}")

        filter_stats['total_bars'] += 1

        if is_weekend(ts):
            filter_stats['weekend'] += 1
            continue

        # New session detection (per day, during session hours)
        if Config.SESSION_START_HOUR <= ts.hour < Config.SESSION_END_HOUR:
            if (session_start_equity is None or
                (ts.hour == Config.SESSION_START_HOUR and ts.minute == 0 and
                 (len(equity_curve) == 0 or equity_curve[-1][0].date() != ts.date()))):
                session_start_equity = equity
                cooldown_until = None
                last_m5_bar_traded = None
                consecutive_losses = 0
                debug_log(f"=== NEW SESSION {ts.date()} STARTED ===")

        # Cooldown
        if cooldown_until and ts < cooldown_until:
            log_rejection("In cooldown period", ts)
            continue

        # Manage open trade
        if open_trade:
            m1_bar = data['M1'].loc[ts]
            m5_closed = data['M5'][data['M5'].index < ts]
            atr_val = m5_closed['ATR_14'].iloc[-1] if len(m5_closed) > 0 else 0.0

            hit, exit_price, reason = check_sl_tp_hit(
                open_trade,
                m1_bar['high'],
                m1_bar['low'],
                m1_bar['close']
            )

            if hit:
                pnl = (exit_price - open_trade['entry_price']) * \
                      (1 if open_trade['is_long'] else -1) * \
                      open_trade['size']
                equity += pnl

                if pnl < 0:
                    consecutive_losses += 1
                else:
                    consecutive_losses = 0

                trades.append({
                    'entry_time': open_trade['entry_time'],
                    'exit_time': ts,
                    'direction': 'LONG' if open_trade['is_long'] else 'SHORT',
                    'type': 'COUNTER' if open_trade['is_counter'] else 'TREND',
                    'entry_price': open_trade['entry_price'],
                    'exit_price': exit_price,
                    'size': open_trade['size'],
                    'pnl': pnl,
                    'reason': reason,
                    'zone_price': open_trade.get('zone_price', 0.0),
                    'comment': open_trade.get('comment', '')
                })

                open_trade = None
                equity_curve.append((ts, equity))
                continue

            # Timeout
            hold_minutes = (ts - open_trade['entry_time']).total_seconds() / 60.0
            if hold_minutes >= Config.MAX_HOLD_MINUTES:
                exit_price = m1_bar['close']
                pnl = (exit_price - open_trade['entry_price']) * \
                      (1 if open_trade['is_long'] else -1) * \
                      open_trade['size']
                equity += pnl

                if pnl < 0:
                    consecutive_losses += 1
                else:
                    consecutive_losses = 0

                trades.append({
                    'entry_time': open_trade['entry_time'],
                    'exit_time': ts,
                    'direction': 'LONG' if open_trade['is_long'] else 'SHORT',
                    'type': 'COUNTER' if open_trade['is_counter'] else 'TREND',
                    'entry_price': open_trade['entry_price'],
                    'exit_price': exit_price,
                    'size': open_trade['size'],
                    'pnl': pnl,
                    'reason': 'timeout',
                    'zone_price': open_trade.get('zone_price', 0.0),
                    'comment': open_trade.get('comment', '')
                })

                open_trade = None
                equity_curve.append((ts, equity))
                continue

            # Breakeven & trailing
            if atr_val > 0:
                r_value = abs(open_trade['entry_price'] - open_trade['sl'])
                current_price = m1_bar['close']
                profit_dist = (current_price - open_trade['entry_price']) * \
                              (1 if open_trade['is_long'] else -1)
                r_now = profit_dist / r_value if r_value > 0 else 0.0

                # Breakeven
                if not open_trade['has_be'] and r_now >= Config.BE_TRIGGER_R:
                    open_trade['sl'] = open_trade['entry_price']
                    open_trade['has_be'] = True

                # Trailing
                if r_now >= Config.TRAIL_TRIGGER_R:
                    trail_dist = Config.TRAIL_ATR_MULT * atr_val
                    new_sl = (current_price - trail_dist
                              if open_trade['is_long']
                              else current_price + trail_dist)
                    min_improvement = 0.5
                    if open_trade['is_long'] and new_sl > open_trade['sl'] + min_improvement:
                        open_trade['sl'] = new_sl
                    elif not open_trade['is_long'] and new_sl < open_trade['sl'] - min_improvement:
                        open_trade['sl'] = new_sl

            equity_curve.append((ts, equity))
            continue

        # ===== ENTRY LOGIC =====
        if not in_session(ts):
            filter_stats['out_of_session'] += 1
            log_rejection("Outside session hours", ts)
            continue

        filter_stats['in_session'] += 1

        if session_start_equity is not None:
            session_loss = (session_start_equity - equity) / session_start_equity
            cap = Config.SESSION_RISK_CAP
            if is_pre_session(ts):
                cap = min(cap, Config.PRE_SESSION_RISK_CAP)
            if session_loss >= cap:
                log_rejection("Session risk cap reached", ts)
                continue

        # One entry per M5 bar
        m5_closed = data['M5'][data['M5'].index < ts]
        if len(m5_closed) > 0:
            current_m5_bar = m5_closed.index[-1]
            if last_m5_bar_traded is not None and current_m5_bar == last_m5_bar_traded:
                log_rejection("Already traded this M5 bar", ts)
                equity_curve.append((ts, equity))
                continue

        # Circuit breaker
        if consecutive_losses >= Config.MAX_LOSS_STREAK and cooldown_until is None:
            cooldown_until = ts + timedelta(minutes=Config.COOLDOWN_MINUTES)
            debug_log(f"Circuit breaker triggered at {ts}, cooldown until {cooldown_until}")
            consecutive_losses = 0
            equity_curve.append((ts, equity))
            continue

        # Current M1 bar
        try:
            m1_bar = data['M1'].loc[ts]
        except KeyError:
            equity_curve.append((ts, equity))
            continue

        # Spread filter
        if get_spread_pct(m1_bar) > Config.MAX_SPREAD_PCT:
            filter_stats['spread_fail'] += 1          # <-- ADD THIS LINE
            log_rejection("Spread too high", ts)
            equity_curve.append((ts, equity))
            continue

         # ATR filter
        if len(m5_closed) == 0:
            equity_curve.append((ts, equity))
            continue
        atr_val = m5_closed['ATR_14'].iloc[-1]
        if pd.isna(atr_val) or atr_val < Config.MIN_ATR_ABS:
            filter_stats['atr_fail'] += 1              # <-- ADD THIS LINE
            log_rejection("ATR too low", ts)
            equity_curve.append((ts, equity))
            continue

        # Trend analysis
        daily_bias = get_daily_bias(data['D1'], ts)
        if daily_bias == 0:
            filter_stats['daily_bias_fail'] += 1       # <-- ADD THIS LINE
            log_rejection("Daily bias unclear", ts)
            equity_curve.append((ts, equity))
            continue

        intraday_trend = get_multi_tf_trend(data, ts)
        if intraday_trend == 0:
            filter_stats['intraday_fail'] += 1            
            log_rejection("No clear intraday trend", ts)
            equity_curve.append((ts, equity))
            continue

        # Zone detection
        zone = find_zone(data['M5'], ts)
        if zone is None:
            filter_stats['no_zone'] += 1                # <-- ADD THIS LINE
            log_rejection("No valid zone found", ts)
            equity_curve.append((ts, equity))
            continue

        current_price = m1_bar['close']
        if not price_near_zone(current_price, zone['price']):
            filter_stats['not_near_zone'] += 1
            log_rejection("Price not near zone", ts)
            equity_curve.append((ts, equity))
            continue
        
        filter_stats['passed_all'] += 1

        trend_aligned = (intraday_trend == daily_bias)
        can_long = zone['is_support']
        can_short = not zone['is_support']

        def attempt_entry(is_long, is_counter):
            nonlocal open_trade, last_m5_bar_traded, equity

            if not m5_rejection(data['M5'], ts, is_long):
                log_rejection("M5 rejection failed", ts)
                return False
            if not m1_momentum(data['M1'], data['M5'], ts, is_long):
                log_rejection("M1 momentum failed", ts)
                return False

            sl_distance = Config.SL_ATR_MULT * atr_val
            entry_price = current_price
            sl_price = entry_price - sl_distance if is_long else entry_price + sl_distance
            tp_price = entry_price + Config.TP_R_MULT * sl_distance if is_long else entry_price - Config.TP_R_MULT * sl_distance

            size = calculate_position_size(equity, entry_price, sl_price, is_counter)
            if size <= 0:
                log_rejection("Invalid position size", ts)
                return False

            comment = (
                f"PhantomScalpXAU|"
                f"{'LONG' if is_long else 'SHORT'}|"
                f"{'COUNTER' if is_counter else 'TREND'}|"
                f"Zone:{zone['price']:.2f}|"
                f"ATR:{atr_val:.2f}"
            )

            open_trade = {
                'entry_time': ts,
                'entry_price': entry_price,
                'sl': sl_price,
                'tp': tp_price,
                'is_long': is_long,
                'is_counter': is_counter,
                'size': size,
                'has_be': False,
                'zone_price': zone['price'],
                'comment': comment
            }

            if len(m5_closed) > 0:
                last_m5_bar_traded = m5_closed.index[-1]

            debug_log(f"ENTRY {comment} | Size={size:.2f} SL={sl_price:.2f} TP={tp_price:.2f}")
            return True

        entry_done = False
        if trend_aligned:
            if can_long and intraday_trend == 1:
                entry_done = attempt_entry(True, False)
            elif can_short and intraday_trend == -1:
                entry_done = attempt_entry(False, False)

        if not entry_done and Config.ALLOW_COUNTER_TREND:
            if can_long:
                entry_done = attempt_entry(True, True)
            elif can_short:
                entry_done = attempt_entry(False, True)

        equity_curve.append((ts, equity))

    # Close any open trade at end
    if open_trade:
        final_time = m1_times[-1]
        final_bar = data['M1'].loc[final_time]
        final_price = final_bar['close']
        pnl = (final_price - open_trade['entry_price']) * \
              (1 if open_trade['is_long'] else -1) * \
              open_trade['size']
        equity += pnl

        trades.append({
            'entry_time': open_trade['entry_time'],
            'exit_time': final_time,
            'direction': 'LONG' if open_trade['is_long'] else 'SHORT',
            'type': 'COUNTER' if open_trade['is_counter'] else 'TREND',
            'entry_price': open_trade['entry_price'],
            'exit_price': final_price,
            'size': open_trade['size'],
            'pnl': pnl,
            'reason': 'end_of_test',
            'zone_price': open_trade.get('zone_price', 0.0),
            'comment': open_trade.get('comment', '')
        })

    # ============================================
    # FILTER STATISTICS (ADD THIS ENTIRE BLOCK)
    # ============================================
    print(f"\n{'='*60}")
    print(f"FILTER STATISTICS")
    print(f"{'='*60}")
    print(f"  Total bars processed:    {filter_stats['total_bars']:>10,}")
    print(f"  Weekend skips:           {filter_stats['weekend']:>10,}")
    print(f"  Out of session:          {filter_stats['out_of_session']:>10,}")
    print(f"  In session:              {filter_stats['in_session']:>10,}")
    print(f"  Spread fails:            {filter_stats['spread_fail']:>10,}")
    print(f"  ATR fails:               {filter_stats['atr_fail']:>10,}")
    print(f"  Daily bias fails:        {filter_stats['daily_bias_fail']:>10,}")
    print(f"  Intraday trend fails:    {filter_stats['intraday_fail']:>10,}")
    print(f"  No zone found:           {filter_stats['no_zone']:>10,}")
    print(f"  Not near zone:           {filter_stats['not_near_zone']:>10,}")
    print(f"  Passed all filters:      {filter_stats['passed_all']:>10,}")
    print(f"{'='*60}\n")

    trades_df = pd.DataFrame(trades)
    equity_df = pd.DataFrame(equity_curve, columns=['time', 'equity'])

    return trades_df, equity_df, equity


# ============================================
# PERFORMANCE ANALYSIS
# ============================================
def analyze_results(trades_df, equity_df, final_equity):
    print("\n" + "=" * 60)
    print("PHANTOM SCALP XAU - BACKTEST RESULTS")
    print("=" * 60)

    if len(trades_df) == 0:
        print("No trades executed.")
        return

    total_trades = len(trades_df)
    wins = trades_df[trades_df['pnl'] > 0]
    losses = trades_df[trades_df['pnl'] <= 0]

    win_rate = len(wins) / total_trades * 100 if total_trades > 0 else 0.0
    total_pnl = trades_df['pnl'].sum()
    avg_win = wins['pnl'].mean() if len(wins) > 0 else 0.0
    avg_loss = losses['pnl'].mean() if len(losses) > 0 else 0.0
    profit_factor = (wins['pnl'].sum() / abs(losses['pnl'].sum())
                     if len(losses) > 0 else float('inf'))

    print(f"\nInitial Equity: ${Config.INITIAL_EQUITY:,.2f}")
    print(f"Final Equity:   ${final_equity:,.2f}")
    print(f"Total Return:   {((final_equity - Config.INITIAL_EQUITY) / Config.INITIAL_EQUITY * 100):.2f}%")

    print(f"\nTotal Trades:   {total_trades}")
    print(f"Win Rate:       {win_rate:.1f}%")
    print(f"Profit Factor:  {profit_factor:.2f}")
    print(f"Avg Win:        ${avg_win:,.2f}")
    print(f"Avg Loss:       ${avg_loss:,.2f}")

    # Drawdown
    equity_df = equity_df.copy()
    equity_df.set_index('time', inplace=True)
    equity_df['peak'] = equity_df['equity'].cummax()
    equity_df['drawdown_pct'] = (equity_df['peak'] - equity_df['equity']) / equity_df['peak'] * 100
    max_dd = equity_df['drawdown_pct'].max()
    print(f"Max Drawdown:   {max_dd:.2f}%")

    # Trend vs counter-trend
    if 'type' in trades_df.columns:
        trend_trades = trades_df[trades_df['type'] == 'TREND']
        counter_trades = trades_df[trades_df['type'] == 'COUNTER']

        print(f"\nTrend-Aligned Trades: {len(trend_trades)}")
        if len(trend_trades) > 0:
            trend_wr = len(trend_trades[trend_trades['pnl'] > 0]) / len(trend_trades) * 100
            print(f"  Win Rate: {trend_wr:.1f}%")
            print(f"  Total PnL: ${trend_trades['pnl'].sum():,.2f}")

        print(f"\nCounter-Trend Trades: {len(counter_trades)}")
        if len(counter_trades) > 0:
            counter_wr = len(counter_trades[counter_trades['pnl'] > 0]) / len(counter_trades) * 100
            print(f"  Win Rate: {counter_wr:.1f}%")
            print(f"  Total PnL: ${counter_trades['pnl'].sum():,.2f}")

    # Exit reasons
    if 'reason' in trades_df.columns:
        print(f"\nExit Reasons:")
        for reason in trades_df['reason'].unique():
            count = len(trades_df[trades_df['reason'] == reason])
            print(f"  {reason}: {count}")


# ============================================
# MAIN
# ============================================
if __name__ == "__main__":
    data = load_data()
    data = calculate_all_indicators(data)
    trades_df, equity_df, final_equity = run_backtest(data)
    analyze_results(trades_df, equity_df, final_equity)