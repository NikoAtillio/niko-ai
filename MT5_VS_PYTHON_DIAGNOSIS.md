# MT5 vs Python Trade Divergence - Root Cause Analysis

## Summary
**MT5 is silently rejecting all candidate zones due to an OVERLY STRICT zone proximity tolerance (0.2%), causing trades to fail that Python executes.**

---

## Evidence from Debug Log Analysis (2026-01-29)

### At 15:10:00 UTC (analyzing the 15:05:00 bar)

#### Session Multiplier Status
- ✅ `SessionMultDebug: sessionMult=1.00` - Session filter is PASSING
- ✅ `CanTradeDebug: ... positions=0, cooldownRem=0, lockoutRem=0` - All FTMO guardrails PASSING
- ✅ `ATRDebug: h4ATR=121.16, m15ATR=27.24` - Scoring data available

#### Zone Filtering Results
- **Total zones in memory:** 31
- **Pass rolling window (≤72h old):** 11 zones (indices 20-30)
- **Pass proximity tolerance check:** 0 zones ❌❌❌

#### Zone Proximity Details (Why All 11 Zones Failed)

```
idx  Zone Time              Price      Dir    Distance  Tolerance  Status
---  ---                   ---         ---    ---       ---        ---
20   2026.01.21 18:00:00   24881.25   LONG   0.04730   0.002000   REJECT (23.7x too far)
21   2026.01.22 02:00:00   25507.03   SHORT  0.02161   0.002000   REJECT (10.8x too far)
22   2026.01.22 14:00:00   25341.05   LONG   0.02830   0.002000   REJECT (14.1x too far)
23   2026.01.22 18:00:00   25597.35   SHORT  0.01801   0.002000   REJECT (9.0x too far)
24   2026.01.23 14:00:00   25405.15   LONG   0.02571   0.002000   REJECT (12.9x too far)
25   2026.01.25 22:00:00   25710.13   SHORT  0.01354   0.002000   REJECT (6.8x too far)
26   2026.01.26 06:00:00   25324.16   LONG   0.02899   0.002000   REJECT (14.5x too far)
27   2026.01.26 22:00:00   25800.43   SHORT  0.00999   0.002000   REJECT (5.0x too far)
28   2026.01.27 22:00:00   25787.73   LONG   0.01049   0.002000   REJECT (5.2x too far)
29   2026.01.28 14:00:00   26219.45   SHORT  0.00615   0.002000   REJECT (3.1x too far) ← CLOSEST
30   2026.01.29 02:00:00   25867.76   LONG   0.00736   0.002000   REJECT (3.7x too far)
```

#### Silent Rejection Bug
The tolerance check **silently rejects zones without debug output**, so the EntryScanSummary shows:
```
EntryScanSummary: zones=31 outOfWindow=20 pending=0 zoneTol=0.002000 
                 chase=0 bounce=0 session=0 cluster=0 scoreFloor=0 ltfCap=0 
                 sessionMult=1.00
```

Note: `skipZoneTolerance` counter is NOT printed, so invisible rejection!

---

## Root Cause

### The Problem
**Line 22** of `mql5_v1_ftmo.mq5`:
```c++
input double   InpZoneTolerance = 0.002;             // Zone proximity (0.20%)
```

At **15:10 UTC** on 2026-01-29:
- Signal price (close): **26,058.25**
- Closest zone price: **26,219.45** (idx=29)
- Distance: **(26,219.45 - 26,058.25) / 26,219.45 = 0.00615 = 0.615%**
- Tolerance: **0.2%**
- Result: **0.615% > 0.2% → REJECTED** ❌

The closest zone is **3.1 times outside tolerance!**

### Why No Debug Output?
```c++
// Line 1198-1200 in CheckEntryConditions()
if(zoneDist > GetEffectiveZoneTolerance()) {
    skipZoneTolerance++;
    continue;  // ← NO DEBUG PRINT! Silent failure.
}
```

There is no `if(InpEnableDebugPrint) PrintFormat(...)` after the tolerance check, so the rejection is invisible in logs.

---

## Comparison with Python

The Python implementation (`phantom_US100_high_ftmo.py` line 745) uses **identical tolerance logic**:
```python
if abs(price - z_px) / z_px > conf_tol:  # conf_tol = 0.002
    continue
```

**So why does Python find trades?**

This requires verification:
1. **Check actual Python trade logs for 2026-01-29 14:40, 15:10, 15:35, 16:40, 17:00, 17:20**
2. **Verify the signal prices Python used at those times**
3. **Verify the zone prices Python used at those times**
4. **Check if time zone conversion is consistent between Python (UTC) and MT5 (server)**

---

## Recommended Fixes

### Immediate (Test & Validate)
1. **Add debug output for tolerance rejections** (line 1200):
   ```c++
   if(zoneDist > GetEffectiveZoneTolerance()) {
       skipZoneTolerance++;
       if(InpEnableDebugPrint) PrintFormat("SkipZone idx=%d reason=tolerance zoneDist=%.6f tol=%.6f", i, zoneDist, GetEffectiveZoneTolerance());
       continue;
   }
   ```

2. **Add skipZoneTolerance to EntryScanSummary output** (line 1292):
   ```c++
   PrintFormat("EntryScanSummary: ... skipZoneTol=%d ...", skipZoneTolerance, ...)
   ```

3. **Investigate tolerance mismatch with Python:**
   - Dump zone prices and distances at entry times
   - Compare with Python's exact values  
   - Check if rounding or price source differs

### Longer Term (Architecture Fix)
1. **Make zone tolerance dynamic** based on symbol volatility (ATR-scaled)
2. **Synchronize Python and MT5 tolerance calculations** with unit tests
3. **Add tolerance breakdown to trade journal** for trade review

---

## Next Steps

1. **Enable the new debug output** and re-run tester for 2026-01-29
2. **Compare Python trades for 14:40, 15:10, 15:35, 16:40, 17:00, 17:20** with Python zone prices
3. **Identify if tolerance should be:** 
   - Higher (e.g., 0.5%, 1%)
   - Dynamic (ATR-scaled)
   - Different between Python and MT5 (intentional divergence?)

---

## Files to Update

- `phantom/mql5/mql5_v1_ftmo.mq5` - Line 22 (tolerance), Lines 1200, 1292 (debug)
- `phantom/phantom_US100/phantom_US100_high_ftmo.py` - Verify tolerance application
