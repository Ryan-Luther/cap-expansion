# Hour Indexing Convention

## Overview
This document describes how hour indexing is handled throughout the capacity expansion model to ensure consistency and prevent data misalignment.

## Internal Representation
- **All internal arrays use 0-based indexing**: Hours 0-8759
- Array index 0 represents the first hour of the year
- Array index 8759 represents the last hour of the year (8760th hour)

## CSV Export Format
- **All CSV exports use 1-based indexing**: Hours 1-8760
- This is the standard format for hourly data in energy modeling
- The "Hour" column in exported CSVs ranges from 1 to 8760
- The "Hour_of_Day" column uses 0-23 format (matching standard time representation)

## CSV Import Handling
The system automatically detects and handles both formats:

### 1-Based Format (Standard)
```csv
Technology,ISO,Hour,Capacity_Factor
Solar,CAISO,1,0.10
Solar,CAISO,2,0.15
...
Solar,CAISO,8760,0.05
```
- Hour values range from 1 to 8760
- Automatically converted to 0-based internally (1 → 0, 8760 → 8759)

### 0-Based Format (Alternative)
```csv
Technology,ISO,Hour,Capacity_Factor
Solar,CAISO,0,0.10
Solar,CAISO,1,0.15
...
Solar,CAISO,8759,0.05
```
- Hour values range from 0 to 8759
- Hour 0 is detected and format recognized as 0-based
- Used directly without conversion

## Auto-Detection Logic
The `normalizeHourIndex()` function handles conversion:
1. If hour = 0: Recognized as 0-based, used directly
2. If hour = 8760: Recognized as 1-based, converted to 8759
3. If hour = 1-8759: Assumed 1-based (for backward compatibility), converted to 0-8758
4. Out of range values: Clamped to 0-8759

## Format Detection
The `detectHourFormat()` function samples the data to determine format:
- Samples first, middle, and last rows
- If any Hour = 0: Format is 0-based
- If max Hour > 8759: Format is 1-based
- If min Hour = 1: Format is 1-based
- Default: 1-based (for backward compatibility)

## Best Practices
1. **For new CSV files**: Use 1-based format (1-8760) - this is the industry standard
2. **For exports**: The system always exports 1-based format automatically
3. **For imports**: The system handles both formats transparently
4. **For custom data**: Either format works - the system will detect and convert appropriately

## Code Locations
- Normalization function: `normalizeHourIndex()` (line ~1335)
- Detection function: `detectHourFormat()` (line ~1365)
- Capacity factor parsing: `rebuildHourlyData()` (line ~3459)
- CSV export: `exportResultsToCSV()` (line ~2317)

## Examples

### Example 1: Reading 1-based CSV
```javascript
// CSV has: Hour = 1
// normalizeHourIndex(1) returns 0
// hourlyData[0] gets the capacity factor for hour 1
```

### Example 2: Reading 0-based CSV
```javascript
// CSV has: Hour = 0
// normalizeHourIndex(0) returns 0
// hourlyData[0] gets the capacity factor for hour 0
```

### Example 3: Writing CSV
```javascript
// Internal: h = 0 (first hour)
// CSV writes: Hour = h + 1 = 1
// Hour_of_Day = h % 24 = 0
```

## Migration Notes
- Existing CSV files with 1-based format continue to work without changes
- New CSV files can use either format
- No breaking changes to existing functionality
