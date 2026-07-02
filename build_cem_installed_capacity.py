"""
build_cem_installed_capacity.py
================================
Builds CEM_installed_capacity_<date>.csv from two sources:
  1. PCM file  -> Operating + Under Construction rows
  2. PRISM     -> Interconnection Agreement rows (eaCombinedProjects, ERCOT)

Usage:
    python build_cem_installed_capacity.py

Before running, paste your PRISM rseg_jwt token when prompted,
or pre-save it at %TEMP%/prism_token.txt to skip the prompt.
"""

import os
import sys
import tempfile
from datetime import datetime

import pandas as pd
import requests

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
PCM_CSV = r"C:\Users\juan.arteaga\Downloads\pcm_to_cem_v7.csv"
OUT_DIR = r"C:\Users\juan.arteaga\OneDrive - Drilling Info\LTF Working Group_SSG - Cap Expansion Model\FINAL L48\ERCOT test"
OUT_FILENAME = f"CEM_installed_capacity_{datetime.now().strftime('%b%d')}.csv"
TOKEN_FILE = os.path.join(tempfile.gettempdir(), "prism_token.txt")

DAS_URL    = "https://data-access-service.prism.enverus.com/sql"
CURSOR_URL = "https://data-access-service.prism.enverus.com/cursor"

# ─────────────────────────────────────────────
# TECHNOLOGY NAME MAPPINGS
# ─────────────────────────────────────────────

# PCM pcm_generator_type  ->  CEM ProjectType
PCM_TYPE_MAP = {
    "CC_GAS":         "Natural Gas",
    "CT_GAS":         "Natural Gas",
    "IC_GAS":         "Natural Gas",
    "ST_GAS":         "Natural Gas",
    "COAL":           "Coal",
    "NUCLEAR":        "Nuclear",
    "OIL":            "Oil",
    "OTHER":          "Other",
    "ST_OTHER":       "Other",
    "zonal_agg_BESS":    "Storage",
    "zonal_agg_BIOMASS": "Biomass",
    "zonal_agg_COAL":    "Coal",
    "zonal_agg_GAS":     "Natural Gas",
    "zonal_agg_Hydro":   "Hydro",
    "zonal_agg_OIL":     "Oil",
    "zonal_agg_OTHER":   "Other",
    "zonal_agg_Solar":   "Solar",
    "zonal_agg_Wind":    "Onshore Wind",
}

# PRISM ProjectType  ->  CEM ProjectType
PRISM_TYPE_MAP = {
    "Solar PV":                    "Solar",
    "Onshore Wind":                "Onshore Wind",
    "Offshore Wind":               "Onshore Wind",
    "CSP":                         "Solar",
    "Battery - Other/Unspecified": "Storage",
    "Other Energy Storage":        "Storage",
    "Pumped Hydro":                "Hydro",
    "Natural Gas":                 "Natural Gas",
    "Hydro":                       "Hydro",
    "Coal":                        "Coal",
    "Nuclear":                     "Nuclear",
    "Oil":                         "Oil",
    "Biomass":                     "Biomass",
    "Landfill Gas":                "Other",
}

CEM_COLUMNS = [
    "ENVProjectID", "ProjectName", "ProjectType", "ENVProjectStatus",
    "ProjectCapacityMW", "CurrentOperatingCapacity",
    "FirstPowerDate", "RetirementDate",
    "ISOTerritory", "ENVZone",
    "HeatRateMmbtuMwh", "ProjectCompletionProbability",
]


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def get_token() -> str:
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE) as f:
            tok = f.read().strip()
        if tok:
            print(f"  Using saved token from {TOKEN_FILE}")
            return tok
    print()
    print("=" * 70)
    print("PRISM TOKEN REQUIRED")
    print("=" * 70)
    print("1. Open prism.enverus.com in Chrome/Edge (must be logged in)")
    print("2. Press F12 → Application tab → Cookies → https://prism.enverus.com")
    print("3. Find cookie named 'rseg_jwt', copy its value (starts with 'eyJ')")
    print("4. Paste it below and press Enter")
    print("=" * 70)
    tok = input("rseg_jwt token: ").strip()
    with open(TOKEN_FILE, "w") as f:
        f.write(tok)
    print(f"  Token saved to {TOKEN_FILE} for future runs.")
    return tok


def fetch_all(sql: str, token: str, page_size: int = 5000, desc: str = "") -> pd.DataFrame:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {"query": sql, "maxPageSize": page_size, "formatting": "tabular"}
    resp = requests.post(DAS_URL, json=payload, headers=headers, timeout=120)
    if resp.status_code == 401:
        os.remove(TOKEN_FILE)
        print("\nERROR: Token expired or invalid. Delete the saved token and re-run.")
        sys.exit(1)
    resp.raise_for_status()
    data = resp.json()
    rows = data.get("data", data.get("rows", []))
    page_count = 1
    while data.get("hasMore"):
        payload2 = {"cursor": data["cursor"], "maxPageSize": page_size, "formatting": "tabular"}
        resp2 = requests.post(CURSOR_URL, json=payload2, headers=headers, timeout=120)
        resp2.raise_for_status()
        data = resp2.json()
        rows.extend(data.get("data", data.get("rows", [])))
        page_count += 1
    df = pd.DataFrame(rows)
    if desc:
        print(f"  {desc}: {len(df):,} rows ({page_count} page{'s' if page_count > 1 else ''})")
    return df


def epoch_ms_to_date(series: pd.Series) -> pd.Series:
    """Convert epoch-millisecond integers to YYYY-MM-DD strings."""
    def convert(v):
        if pd.isna(v):
            return None
        try:
            return datetime.utcfromtimestamp(float(v) / 1000).strftime("%Y-%m-%d")
        except Exception:
            return None
    return series.apply(convert)


# ─────────────────────────────────────────────
# STEP 1: Process PCM file
# ─────────────────────────────────────────────

print("\n[1/3] Processing PCM file...")
pcm = pd.read_csv(PCM_CSV)
print(f"  Loaded {len(pcm):,} rows")

# Drop DR_ demand response types
dr_mask = pcm["pcm_generator_type"].isin(["DR_AS", "DR_DA"])
print(f"  Dropping {dr_mask.sum()} DR_ rows (DR_AS, DR_DA)")
pcm = pcm[~dr_mask].copy()

# Map status
pcm["ENVProjectStatus"] = pcm["current_is_operating"].map(
    {True: "Operating", False: "Under Construction"}
)

# Map technology
unmapped_types = set(pcm["pcm_generator_type"].dropna()) - set(PCM_TYPE_MAP.keys())
if unmapped_types:
    print(f"  WARNING: Unmapped generator types (will be 'Other'): {unmapped_types}")
pcm["ProjectType"] = pcm["pcm_generator_type"].map(PCM_TYPE_MAP).fillna("Other")

# ST_OTHER override: fuel codes that indicate biomass -> Biomass
BIOMASS_FUEL_CODES = {"WDS", "AB", "OBS", "BLQ", "OBL", "MSW", "SLW", "LFG", "OBG", "TDF"}
biomass_mask = (pcm["pcm_generator_type"] == "ST_OTHER") & pcm["eia_fuel_code"].isin(BIOMASS_FUEL_CODES)
if biomass_mask.sum():
    print(f"  Reclassifying {biomass_mask.sum()} ST_OTHER biomass unit(s) -> Biomass")
    pcm.loc[biomass_mask, "ProjectType"] = "Biomass"

# Build output dataframe
pcm_out = pd.DataFrame({
    "ENVProjectID":               pcm["pcm_uid"],
    "ProjectName":                pcm["pcm_uid"],
    "ProjectType":                pcm["ProjectType"],
    "ENVProjectStatus":           pcm["ENVProjectStatus"],
    "ProjectCapacityMW":          pcm["ProjectCapacityMW"],
    "CurrentOperatingCapacity":   pcm["ProjectCapacityMW"],
    "FirstPowerDate":             pcm["FirstPowerDate"],
    "RetirementDate":             pcm["retirement_date"],
    "ISOTerritory":               pcm["iso_territory"],
    "ENVZone":                    pcm["ENVZone"],
    "HeatRateMmbtuMwh":           pcm["hr_avg"],
    "ProjectCompletionProbability": 100,
})

op_count = (pcm_out["ENVProjectStatus"] == "Operating").sum()
uc_count = (pcm_out["ENVProjectStatus"] == "Under Construction").sum()
print(f"  PCM rows: {op_count} Operating, {uc_count} Under Construction")


# ─────────────────────────────────────────────
# STEP 2: Query PRISM for IA projects
# ─────────────────────────────────────────────

print("\n[2/3] Querying PRISM for Interconnection Agreement projects...")
token = get_token()

sql = """
SELECT
    ENVProjectID,
    ProjectName,
    ProjectType,
    ProjectStatus,
    ProjectCapacityMW,
    CurrentOperatingCapacityMW,
    FirstPowerDate,
    ISOTerritory,
    ENVZone,
    heat_rate_mmbtu_mwh
FROM eaCombinedProjects
WHERE ISO = 'ERCOT'
  AND ProjectStatus = 'Interconnection Agreement'
  AND Country = 'US'
"""

prism = fetch_all(sql, token, desc="ERCOT Interconnection Agreement projects")

if prism.empty:
    print("  WARNING: No IA projects returned from PRISM. Check token or filters.")
    prism_out = pd.DataFrame(columns=CEM_COLUMNS)
else:
    # Convert epoch-ms FirstPowerDate to YYYY-MM-DD
    prism["FirstPowerDate"] = epoch_ms_to_date(prism["FirstPowerDate"])

    # Map PRISM ProjectType -> CEM ProjectType
    unmapped_prism = set(prism["ProjectType"].dropna()) - set(PRISM_TYPE_MAP.keys())
    if unmapped_prism:
        print(f"  WARNING: Unmapped PRISM project types (will be 'Other'): {unmapped_prism}")
    prism["CEM_ProjectType"] = prism["ProjectType"].map(PRISM_TYPE_MAP).fillna("Other")

    prism_out = pd.DataFrame({
        "ENVProjectID":               prism["ENVProjectID"],
        "ProjectName":                prism["ProjectName"],
        "ProjectType":                prism["CEM_ProjectType"],
        "ENVProjectStatus":           "Interconnection Agreement",
        "ProjectCapacityMW":          pd.to_numeric(prism["ProjectCapacityMW"], errors="coerce"),
        "CurrentOperatingCapacity":   pd.to_numeric(prism["ProjectCapacityMW"], errors="coerce"),
        "FirstPowerDate":             prism["FirstPowerDate"],
        "RetirementDate":             None,
        "ISOTerritory":               prism["ISOTerritory"],
        "ENVZone":                    prism["ENVZone"],
        "HeatRateMmbtuMwh":           pd.to_numeric(prism["heat_rate_mmbtu_mwh"], errors="coerce"),
        "ProjectCompletionProbability": 100,
    })
    print(f"  PRISM ProjectType breakdown:\n{prism['CEM_ProjectType'].value_counts().to_string()}")


# ─────────────────────────────────────────────
# STEP 3: Combine and write output
# ─────────────────────────────────────────────

print("\n[3/3] Combining and writing output...")

combined = pd.concat([pcm_out, prism_out], ignore_index=True)

# Ensure correct column order, drop any extras
combined = combined[CEM_COLUMNS]

out_path = os.path.join(OUT_DIR, OUT_FILENAME)
combined.to_csv(out_path, index=False)

print(f"\n  Output: {out_path}")
print(f"  Total rows: {len(combined):,}")
print(f"  Status breakdown:\n{combined['ENVProjectStatus'].value_counts().to_string()}")
print(f"  ProjectType breakdown:\n{combined['ProjectType'].value_counts().to_string()}")
print("\nDone.")
