"""
transform_pcm_installed_capacity.py
===================================
Transforms the full-L48 PCM installed-capacity export into the CEM project-DB
format the ETR HTML model already ingests, then appends the Net Imports + FERVO
rows and writes CEM_installed_capacity.csv into the Combined L48 folder.

Input : pcm_to_cem_v7 (1) (1).csv   (CEM-shaped, ProjectType still PCM codes)
Output : <Combined L48>/CEM_installed_capacity.csv   (existing one backed up first)

Rules (per user):
  - Map ProjectType codes -> canonical names (PCM_TYPE_MAP, incl. Offshore Wind /
    Storage / Geothermal for the three types the original build script missed).
  - Default ProjectStatus = "Operating" for every row (timing handled by dates).
  - Drop DR_AS / DR_DA (no demand-response tech in the model).
  - Drop rows with blank ProjectType (all-empty placeholder rows).
  - Normalize dates: FirstPowerDate M/D/YYYY -> YYYY-MM-DD; RetirementDate
    ISO-with-time or literal "null" -> YYYY-MM-DD or blank.
  - ProjectCompletionProbability -> 100 when blank.
  - Note: the ST_OTHER->Biomass override is NOT applied (needs eia_fuel_code,
    absent from the full-L48 file) -> ST_OTHER maps to Other.
"""

import csv, os, re, shutil, collections
from datetime import datetime

SRC = r"C:\Users\juan.arteaga\Downloads\pcm_to_cem_v7 (1) (1).csv"
OUT_DIR = r"C:\Users\juan.arteaga\OneDrive - Enverus\LTF Working Group_SSG - Cap Expansion Model\FINAL L48\Combined L48"
OUT = os.path.join(OUT_DIR, "CEM_installed_capacity.csv")

CEM_COLUMNS = [
    "ENVProjectID", "ProjectName", "ProjectType", "ProjectStatus",
    "ProjectCapacityMW", "CurrentOperatingCapacity",
    "FirstPowerDate", "RetirementDate",
    "ISOTerritory", "ENVZone",
    "HeatRateMmbtuMwh", "ProjectCompletionProbability",
]

# PCM code -> canonical CEM ProjectType (all canonical names resolve in the model's techMap).
PCM_TYPE_MAP = {
    "CC_GAS": "Natural Gas", "CT_GAS": "Natural Gas", "IC_GAS": "Natural Gas", "ST_GAS": "Natural Gas",
    "zonal_agg_GAS": "Natural Gas",
    "COAL": "Coal", "zonal_agg_COAL": "Coal",
    "OIL": "Oil", "zonal_agg_OIL": "Oil",
    "NUCLEAR": "Nuclear",
    "OTHER": "Other", "ST_OTHER": "Other", "zonal_agg_OTHER": "Other",
    "BIOMASS": "Biomass", "zonal_agg_BIOMASS": "Biomass",
    "zonal_agg_Solar": "Solar",
    "zonal_agg_Wind": "Onshore Wind",
    "zonal_agg_Hydro": "Hydro",
    "zonal_agg_BESS": "Storage",
    # The three the original build script left unmapped (were dumped into "Other"):
    "zonal_agg_Offshore_Wind": "Offshore Wind",
    "zonal_agg_PumpedHydro": "Storage",
    "zonal_agg_GEO": "Geothermal",
    # Pass-through canonical names (appended rows / already-canonical inputs):
    "Net Imports": "Net Imports", "Geothermal": "Geothermal", "Natural Gas": "Natural Gas",
    "Coal": "Coal", "Oil": "Oil", "Nuclear": "Nuclear", "Other": "Other", "Biomass": "Biomass",
    "Solar": "Solar", "Solar PV": "Solar", "Onshore Wind": "Onshore Wind",
    "Offshore Wind": "Offshore Wind", "Hydro": "Hydro", "Storage": "Storage",
}
DROP_TYPES = {"DR_AS", "DR_DA"}

# PCM uses WECC/SERC/NEISO for ISOTerritory; the model's project-DB convention (and the original
# Combined L48 file) uses WEST/SE/ISONE (the ENVZone token keeps its WECC_/SERC_/NEISO_ prefix).
ISO_NORMALIZE = {"WECC": "WEST", "SERC": "SE", "NEISO": "ISONE"}


def norm_iso(s):
    s = (s or "").strip()
    return ISO_NORMALIZE.get(s, s)


def norm_first_power(s):
    s = (s or "").strip()
    if s == "" or s.lower() == "null":
        return ""
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", s)          # M/D/YYYY
    if m:
        mm, dd, yy = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{yy:04d}-{mm:02d}-{dd:02d}"
    if re.match(r"^\d{4}-\d{2}-\d{2}", s):                      # YYYY-MM-DD or ISO-T
        return s[:10]
    return s


def norm_retire(s):
    s = (s or "").strip()
    if s == "" or s.lower() == "null":
        return ""
    if re.match(r"^\d{4}-\d{2}-\d{2}", s):                      # ISO-T or YYYY-MM-DD
        return s[:10]
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", s)
    if m:
        mm, dd, yy = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{yy:04d}-{mm:02d}-{dd:02d}"
    return s


def make_row(env_id, name, ptype, cap, first_power, iso,
             status="Operating", retire="", zone="", hr="", prob="100", cur=""):
    return {
        "ENVProjectID": env_id, "ProjectName": name, "ProjectType": ptype,
        "ProjectStatus": status, "ProjectCapacityMW": cap,
        "CurrentOperatingCapacity": cur if cur != "" else cap,
        "FirstPowerDate": first_power, "RetirementDate": retire,
        "ISOTerritory": iso, "ENVZone": zone,
        "HeatRateMmbtuMwh": hr, "ProjectCompletionProbability": prob,
    }


# ─── 1. Transform PCM rows ────────────────────────────────────────────────
src_rows = list(csv.DictReader(open(SRC, newline="", encoding="utf-8")))
out_rows = []
dropped_dr = dropped_empty = 0
unmapped = collections.Counter()

for r in src_rows:
    code = (r.get("ProjectType") or "").strip()
    if code == "":
        dropped_empty += 1
        continue
    if code in DROP_TYPES:
        dropped_dr += 1
        continue
    canonical = PCM_TYPE_MAP.get(code)
    if canonical is None:
        unmapped[code] += 1
        canonical = "Other"
    out_rows.append(make_row(
        env_id=(r.get("ENVProjectID") or "").strip(),
        name=(r.get("ProjectName") or "").strip() or (r.get("ENVProjectID") or "").strip(),
        ptype=canonical,
        cap=(r.get("ProjectCapacityMW") or "").strip(),
        first_power=norm_first_power(r.get("FirstPowerDate")),
        iso=norm_iso(r.get("ISOTerritory")),
        status="Operating",
        retire=norm_retire(r.get("RetirementDate")),
        zone=(r.get("ENVZone") or "").strip(),
        hr=(r.get("HeatRateMmbtuMwh") or "").strip(),
        prob="100",
        cur=(r.get("CurrentOperatingCapacity") or "").strip(),
    ))

# ─── 2. Appended rows: Net Imports + FERVO (all Operating) ─────────────────
net_imports = [
    # (id, iso, MW, first_power)
    ("Net Imports_CAISO_2020", "CAISO", 10000, "2020-01-01"),
    ("Net Imports_ERCOT_2020", "ERCOT", 1000, "2020-01-01"),
    ("Net Imports_ISONE_2020", "ISONE", 4000, "2020-01-01"),
    ("Net Imports_MISO_2020",  "MISO",  15000, "2020-01-01"),
    ("Net Imports_NYISO_2020", "NYISO", 5000, "2020-01-01"),
    ("Net Imports_PJM_2020",   "PJM",   8000, "2020-01-01"),
    ("Net Imports_SPP_2020",   "SPP",   8000, "2020-01-01"),
    ("Net Imports_SE_2020",    "SE",    8000, "2020-01-01"),
    ("Net Imports_WEST_2020",  "WEST",  8000, "2020-01-01"),
    ("Net Imports_CAISO_2027", "CAISO", 2000, "2027-01-01"),
    ("Net Imports_CAISO_2035", "CAISO", 500,  "2035-01-01"),
    ("Net Imports_CAISO_2040", "CAISO", 500,  "2040-01-01"),
    ("Net Imports_CAISO_2045", "CAISO", 500,  "2045-01-01"),
    ("Net Imports_WECC_2027",  "WEST",  2000, "2027-01-01"),
    ("Net Imports_WECC_2035",  "WEST",  500,  "2035-01-01"),
    ("Net Imports_WECC_2040",  "WEST",  500,  "2040-01-01"),
    ("Net Imports_WECC_2045",  "WEST",  500,  "2045-01-01"),
]
for pid, iso, mw, fp in net_imports:
    out_rows.append(make_row(pid, "Net Imports", "Net Imports", mw, fp, iso))

fervo = [(2026, 30), (2027, 70), (2028, 400), (2029, 150), (2030, 300),
         (2031, 400), (2032, 500), (2033, 600), (2034, 750), (2035, 900)]
for yr, mw in fervo:
    out_rows.append(make_row(f"FERVO_{yr}", "FERVO", "Geothermal", mw, f"{yr}-01-01", "WEST"))

# ─── 3. Back up existing output, then write ───────────────────────────────
if os.path.exists(OUT):
    bak = os.path.join(OUT_DIR, f"CEM_installed_capacity.backup-{datetime.now().strftime('%b%d_%H%M')}.csv")
    shutil.copy2(OUT, bak)
    print(f"Backed up existing -> {os.path.basename(bak)}")

with open(OUT, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=CEM_COLUMNS)
    w.writeheader()
    w.writerows(out_rows)

# ─── 4. Summary ───────────────────────────────────────────────────────────
print(f"\nSource rows: {len(src_rows)}")
print(f"  dropped DR: {dropped_dr}, dropped empty: {dropped_empty}")
if unmapped:
    print(f"  UNMAPPED codes -> 'Other': {dict(unmapped)}")
else:
    print("  unmapped codes: none")
print(f"Appended: {len(net_imports)} Net Imports + {len(fervo)} FERVO")
print(f"Total output rows: {len(out_rows)}")
print(f"Output: {OUT}")
tc = collections.Counter(r["ProjectType"] for r in out_rows)
print("\nProjectType breakdown:")
for k, v in tc.most_common():
    print(f"  {v:6d}  {k}")
ic = collections.Counter(r["ISOTerritory"] for r in out_rows)
print("ISOTerritory breakdown:", dict(ic.most_common()))
