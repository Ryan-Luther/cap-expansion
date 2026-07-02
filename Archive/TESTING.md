# Testing Instructions for Auto-Calibration Fix

## Overview
This document provides instructions for testing the auto-calibration fixes for historical data access.

## What Was Fixed

### 1. Format Auto-Detection
- `handleHistoricalUpload()` now detects whether the file is in:
  - **Zone format** (new): Columns like "MISO_1 LMP ($/MWh)"
  - **Legacy format** (old): Columns like "Power ($)" and "Gas ($)"
- Automatically routes to the correct processor

### 2. Enhanced Logging
- Comprehensive console logging throughout the data pipeline
- Shows data loading, zone detection, and calibration triggers
- Helps debug any issues

### 3. Fixed Price Extraction
- `extractHistoricalPricesForZone()` now properly extracts prices from data rows
- Previously tried to return `.lmp` property which didn't exist
- Now extracts from the actual data array using the column name

### 4. Better Diagnostics
- New `getAutoCalibrationBlockers()` function lists all reasons auto-calibration can't run
- Updated `shouldAutoCalibrate()` with clearer logging

### 5. Testing API
- Exported functions via `window.testingAPI` for testing/debugging
- Can inspect data and state from browser console

## How to Test

### Step 1: Open the Application
1. Open `ETR_Dynamic_Cap_Expansion_Forecast_1.6.html` in a web browser
2. Open the browser's Developer Console (F12 or Cmd+Option+I)

### Step 2: Load Required Data Files
Load the following files from `Cap Expansion 1.0 test files/`:

1. **Capacity Factors** (`capacity_factors.csv`)
2. **Load Data** (`installed_capacity.csv` or load file)
3. **Market Assumptions** (`Econ and Market Assumptions.csv`)
4. **Daily Gas Prices** (`Daily Gas Prices.csv`) - if needed

### Step 3: Run the Model
1. Select an ISO (e.g., "MISO")
2. Select a year
3. Click "Run Optimizer" or the equivalent button
4. Wait for the model to complete

### Step 4: Upload Historical Prices
1. Click the "Historical Prices (.csv)" file input
2. Select `hist_prices.csv` from `Cap Expansion 1.0 test files/`
3. Watch the console for logs

### Expected Console Output

You should see something like this:

```
=== Historical File Loaded ===
Total rows: 16728
Column headers: Snapshots,CAISO_NP15 LMP ($/MWh),CAISO_SP15 LMP ($/MWh),...
Format detection - Legacy format: false Zone format: true
Processing as zone-based format (new format)

=== Processing Historical Zones Data ===
First row: {Snapshots: "2024-01-01 00", CAISO_NP15 LMP ($/MWh): 50.00157, ...}
Found 56 LMP columns
Found 56 Gas Price columns
Built zone map for ISOs: CAISO,ERCOT,ISONE,MISO,NYISO,PJM,SE,SPP,WEST

  CAISO: 2 zones - NP15, SP15
  ERCOT: 10 zones - COAST, EAST, FARWEST, NORTH, NORTHCENTRAL, SOUTH, SOUTHCENTRAL, WEST
  MISO: 6 zones - 1, 2, 3, 4, 6, 8
  ... etc

Available zones: {CAISO: [...], ERCOT: [...], ...}
Stored rawHistoricalData with 16728 rows and zone map
Current ISO selector value: MISO
Selected zone: {iso: "MISO", zone: "1"}

extractHistoricalPricesForZone called with: {iso: "MISO", zone: "1"}
Found zone data - LMP column: "MISO_1 LMP ($/MWh)", Gas column: "MISO_1 Gas Price ($/MMbtu)"
Extracted 16728 prices for zone MISO_1
Price statistics - Avg: $35.23/MWh, Min: $12.45/MWh, Max: $89.34/MWh

All conditions met for auto-calibration ✓
Triggering auto-calibration after historical file load

=== Starting Auto-Calibration ===
...
```

### Step 5: Verify Auto-Calibration
If all conditions are met, auto-calibration should trigger automatically:
- Console shows "All conditions met for auto-calibration ✓"
- Console shows "=== Starting Auto-Calibration ==="
- Price configuration modal updates to show calibration status

If auto-calibration doesn't trigger, check blockers:
```javascript
// In browser console:
window.testingAPI.getAutoCalibrationBlockers()
```

This will return an array of reasons, such as:
- `"No historical data loaded"`
- `"No zone selected"`
- `"No cached reserve margins (model not run)"`
- etc.

## Using the Testing API

The testing API is exposed on `window.testingAPI` and provides:

```javascript
// Get current state
window.testingAPI.getRawHistoricalData()      // Historical data structure
window.testingAPI.getSelectedZone()            // Currently selected zone
window.testingAPI.getAvailableZones()          // All available zones
window.testingAPI.getCalibratorState()         // Calibrator training state
window.testingAPI.getCachedData()              // What model data exists

// Check readiness
window.testingAPI.shouldAutoCalibrate()        // Returns true/false
window.testingAPI.getAutoCalibrationBlockers() // Returns array of blockers

// Extract prices for a zone
window.testingAPI.extractHistoricalPricesForZone({iso: "MISO", zone: "1"})

// Manually trigger calibration
window.testingAPI.autoCalibrate()
```

## Test Suite

A standalone test suite is available at `test_auto_calibration.html`:
1. Open `test_auto_calibration.html` in a browser
2. Click "Run Tests with Test Files"
3. View test results

**Note**: The test suite requires PapaParse library. If CDN is blocked, tests may fail, but the main application will still work (it has inline PapaParse or loads it differently).

## Expected Results

After these fixes:

✅ **Historical file loads correctly**
- Zone-based format is detected
- Zones are parsed from column headers
- Data is stored in proper structure

✅ **Price extraction works**
- Actual price data is extracted from rows
- Prices are validated (non-null, non-NaN)
- Statistics are calculated and logged

✅ **Auto-calibration triggers automatically**
- When all conditions are met
- Console shows detailed progress
- Calibrator is trained and optimized

✅ **Better debugging**
- Clear console logs throughout
- Blocker detection helps diagnose issues
- Testing API allows manual inspection

## Troubleshooting

### Issue: "Cannot auto-calibrate yet"
**Solution**: Check blockers with:
```javascript
window.testingAPI.getAutoCalibrationBlockers()
```
Address each blocker (load data, run model, etc.)

### Issue: "No historical data loaded"
**Solution**: 
- Ensure file is uploaded successfully
- Check that file has LMP columns with format: "ISO_ZONE LMP ($/MWh)"
- Check console for parsing errors

### Issue: "Insufficient historical data for zone"
**Solution**:
- File may not have data for the selected zone
- Check available zones with: `window.testingAPI.getAvailableZones()`
- Select a different zone or ISO

### Issue: "Model has not run yet"
**Solution**:
- Load all required data files first
- Click "Run Optimizer" to run the model
- Wait for model to complete
- Then upload historical prices

## File Format Requirements

Historical price file must have:

1. **Date/Time column**: One of:
   - "Snapshots"
   - "Date" 
   - "Timestamp"
   - "DateTime"

2. **LMP columns** for each zone:
   - Format: `ISO_ZONE LMP ($/MWh)`
   - Example: `MISO_1 LMP ($/MWh)`

3. **Gas Price columns** (optional):
   - Format: `ISO_ZONE Gas Price ($/MMbtu)`
   - Example: `MISO_1 Gas Price ($/MMbtu)`

4. **Data rows**: At least 100 rows (preferably 8760 for full year)

## Success Criteria

✅ Historical file loads without errors
✅ Zones are detected and displayed
✅ Console shows detailed logs
✅ Auto-calibration triggers automatically (if conditions met)
✅ Calibration completes successfully
✅ Price configuration shows calibrated status

## Questions or Issues?

If you encounter issues:
1. Check the browser console for error messages
2. Use `window.testingAPI.getAutoCalibrationBlockers()` to diagnose
3. Verify file format matches requirements above
4. Check that all prerequisite data is loaded
