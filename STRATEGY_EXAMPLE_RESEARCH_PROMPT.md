# Chart Example Research Prompt for AI-Assisted Discovery

**For use with Claude, ChatGPT, or similar AI to find/generate trading strategy chart examples.**

---

## Task Overview

I am building a **deterministic, multi-instrument trading strategy recognition platform** with 7 core strategies. I need **2-3 real or synthetic chart examples per strategy** showing:
- ✅ GOOD example (all key rules met, expected outcome)
- ❌ BAD example (rule violation, why it failed)
- Optional: ⚠️ EDGE CASE example (ambiguous, borderline)

Each example should be **annotated with specific rule checks** and **clearly labeled with timeframes and market context**.

---

## The 7 Core Strategies to Find Examples For

| # | Strategy ID | Strategy Name | Market Context | Use Case |
|---|---|---|---|---|
| 1 | TREND_PULLBACK | Trend Continuation Pullback | Confirmed trending market, wait for retrace | Most universal, highest probability |
| 2 | BREAKOUT_CONFIRM | Breakout with Confirmation | Range/consolidation breakout with volume | Captures regime shifts |
| 3 | RANGE_REVERSION | Range Reversion (S/R Bounce) | Oscillating market, fade boundaries | Range-bound markets |
| 4 | MEAN_REVERT_BAND | Mean Reversion to VWAP/Bands | Statistical extremes | Overextended moves |
| 5 | VOL_SQUEEZE | Volatility Compression Breakout | BB/KC squeeze → expansion | Volatility transitions |
| 6 | ORB | Opening Range Breakout | Session open, time-boxed | Liquid, directional opens |
| 7 | MOMENTUM_CONT | Momentum Continuation (Flag/Pennant) | Strong move with brief pause | Trend-riding continuation |

---

## What I Need Per Strategy

For **EACH strategy**, find or generate **3 chart examples**:

### ✅ GOOD Example (High Confidence Setup)
**What to include:**
- Chart image (PNG/JPG) showing 40–80 candles visible
- Annotate with labeled arrows/boxes for:
  - Entry point (green dot)
  - Stop loss zone (red line)
  - Take profit target (blue line)
  - Key support/resistance (dashed lines)
- Metadata:
  - Instrument (e.g., XAUUSD, US100, EURUSD, BTC)
  - Timeframe (e.g., M5, H1, D1)
  - Date/time range
  - Reason WHY this is a good example (which rules it satisfies):
    - Trend confirmed ✓
    - Rejection candle present ✓
    - Volume confirmation ✓
    - No conflicting signals ✓
  - Outcome (if known): +2R, +3R, -1R, etc.

**Example description format:**
```
STRATEGY: TREND_PULLBACK
GOOD Example: Clean H4 Trend Pullback on EURUSD
- Chart: 2024-01-15 to 2024-01-20, M5 timeframe
- Context TF: H4 (Strong uptrend, HH/HL structure)
- Entry TF: M5 (Price pulled to EMA50, rejection candle formed)
- Rules Met:
  ✓ Trend confirmed (EMA20 > EMA50, HH/HL on H4)
  ✓ Pullback depth 45% of impulse leg (in range 23.6%-78.6%)
  ✓ Rejection candle with wick ratio 0.52 (threshold 0.4)
  ✓ Confirmation candle closes above rejection
  ✓ Volume decreases on pullback, increases on continuation
- Outcome: Entry at 1.0820, SL 1.0785, TP 1.0890 = +2.0R
- Source: Real trade from 2024 backtest data
```

### ❌ BAD Example (Rule Violation)
**What to include:**
- Chart showing WHY this should have been rejected
- Annotate the violation clearly
- Metadata:
  - What rule was violated?
  - What should have been different?
  - Why traders would avoid this setup

**Example description format:**
```
STRATEGY: TREND_PULLBACK
BAD Example: Choppy H4 vs. Strong Pullback Signal on GBPUSD
- Chart: 2024-03-10 to 2024-03-15, M5 timeframe
- Context TF: H4 (FLAT, no clear HH/HL structure, ADX 18)
- Entry TF: M5 (Price touched EMA50, rejection candle looks valid)
- Rules Violated:
  ✗ Trend NOT confirmed on H4 (EMA slopes flat, no HH/HL)
  ✗ ADX 18 < threshold 20 (weak trend, high noise)
- Why this fails: Without confirmed trend on higher TF, signal is likely false
- Real outcome: Entry triggered, price reversed immediately, -1.5R
- Lesson: Always confirm trend on context TF FIRST
```

### ⚠️ EDGE CASE Example (Optional but Valuable)
**What to include:**
- Ambiguous setup where rule interpretation matters
- Show how regime or parameters would change the decision

---

## Where to Find Chart Examples

### REAL EXAMPLES (Preferred):
1. **Your own backtest data** (highest priority)
   - Extract candle windows from: `/Users/niko/Documents/projects/niko-ai/phantom/`
   - Use backtest CSVs to generate annotated PNGs
   - Map v1/v2/v3/v4 trades to your 7 strategies

2. **Public trading sites:**
   - TradingView charts (free, zoomable, downloadable)
   - Forex Factory trading ideas and charts
   - CoinGecko/CoinMarketCap for crypto
   - Yahoo Finance for equities
   - Look for user posts with marked entries/exits

3. **Trading education sites:**
   - Babypips.com (Forex education examples)
   - TradingView community ideas (search by strategy type)
   - YouTube trading channels with clear annotations
   - Books: "A Complete Guide to the Futures Market" (Schwager), "Trading in the Zone" (Douglas) — both have case studies

4. **AI-Generated synthetic charts** (fallback):
   - Use a Python script to generate synthetic price data matching rule patterns
   - Annotate with entry/SL/TP as if real

### SEARCH KEYWORDS to use:
- "TREND_PULLBACK": `pullback EMA trend continuation M5 H1 chart example`
- "BREAKOUT_CONFIRM": `range breakout confirmation volume chart setup`
- "RANGE_REVERSION": `support resistance bounce rejection candle chart`
- "MEAN_REVERT_BAND": `mean reversion Bollinger Band fade chart`
- "VOL_SQUEEZE": `volatility squeeze Keltner Channel expansion breakout chart`
- "ORB": `opening range breakout ORB 15-min 30-min chart`
- "MOMENTUM_CONT": `flag pennant continuation momentum trading chart`

---

## Specific Data Points to Extract Per Example

For each chart example you find/create, extract and document:

```json
{
  "strategy_id": "TREND_PULLBACK",
  "example_type": "GOOD",
  "instrument": "XAUUSD",
  "context_timeframe": "H4",
  "entry_timeframe": "M5",
  "outcome_timeframe": "H1",
  "date_start": "2024-01-15",
  "date_end": "2024-01-20",
  "candles_visible": 60,
  "entry_price": 2050.50,
  "stop_loss_price": 2048.00,
  "take_profit_1": 2055.00,
  "take_profit_2": 2060.00,
  "outcome": "2.4R_win",
  "rules_met": [
    "trend_confirmed_on_context_tf",
    "pullback_to_ema_zone",
    "rejection_candle_present",
    "confirmation_candle_present",
    "volume_pattern_correct"
  ],
  "rules_violated": [],
  "confidence_score": 0.82,
  "notes": "Clean setup, no conflicting signals on any timeframe",
  "source": "synthetic_or_real_trade_ID"
}
```

---

## Format Requirements for Examples

1. **Image format**: PNG or JPG, minimum 600x400 px
2. **Annotations**: Use contrasting colors (green entry, red SL, blue TP, yellow zones)
3. **Labels**: Time, price, timeframe, and key levels clearly marked
4. **Data window**: Show enough context (30-80 candles) for indicator calculation
5. **Filename convention**: `{STRATEGY_ID}_{EXAMPLE_TYPE}_{NUMBER}.png`
   - Example: `TREND_PULLBACK_GOOD_1.png`, `RANGE_REVERSION_BAD_2.png`

---

## Deliverable Format

Once you gather examples, return them structured like this:

```
📁 strategy-examples/
├── TREND_PULLBACK/
│   ├── TREND_PULLBACK_GOOD_1.png
│   ├── TREND_PULLBACK_GOOD_1.json  (metadata)
│   ├── TREND_PULLBACK_BAD_1.png
│   ├── TREND_PULLBACK_BAD_1.json
│   └── TREND_PULLBACK_EDGE_CASE_1.png (optional)
├── BREAKOUT_CONFIRM/
│   ├── BREAKOUT_CONFIRM_GOOD_1.png
│   └── ...
└── [5 more strategy folders]
```

---

## Priority Order

1. **HIGH PRIORITY**: TREND_PULLBACK, BREAKOUT_CONFIRM, RANGE_REVERSION (most universal)
2. **MEDIUM PRIORITY**: MEAN_REVERT_BAND, VOL_SQUEEZE, ORB (specialized but important)
3. **LOWER PRIORITY**: MOMENTUM_CONT (fewer examples available publicly)

---

## Critical Questions to Answer

Before you finalize examples, clarify:

1. **Are these examples meant to be synthetic or real?**
   - Synthetic: Faster, fully controlled
   - Real: More credible for model training, harder to find

2. **Which instruments should I focus on?**
   - XAUUSD (gold) — primary
   - EURUSD, GBPUSD (forex)
   - US100, S&P500 (indices)
   - BTC, ETH (crypto)
   - All of the above for universality?

3. **What timeframe combinations?**
   - Suggested: Start with M5/M15 entry, H1/H4 context (matches your v2 backtest)

4. **Do you want real-trade examples from your backtest data?**
   - If yes, I can extract winning/losing trades from phantom/v2/v4 logs and annotate them

---

## Next Steps

1. **Verify strategy definitions** — Confirm the 7 strategies and rule thresholds are locked
2. **Gather or generate 2-3 examples per strategy** — Use this prompt to search/create
3. **Annotate with rule checks** — Mark which rules each example satisfies/violates
4. **Compile into JSON + images** — Structured dataset
5. **Feed to code generation AI** — "Generate TypeScript detector functions using these examples"

---

## Additional Resources

- **Books**: "The Disciplined Trader" (Douglas) has classic pullback + breakout examples
- **Sites**: TradingView.com (free charts, searchable), Forex Factory, CoinGecko
- **Tools**: Python `mplfinance` or `plotly` to generate annotated chart PNGs from CSV candle data
- **Your data**: Check `/phantom/v2/phantom_v5_1_trades_*.csv` for real trade data to extract examples from

---

**Once you gather these examples, share them back and I can:**
- Verify they match rule specs
- Generate JSON schemas
- Create TypeScript detector code
- Build unit test cases

Good luck with the research drive! 🎯
