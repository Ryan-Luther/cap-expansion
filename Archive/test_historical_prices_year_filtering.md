# Test: Historical Power Prices Year Filtering Fix

## Overview
This test validates that historical power prices are correctly filtered by year in:
1. The 24-hour summary widget (diurnal mix chart) - displays only selected year's data
2. The 8760 export CSV file - includes year-specific data for each exported year

## Problem Fixed
**Before**: Historical prices always showed the first 8760 hours from the file, regardless of year selected
**After**: Historical prices are filtered to match the selected/exported year

## Changes Made

### 1. Added Helper Function `extractHistoricalPricesByYear(targetYear)`
- **Location**: Lines 1677-1759
- **Purpose**: Extract historical prices for a specific year from multi-year historical data
- **Features**:
  - Finds date column (Snapshots, Date, Timestamp, DateTime, etc.)
  - Parses year from date string (format: "YYYY-MM-DD HH")
  - Validates year (2000-2100 range)
  - Filters data to match target year
  - Handles leap years (8784 hours, removes Feb 29)
  - Returns null if incomplete data for that year

### 2. Modified UI Update Section
- **Location**: Line 6664
- **Changes**:
  - Replaced inline extraction code with `extractHistoricalPricesByYear(parseInt(currentYear))`
  - Now filters by currently selected year from year dropdown
  - Chart shows only historical data for that specific year

### 3. Modified `exportResultsToCSV` Function
- **Location**: Line 3210
- **Changes**:
  - Moved historical price extraction inside the year loop
  - Now calls `extractHistoricalPricesByYear(parseInt(year))` for each year
  - Each exported year gets its own historical data (or null if unavailable)

## Test Scenarios

### Scenario 1: Single Year Historical Data
**Setup**:
- Historical file contains only 2024 data (8760 hours)
- Year column format: "2024-01-01 00", "2024-01-01 01", etc.

**Test Steps**:
1. Load historical file with 2024 data
2. Select year 2024 in UI
3. Run model
4. Check 24-hour chart - should show historical prices
5. Export results for 2024
6. Verify Historical_Price_per_MWh column is populated

**Expected Results**:
- ✅ Chart displays 2024 historical prices
- ✅ Export contains 2024 historical prices
- ✅ No errors or warnings

### Scenario 2: Multi-Year Historical Data - Correct Year Filtering
**Setup**:
- Historical file contains 2024 + 2025 data (17,520 hours total)
- 2024 average: $32/MWh
- 2025 average: $48/MWh
- Combined average: $40/MWh

**Test Steps**:
1. Load historical file with both years
2. Select year 2024
3. Run model and check chart
4. Select year 2025
5. Run model and check chart
6. Export results for years 2024-2025

**Expected Results**:
- ✅ Chart for 2024 shows ~$32 average (NOT $40 combined average)
- ✅ Chart for 2025 shows ~$48 average (NOT $40 combined average)
- ✅ Export 2024 row: Historical_Price_per_MWh populated with 2024 prices
- ✅ Export 2025 row: Historical_Price_per_MWh populated with 2025 prices

### Scenario 3: Export Multiple Years, Partial Historical Data
**Setup**:
- Historical file contains only 2024 + 2025 data
- Exporting years 2024-2030 (7 years)

**Test Steps**:
1. Load historical file (2024-2025 only)
2. Export results for years 2024-2030

**Expected Results**:
- ✅ Export 2024 row: Historical_Price_per_MWh populated with 2024 data
- ✅ Export 2025 row: Historical_Price_per_MWh populated with 2025 data
- ✅ Export 2026-2030 rows: Historical_Price_per_MWh column is empty (no data for these years)
- ✅ No errors during export

### Scenario 4: Leap Year Handling
**Setup**:
- Historical file contains 2024 data (leap year, 8784 hours)
- Includes Feb 29 data (hours 1416-1439)

**Test Steps**:
1. Load historical file with leap year 2024 (8784 hours)
2. Select year 2024
3. Run model

**Expected Results**:
- ✅ Function detects leap year (8784 hours expected)
- ✅ Feb 29 data is removed (hours 1416-1439)
- ✅ Exactly 8760 hours returned
- ✅ Chart displays correctly
- ✅ Export contains 8760 rows with correct data

### Scenario 5: Invalid/Incomplete Year Data
**Setup**:
- Historical file contains 2024 data but only 4000 hours (incomplete)

**Test Steps**:
1. Load incomplete historical file
2. Select year 2024
3. Run model

**Expected Results**:
- ✅ Console warning: "Incomplete historical data for year 2024: found 4000 hours, expected 8760"
- ✅ Function returns null
- ✅ Chart does not show historical price line
- ✅ Export Historical_Price_per_MWh column is empty
- ✅ No errors, application continues normally

### Scenario 6: No Historical Data
**Setup**:
- No historical file loaded
- OR historical file doesn't contain the selected year

**Test Steps**:
1. Don't load any historical file (or load file with different years)
2. Select any year
3. Run model
4. Export results

**Expected Results**:
- ✅ Function returns null
- ✅ Chart shows only simulated prices (no historical line)
- ✅ Export includes Historical_Price_per_MWh column but it's empty
- ✅ No errors

## Manual Testing Instructions

### Quick Validation Test
1. Open `ETR_Dynamic_Cap_Expansion_Forecast_1.6.html` in browser
2. Load test files:
   - Load data
   - Capacity factors
   - Economic assumptions
   - Historical prices file with 2+ years of data
3. Select ISO and Zone matching historical data
4. **Test UI filtering**:
   - Select year 2024 → Run model → Note the historical price average on chart
   - Select year 2025 → Run model → Note the historical price average on chart
   - Verify the averages are different (confirming year-specific filtering)
5. **Test Export filtering**:
   - Export results for years 2024-2030
   - Open CSV file
   - Verify Historical_Price_per_MWh column:
     - Years 2024-2025: Should have values
     - Years 2026-2030: Should be empty (if no historical data for those years)

### Detailed Validation Test
For comprehensive testing, create a test historical file with distinct prices:
```csv
Snapshots,CAISO_NP15 LMP ($/MWh)
2024-01-01 00,30.00
2024-01-01 01,30.00
... (8760 hours, all $30)
2025-01-01 00,50.00
2025-01-01 01,50.00
... (8760 hours, all $50)
```

Then verify:
- Year 2024 chart shows ~$30 average
- Year 2025 chart shows ~$50 average
- Export for 2024 has all hours at $30
- Export for 2025 has all hours at $50

## Success Criteria
✅ Historical prices filter by selected year in UI
✅ Historical prices filter by exported year in CSV
✅ Leap years handled correctly (Feb 29 removed)
✅ Incomplete data handled gracefully (returns null, no errors)
✅ Years without historical data show empty columns (not repeated data)
✅ No regression in existing functionality
✅ Console warnings for incomplete data
✅ Performance: No significant slowdown

## Code Quality Checks
✅ Reusable helper function (DRY principle)
✅ Consistent with existing code patterns (`isLeapYear`, `removeLeapDay`)
✅ Year validation follows existing pattern (`detectCompleteHistoricalYears`)
✅ Proper error handling and null checks
✅ Clear console warnings for debugging
✅ No breaking changes to existing APIs

## Regression Prevention
Verify these still work:
- ✅ Export without historical data loaded
- ✅ Switching ISOs/zones
- ✅ Running model multiple times with different years
- ✅ All existing chart functionality
- ✅ Other CSV export columns

## Known Limitations
- Historical data must have a date column (Snapshots, Date, Timestamp, etc.)
- Date format must start with YYYY (e.g., "2024-01-01 00")
- Function iterates through all data on each call (could be optimized with caching for large datasets)
- Requires complete year data (8760 or 8784 hours)

## Future Improvements (Not in Scope)
- Add caching to avoid re-filtering the same year multiple times
- Pre-index historical data by year when file is first loaded
- Support partial year data (e.g., first 6 months of a year)
