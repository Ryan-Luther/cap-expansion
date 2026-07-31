"""
Pre-shrink 'Daily Gas Prices by ENV Zone.csv' (long, 332MB, 2024-2100) into a compact
wide multi-year CSV for the CEM HTML model.

Output columns:  year, DayOfYear, <zone1>, <zone2>, ...   (price = usd_per_mmbtu)
- Years filtered to [2024, 2060] inclusive.
- Feb 29 dropped so every year is exactly 365 days (matches the model's leap handling).
- DayOfYear is 1..365 using a fixed non-leap calendar (so day indices align across years).
- One row per (year, DayOfYear); missing (zone, day) cells left blank.
"""
import csv, os, sys

SRC = r"C:\Users\juan.arteaga\OneDrive - Enverus\LTF Working Group_SSG - Cap Expansion Model\FINAL L48\Combined L48\Daily Gas Prices by ENV Zone.csv"
OUT = r"C:\Users\juan.arteaga\OneDrive - Enverus\Documents\cap-expansion\CEM_Daily_Gas_Prices_MultiYear.csv"
YEAR_MIN, YEAR_MAX = 2024, 2060

# Cumulative days before each month in a NON-leap year (index by month-1).
CUM = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]

def day_of_year(month, day):
    # Returns 1..365 on the fixed non-leap calendar; None for Feb 29 (dropped).
    if month == 2 and day == 29:
        return None
    return CUM[month - 1] + day

# data[year][zone] = list of 365 price strings ('' = missing)
data = {}
zones = set()

with open(SRC, newline="", encoding="utf-8") as f:
    r = csv.reader(f)
    header = next(r)
    ix = {name: i for i, name in enumerate(header)}
    i_dt, i_price, i_zone = ix["start_datetime"], ix["usd_per_mmbtu"], ix["ENVZone"]
    n = 0
    kept = 0
    for row in r:
        n += 1
        if n % 500000 == 0:
            print(f"  ...{n:,} rows scanned, {kept:,} kept", file=sys.stderr)
        dt = row[i_dt]
        year = int(dt[0:4])
        if year < YEAR_MIN or year > YEAR_MAX:
            continue
        month = int(dt[5:7]); day = int(dt[8:10])
        doy = day_of_year(month, day)
        if doy is None:
            continue  # drop Feb 29
        zone = row[i_zone]
        price = row[i_price]
        zones.add(zone)
        yz = data.setdefault(year, {})
        arr = yz.get(zone)
        if arr is None:
            arr = [""] * 365
            yz[zone] = arr
        arr[doy - 1] = price
        kept += 1

print(f"scanned {n:,} rows; kept {kept:,}; years {min(data)}..{max(data)}; zones {len(zones)}", file=sys.stderr)

zone_list = sorted(zones)
years = sorted(data.keys())

with open(OUT, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["year", "DayOfYear"] + zone_list)
    for year in years:
        yz = data.get(year, {})
        for d in range(365):
            row = [year, d + 1]
            for z in zone_list:
                arr = yz.get(z)
                row.append(arr[d] if arr is not None else "")
            w.writerow(row)

out_rows = len(years) * 365
print(f"WROTE {OUT}")
print(f"rows: {out_rows:,} ({len(years)} years x 365 days), columns: {2 + len(zone_list)}")
print(f"size: {os.path.getsize(OUT)/1024/1024:.2f} MB")
