# Root Cause: Time Zone Mismatch MT5 vs Python

## Problem Summary
Python trades on 2026-01-29 at 14:40, 15:10, 15:35, 16:40, 17:00, 17:20 UTC (6 trades).
MT5 doesn't execute these trades. Only found tolerance rejection as visible blocker, but discovered deeper issue.

## Timeline Diagnosis

### MT5 Session Debug Output (from tester log):
```
2026.01.29 14:40:00   SessionDebug: serverTime=2026.01.29 14:40 utcHour=12 (session=13-21) → sessionMult=0.00 ❌
2026.01.29 15:10:00   SessionDebug: serverTime=2026.01.29 15:10 utcHour=13 (session=13-21) → sessionMult=1.00 ✓
2026.01.29 15:35:00   SessionDebug: serverTime=2026.01.29 15:35 utcHour=13 (session=13-21) → sessionMult=1.00 ✓
```

### The Issue: Wrong UTC Offset

**MT5 EA Configuration** (mql5_v1_ftmo.mq5 lines 78-81):
```c
input int  InpBrokerUTCOffset = 2;         // Broker time = UTC + offset
input bool InpAutoUTCOffset = true;        // Auto-switch winter/summer
input int  InpWinterUTCOffset = 2;         // Winter (Nov-Mar)
input int  InpSummerUTCOffset = 3;         // Summer (Mar-Nov)
```

**Time Conversion Function** (mql5_v1_ftmo.mq5 lines 2017-2019):
```c
datetime ToUTC(datetime serverTime) {
   int offset = GetEffectiveUTCOffset();   // Returns 2 in January (winter)
   return serverTime - (offset * 3600);    // Convert UTC+2 → UTC
}
```

**What Happens at 14:40 on 2026-01-29 (January = winter)**:
```
barTime = 14:40 (as displayed by MT5)
offset = 2 (winter offset for CET)
barTimeUtc = 14:40 - 2:00 = 12:40 UTC ← WRONG!
utc.hour = 12 ← WRONG!
Session check: 12 < 13 → sessionMult=0.00 (outside session)
```

### The Real Problem: Data Source Timezone

**US100 Cash Data** (from /data/US100/US100.cash_M5_...):
- Exported from MT5 historical data which is in **NYSE Local Time (EST = UTC-5)**
- Sample: 2026.01.29 14:40 in the CSV is actually **14:40 EST = 19:40 UTC**

**EA's Offset**:
- Treating data as UTC+2 (European/CET timezone)
- Applying wrong conversion: 14:40 - 2hrs = 12:40 UTC (but should be 14:40 - (-5) = 19:40 UTC)

### Evidence: CSV Data Format

```
<DATE>      <TIME>      <OPEN>      ...
2026.01.29  14:40:00    26038.55    ...  ← This is 14:40 EST (NYC time)
2026.01.29  14:45:00    26035.25    ...  ← This is 14:45 EST (NYC time)
```

Converting to UTC:
- 14:40 EST = 14:40 + 5 = 19:40 UTC ✓ (inside session 13:00-21:00)
- 15:10 EST = 15:10 + 5 = 20:10 UTC ✓ (inside session 13:00-21:00)

But EA calculation:
- 14:40 (displayed) - 2 = 12:40 UTC ✗ (outside session 13:00-21:00)
- 15:10 (displayed) - 2 = 13:10 UTC ✓ (inside session 13:00-21:00, barely)

**This explains the trade times:**
- 14:40, 14:45: sessionMult=0.00 (rejected as out-of-session)
- 15:10+ : sessionMult=1.00 or 1.20 (passes session check)

### Why Python "Works" (But Might Have Different Issue)

Python code (phantom_US100_high_ftmo.py):
1. Loads CSV directly: times are in EST but treated as naive datetime
2. Extracts `hour = ts.hour` directly: gets 14, 15, 16, 17, etc.
3. Checks session: `13 <= 14 < 21` → TRUE (passes!)
4. But this is ALSO wrong! The times should be in UTC for the session comparison.

**Python might be executing trades at EST times when session is supposed to be UTC times:**
- Python sees 14:40, hour=14, 13 ≤ 14 < 21 → trade allowed
- But 14:40 EST is actually 19:40 UTC, which is INSIDE peak session (14-17 UTC is wrong hour range anyway)

### Secondary Issue: Peak Session Hours

Config shows peak session as 14-17 UTC (InpPeakSessionBoost).
But NYSE peak hours would be different in UTC (14-17 UTC = 9-12 EST, which is market OPEN but not peak).

## Solution

Need to fix the UTC offset to match NYSE/US100 timezone:
- US100 trades in EST (UTC-5) in winter, EDT (UTC-4) in summer
- Should be: `InpBrokerUTCOffset = -5` (winter) or `-4` (summer) OR auto-detect correctly

### Option 1: Fix EA to Use US100 Hours Directly
```c
// For US100, use EST/EDT offset
input int  InpBrokerUTCOffset = -5;       // EST (winter)
input int  InpSummerUTCOffset = -4;       // EDT (summer)
```

### Option 2: Align Python with MT5 Session Windows
```python
# Ensure Python converts to UTC before session check
ts_utc = pd.to_datetime(ts, utc=True).dt.tz_convert('UTC')
hour_utc = ts_utc.hour
session_check = 13 <= hour_utc < 21
```

### Option 3: Clarify Session Definition in Config
- Specify if session is "NYSE hours" (9:30-16:00 EST = 14:30-21:00 UTC)
- Specify if peaks are "market volume peak" (14:30-16:00 UTC = 9:30-11:00 EST)

## Validation

After fix, verify:
1. 14:40 EST (19:40 UTC) should be sessionMult=1.00 (inside 13-21 UTC)
2. 14:00 EST (19:00 UTC) should be sessionMult=1.20 (peak hours 14-17 UTC) - WAIT, this is wrong!
3. Python and MT5 use same time reference for trades

## Immediate Action

1. Check what `TimeCurrent()` actually returns in MT5 backtesting for US100
2. Determine if MT5 chart times are displayed in broker time or symbol's native time
3. Update `InpBrokerUTCOffset` to -5 (for EST) or implement proper timezone detection
4. Add debug output to show both displayed time AND UTC time for verification
5. Align Python session window calculation with corrected MT5 offset
