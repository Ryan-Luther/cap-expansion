# Historical Price Year Filtering Fix - Implementation Summary

## Overview

This implementation fixes the historical price year filtering issues by improving date column detection and replacing calls to `extractHistoricalPricesForZone()` with year-filtered extraction.

## Problem Statement

The console was showing:
```
No date or year column found, assuming data is continuous from first to last row
Calibration years: undefined (* = leap year)
extractHistoricalPricesForZone called with: Object
Extracted 16728 prices for zone NYISO_A
Price statistics - Avg: $42.22/MWh  ← Wrong! Should be ~$32 for 2024 only
```

### Root Causes

1. **Date column not detected**: CSV had "Snapshots" column but detection failed due to whitespace/BOM/case issues
2. **Wrong function used**: `extractHistoricalPricesForZone()` extracted ALL data without year filtering
3. **Missing historical prices**: Chart showed no historical data because date column detection failed

## Solution Implemented

### Key Changes

1. **Shared utility function** `normalizeColumnName()` (lines ~1677-1684)
2. **Enhanced** `detectCompleteHistoricalYears()` (lines ~5201-5300)
3. **Enhanced** `extractHistoricalPricesByYear()` (lines ~1700-1750)
4. **Refactored** `extractHistoricalPricesForCompleteYears()` (lines ~5352-5380)
5. **Updated** `getAutoCalibrationBlockers()` (lines ~5083-5088)
6. **Enhanced** `handleHistoricalUpload()` (lines ~4031-4046)

### Technical Details

#### 1. Shared Utility: `normalizeColumnName()`

Extracts common normalization logic to avoid duplication:

```javascript
function normalizeColumnName(col) {
    if (!col) return '';
    // Remove BOM (Byte Order Mark) and trim whitespace
    return col.replace(/^\uFEFF/, '').trim().toLowerCase();
}
```

Used by both `extractHistoricalPricesByYear()` and `detectCompleteHistoricalYears()`.

#### 2. Two-Pass Column Detection

Prioritizes exact matches before fuzzy matching to avoid false positives:

**Pass 1 - Exact matches:**
```javascript
const possibleDateNames = ['snapshots', 'date', 'datetime', 'timestamp'];
for (const col of columns) {
    const normalized = normalizeColumnName(col);
    if (possibleDateNames.includes(normalized)) {
        dateCol = col;
        console.log(`Found date column: "${col}" (exact match)`);
        break;
    }
}
```

**Pass 2 - Fuzzy matching (fallback):**
```javascript
if (!dateCol) {
    for (const col of columns) {
        const normalized = normalizeColumnName(col);
        if (normalized.includes('date') || normalized.includes('time')) {
            dateCol = col;
            console.log(`Found date column: "${col}" (contains date/time)`);
            break;
        }
    }
}
```

#### 3. Year-by-Year Extraction

Replaced bulk extraction with year-filtered approach:

**Before:**
```javascript
const allPrices = extractHistoricalPricesForZone(zoneInfo);
// ... 60+ lines of complex leap day removal logic
```

**After:**
```javascript
const allPrices = [];
for (const yearData of yearInfo.completeYears) {
    const year = yearData.year;
    const yearPrices = extractHistoricalPricesByYear(year);
    if (yearPrices) {
        allPrices.push(...yearPrices);
    }
}
```

#### 4. Consistent Data Structures

Fixed fallback case to return same structure as normal case:

**Before:**
```javascript
return {
    completeYears: Array.from({length: numYears}, (_, i) => 2020 + i), // Plain numbers
    ...
};
```

**After:**
```javascript
const completeYearsArray = [];
for (let i = 0; i < numYears; i++) {
    const year = 2020 + i;
    completeYearsArray.push({
        year: year,
        actualHours: 8760,
        expectedHours: 8760,
        isLeap: false
    });
}
return {
    completeYears: completeYearsArray, // Same structure as normal case
    ...
};
```

#### 5. Enhanced Debugging

Added comprehensive logging in `handleHistoricalUpload()`:

```javascript
console.log('First row keys:', Object.keys(accumulatedData[0]));

// Detect problematic column names
Object.keys(accumulatedData[0]).forEach(col => {
    const hasWhitespace = col !== col.trim();
    const hasBOM = col.charCodeAt(0) === 0xFEFF;
    if (hasWhitespace || hasBOM) {
        console.warn(`⚠️ Column name has issues: "${col}" (BOM: ${hasBOM}, Whitespace: ${hasWhitespace})`);
    }
});
```

## Expected Console Output (After Fix)

```
=== Historical File Loaded ===
First row keys: ["Snapshots", "CAISO_NP15 LMP ($/MWh)", ...]
Available columns: ["Snapshots", "CAISO_NP15 LMP ($/MWh)", ...]
Found date column: "Snapshots" (exact match)
Detected 2 complete year(s): 2024, 2025 (partial excluded)
Calibrating against 1 complete year(s): 2024
extractHistoricalPricesByYear: Using date column "Snapshots" (exact match)
Total calibration hours: 8760 (1 × 8760)
Price statistics - Avg: $32.00/MWh ✅ (2024 only)
```

## Issues Fixed

| Issue | Root Cause | Solution | Status |
|-------|------------|----------|--------|
| Date column not detected | Column name had whitespace/BOM/case issues | Robust normalization + two-pass detection | ✅ |
| Wrong extraction function | `extractHistoricalPricesForZone()` extracted all data | Replaced with year-filtered `extractHistoricalPricesByYear()` | ✅ |
| No historical prices in chart | Date detection failed → function returned null | Improved detection ensures column is found | ✅ |
| Inconsistent data structure | Fallback returned plain numbers vs objects | Fixed to return consistent structure | ✅ |
| Code duplication | `normalizeColumnName()` duplicated 3 times | Extracted to shared utility function | ✅ |
| Overly broad matching | Single-pass fuzzy matching → false positives | Two-pass approach: exact then fuzzy | ✅ |

## Testing

### Test File Created

`test_date_column_detection.html` validates:
- ✅ Standard column name detection ("Snapshots")
- ✅ Case insensitivity ("snapshots", "SNAPSHOTS")
- ✅ Leading/trailing whitespace (" Snapshots", "Snapshots ")
- ✅ BOM character ("\uFEFFSnapshots")
- ✅ Alternative names (Date, DateTime, Timestamp)
- ✅ Combined issues (BOM + whitespace + case)
- ✅ No false positives when date column absent

### Manual Testing Checklist

- [ ] Upload historical file with "Snapshots" column
- [ ] Verify console shows "Found date column: 'Snapshots' (exact match)"
- [ ] Verify year detection works correctly
- [ ] Verify calibration uses only selected year's data
- [ ] Verify correct price statistics (e.g., $32/MWh for 2024)
- [ ] Test with files having whitespace in column names
- [ ] Test with files having BOM characters
- [ ] Test with files using alternative date column names

## Code Review Feedback Addressed

1. ✅ **Data structure consistency**: Fixed fallback case to return objects not plain numbers
2. ✅ **Code duplication**: Extracted `normalizeColumnName()` to shared function
3. ✅ **Overly broad matching**: Implemented two-pass detection (exact then fuzzy)
4. ✅ **Debug logging**: Added comprehensive logging throughout
5. ✅ **Consistent behavior**: Ensured all code paths work correctly

## Files Modified

- `ETR_Dynamic_Cap_Expansion_Forecast_1.6.html` - Core fixes
- `test_date_column_detection.html` - Test suite
- `IMPLEMENTATION_HISTORICAL_PRICE_FIX.md` - This documentation

## Notes

- `extractHistoricalPricesForZone()` still exists but only used by testing API
- All production code now uses year-filtered extraction
- Leap day removal handled automatically by `extractHistoricalPricesByYear()`
- Date column detection prioritizes exact matches to avoid false positives
