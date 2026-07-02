# ISO Toggle Bug Fix - Summary

## Problem Statement
When switching from one ISO to another in the Capacity Expansion Model, the installed capacity from the previous ISO was incorrectly displaying as "new build" capacity in the newly selected ISO.

## Root Cause Analysis

### The Bug
The issue was in the `applyAssumptions()` function in the file `ETR_Dynamic_Cap_Expansion_Forecast_1.6.html`. The problem occurred due to improper ordering of operations when an ISO change was detected:

1. **Lines 4482-4504**: When ISO changed, code reset all sliders and `etrCapacities` to 0
2. **Lines 4516-4569**: Calibration logic ran, including multiple calls to `runModel()`:
   - Line 4532: `calibrateFromZone()` called, which invokes `runModel()` at line 4043
   - Line 4539: Direct `runModel()` call during training
   - Line 4551: Another `runModel()` call after switching back to original year
3. **Line 4558 (OLD)**: `updateSystemFromProjectDB()` was FINALLY called to properly set capacities

The problem: All `runModel()` executions happened with `etrCapacities = 0`, while sliders may have been set to non-zero values. This caused the "New Build" calculation to be incorrect:

```javascript
// In getFinancialsWithMetrics() at line 7676:
const newBuildMw = Math.max(0, capacity - (etrCapacities[tech.id] || 0));
```

If `capacity = 30000` (from slider) but `etrCapacities[tech.id] = 0`, then:
```
newBuildMw = 30000 - 0 = 30000
```

This showed the full installed capacity as "new build", which is incorrect.

## The Fix

### Changes Made
Moved the `updateSystemFromProjectDB()` call to execute **BEFORE** any calibration or model runs:

1. **Line 4508-4512 (NEW)**: Call `updateSystemFromProjectDB(iso, year)` immediately after setting `lastSelectedIso`
   - This happens BEFORE calibration logic
   - Ensures `etrCapacities` is properly set for the new ISO before any model execution

2. **Line 4531 (NEW)**: Added `updateSystemFromProjectDB(iso, BASE_CALIBRATION_YEARS[0])` when temporarily switching to calibration year
   - Ensures capacities are correct for the calibration year during training

3. **Line 4558 (NEW)**: Added `updateSystemFromProjectDB(iso, originalYear)` when switching back to original year
   - Ensures capacities are correct for the original year after training

### Code Changes
```javascript
// OLD CODE (BUGGY):
lastSelectedIso = iso;

// Auto-select first zone...
// ... calibration logic that calls runModel() ...

// Update Tech/Dispatch from DB (TOO LATE!)
if(projectDatabase) {
    updateSystemFromProjectDB(iso, year);
}

// NEW CODE (FIXED):
lastSelectedIso = iso;

// Update Tech/Dispatch from DB FIRST (BEFORE model runs)
if(projectDatabase) {
    updateSystemFromProjectDB(iso, year);
}

// Auto-select first zone...
// ... calibration logic that calls runModel() ...
// (now etrCapacities is already set correctly)
```

## Impact

### What Was Fixed
- When switching ISOs, `etrCapacities` is now properly initialized BEFORE any model calculations
- "New Build" column correctly shows only actual new builds, not existing installed capacity
- The fix is minimal and surgical - only reorders existing function calls

### What Wasn't Changed
- No changes to calculation logic
- No changes to data structures
- No changes to UI components
- No changes to model algorithms

## Testing Protocol

To verify the fix works:

1. Load test data (project database, load data, pricing data)
2. Select ISO #1 (e.g., CAISO)
3. Observe installed capacity sliders and "New Build MW" column in the economics table
4. Switch to ISO #2 (e.g., ERCOT)
5. Observe installed capacity sliders and "New Build MW" column again
6. **Expected Result**: New Build MW should show only actual new builds for ISO #2, NOT the installed capacity values from ISO #1

## Technical Details

### Key Variables
- `etrCapacities`: Object storing baseline installed capacity for each technology
- `sliderValue`: Current slider value representing total installed capacity
- `newBuildMw`: Calculated as `sliderValue - etrCapacities[tech.id]`

### Why This Works
By ensuring `updateSystemFromProjectDB()` runs before any model execution:
1. Sliders are set to the new ISO's installed capacities
2. `etrCapacities` is set to match (excluding scheduled builds)
3. When `runModel()` executes, it uses correct values
4. Financial table displays correct "New Build" values: `newBuildMw = capacity - etrCapacities`

### Example
**Scenario: Switch from CAISO to ERCOT**

#### Before Fix (Buggy):
1. CAISO selected: slider=50000 MW, etrCapacities=45000 MW, newBuild=5000 MW ✓
2. Switch to ERCOT:
   - Reset: slider=0, etrCapacities=0
   - runModel() called with etrCapacities=0
   - updateSystemFromProjectDB: slider=30000, etrCapacities=0 still (too late!)
   - Result: newBuild = 30000 - 0 = 30000 MW ✗ (shows full capacity as new build)

#### After Fix (Correct):
1. CAISO selected: slider=50000 MW, etrCapacities=45000 MW, newBuild=5000 MW ✓
2. Switch to ERCOT:
   - Reset: slider=0, etrCapacities=0
   - updateSystemFromProjectDB: slider=30000, etrCapacities=28000 (excludes 2000 MW scheduled builds)
   - runModel() called with correct etrCapacities=28000
   - Result: newBuild = 30000 - 28000 = 2000 MW ✓ (shows only actual new builds)

## Conclusion

This fix resolves the ISO toggle bug by ensuring proper initialization order. The change is minimal, only reordering when `updateSystemFromProjectDB()` is called, ensuring data is set before it's used in calculations. This prevents the incorrect display of installed capacity as new build capacity when switching between ISOs.
