# Apply Installed Capacities Fix - Summary

## Problem Statement
When users load an Installed Capacity CSV file **after** switching ISOs, the "New Build" values displayed in the economics table were incorrect. They showed the delta between the old ISO's capacity and the new CSV's capacity, rather than showing only the actual new builds for the current ISO.

## Root Cause Analysis

### The Bug
The issue was in the `applyInstalledCapacities()` function (lines 6004-6065). This function is called when users upload an Installed Capacity CSV file. It had logic that **intentionally skipped** setting `etrCapacities` for retire-only technologies:

```javascript
// OLD CODE (BUGGY):
if (techId !== 'new-gas-ccgt' && techId !== 'new-gas-ct' && 
    techId !== 'existing-gas' && techId !== 'coal' && techId !== 'oil' && techId !== 'other') {
    etrCapacities[techId] = capacity;
}
```

This meant that for retire-only technologies (existing-gas, coal, oil, other), their `etrCapacities` values were never updated when loading a CSV file.

### Why This Caused the Bug

The "New Build" calculation uses this formula:
```javascript
const newBuildMw = Math.max(0, capacity - (etrCapacities[tech.id] || 0));
```

**Scenario that triggered the bug:**
1. User selects ISO A (e.g., CAISO)
   - `updateSystemFromProjectDB()` sets `etrCapacities['coal'] = 5000` (for CAISO)
2. User switches to ISO B (e.g., ERCOT)
   - `updateSystemFromProjectDB()` properly updates `etrCapacities['coal'] = 8000` (for ERCOT)
3. User loads an Installed Capacity CSV for ISO B
   - `applyInstalledCapacities()` runs
   - Sets slider to `capacity = 8000`
   - **SKIPS** updating `etrCapacities['coal']` (still has 8000 from step 2, but might be stale if CSV is for different year)
   - If CSV is for a different year or the value changed: `newBuildMw = 10000 - 8000 = 2000` ✗ (wrong)

**Expected behavior:**
- `etrCapacities['coal'] = 10000 - scheduledBuildMw` (e.g., 10000 - 500 = 9500)
- `newBuildMw = 10000 - 9500 = 500` ✓ (correct - only scheduled builds show as new)

## The Fix

### Changes Made
Modified `applyInstalledCapacities()` to properly set `etrCapacities` for **all technologies** (except new-gas-ccgt and new-gas-ct):

```javascript
// NEW CODE (FIXED):
// Get current ISO and year for scheduled builds lookup
const iso = document.getElementById('isoSelector')?.value;
const year = document.getElementById('yearSelector')?.value;

// ... in the data loop ...

// Set etrCapacities for all technologies to ensure consistency when CSV is loaded after ISO switching
// Don't set for new-gas-ccgt and new-gas-ct as they should remain at their dispatch stack value (or 0)
if (techId !== 'new-gas-ccgt' && techId !== 'new-gas-ct') {
    // For retire-only technologies, account for scheduled builds so they show as "new build"
    if (techId === 'existing-gas' || techId === 'coal' || techId === 'oil' || techId === 'other') {
        const scheduledBuildMw = getScheduledBuilds(iso, year, techId);
        etrCapacities[techId] = Math.max(0, capacity - scheduledBuildMw);
    } else {
        // For expandable technologies, use the capacity directly as baseline
        etrCapacities[techId] = capacity;
    }
}
```

### Key Improvements

1. **Get ISO/Year Context** (lines 6017-6019):
   - Retrieve current ISO and year to enable scheduled builds lookup
   - Required to calculate correct baseline for retire-only technologies

2. **Update etrCapacities for Retire-Only Technologies** (lines 6045-6047):
   - Calculate scheduled builds: `getScheduledBuilds(iso, year, techId)`
   - Set baseline: `etrCapacities[techId] = Math.max(0, capacity - scheduledBuildMw)`
   - Use `Math.max(0, ...)` to prevent negative values (consistent with `updateRetireOnlySlider`)

3. **Update etrCapacities for Expandable Technologies** (lines 6049-6050):
   - Set baseline: `etrCapacities[techId] = capacity`
   - These technologies can expand, so full capacity is the baseline

4. **Skip new-gas-ccgt and new-gas-ct** (line 6043):
   - These remain at dispatch stack values (or 0)
   - This is intentional and unchanged from original behavior

## Impact

### What Was Fixed
✅ When switching ISOs then loading a CSV, `etrCapacities` is now properly set for retire-only technologies
✅ "New Build" column correctly shows only actual new builds, not the full installed capacity
✅ Scheduled builds are properly accounted for and appear as "new build" capacity
✅ The fix is minimal and surgical - only modifies the conditional logic for setting `etrCapacities`

### What Wasn't Changed
- No changes to slider behavior
- No changes to annual capacity calculations
- No changes to UI components
- No changes to model algorithms
- new-gas-ccgt and new-gas-ct behavior remains unchanged

## Consistency with Other Functions

This fix makes `applyInstalledCapacities` consistent with:

1. **`updateSystemFromProjectDB()`** (line 4282):
   - Also sets `etrCapacities[id] = mw - scheduledBuildMw` for all technologies
   - CSV loader now follows the same pattern

2. **`updateRetireOnlySlider()`** (line 5969):
   - Uses `Math.max(0, effectiveTotalCapacity - scheduledBuildMw)`
   - CSV loader now uses the same safeguard against negative values

## Testing Protocol

To verify the fix works:

1. Load project database and all required data files
2. Select ISO #1 (e.g., CAISO)
3. Note the installed capacity values and "New Build MW" in the economics table
4. Switch to ISO #2 (e.g., ERCOT)
5. **Load an Installed Capacity CSV file** for ISO #2
6. Observe the "New Build MW" column in the economics table

**Expected Result**: 
- New Build MW should show only actual scheduled builds for ISO #2
- Should NOT show the full installed capacity as new build
- Should NOT show the delta between ISO #1 and ISO #2 capacities

## Example Scenario

**Before Fix (Buggy):**
1. CAISO selected: coal slider=5000 MW, etrCapacities['coal']=4800 MW
2. Switch to ERCOT: coal slider=10000 MW, etrCapacities['coal']=9500 MW (500 MW scheduled builds)
3. Load CSV with coal=10000 MW:
   - Slider set to 10000 MW
   - etrCapacities['coal'] NOT updated (still 9500 MW from step 2)
   - newBuild = 10000 - 9500 = 500 MW ✓ (works if values match)
4. BUT if CSV has coal=11000 MW:
   - Slider set to 11000 MW
   - etrCapacities['coal'] NOT updated (still 9500 MW)
   - newBuild = 11000 - 9500 = 1500 MW ✗ (wrong! should be 500 MW scheduled builds)

**After Fix (Correct):**
1. CAISO selected: coal slider=5000 MW, etrCapacities['coal']=4800 MW
2. Switch to ERCOT: coal slider=10000 MW, etrCapacities['coal']=9500 MW
3. Load CSV with coal=11000 MW:
   - Slider set to 11000 MW
   - scheduledBuildMw = 500 MW (from getScheduledBuilds)
   - etrCapacities['coal'] = 11000 - 500 = 10500 MW (updated!)
   - newBuild = 11000 - 10500 = 500 MW ✓ (correct! only scheduled builds)

## Technical Details

### Key Variables
- **`etrCapacities`**: Object storing baseline installed capacity for each technology
- **`capacity`**: Current capacity value from the CSV file
- **`scheduledBuildMw`**: Capacity of projects scheduled to come online in the selected year
- **`newBuildMw`**: Calculated as `capacity - etrCapacities[tech.id]`

### Why This Works
By ensuring `applyInstalledCapacities()` properly sets `etrCapacities` for all technologies:
1. CSV values are loaded into sliders
2. `etrCapacities` is set to match, accounting for scheduled builds
3. When the economics table calculates "New Build", it uses the correct baseline
4. Result: Only actual new builds are shown, not artifacts from ISO switching

## Conclusion

This fix resolves the ISO switching bug when loading CSV files by ensuring `etrCapacities` is properly updated for retire-only technologies. The change is minimal and surgical - it only extends the existing logic to cover previously excluded technologies, while maintaining the same scheduled builds accounting used elsewhere in the codebase.
