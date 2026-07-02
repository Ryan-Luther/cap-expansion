# ETR Dynamic Capacity Expansion Forecast

This is a single-page HTML application for capacity expansion modeling and forecasting.

## Export Features

The application exports capacity expansion results to CSV files. When you click "Export Results", two CSV files are generated:

1. **Annual Results CSV** (`capacity_expansion_results_{ISO}_all_years.csv`) - Contains annual summary data for each year and ISO
2. **8760 Hourly Time Series CSV** (`capacity_expansion_8760_timeseries_{ISO}_all_years.csv`) - Contains hourly generation data

### Annual Results CSV Columns

The annual results CSV includes the following categories of data:

#### Load and Net Load Statistics (New)
- **Peak Load (MW)**: Maximum hourly load during the year
- **Average Load (MW)**: Average hourly load across all 8760 hours
- **Total Annual Load (MWh)**: Sum of all hourly loads for the year
- **Peak Net Load (MW)**: Maximum hourly net load (load minus renewable/firm generation, before imports and storage)
- **Average Net Load (MW)**: Average hourly net load across all 8760 hours
- **Total Annual Net Load (MWh)**: Sum of all hourly net loads for the year

#### Other Columns
- ISO and Year identifiers
- Installed capacities for all generation technologies (MW)
- Market assumptions (fuel costs, storage parameters, transmission, policy targets)
- Market results (unserved energy, reserve margin, renewable share, prices, costs)
- Per-technology financial data (new builds, capacity factors, ELCC, revenues, IRR)

### Storage Dispatch Price Columns

The 8760 hourly time series CSV includes storage dispatch validation columns:

- **Storage_Pcharge_Raw_per_MWh**: Raw fundamental charge price (before scarcity and stretch adjustments - used for dispatch decisions)
- **Storage_Pdischarge_Raw_per_MWh**: Raw fundamental discharge price (before scarcity and stretch adjustments - used for dispatch decisions)
- **Storage_Pcharge_Processed_per_MWh**: Post-processed charge price (after scarcity and stretch adjustments - for diagnostic/validation purposes)
- **Storage_Pdischarge_Processed_per_MWh**: Post-processed discharge price (after scarcity and stretch adjustments - for diagnostic/validation purposes)
- **Storage_SoC_Pct**: The state of charge (energy stored in the battery) as a percentage of maximum storage capacity (0-100%)
- **Storage_Inventory_Cost_per_MWh**: The weighted average cost of the energy currently sitting in the battery
- **Storage_Hold_Price_per_MWh**: The price if the battery did nothing (0 MW action) in this hour
- **Storage_Action_State**: Action taken by storage (1 = Charge, -1 = Discharge, 0 = Hold)
- **Day**: Day number (1-365) for each hour
- **Hour_of_Day**: Hour of the day (0-23) for each hour

These columns are used to validate that storage dispatch is working correctly:
- Raw prices show the fundamental price signals that are now used for storage dispatch decisions
- Processed prices reflect the prices after scarcity and stretch adjustments (for diagnostic purposes only)
- When storage discharges, raw discharge price should be high relative to other hours
- When storage charges, raw charge price should be low relative to other hours
- When storage doesn't act, discharge_price < final_price < charge_price
- Storage_SoC_Pct reveals if the battery is empty during price spikes (capacity constraint) - 0% means empty, 100% means full
- Storage_Inventory_Cost_per_MWh shows the weighted average cost of energy in storage
- Storage_Hold_Price_per_MWh vs. Storage_Discharge_Price_per_MWh reveals price impact


## Usage

1. Load the HTML file in a web browser
2. Upload required data files (capacity factors, load data, project database, market assumptions)
3. Select an ISO and year
4. Adjust capacity sliders and market assumptions as needed
5. Click "Export Results" to generate CSV files with annual and hourly data

## Testing Storage Dispatch

Use the `test_storage_dispatch.html` file to validate storage dispatch behavior:

1. Export results from the main application with storage capacity > 0
2. Open `test_storage_dispatch.html` in a browser
3. Upload the exported 8760 timeseries CSV file
4. Click "Run Validation Tests"

The test will verify:
- Storage price columns are populated
- Storage dispatch logic is correct (dispatches regardless of arbitrage spread)
- Hypothetical prices have the correct relationship to final prices
