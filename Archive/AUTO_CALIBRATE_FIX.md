# Auto-Calibrate Fix - ISO Switching Race Condition

## Problem Statement
Auto-calibration was failing when switching ISOs after web workers were added. When manually running auto-calibration, it would find a different solution than what it automatically set when changing ISOs.

## Root Cause
The issue was caused by race conditions due to async `runModel()` calls not being properly awaited:

1. **In `applyAssumptions()` (line 4388)**:
   - When ISO changed, it would temporarily switch to a calibration year (2024)
   - Call `runModel()` WITHOUT await (line 4436)
   - Switch back to user's selected year
   - Call `runModel()` again WITHOUT await (line 4448)
   - Then trigger `autoCalibrate()` (line 4751)
   - Result: `autoCalibrate()` would run before the model runs completed, using stale cached values

2. **Duplicate `runModel()` calls**:
   - `rebuildHourlyData()` was calling `runModel()` both via `checkEnableButtons()` AND directly
   - This caused parallel model runs that could interfere with each other

3. **Web worker year processing**:
   - `processYearOnMainThread()` was calling `applyAssumptions()` without await
   - This meant the year's assumptions might not be fully applied before running the model

## Solution
Made all async function calls properly awaited to ensure sequential execution:

### 1. Made `applyAssumptions()` async (line 4388)
```javascript
async function applyAssumptions() {
```

### 2. Made `enableControlsAndRun()` async and await runModel (line 5876)
```javascript
async function enableControlsAndRun() {
    // ... UI updates ...
    await runModel();
}
```

### 3. Added await to runModel calls in year-switching logic (lines 4435, 4447)
```javascript
if (needsTraining) {
    try {
        if (hourlyData.length > 0) await runModel(); // Line 4435
    } catch (error) {
        console.error('Error during calibration training:', error);
    }
    
    // Switch back to original year
    const yearSelector = document.getElementById('yearSelector');
    yearSelector.value = originalYear;
    rebuildHourlyData();
    if (hourlyData.length > 0) await runModel(); // Line 4447
}
```

### 4. Added await to enableControlsAndRun in applyAssumptions (line 4738)
```javascript
if(hourlyData.length > 0 && dispatchAssets.length > 0) {
    await enableControlsAndRun();
}
```

### 5. Added await to applyAssumptions in processYearOnMainThread (line 2587)
```javascript
// Apply assumptions for this year
await applyAssumptions();
```

### 6. Added await to applyAssumptions in exportResultsToCSV (line 3015)
```javascript
// Apply assumptions for this year first
await applyAssumptions();
```

### 7. Removed duplicate runModel call from rebuildHourlyData (line 4385)
```javascript
// REMOVED: if(dispatchAssets.length > 0) runModel();
// Already called via checkEnableButtons() → enableControlsAndRun() → runModel()
```

## Execution Flow After Fix

### ISO Switching Flow:
1. User changes ISO
2. `applyAssumptions()` is called (async)
3. If training needed:
   - Switch to calibration year (2024)
   - `await runModel()` - WAIT for completion ✓
   - Cached values now set for calibration year
   - Switch back to user's year
   - `await runModel()` - WAIT for completion ✓
   - Cached values now set for user's year
4. `await enableControlsAndRun()` - WAIT if needed ✓
5. Check if should auto-calibrate
6. Call `autoCalibrate()` with correct cached values ✓

### Web Worker Year Processing:
1. Worker sends 'process_year' message
2. Main thread calls `processYearOnMainThread()`
3. Set year in selector
4. `await applyAssumptions()` - WAIT for completion ✓
5. Apply saved data and previous year capacities
6. `await runModel()` or `await runOptimizer()` - WAIT for completion ✓
7. Save year data
8. Notify worker year is complete

## Testing Recommendations

1. **Test ISO Switching**:
   - Load historical data for multiple ISOs
   - Switch between ISOs
   - Verify auto-calibration runs and produces consistent results
   - Compare auto-calibration results with manual calibration

2. **Test Multi-Year Optimization**:
   - Run "Optimize All Years" with web worker
   - Verify each year completes before next starts
   - Check that year data is correctly applied

3. **Test Manual Calibration**:
   - Manually run calibration after loading data
   - Verify results match auto-calibration

4. **Console Logging**:
   - Check for "=== Starting Auto-Calibration ===" messages
   - Verify "All conditions met for auto-calibration ✓" appears
   - No race condition errors in console

## Benefits

1. **Consistent Auto-Calibration**: Auto-calibration now produces same results as manual calibration
2. **No Race Conditions**: All async operations properly sequenced
3. **Correct Cached Values**: Auto-calibration uses values from correct year/ISO
4. **Better Performance**: No duplicate model runs wasting computation
5. **Reliable Web Worker**: Year processing properly waits for each step

## Files Changed
- `ETR_Dynamic_Cap_Expansion_Forecast_1.6.html`

## Commits
1. Fix async race condition in auto-calibrate when switching ISOs
2. Add await to applyAssumptions calls in async contexts
3. Remove duplicate runModel call from rebuildHourlyData
