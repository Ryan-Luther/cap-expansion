# Test Plan: Year Switching Data Persistence Fix

## Issue
When optimizing all years then changing the year selector, optimized values briefly show but then reset to non-optimized (database) values.

## Root Cause
Event listeners for ISO/year selector changes were calling `applyAssumptions()` without awaiting it, then immediately calling `restoreSavedCapacities()`. This caused a race condition where:
1. `restoreSavedCapacities()` would briefly restore optimized values
2. `applyAssumptions()` would continue executing asynchronously and call `updateSystemFromProjectDB()` which overwrites sliders with database values
3. `applyAssumptions()` would then try to restore saved data, but timing issues could cause incomplete restoration

## Fix Applied
- Made event listeners async and added `await` before `applyAssumptions()` calls
- Removed redundant `restoreSavedCapacities()` calls since `applyAssumptions()` already handles data restoration at lines 4847-4884
- Applied fix to both `isoSelector` and `yearSelector` event listeners for consistency

## Manual Test Steps

### Prerequisites
1. Open `ETR_Dynamic_Cap_Expansion_Forecast_1.6.html` in a web browser
2. Upload required data files:
   - Capacity factors CSV
   - Load data CSV
   - Project database CSV
   - Market assumptions CSV

### Test Case 1: Optimize All Years Then Switch Years
1. Select an ISO (e.g., "PJM")
2. Click "Run All Years" button to optimize all years
3. Wait for optimization to complete (status should show "Batch optimization complete")
4. Note the capacity values for the last optimized year
5. Use the year dropdown to switch to a different year (e.g., from 2026 to 2027)
6. **Expected Result**: The capacity sliders should show the optimized values for year 2027 (not database defaults)
7. Switch back to the previous year (e.g., 2026)
8. **Expected Result**: The capacity sliders should show the optimized values for year 2026
9. Switch to several different years that were optimized
10. **Expected Result**: Each year should retain its optimized capacity values

### Test Case 2: Verify Persistence After Page Reload
1. After completing Test Case 1, note the optimized capacity values for a specific year
2. Refresh the page (F5 or browser refresh)
3. Upload the data files again
4. Select the same ISO and year
5. **Expected Result**: The optimized capacity values should be restored from localStorage

### Test Case 3: Switch ISO After Optimization
1. Optimize all years for ISO "PJM"
2. Note capacity values for year 2026
3. Switch ISO to "ISONE" using the ISO dropdown
4. **Expected Result**: Capacity values should update to ISONE database/saved values
5. Switch back to "PJM"
6. Select year 2026
7. **Expected Result**: PJM 2026 optimized capacity values should be restored

### Test Case 4: Visual Validation (No Flicker)
1. Optimize all years for an ISO
2. Quickly switch between different years using the dropdown
3. **Expected Result**: Capacity sliders should update smoothly without visible flickering between optimized and database values

## Success Criteria
- ✓ Optimized capacity values persist when switching years
- ✓ No visible flickering or brief display of incorrect values
- ✓ Values are properly restored from localStorage
- ✓ ISO switching does not break year-specific data persistence
- ✓ All event listeners properly await async operations

## Technical Validation
The fix ensures proper async/await flow:
```javascript
// BEFORE (broken):
document.getElementById('yearSelector').addEventListener('change', () => {
    applyAssumptions();  // Not awaited - causes race condition
    restoreSavedCapacities();  // Runs immediately
});

// AFTER (fixed):
document.getElementById('yearSelector').addEventListener('change', async () => {
    await applyAssumptions();  // Properly awaited - no race condition
    // restoreSavedCapacities() removed - applyAssumptions() handles it
});
```

## Notes
- The fix is minimal and surgical - only changes the async/await handling
- No changes to the core data restoration logic in `applyAssumptions()`
- The `restoreSavedCapacities()` function remains in the codebase but is no longer called from event listeners (it may be used elsewhere)
