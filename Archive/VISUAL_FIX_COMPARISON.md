# Visual Comparison: Before and After Fix

## BEFORE (Broken - Race Condition)

```
User changes year dropdown
         |
         v
+------------------+
| Event Listener   |
| (not async)      |
+------------------+
         |
         |----[Call 1]----> applyAssumptions() [ASYNC - starts but doesn't wait]
         |                      |
         |                      v
         |                  rebuildHourlyData()
         |                      |
         |                      v
         |                  updateSystemFromProjectDB()
         |                      |
         |                      v
         |                  [Sets sliders to DB values] ⚠️
         |                      |
         |----[Call 2]----> restoreSavedCapacities()
                               |
                               v
                          [Restores optimized values] ✓
                          [VISIBLE: Brief flash of correct values]
                               |
    [Meanwhile, Call 1 continues...]
                               v
                          Check for savedData
                               |
                               v
                          Try to restore... [May be unreliable due to timing]
                               |
                               v
                          runModel()
                               |
                               v
                          RESULT: Database values shown ❌
                          (Optimized values lost!)
```

**Timeline:**
```
T=0ms:   yearSelector.change event fires
T=1ms:   applyAssumptions() starts (async, not awaited)
T=2ms:   restoreSavedCapacities() runs
T=3ms:   Optimized values appear on screen ✓
T=50ms:  applyAssumptions() calls updateSystemFromProjectDB()
T=51ms:  Database values overwrite optimized values ❌
T=52ms:  applyAssumptions() tries to restore saved data
T=53ms:  Race condition - may or may not work properly
T=100ms: User sees database values (wrong!) ❌
```

---

## AFTER (Fixed - Proper Async/Await)

```
User changes year dropdown
         |
         v
+------------------+
| Event Listener   |
| (ASYNC)          |
+------------------+
         |
         v
    await applyAssumptions() [WAITS for completion]
         |
         v
    rebuildHourlyData()
         |
         v
    updateSystemFromProjectDB()
         |
         v
    [Sets sliders to DB values]
         |
         v
    Check for savedData[ISO][Year]
         |
         v
    IF saved data exists:
         |
         v
    [Restores optimized values] ✓
         |
         v
    runModel() with correct values
         |
         v
    RESULT: Optimized values shown ✅
    (Database values properly overwritten by saved data!)
```

**Timeline:**
```
T=0ms:   yearSelector.change event fires
T=1ms:   Event listener starts
T=2ms:   await applyAssumptions() - BLOCKS until complete
T=50ms:  applyAssumptions() calls updateSystemFromProjectDB()
T=51ms:  Database values loaded
T=52ms:  applyAssumptions() checks for saved data
T=53ms:  Saved data found! Restores optimized values ✓
T=100ms: runModel() runs with optimized values
T=150ms: await completes, event listener continues
T=151ms: User sees optimized values (correct!) ✅
```

---

## Key Differences

| Aspect | Before | After |
|--------|--------|-------|
| **Event Listener** | Synchronous | **Async** |
| **applyAssumptions() Call** | Not awaited | **Awaited** |
| **restoreSavedCapacities() Call** | Redundant, runs too early | **Removed** |
| **Execution Order** | Race condition | **Sequential** |
| **User Experience** | Flash then reset | **Smooth transition** |
| **Data Integrity** | Unreliable | **Reliable** |

---

## Code Comparison

### Before (Broken)
```javascript
document.getElementById('yearSelector').addEventListener('change', () => {
    cachedYear = null;
    cachedCoreResults = null;
    applyAssumptions();        // ❌ Not awaited
    restoreSavedCapacities();  // ❌ Runs immediately
});
```

### After (Fixed)
```javascript
document.getElementById('yearSelector').addEventListener('change', async () => {
    cachedYear = null;
    cachedCoreResults = null;
    await applyAssumptions();  // ✅ Properly awaited
    // restoreSavedCapacities() removed - not needed
});
```

---

## What Users Experience

### Before Fix
1. User optimizes all years → Values saved to localStorage ✓
2. User changes year dropdown
3. **Brief flash** of optimized values appear
4. Values suddenly **reset** to database defaults ❌
5. User confused - "Where did my optimized values go?"

### After Fix
1. User optimizes all years → Values saved to localStorage ✓
2. User changes year dropdown
3. Optimized values appear and **stay** ✓
4. User happy - data persists correctly! ✅

---

## Technical Explanation

### The Race Condition Problem

When you call an async function without `await`, JavaScript doesn't wait for it to complete:

```javascript
// This is what was happening:
function eventHandler() {
    asyncFunction();  // Starts, but doesn't wait
    syncFunction();   // Runs immediately, before asyncFunction finishes
}
```

### The Proper Solution

Using `await` forces JavaScript to wait for the async function to complete:

```javascript
// This is the fix:
async function eventHandler() {
    await asyncFunction();  // Waits for completion
    // syncFunction() removed - not needed
}
```

---

## Lessons Learned

1. **Always await async functions** in event handlers
2. **Remove redundant code** - don't duplicate logic
3. **Race conditions are subtle** - they cause intermittent "flashing" bugs
4. **Test with timing in mind** - some bugs only appear with specific timing
5. **Document async flow** - make it clear what blocks and what doesn't

---

## Impact

- **Lines Changed**: 8 (minimal, surgical fix)
- **Risk Level**: Very Low (only affects timing, not logic)
- **User Experience**: Significantly Improved
- **Code Quality**: Improved (removed redundancy)
- **Maintainability**: Improved (single source of truth)
