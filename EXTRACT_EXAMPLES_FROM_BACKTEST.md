# Extract Real Strategy Examples from Your Backtest Data

## Your Trade Data Structure

You have real winning and losing trades in:
- `/phantom/v2/phantom_v5_1_trades_B_23_24.csv` (Scenario B — your best strategy)
- `/phantom/v2/phantom_v5_1_trades_A_23_24.csv` (Scenario A — M1 entry variant)
- `/phantom/v2/phantom_v5_1_trades_D_23_24.csv` (Scenario D — conservative risk)

### Columns Available
```
entry_ts     → Entry timestamp (e.g., "2023-03-31 04:00:00")
exit_ts      → Exit timestamp
dir          → "long" or "short"
entry        → Entry price
exit         → Exit price
pnl          → Profit/loss in dollars
win          → True/False (winning or losing trade)
exit_reason  → "stop", "target", "timeout" (why it exited)
qty          → Position size
```

---

## How to Map Trades to Your 7 Strategies

Your v2 Scenario B backtest is primarily detecting **TREND_PULLBACK** and **RANGE_REVERSION** setups with H4 zone confluence. But you can extract examples and **manually label them by strategy type** after review.

### Strategy Mapping Logic (from your code)

Your v2 backtest likely triggered on:
1. **TREND_PULLBACK**: Price pulled to a zone, tested it with rejection, resumed trend
2. **RANGE_REVERSION**: Price bounced off H4 pivot level/zone boundary
3. **BREAKOUT_CONFIRM**: Rare in your backtest, but watch for zone breaks with volume

For other strategies (MEAN_REVERT_BAND, VOL_SQUEEZE, ORB, MOMENTUM_CONT), you'll primarily need **examples from public charts or synthetic data**.

---

## Step 1: Select a Winning Trade from the CSV

Example from your data:
```
entry_ts:  2023-03-31 15:30:00
exit_ts:   2023-03-31 22:50:00
dir:       long
entry:     12995.0
exit:      13131.732931822005
pnl:       98.07 (winning)
exit_reason: stop (hit take profit)
```

This is a **short duration trade (7.3 hours)** from entry to exit on US100. Good for a **scalp or swing example**.

---

## Step 2: Gather the Candle Data Around Entry/Exit

You'll need OHLCV (Open, High, Low, Close, Volume) candle data around the entry time.

Check if you have the raw OHLCV files:
```bash
find /Users/niko/Documents/projects/niko-ai -name "*M1*" -o -name "*M5*" -o -name "*H1*" -o -name "*H4*"
```

If you have CSV candle files with datetime and OHLCV, you can extract the window:
- **Start**: 40 candles **before** entry_ts
- **End**: 20 candles **after** exit_ts

Example extraction (pseudocode):
```python
import pandas as pd

# Load the M5 candle data
m5_data = pd.read_csv("US100_M5_2023.csv", parse_dates=["datetime"])

# Trade details
entry_time = "2023-03-31 15:30:00"
exit_time = "2023-03-31 22:50:00"
entry_price = 12995.0

# Extract window: 40 candles before entry, 20 after exit
entry_idx = m5_data[m5_data['datetime'] == entry_time].index[0]
start_idx = max(0, entry_idx - 40)
end_idx = min(len(m5_data), entry_idx + 50)

window = m5_data.iloc[start_idx:end_idx]

# Price levels for annotation
stop_loss = entry_price - 30  # Example: 30 points below
take_profit = entry_price + 100  # Example: 100 points above

# Output for chart annotation
print(f"Chart window: {window.iloc[0]['datetime']} to {window.iloc[-1]['datetime']}")
print(f"Entry: {entry_price}")
print(f"SL: {stop_loss}")
print(f"TP: {take_profit}")
print(f"Outcome: Trade closed at {exit_price}, {pnl} PnL")
```

---

## Step 3: Generate Annotated Chart

Option A: **Python with mplfinance** (Recommended)
```python
import mplfinance as mpf
import pandas as pd

# Load data
data = pd.read_csv("window.csv", parse_dates=["datetime"], index_col="datetime")

# Define markers for entry, SL, TP
apds = [
    mpf.make_addplot([entry_price] * len(data), color='green', width=2, ylabel='Entry'),
    mpf.make_addplot([stop_loss] * len(data), color='red', width=2, ylabel='SL'),
    mpf.make_addplot([take_profit] * len(data), color='blue', width=2, ylabel='TP'),
]

mpf.plot(data, type='candle', addplot=apds, volume=True, title='TREND_PULLBACK_GOOD_1')
```

Option B: **TradingView Chart Export**
- Export the chart image directly from TradingView
- Manually annotate with Paint/Photoshop: entry dot, SL line, TP line, zones

---

## Step 4: Classify Each Trade by Strategy

For each real trade you extract, answer:

```json
{
  "trade_id": "<entry_ts>",
  "strategy_match": "TREND_PULLBACK|RANGE_REVERSION|OTHER",
  "confidence": 0.80,
  "reasoning": [
    "Price pulled to EMA20 where?",
    "Rejection candle visible?",
    "Volume pattern correct?",
    "Entry timing relative to zone touch?"
  ],
  "rule_checks": {
    "trend_confirmed": true,
    "pullback_depth_valid": true,
    "rejection_candle": true,
    "confirmation_candle": true,
    "volume_decreasing_on_pullback": true
  }
}
```

---

## Step 5: Separate Good vs. Bad Examples

From Scenario B trades:
- **WIN trades** (win=True) → "GOOD examples"
- **LOSS trades** (win=False, but low loss or stopped out early) → "BAD examples"
- **BREAK-EVEN trades** → Optional edge cases

Example Bad Trade:
```
entry_ts:  2023-03-31 04:00:00
exit_ts:   2023-03-31 09:20:00
dir:       long
entry:     13007.8
exit:      12974.51
pnl:       -25.27 (LOSS)
exit_reason: stop
```

**Why is this a bad example?**
- Short duration (5 hours), stopped out
- Price never reached take profit
- Likely rejected before trend confirmation
- Good example of a violated rule (no follow-through after zone touch)

---

## Where to Get Raw OHLCV Data

If you don't have raw candle data, you can source it:

1. **From your backtest engine**: Your phantom scripts must have loaded CSV files. Check:
   ```bash
   ls -la /Users/niko/Documents/projects/niko-ai/phantom/v2/
   ```
   Look for `*M1*.csv`, `*M5*.csv`, `*H1*.csv` input files.

2. **Download fresh** (1-week backtest period):
   - TradingView: Export OHLCV to CSV (Free plan allows limited exports)
   - IQFeed, MetaTrader data feeds
   - Alpaca API (crypto/stocks)
   - FRED (macro data)

3. **Synthetic generation**: If stuck, I can create a Python script that generates realistic OHLCV matching your 7 strategy patterns.

---

## Quick Wins: Extract 5–10 Real Examples

**Fastest path:**

1. Open `/phantom/v2/phantom_v5_1_trades_B_23_24.csv`
2. Look at rows 1–20 (first trades)
3. Pick 3 WIN trades → "GOOD examples"
4. Pick 3 LOSS trades → "BAD examples"
5. Note the entry_ts and exit_ts for each
6. If you have hourly or M5 candle data, extract those windows
7. Generate PNG chart for each
8. Annotate with entry/SL/TP
9. Save as `TREND_PULLBACK_GOOD_1.png`, etc.

---

## Tools & Scripts Needed

| Task | Tool | Effort |
|------|------|--------|
| Extract trades from CSV | Excel or pandas | 30 min |
| Get OHLCV windows | pandas script | 1 hour |
| Generate charts | mplfinance or matplotlib | 1-2 hours |
| Annotate (manual) | Paint, Photoshop, Figma | 30 min per image |
| Organize into folders | File system | 15 min |

**Total time: 4-5 hours** for 2-3 real examples per strategy.

---

## Alternative: Use Public Examples First

If extracting your own data is too time-consuming:

1. **Start with the research prompt** I provided — use it to find public examples
2. **Prioritize**: TREND_PULLBACK, BREAKOUT_CONFIRM, RANGE_REVERSION
3. **Once those 3 are locked**, you can use your real backtest data to add more

---

## Questions to Clarify Before Starting

1. **Do you have the raw OHLCV data** that fed your v2 backtest?
2. **Which timeframe is most important** for examples — M1, M5, H1?
3. **Should all examples be US100** or mix with XAUUSD?
4. **How many examples per strategy minimum**? (I recommend 2-3 to start, 5+ per strategy for production)

Let me know and I can help with the extraction script!
