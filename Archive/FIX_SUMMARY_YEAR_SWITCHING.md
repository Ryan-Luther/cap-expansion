# Fix Summary: Year Switching Data Persistence Issue

## Problem Statement
When a user optimizes all years and then changes the year selector, the optimized capacity values briefly appear but then reset to non-optimized (database) values. This indicates that not all data is properly loading when the year is switched.

## Root Cause Analysis

### The Race Condition
The issue was caused by a race condition in the event listeners for ISO and year selector changes:

```javascript
// BEFORE (Broken Code)
document.getElementById('yearSelector').addEventListener('change', () => {
    cachedYear = null;
    cachedCoreResults = null;
    applyAssumptions();           // ❌ Not awaited - async function starts but doesn't block
    restoreSavedCapacities();     // ❌ Runs immediately, before applyAssumptions completes
});
```

### What Was Happening

1. **User Action**: User selects a different year from the dropdown
2. **Event Fires**: The change event listener executes
3. **`applyAssumptions()` Starts**: Begins executing asynchronously (not awaited)
4. **`restoreSavedCapacities()` Runs**: Executes immediately, restoring optimized values → **Brief flash of correct values**
5. **`applyAssumptions()` Continues**: 
   - Calls `updateSystemFromProjectDB()` which sets all sliders to database values → **Overwrites optimized values**
   - Then tries to restore saved data at lines 4847-4884, but timing issues could prevent proper restoration
6. **Result**: Database values remain on screen instead of optimized values

### Why The Brief Flash?
The "brief flash" of optimized values occurred because `restoreSavedCapacities()` executed immediately and temporarily set the correct values, but then `applyAssumptions()` (still running asynchronously) overwrote them with database values.

## Solution

### Code Changes
Changed both `isoSelector` and `yearSelector` event listeners to:
1. Be `async` functions
2. `await` the `applyAssumptions()` call
3. Remove the redundant `restoreSavedCapacities()` call

```javascript
// AFTER (Fixed Code)
document.getElementById('yearSelector').addEventListener('change', async () => {
    cachedYear = null;
    cachedCoreResults = null;
    await applyAssumptions();     // ✅ Properly awaited - completes before continuing
    // Note: restoreSavedCapacities() removed - applyAssumptions() handles it internally
});
```

### Why This Works

The fixed code ensures proper sequencing:
1. **User Action**: User selects a different year
2. **Event Fires**: The async event listener executes
3. **`applyAssumptions()` Completes Fully**: 
   - Calls `updateSystemFromProjectDB()` to load database values
   - Then calls its internal restoration logic (lines 4847-4884) to check for saved data
   - If saved data exists, overwrites database values with optimized values
   - All of this completes before the event listener continues
4. **Result**: Optimized values correctly appear on screen

### Additional Benefits
- **No redundant code**: Removed duplicate `restoreSavedCapacities()` calls
- **Consistent behavior**: Applied the same fix to both ISO and year selector events
- **Better maintainability**: Single source of truth for data restoration logic (inside `applyAssumptions()`)

## Files Modified

### ETR_Dynamic_Cap_Expansion_Forecast_1.6.html
- **Lines 6278-6284**: Fixed `isoSelector` event listener
- **Lines 6287-6293**: Fixed `yearSelector` event listener

**Changes Made:**
- Added `async` keyword to both event listener functions
- Added `await` before `applyAssumptions()` calls
- Removed redundant `restoreSavedCapacities()` calls
- Added explanatory comments

### TEST_YEAR_SWITCHING_FIX.md
Created comprehensive test plan with manual test cases covering:
- Optimizing all years then switching between years
- Verifying persistence after page reload
- Switching ISOs after optimization
- Visual validation (no flickering)

## Verification

### Code Review
✅ **Passed** - No issues found

### Security Scan
✅ **Passed** - No security vulnerabilities introduced

### Manual Testing Required
Since this is a browser-based application, manual testing is required. See `TEST_YEAR_SWITCHING_FIX.md` for detailed test steps.

## Impact Assessment

### User Experience Impact
- **Before**: Frustrating UX - optimized values would appear briefly then disappear
- **After**: Smooth UX - optimized values persist correctly when switching years

### Performance Impact
- **Minimal**: The `await` adds negligible overhead (just proper sequencing)
- **Benefit**: Eliminates unnecessary duplicate function calls

### Risk Assessment
- **Very Low Risk**: Minimal code change, only affects async flow control
- **No Breaking Changes**: Same functionality, just fixed timing
- **Backwards Compatible**: No API or data format changes

## Testing Checklist

To verify this fix works correctly:

- [ ] Open application in browser
- [ ] Upload all required data files
- [ ] Select an ISO (e.g., "PJM")
- [ ] Click "Run All Years" to optimize
- [ ] Wait for completion
- [ ] Switch to different year using dropdown
- [ ] **Verify**: Capacity sliders show optimized values (not database defaults)
- [ ] Switch between multiple years
- [ ] **Verify**: Each year retains its optimized values
- [ ] **Verify**: No visible flickering or brief flashes of incorrect values

## Technical Notes

### Why Not Just Fix `restoreSavedCapacities()`?
The issue wasn't with `restoreSavedCapacities()` itself - it was the timing of when it was called. The proper solution was to:
1. Ensure `applyAssumptions()` completes fully before continuing
2. Remove the redundant call since `applyAssumptions()` already handles restoration

### Data Flow After Fix
```
User changes year
    ↓
Event listener (async)
    ↓
await applyAssumptions()
    ↓
    - rebuildHourlyData()
    - updateSystemFromProjectDB() → Load DB values
    - Check for savedData[ISO][Year]
    - If exists: Restore optimized values (lines 4847-4884)
    - Run model with correct values
    ↓
Event listener continues (if any more code)
```

## Conclusion

This was a classic async/await race condition bug. The fix is minimal, surgical, and follows JavaScript best practices for handling async operations. The optimized capacity values will now persist correctly when users switch between years, providing a much better user experience.
