# Next Steps: Finding the 13.02% Configuration Difference

## Root Cause Established
**Strategy C uses 13.02% larger position sizes on identical trades.**  
**This equals a 1.1302x risk_amt multiplier.**

## Investigation Steps

### Step 1: Check Strategy C Run Script
```bash
# Find what script generated the Strategy C backtest
grep -r "branch-competition-us100-20260416" /Users/niko/Documents/projects/niko-ai/
# Look for: run_us100_branch_competition.sh or similar
# Check the actual command that was executed
# Specifically look for: --capital, --risk, --risk_pct arguments
```

### Step 2: Check Current Live Run Script
```bash
# Find what script generated the phantom-p2-fixed-20260417_203820 backtest
grep -r "phantom-p2-fixed-20260417" /Users/niko/Documents/projects/niko-ai/
# Compare the command-line arguments used
```

### Step 3: Check for Configuration Overrides
```bash
# In phantom/v2/phantom_p2.py, search for:
grep -n "risk_pct\|risk_amt\|capital" /Users/niko/Documents/projects/niko-ai/phantom/v2/phantom_p2.py

# Look for:
# - Instrument-specific overrides: INSTRUMENTS['US100']['risk_pct']
# - Runtime parameter application
# - Special handling for 'B' scenario
```

### Step 4: Check Run Script Parameters
```bash
# Open the branch competition run script:
cat /Users/niko/Documents/projects/niko-ai/run_us100_branch_competition.sh

# Look for:
# - --capital or -c (initial capital)
# - --risk or -r (risk percentage)
# - --risk_pct (alternative risk naming)
# - Any scaling factors
```

### Step 5: Verify Git History
```bash
# Check if risk_pct changed in git history:
git log --oneline -p p2_filter_test2 -- phantom/v2/phantom_p2.py | grep -B3 -A3 "risk_pct"
git log --oneline -p p2_filter_test3 -- phantom/v2/phantom_p2.py | grep -B3 -A3 "risk_pct"

# Check if it's a per-instrument setting:
git show p2_filter_test2:phantom/v2/phantom_p2.py | grep -A 50 "INSTRUMENTS\|US100"
git show p2_filter_test3:phantom/v2/phantom_p2.py | grep -A 50 "INSTRUMENTS\|US100"
```

### Step 6: Check for Multiplier Constants
```bash
# Search for hardcoded multipliers:
grep -n "1.13\|1.1\|0.79\|0.791" /Users/niko/Documents/projects/niko-ai/phantom/v2/phantom_p2.py
grep -n "1.13\|1.1\|0.79\|0.791" /Users/niko/Documents/projects/niko-ai/run_p2_validation_matrix.py

# The exact 1.1302x ratio must come from something...
```

---

## Possible Findings

### Scenario A: Different Risk Percentage
```python
# If test2 uses: risk_pct = 0.007
# And test3 uses: risk_pct = 0.007915
# Then: 0.007915 / 0.007 = 1.1307x ✓ PERFECT MATCH
```

**Where to look:**
- `SCENARIOS['B']['risk_pct']` in both branches
- Instrument-specific overrides: `INSTRUMENTS['US100']['risk_pct']`
- Runtime arguments: `--risk_pct` or similar

### Scenario B: Different Initial Capital
```python
# If test2 uses: capital = 10000
# And test3 uses: capital = 11302
# Then position sizes would be 1.1302x larger
```

**Where to look:**
- Command-line argument: `--capital 11302`
- Default in code: `capital = args.capital or 10000`
- Run script variable: `CAPITAL=11302`

### Scenario C: Confidence Multiplier Difference
```python
# If test2 applies: confidence_mult scaling differently
# And test3 applies: base multiplier 1.13x higher
```

**Where to look:**
- Confidence multiplier application logic
- Per-trade multiplier variations
- But unlikely because: ratio is consistent across ALL trades

### Scenario D: Size Multiplier Configuration
```python
# If test2 uses: session_mult or regime_mult baseline
# And test3 uses: 1.13x that baseline
```

**Where to look:**
- `session_mult` calculation
- `regime_mult` values  
- `conf_mult` application

---

## How to Verify Once Found

Once you identify the configuration difference, verify by:

```bash
# Re-run Strategy C with Current Live's config:
python phantom/v2/phantom_p2.py \
  --branch p2_filter_test3 \
  --capital 10000 \
  --risk_pct 0.007 \
  --instrument US100 \
  --scenario B \
  --data_path /path/to/data

# Compare resulting qty column - should now match Current Live
# If PnL % matches Current Live, the difference is confirmed
```

---

## Expected Outcome

Once the 13.02% configuration difference is identified:

1. **Document the difference** in a config/parameters file
2. **Decide which is correct**: Is aggressive (test3) or conservative (test2) the standard?
3. **Apply consistently**: Update the branch that should use the different config
4. **Re-run comparison**: Confirm new results

---

## Summary

**We know the problem:** Position sizing multiplier is 1.1302x different  
**We know it's not the code:** Entry/exit logic is identical  
**We need to find:** Where in configuration/parameters this difference is set

The investigation is narrowed down to configuration files, run scripts, and command-line arguments. The difference is **deterministic and calculable**, just not yet located in the source.
