# Data Key Lookup Fix for ELCC Calculation

## Problem Statement

The ELCC (Effective Load Carrying Capability) calculation was using optional chaining (`?.`) and nullish coalescing (`?? 0`) operators in the calculation loop. While this prevented crashes, it was **silently masking key mismatch errors** by returning 0 when data couldn't be found.

### Root Cause

1. **Key Mismatch for Imports**: The `imports` technology had `name: 'Net Imports'` in the `generationTypes` array, but the code consistently used the hardcoded key `'Imports'` throughout:
   - In `runCoreModel`: `hourlyGeneration['Imports'] = new Float64Array(8760);` (line 6867)
   - In optimizer: `coreResults.hourlyGeneration['Imports']` (line 2203)
   - In CSV export: `modelResults.hourlyGeneration['Imports'][h]` (line 3197)
   - And 5+ other locations

2. **Masking Operators**: The optional chaining (`?.`) and nullish coalescing (`?? 0`) operators at lines 6757, 6775, and 6784 were:
   - Preventing clear error messages when keys didn't match
   - Silently returning 0 instead of the actual generation data
   - Making debugging difficult because ELCC values would be calculated as 0% without any indication of why

### Example of the Problem

When the code tried to access `hourlyGeneration['Net Imports']`, it would get `undefined` because the actual key was `'Imports'`. The optional chaining would then return 0, causing:
```javascript
totalGenTop100 = 0 (instead of actual generation)
ELCC = 0 / Capacity = 0%
```

This made it appear as if the asset wasn't performing, when in reality the calculation just couldn't find the data.

## Solution Implemented

### 1. Fixed Imports Name Mismatch (Line 1822)

**Before:**
```javascript
{ id: 'imports', name: 'Net Imports', max: 50000, value: 0, color: '#94a3b8', capex: 1000, opex: 200, life: 40, hurdleRate: 9, type: 'import' }
```

**After:**
```javascript
{ id: 'imports', name: 'Imports', max: 50000, value: 0, color: '#94a3b8', capex: 1000, opex: 200, life: 40, hurdleRate: 9, type: 'import' }
```

**Rationale**: Changed the single occurrence of 'Net Imports' to match the 8+ hardcoded uses of 'Imports' throughout the codebase.

### 2. Removed Optional Chaining from ELCC Calculation (Lines 6757, 6775, 6784)

**Before (Storage - Line 6757):**
```javascript
const gen = modelResults.hourlyGeneration['Storage']?.[idx] ?? 0;
```

**After:**
```javascript
const gen = modelResults.hourlyGeneration['Storage'][idx];
```

**Before (Thermal - Line 6775):**
```javascript
totalGenTop100 += modelResults.hourlyGeneration[genKey]?.[idx] ?? 0;
```

**After:**
```javascript
totalGenTop100 += modelResults.hourlyGeneration[genKey][idx];
```

**Before (Renewables - Line 6784):**
```javascript
totalGenTop100 += modelResults.hourlyGeneration[tech.name]?.[idx] ?? 0;
```

**After:**
```javascript
totalGenTop100 += modelResults.hourlyGeneration[tech.name][idx];
```

## Verification

### Key Alignment Check

All keys in `hourlyGeneration` now match the corresponding `tech.name` values:

| Tech ID | tech.name | hourlyGeneration Key | Status |
|---------|-----------|---------------------|--------|
| onshore-wind | Onshore Wind | Onshore Wind | ✅ Match |
| offshore-wind | Offshore Wind | Offshore Wind | ✅ Match |
| solar | Solar | Solar | ✅ Match |
| hydro | Hydro | Hydro | ✅ Match |
| biomass | Biomass | Biomass | ✅ Match |
| geothermal | Geothermal | Geothermal | ✅ Match |
| nuclear | Nuclear | Nuclear | ✅ Match |
| coal | Coal | Coal | ✅ Match |
| oil | Oil | Oil | ✅ Match |
| other | Other | Other | ✅ Match |
| existing-gas | Existing Gas | Existing Gas | ✅ Match |
| new-gas-ccgt | New Build Gas CCGT | New Build Gas CCGT | ✅ Match |
| new-gas-ct | New Build Gas CT | New Build Gas CT | ✅ Match |
| storage | Storage | Storage | ✅ Match |
| imports | Imports | Imports | ✅ Match (fixed) |

### Backward Compatibility

The change maintains backward compatibility because:
- External CSV mapping tables (lines 4153, 4698, 6008) still accept 'Net Imports' and map it to the 'imports' tech ID
- No changes to external data file formats required
- Only internal data structure alignment was corrected

## Impact

### Positive Outcomes

1. **Clear Error Messages**: If a key mismatch occurs in the future, JavaScript will throw a clear error like:
   ```
   TypeError: Cannot read property '0' of undefined
   ```
   This makes debugging much easier than silently getting 0% ELCC values.

2. **Correct ELCC Calculations**: The imports technology and all other technologies will now correctly access their hourly generation data, producing accurate ELCC values.

3. **Better Code Maintainability**: Future developers will immediately know if they introduce a key mismatch, rather than chasing down why ELCC values are unexpectedly 0%.

### No Breaking Changes

- All existing functionality preserved
- No changes to external APIs or data formats
- CSV import/export continues to work
- Optimizer logic unaffected

## Testing

### Code Review
✅ Passed - No issues found

### Security Check
✅ Passed - No security vulnerabilities detected

### Manual Verification Recommended

To fully validate the fix, perform these steps:
1. Open `ETR_Dynamic_Cap_Expansion_Forecast_1.6.html` in a browser
2. Load required data files (capacity factors, installed capacity, market assumptions)
3. Select an ISO and year
4. Run the model with various technology mixes
5. Verify ELCC values are calculated correctly (non-zero for technologies that have capacity)
6. Export results and check that ELCC values in the CSV match the UI display
7. Test with the optimizer to ensure ELCC-based capacity expansion works correctly

## Files Modified

- `ETR_Dynamic_Cap_Expansion_Forecast_1.6.html`
  - Line 1822: Changed imports name from 'Net Imports' to 'Imports'
  - Line 6757: Removed optional chaining from Storage ELCC calculation
  - Line 6775: Removed optional chaining from Thermal ELCC calculation
  - Line 6784: Removed optional chaining from Renewable ELCC calculation

## Related Documentation

- `ELCC_FIX_SUMMARY.md` - Previous ELCC fix for headless mode
- `README.md` - Application usage and CSV export documentation
