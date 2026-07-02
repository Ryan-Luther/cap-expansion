# Fresh Start Year Fix - etrCapacities Baseline Logic

## Problem Statement

After the ISO Toggle Bug Fix was implemented, there remained a logic gap for "fresh start years" - years where no savedData or priorYearData exists for an ISO/Year combination.

### The Issue

In `applyAssumptions()`, after `updateSystemFromProjectDB(iso, year)` runs:
1. The code loads the new ISO's capacity into the sliders (e.g., 5000 MW)
2. `updateSystemFromProjectDB` sets `etrCapacities[tech.id] = mw - scheduledBuildMw` (line 4310)
   - This excludes scheduled builds from the baseline
   - Designed to make scheduled builds appear as "new build" capacity
3. For a **fresh start year** (no saved history), this causes the entire installed capacity to incorrectly show as 'New Build'

### Example Scenario

**Fresh Start Year (CAISO 2025, no saved data):**
- Database has 5000 MW of solar (including 200 MW scheduled builds)
- Slider is set to 5000 MW
- `updateSystemFromProjectDB` sets `etrCapacities['solar'] = 5000 - 200 = 4800 MW`
- Result: New Build = 5000 - 4800 = **200 MW** ❌

**Expected Behavior:**
- For a base/fresh start year, New Build should be **0 MW** ✓
- The baseline (etrCapacities) should match the full installed capacity

## The Fix

### Solution
Added logic immediately after `updateSystemFromProjectDB` is called (after line 4512) to:
1. Check if `savedData[iso]?.[year]` exists
2. Check if `getMostRecentPriorYearData(iso, year)` returns any prior year data
3. If BOTH checks are false (meaning this is a fresh start year):
   - Iterate through all `generationTypes`
   - Set `etrCapacities[tech.id] = slider.value`
   - This ensures baseline matches installed capacity
4. Only apply when `projectDatabase` exists (to ensure sliders were actually updated)

### Code Changes

```javascript
// Added after line 4512 in applyAssumptions()
// Check if this is a fresh start year (no savedData or priorYearData)
// If so, set etrCapacities to match slider values to ensure baseline = installed capacity
// Only apply this fix when projectDatabase exists and has updated the sliders
if (projectDatabase && !savedData[iso]?.[year] && !getMostRecentPriorYearData(iso, year)) {
    // This is a fresh start year - set baseline to match installed capacity
    generationTypes.forEach(tech => {
        const slider = document.getElementById(`${tech.id}-slider`);
        if (slider) {
            etrCapacities[tech.id] = parseFloat(slider.value) || 0;
        }
    });
}
```

## Impact

### What Was Fixed
✅ Fresh start years now correctly show 0 MW of New Build for existing capacity
✅ Baseline (etrCapacities) matches installed capacity for base years
✅ Scheduled builds in fresh start years are included in the baseline (not shown as new build)
✅ No impact on years with saved data or prior year data (existing logic remains unchanged)

### Behavior by Scenario

#### Scenario 1: Fresh Start Year (NEW FIX)
- **Condition:** No savedData, no priorYearData
- **Slider Value:** 5000 MW (from database)
- **etrCapacities:** 5000 MW (full capacity, including scheduled builds)
- **New Build:** 5000 - 5000 = **0 MW** ✓

#### Scenario 2: Year with Current SavedData (UNCHANGED)
- **Condition:** savedData exists for current year
- **Behavior:** Lines 4593-4628 handle this case
- **etrCapacities:** Set based on prior year capacity minus retirements
- **New Build:** Shows actual capacity additions from saved state ✓

#### Scenario 3: Year with Prior Year SavedData (UNCHANGED)
- **Condition:** No current year savedData, but priorYearData exists
- **Behavior:** Lines 4631-4667 handle this case
- **etrCapacities:** Prior year capacity minus retirements (excludes scheduled builds)
- **New Build:** Shows retirements + scheduled builds ✓

## Technical Details

### Why This Works

1. **Fresh Start Logic Only Applies When Appropriate:**
   - Checks `projectDatabase` exists to ensure sliders were updated
   - Checks for absence of both savedData and priorYearData
   - Only overwrites etrCapacities in the specific case of a fresh start

2. **Preserves Existing Behavior:**
   - If savedData exists, the existing logic at lines 4593-4628 runs instead
   - If priorYearData exists, the existing logic at lines 4631-4667 runs instead
   - The new logic fills the gap for the case that was previously unhandled

3. **Includes Scheduled Builds in Baseline for Fresh Start:**
   - For a fresh start year, all capacity (including scheduled builds) is treated as baseline
   - This is correct because we're starting from a clean slate
   - We don't want existing/scheduled capacity to show as "new build" on day 1

### Key Variables
- `etrCapacities`: Object storing baseline installed capacity for each technology
- `slider.value`: Current slider value representing total installed capacity
- `newBuildMw`: Calculated as `slider.value - etrCapacities[tech.id]`
- `savedData[iso][year]`: Stored capacity data for a specific ISO/Year
- `priorYearData`: Most recent prior year's saved capacity data

### Implementation Notes
- Avoided variable shadowing by using inline checks instead of declaring intermediate variables
- Added `projectDatabase` check to ensure sliders have been updated before applying fix
- Used `parseFloat(slider.value) || 0` to handle any edge cases with slider values

## Testing Recommendations

To verify the fix works correctly:

1. **Test Fresh Start Year:**
   - Load project database with capacity data for an ISO
   - Select an ISO/Year combination with no saved history
   - Verify: New Build MW = 0 for all technologies with installed capacity
   - Verify: Sliders show database capacity values

2. **Test Year with Saved Data:**
   - Save capacity data for an ISO/Year
   - Navigate away and back to that ISO/Year
   - Verify: Saved capacities are restored correctly
   - Verify: New Build shows changes from saved state

3. **Test Year with Prior Year Data:**
   - Save capacity data for Year 1
   - Switch to Year 2 (no saved data)
   - Verify: Capacities carried forward from Year 1
   - Verify: New Build shows retirements + scheduled builds

4. **Test ISO Toggle:**
   - Load data for multiple ISOs
   - Switch between ISOs
   - Verify: Each ISO shows correct capacity and New Build values
   - Verify: No "ghost" capacity from previous ISO

## Conclusion

This fix completes the logic for handling capacity baselines in the `applyAssumptions()` function. By ensuring that fresh start years have a baseline equal to installed capacity, we prevent the misleading display of existing capacity as "new build" capacity. The fix is minimal, targeted, and preserves all existing behavior for years with saved data or prior year data.
