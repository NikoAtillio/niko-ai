# PHANTOM Strategy Ruleset Canonical v1.1

This is the single source of truth for platform detection, scoring, conflict resolution, and training labels.

Supersedes:
- phantom_strategy_spec_part1.txt
- strategy_platform_part2a.txt
- strategy_platform_part2b.txt

## 1) Canonical Enums

### 1.1 Strategy IDs
- TREND_PULLBACK
- BREAKOUT_CONFIRM
- RANGE_REVERSION
- MEAN_REVERT_BAND
- VOL_COMPRESS_BREAK
- ORB
- MOMENTUM_CONT

### 1.2 Regime IDs
- STRONG_TREND
- WEAK_TREND
- RANGE
- HIGH_VOL

### 1.3 Direction
- long
- short

## 2) Universal Candle and Rejection Definitions

### 2.1 Candle Math
- body = abs(close - open)
- total_range = max(1e-9, high - low)
- body_pct = body / total_range
- upper_wick = max(0, high - max(open, close))
- lower_wick = max(0, min(open, close) - low)
- longer_wick = max(upper_wick, lower_wick)

### 2.2 Wick Ratio (single universal formula)
- wick_ratio = longer_wick / max(1e-9, body)

### 2.3 Canonical rejection thresholds
Global defaults (used by all strategies unless strategy override is stricter):
- min_body_pct = 0.10
- min_wick_share = 0.35
- min_wick_ratio = 1.5

Bullish rejection requires all:
- body_pct >= min_body_pct
- lower_wick / total_range >= min_wick_share
- lower_wick > upper_wick
- wick_ratio >= min_wick_ratio
- close > open
- close >= low + 0.60 * total_range

Bearish rejection requires all:
- body_pct >= min_body_pct
- upper_wick / total_range >= min_wick_share
- upper_wick > lower_wick
- wick_ratio >= min_wick_ratio
- close < open
- close <= high - 0.60 * total_range

Engulfing alternative confirmation:
- bullish: close[0] > open[1] and open[0] < close[1] and body[0] > body[1]
- bearish: close[0] < open[1] and open[0] > close[1] and body[0] > body[1]

## 3) Universal Scoring and Signal Gating

### 3.1 Rule weights
- MANDATORY = 3
- STRONG = 2
- OPTIONAL = 1

### 3.2 Confidence formula
- If any mandatory rule fails: confidence = 0.0
- Else confidence = round(sum(weights of passed rules) / sum(weights of all rules), 2)

### 3.3 Global gates order (non-negotiable)
1. min bars history gate
2. regime classification gate
3. strategy detector rule checks
4. confidence calculation
5. strategy-specific penalties and caps
6. global min confidence threshold gate
7. conflict resolution gate
8. risk/position gate

### 3.4 Defaults
- min_bars_history = 200 (hard minimum, cannot be reduced)
- min_confidence_threshold = 0.65

## 4) Timeframe and Indicator Standards

### 4.1 Timeframe scaling
All indicator periods are bar-count based.

### 4.2 Indicator defaults
- EMA: 20, 50, 200
- ATR: 14
- ADX: 14
- Bollinger: 20, 2.0
- RSI: 14
- Volume MA: 20

### 4.3 Caching
Indicators are computed once per bar and shared across all detectors.

## 5) Regime Switcher (authoritative)

### 5.1 Inputs
- ADX(14)
- EMA50 slope
- ATR ratio = ATR_now / mean(ATR_20)
- BB width

### 5.2 Hysteresis thresholds
- STRONG_TREND enter: ADX > 25
- STRONG_TREND exit: ADX < 22
- RANGE enter: ADX < 18 and BB width < 0.03
- RANGE exit: ADX > 21
- HIGH_VOL enter: ATR ratio > 2.0
- HIGH_VOL exit: ATR ratio < 1.6
- regime_hold_min_bars = 3

### 5.3 Activation matrix (authoritative)
- STRONG_TREND: TREND_PULLBACK, MOMENTUM_CONT, BREAKOUT_CONFIRM, ORB
- WEAK_TREND: TREND_PULLBACK, BREAKOUT_CONFIRM, MEAN_REVERT_BAND, VOL_COMPRESS_BREAK, ORB
- RANGE: RANGE_REVERSION, MEAN_REVERT_BAND, VOL_COMPRESS_BREAK, ORB
- HIGH_VOL: BREAKOUT_CONFIRM, ORB

### 5.4 HIGH_VOL risk override
In HIGH_VOL, allowed strategies execute at 50% normal position size.

## 6) Volume Handling (authoritative)

Volume threshold baseline by instrument family:
- crypto, equities, futures: volume > 1.5 x vol_ma20
- forex, metals, indices tick volume: volume > 1.3 x vol_ma20

Final threshold resolution rule:
- effective_volume_mult = max(global_instrument_mult, strategy_volume_mult)

## 7) Session and Time Rules

- Internal storage timezone: UTC
- Inputs may be exchange local time, but must be converted to UTC at ingest
- DST must be resolved at conversion time
- ORB sessions:
  - London: range 07:00-07:30 UTC, breakout 07:30-10:00 UTC
  - New York: range 13:30-14:00 UTC, breakout 14:00-17:00 UTC
  - Asia: range 00:00-00:30 UTC, breakout 00:30-04:00 UTC
  - crypto default anchor: 00:00 UTC (unless user override)

## 8) Strategy Specs (authoritative)

Each strategy has 9 weighted checks: 3 mandatory, 3 strong, 3 optional.

### 8.1 TREND_PULLBACK
Mandatory:
- trend alignment: EMA20 > EMA50 > EMA200 (long) or inverse (short)
- pullback zone touch: EMA20/EMA50 zone with ATR buffer
- rejection confirmation: canonical rejection or engulfing

Strong:
- ADX > 20
- volume threshold pass
- fib pullback depth in [0.236, 0.786] of latest completed impulse

Optional:
- higher timeframe trend alignment
- session quality (London/NY)
- spread quality pass

Risk model:
- SL: signal extreme +/- 0.5 x ATR
- TP1: 1R (partial 50%)
- TP2: 2R (close remainder)
- move stop to break-even after TP1
- time exit: 20 bars

### 8.2 BREAKOUT_CONFIRM
Mandatory:
- valid tested level or consolidation structure
- close breaks level by >= 0.2 x ATR
- volume threshold pass

Strong:
- retest and rejection quality
- ADX directional expansion
- no major opposing level within 1.5R

Optional:
- higher timeframe alignment
- active session quality
- BB width expansion

Risk model:
- break entry or retest entry
- SL: beyond broken level +/- 0.5 x ATR
- TP1: 1R (partial 50%)
- TP2: 2R
- time exit: 15 bars

### 8.3 RANGE_REVERSION
Mandatory:
- valid range structure (touch count, ADX, width)
- boundary touch with ATR tolerance
- canonical rejection at boundary

Strong:
- RSI extreme
- volume threshold pass at boundary
- prior boundary respect evidence

Optional:
- BB boundary touch
- active session quality
- stronger wick ratio (>= 2.0)

Risk model:
- SL: beyond boundary +/- 0.5 x ATR
- TP1: range midpoint (partial 50%)
- TP2: opposite boundary minus buffer
- time exit: 25 bars
- in WEAK_TREND, confidence capped at 0.65

### 8.4 MEAN_REVERT_BAND
Mandatory:
- extreme stretch: beyond BB outer OR VWAP distance threshold
- regime is RANGE or WEAK_TREND
- canonical rejection at extreme

Strong:
- RSI divergence present
- BB width not expanding (compression or neutral)
- no trend acceleration signs

Optional:
- volume threshold pass
- fresh extreme condition
- not within user news stand-down window

Risk model:
- SL: extreme wick + 0.5 x ATR
- TP1: BB midline or EMA20
- TP2: VWAP or opposite BB
- max hold: 10 bars
- forced exit if ADX crosses > 25 while trade open

### 8.5 VOL_COMPRESS_BREAK
Mandatory:
- squeeze detected (BB inside KC for min bars)
- squeeze release confirmed
- expansion candle body_pct >= 0.55

Strong:
- volume expansion above effective threshold
- direction agreement by at least 2 of 3 methods
- ATR expansion vs squeeze baseline

Optional:
- long squeeze duration bonus
- clear air to nearest opposing level
- higher timeframe directional agreement

Risk model:
- SL: opposite side of expansion candle +/- 0.3 x ATR
- TP1: +2 x ATR from entry
- TP2: +4 x ATR from entry
- trailing after TP1
- invalidation: price re-enters squeeze zone within 3 bars

### 8.6 ORB
Mandatory:
- ORB range built from configured session window
- breakout close beyond ORB high/low
- breakout candle body_pct >= 0.55

Strong:
- volume expansion above effective threshold
- ORB width meaningful vs ATR
- first valid breakout attempt in window

Optional:
- higher timeframe trend alignment
- clear air to nearby opposing level
- low spread quality pass

Risk model:
- one signal per instrument per session
- SL: ORB midline
- TP1: 1 x ORB width
- TP2: 2 x ORB width
- TP3 optional: 3 x ORB width
- time exit at breakout-window end if TP1 not reached

### 8.7 MOMENTUM_CONT
Mandatory:
- impulse >= 3 x ATR within max bars
- consolidation depth <= 50% of impulse
- breakout close beyond consolidation in impulse direction

Strong:
- strong trend regime confirmation
- impulse volume expansion then consolidation volume contraction
- continuation candle quality

Optional:
- shallow pullback quality bonus
- clear air to opposing level
- higher timeframe trend alignment

Risk model:
- SL: opposite consolidation side +/- 0.3 x ATR
- TP1: 0.618 x impulse extension
- TP2: 1.0 x impulse extension
- TP3: 1.618 x impulse extension
- invalidation: consolidation exceeds max bars or depth

## 9) Conflict Resolution (authoritative)

Order:
1. min bars gate
2. regime gate
3. min confidence gate
4. split by direction
5. if long and short both exist:
   - compare best long vs best short confidence
   - if abs(diff) < 0.10: no-trade
   - else keep higher confidence side only
6. if multiple remain same side:
   - choose highest confidence
   - if exact confidence tie, use strategy priority list below
7. enforce max concurrent positions
8. reject duplicate instrument + direction if already open

Priority (high to low):
1. ORB
2. TREND_PULLBACK
3. MOMENTUM_CONT
4. BREAKOUT_CONFIRM
5. VOL_COMPRESS_BREAK
6. RANGE_REVERSION
7. MEAN_REVERT_BAND

## 10) Canonical Signal Schema

```json
{
  "strategy_id": "TREND_PULLBACK",
  "direction": "long",
  "regime": "STRONG_TREND",
  "instrument": "XAUUSD",
  "entry_timeframe": "M5",
  "context_timeframe": "H1",
  "signal_time": "2026-04-06T15:00:00Z",
  "entry_price": 1932.5,
  "stop_loss": 1929.8,
  "take_profit_1": 1935.2,
  "take_profit_2": 1938.0,
  "confidence": 0.82,
  "rules_met": {
    "M1": true,
    "M2": true,
    "M3": true,
    "S1": true,
    "S2": false,
    "S3": true,
    "O1": true,
    "O2": true,
    "O3": false
  },
  "meta": {
    "ruleset_version": "1.1",
    "detector_version": "1.1.0",
    "effective_volume_mult": 1.3,
    "position_size_multiplier": 1.0
  }
}
```

## 11) Training Label Quality Rules

- Use this ruleset version to generate labels.
- Do not mix labels across versions.
- Split datasets by time (walk-forward), not random split.
- Include hard negatives by category:
  - near_miss
  - invalid_mandatory
  - opposite_strategy
  - regime_mismatch
- Track label metadata:
  - ruleset_version
  - detector_version
  - dataset_hash
  - parameter_profile

## 12) Release Checklist

- All strategy IDs and regime IDs match canonical enums.
- All rejection checks call the same shared utility.
- All confidence calculations use the same weighted scorer.
- All session timestamps normalized to UTC before detection.
- One authoritative activation matrix is used everywhere.
- Backtest and live engines share the same ruleset package and version.
