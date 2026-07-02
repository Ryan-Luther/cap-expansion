# Test: Historical Power Prices Feature

## Overview
This test validates that historical power prices are correctly displayed in:
1. The 24-hour summary widget (diurnal mix chart)
2. The 8760 export CSV file

## Changes Made

### 1. Modified `updateDiurnalMixChart` Function
- **Location**: Line ~7850
- **Changes**:
  - Added `historicalPrices` parameter to function signature
  - Added `avgHistoricalPrices` array to accumulate historical prices by hour of day
  - Added conditional logic to sum historical prices: `if (historicalPrices) avgHistoricalPrices[h] += historicalPrices[i]`
  - Added averaging logic: `if (historicalPrices) avgHistoricalPrices[h] /= 365`
  - Added new chart dataset for historical prices with amber/yellow color (#fbbf24) and distinctive dash pattern [10, 5]

### 2. Modified UI Update Section
- **Location**: Line ~6609
- **Changes**:
  - Added code to extract historical prices from `rawHistoricalData` when available
  - Extracts prices for the selected ISO and zone from the historical CSV data
  - Creates `historicalPrices` Float64Array (8760 hours) populated from the LMP column
  - Passes `historicalPrices` as 4th parameter to `updateDiurnalMixChart`

### 3. Modified `exportResultsToCSV` Function
- **Location**: Line ~3140 and ~3195
- **Changes**:
  - Added code to extract `historicalPricesForExport` before the 8760 hour loop
  - Same logic as UI section: extracts from selected ISO/zone's LMP column
  - Added new column `Historical_Price_per_MWh` to the CSV export
  - Column is populated with historical price for each hour, or empty string if no data available
  - Positioned after `Raw_Energy_Price_per_MWh` column in the export

## Test Steps

### Prerequisites
1. Open `ETR_Dynamic_Cap_Expansion_Forecast_1.6.html` in a web browser
2. Have the following test files ready:
   - `test files/hist_prices.csv` (historical LMP prices by ISO/zone)
   - `test files/Load 4.csv` (load data)
   - `test files/Econ and Market Assumptions 1.csv` (economic assumptions)
   - `test files/capacity_factors.csv` (capacity factors)

### Test Procedure

#### Part 1: Verify 24-Hour Summary Widget
1. Load all required CSV files using the "Data Sources" section
2. Upload `hist_prices.csv` using the "Historical Prices (.csv)" file input
3. Select an ISO (e.g., "CAISO", "ERCOT", "PJM") from the ISO dropdown
4. Select a Zone that matches the historical data (e.g., "CAISO_NP15", "ERCOT_NORTH", "PJM_AEP")
5. Select a year and run the model
6. Scroll to the "24 Hour Average Generation Mix" chart
7. **Expected Results**:
   - Chart should display 3 price lines:
     - **White solid line**: "Price" (final simulated price)
     - **Gray dashed line**: "Raw Price" (raw energy price before post-processing)
     - **Amber/yellow dashed line**: "Historical Price" (from uploaded CSV) ← NEW
   - Historical Price line should show realistic values matching the uploaded data
   - Legend should show all three price series
   - Tooltip on hover should show historical price values

#### Part 2: Verify 8760 Export File
1. With the same data loaded (including historical prices), click "Export Results"
2. Wait for the CSV export to download
3. Open the exported CSV file
4. **Expected Results**:
   - CSV should contain a column named `Historical_Price_per_MWh`
   - Column should be positioned after `Raw_Energy_Price_per_MWh`
   - For hours where historical data exists:
     - Values should match the corresponding hour in `hist_prices.csv`
     - Values should be formatted to 2 decimal places (e.g., "45.23")
   - For years/ISOs without historical data:
     - Column should be empty strings
   - All 8760 rows should have the historical price column

#### Part 3: Data Validation
1. Compare a sample of exported historical prices with the source `hist_prices.csv`
2. Pick a specific hour (e.g., Hour 100, which is January 5 at 4 AM)
3. Find the corresponding row in `hist_prices.csv` (2024-01-05 04)
4. Verify the exported value matches the source data for the selected zone
5. Verify the 24-hour chart values make sense:
   - Calculate average of hours 0-23 for a specific hour of day from `hist_prices.csv`
   - Compare with the chart's displayed value for that hour

## Expected Behavior

### When Historical Data IS Available
- **24-Hour Chart**: Shows historical price line alongside simulated prices
- **8760 Export**: `Historical_Price_per_MWh` column populated with values
- **Color Scheme**: Historical price uses amber (#fbbf24) to distinguish from other price lines

### When Historical Data IS NOT Available
- **24-Hour Chart**: Only shows simulated price lines (no historical line)
- **8760 Export**: `Historical_Price_per_MWh` column exists but contains empty strings
- **No Errors**: Application functions normally, just without historical data

## Success Criteria
✅ Historical prices display correctly in the 24-hour chart when data is available
✅ Historical Price line uses distinctive amber color and dash pattern
✅ Chart legend includes "Historical Price" label
✅ Export CSV includes `Historical_Price_per_MWh` column in correct position
✅ Exported values match source historical data
✅ Empty values when no historical data available (no errors)
✅ No regression in existing functionality

## Code Quality Checks
✅ Function signature updated consistently
✅ Conditional checks prevent errors when historicalPrices is null/undefined
✅ Code follows existing patterns (similar to rawPrices handling)
✅ No breaking changes to existing parameters or return values
✅ Performance: Historical price extraction happens once per run, not per hour

## Known Limitations
- Historical prices are only shown for hours uploaded from the CSV file (typically 8760 hours for one year)
- The feature assumes the historical CSV contains matching ISO and zone columns
- If zone is not selected or doesn't match historical data, historical prices will not display
- The 24-hour chart shows daily averages, not individual hourly values

## Rollback Plan
If issues are discovered:
1. Revert commit: `git revert <commit-hash>`
2. Remove 4th parameter from `updateDiurnalMixChart` calls
3. Remove historical price extraction code from export function
4. Remove historical price column from CSV export
