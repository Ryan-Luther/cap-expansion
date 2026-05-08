"""
Headless calibration harness for the ETR Dynamic Cap Expansion Forecast model.

Drives the single-file HTML model in Chromium, attaches the 6 input CSVs,
runs every ISO across every available year, and writes the per-ISO/year
`Annual Gas Fuel (MMBtu)` to JSON.

Strategy:
  - Inject an init script BEFORE page scripts that hooks `localStorage.setItem`
    so we get notified every time the model persists savedData. We also expose
    a getter that we can poll.
  - Override `exportResultsToCSV` to be a fast no-op so the page doesn't try
    to download files for each ISO. The model's save path that populates
    `savedData[iso][year].metrics.annualGasFuelMMBtu` runs *before* the export,
    so we lose nothing.
  - Drive each ISO via the same code path runAllIsosAndYears uses internally:
    set isoSelector, await applyAssumptions(), await optimizeAllYears(),
    await waitForWorkerIdle(). We do this by evaluating an async function in
    the page (so `await` works against the page's own functions and closures).
  - Read results from localStorage.

Usage:
    python tools/calibrate.py
"""
from __future__ import annotations

import io
import json
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright, Page, TimeoutError as PWTimeoutError

# Force UTF-8 stdout so log lines containing console messages with unicode
# (e.g. the worker's '✓' prefix) don't crash on Windows cp1252 consoles.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    # Older Pythons or wrapped streams: wrap manually.
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
HTML_FILE = REPO_ROOT / "ETR_Dynamic_Cap_Expansion_Forecast_1.6.html"
# L48 combined inputs (per user direction 2026-05-08)
INPUT_DIR = Path(
    r"C:\Users\juan.arteaga\OneDrive - Drilling Info\LTF Working Group_SSG - Cap Expansion Model\FINAL L48\Combined L48"
)
TOOLS_DIR = REPO_ROOT / "tools"
DEBUG_DIR = TOOLS_DIR / "debug"
OUT_FILE = TOOLS_DIR / "calibration-results.json"

FILE_ATTACHMENTS = [
    ("genFile",            "CEM_Capacity_Factors.csv"),
    ("loadFile",           "CEM_Load.csv"),
    ("projectDbFile",      "CEM_Installed_Capacity.csv"),
    ("historicalFile",     "CEM_Hist_Prices.csv"),
    ("assumptionsFile",    "Econ and Market Assumptions - Base.csv"),
    ("dailyGasPricesFile", "CEM_Daily_Gas_Prices.csv"),
]

EXPECTED_ISOS = ["CAISO", "ERCOT", "ISONE", "MISO", "NYISO", "PJM", "SE", "SPP", "WEST"]
TARGET_YEARS = ["2024", "2025"]

# Calibration multiplier: scales per-asset Heat_Rate for gas-fueled dispatch assets
# (Asset_Type matching Natural Gas / Other Gas / Landfill Gas etc.) at every
# updateSystemFromProjectDB rebuild. Set to 1.0 for true baseline.
# Override via CLI: `python calibrate.py --hr-mult 1.40`
DEFAULT_HR_MULTIPLIER = 1.0

# Set in main() so _write_results can record it without threading through every call.
_CURRENT_HR_MULT = DEFAULT_HR_MULTIPLIER

HEAT_RATE_PARAMS = {
    "HEAT_RATE_CT": 8.5,
    "HEAT_RATE_CCGT": 6.5,
    "HEAT_RATE_EXISTING_GAS": 8.5,
    "HEAT_RATE_OTHER": 7.0,
    "HEAT_RATE_COAL": 10.0,
    "HEAT_RATE_OIL": 10.0,
}

SAVED_DATA_KEY = "capacityExpansionSavedData"

# Total wall-clock budget for the whole batch (9 ISOs × TARGET_YEARS).
TOTAL_BATCH_TIMEOUT_S = 20 * 60
PER_ISO_TIMEOUT_MS = 5 * 60 * 1000

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        # Last-resort defensive fallback if reconfigure() didn't take.
        enc = getattr(sys.stdout, "encoding", "utf-8") or "utf-8"
        sys.stdout.write(line.encode(enc, errors="replace").decode(enc, errors="replace") + "\n")
        sys.stdout.flush()


# ---------------------------------------------------------------------------
# Init-script: runs in page context BEFORE the page's <script> blocks execute
# ---------------------------------------------------------------------------
INIT_SCRIPT = r"""
(() => {
    // 0) Patch runCoreModel to scale `existingGasWeightedHeatRate` in its return
    //    value by window.__hrMultiplier. This affects only the gas-burn
    //    aggregation downstream — dispatch decisions inside runCoreModel use the
    //    original (unscaled) per-asset Heat_Rate, so no substitution against
    //    coal/imports occurs. The result: gas burn scales ~linearly with k.
    function patchRunCoreModel() {
        try {
            if (typeof window.runCoreModel === 'function' && !window.__runCoreModelPatched) {
                const orig = window.runCoreModel;
                window.runCoreModel = async function(...args) {
                    const result = await orig.apply(this, args);
                    try {
                        const k = window.__hrMultiplier;
                        if (typeof k === 'number' && k !== 1.0 && result && typeof result.existingGasWeightedHeatRate === 'number') {
                            const before = result.existingGasWeightedHeatRate;
                            result.existingGasWeightedHeatRate = before * k;
                            window.__lastHRScaledFrom = before;
                            window.__lastHRScaledTo = result.existingGasWeightedHeatRate;
                            window.__hrScaleCount = (window.__hrScaleCount || 0) + 1;
                        }
                    } catch (e) {
                        console.log('[harness] HR scaling error: ' + (e.message || e));
                    }
                    return result;
                };
                window.__runCoreModelPatched = true;
                console.log('[harness] runCoreModel wrapped for HR-on-burn scaling');
            }
        } catch (e) {
            console.log('[harness] patchRunCoreModel error: ' + (e.message || e));
        }
    }
    document.addEventListener('DOMContentLoaded', () => {
        patchRunCoreModel();
        let tries = 0;
        const t = setInterval(() => {
            patchRunCoreModel();
            if (window.__runCoreModelPatched || ++tries > 60) clearInterval(t);
        }, 100);
    });

    // 1) Tag every localStorage write so we know progress.
    try {
        const _origSet = Storage.prototype.setItem;
        Storage.prototype.setItem = function(k, v) {
            try {
                if (k === 'capacityExpansionSavedData') {
                    window.__lastPersistAt = Date.now();
                    window.__persistCount = (window.__persistCount || 0) + 1;
                }
            } catch (e) {}
            return _origSet.apply(this, arguments);
        };
    } catch (e) {}

    // 2) Once the page has booted and the model functions are defined, wrap
    //    exportResultsToCSV to a no-op so we don't trigger downloads. We do
    //    this by polling for the function on window after DOMContentLoaded.
    function patchExport() {
        try {
            if (typeof window.exportResultsToCSV === 'function' && !window.__exportPatched) {
                window.__origExportResultsToCSV = window.exportResultsToCSV;
                window.exportResultsToCSV = async function(mode) {
                    console.log('[harness] exportResultsToCSV(' + mode + ') stubbed');
                    return Promise.resolve();
                };
                window.__exportPatched = true;
                console.log('[harness] exportResultsToCSV patched to no-op');
            }
        } catch (e) {
            console.log('[harness] patchExport error: ' + (e.message || e));
        }
    }
    document.addEventListener('DOMContentLoaded', () => {
        // The model assigns the function as a top-level `function` declaration in
        // a non-module <script>, which means it lives on window. Patch a few
        // times in case of timing issues.
        patchExport();
        let tries = 0;
        const t = setInterval(() => {
            patchExport();
            if (window.__exportPatched || ++tries > 60) clearInterval(t);
        }, 100);
    });

    // 3) Convenience getter: surface savedData via JSON.parse of localStorage.
    window.__getSaved = function() {
        try {
            const raw = localStorage.getItem('capacityExpansionSavedData');
            return raw ? JSON.parse(raw) : {};
        } catch (e) { return {}; }
    };

    // 4) Watch console.log for the worker's "Simulation worker initialized"
    //    signal and set window.__workerReady. We can't easily hook the worker
    //    onmessage from outside, but the page logs that string when it sees
    //    the 'ready' message.
    try {
        const _origLog = console.log;
        console.log = function(...args) {
            try {
                const s = args.map(a => typeof a === 'string' ? a : '').join(' ');
                if (s.indexOf('Simulation worker initialized') !== -1) {
                    window.__workerReady = true;
                }
                if (s.indexOf('All years completed') !== -1) {
                    window.__lastFinishAt = Date.now();
                    window.__finishCount = (window.__finishCount || 0) + 1;
                }
            } catch (e) {}
            return _origLog.apply(this, args);
        };
    } catch (e) {}
})();
"""


# ---------------------------------------------------------------------------
# Debug helpers
# ---------------------------------------------------------------------------
def dump_debug(page: Page, console_buf: list, tag: str) -> None:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    try:
        page.screenshot(path=str(DEBUG_DIR / f"{tag}-{ts}.png"), full_page=True)
        log(f"  screenshot saved: tools/debug/{tag}-{ts}.png")
    except Exception as e:
        log(f"  screenshot failed: {e}")
    log_path = DEBUG_DIR / f"{tag}-{ts}.log"
    log_path.write_text("\n".join(console_buf), encoding="utf-8")
    log(f"  console log saved: tools/debug/{tag}-{ts}.log ({len(console_buf)} lines)")


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------
def attach_inputs(page: Page) -> None:
    for input_id, fname in FILE_ATTACHMENTS:
        path = INPUT_DIR / fname
        if not path.exists():
            raise FileNotFoundError(f"Missing input CSV: {path}")
        log(f"  attaching {fname} -> #{input_id}")
        page.set_input_files(f"#{input_id}", str(path))


def wait_for_ready(page: Page, timeout_ms: int = 180_000) -> None:
    """
    Wait until the model has ingested inputs:
      - optimizeAllYearsButton is enabled (set by enableControlsAndRun)
      - ISO selector populated
    """
    page.wait_for_function(
        """() => {
            const btn = document.getElementById('optimizeAllYearsButton');
            const sel = document.getElementById('isoSelector');
            if (!btn || btn.disabled) return false;
            if (!sel || sel.options.length < 2) return false;
            return true;
        }""",
        timeout=timeout_ms,
    )
    # Also wait for the worker 'ready' message to appear in console (we attach a
    # console listener; the run loop polls __workerReady set by that listener).
    page.wait_for_function(
        "() => window.__workerReady === true",
        timeout=timeout_ms,
    )


def list_isos(page: Page) -> list[str]:
    return page.evaluate(
        """() => Array.from(document.getElementById('isoSelector').options)
            .map(o => o.value).filter(v => v && v.trim())"""
    )


def list_years(page: Page) -> list[str]:
    return page.evaluate(
        """() => Array.from(document.getElementById('yearSelector').options)
            .map(o => o.value).filter(v => v && v.trim())"""
    )


def run_iso(page: Page, iso: str, timeout_ms: int = PER_ISO_TIMEOUT_MS) -> dict:
    """
    Drive a single ISO for the calibration target years only (TARGET_YEARS).

    Bypasses `optimizeAllYears` (which iterates 26 years and runs capacity
    expansion for 2026+, taking ~40s per year). Instead, posts directly to the
    simulation worker with `years: TARGET_YEARS` and both years marked as
    skip-optimization (save-as-is dispatch, no expansion search). This makes
    each ISO take ~10-20s instead of ~17 minutes.
    """
    target_years_js = json.dumps(TARGET_YEARS)
    log(f"  [{iso}] starting calibration-years-only run (years={TARGET_YEARS})")

    page.evaluate(
        f"""() => {{
            window.__runError = null;
            window.__runDone = false;
            const iso = {json.dumps(iso)};
            const targetYears = {target_years_js};
            (async () => {{
                try {{
                    const sel = document.getElementById('isoSelector');
                    sel.value = iso;
                    sel.dispatchEvent(new Event('change', {{bubbles: true}}));
                    await Promise.resolve();
                    if (typeof window.applyAssumptions === 'function') {{
                        await window.applyAssumptions();
                    }}
                    // Make sure the year selector has options for target years so
                    // processYearOnMainThread's `yearSelector.value = year` succeeds.
                    const yearSel = document.getElementById('yearSelector');
                    if (yearSel) {{
                        const existing = new Set(Array.from(yearSel.options).map(o => o.value));
                        targetYears.forEach(y => {{
                            if (!existing.has(y)) {{
                                const opt = document.createElement('option');
                                opt.value = y; opt.textContent = y;
                                yearSel.appendChild(opt);
                            }}
                        }});
                    }}
                    // simulationWorker / isWorkerReady / isWorkerProcessing are top-level `let`
                    // declarations in the page script — accessible by name in this scope but NOT
                    // as window properties. We probe via name and fall back to optimizeAllYears
                    // if unreachable.
                    let postedDirect = false;
                    try {{
                        // eslint-disable-next-line no-undef
                        if (typeof simulationWorker !== 'undefined' && simulationWorker
                            && typeof isWorkerReady !== 'undefined' && isWorkerReady) {{
                            // eslint-disable-next-line no-undef
                            isWorkerProcessing = true;
                            // eslint-disable-next-line no-undef
                            simulationWorker.postMessage({{
                                type: 'start_optimization',
                                data: {{
                                    years: targetYears,
                                    skipOptimizationYears: targetYears
                                }}
                            }});
                            postedDirect = true;
                        }}
                    }} catch (e) {{
                        console.log('[harness] direct worker post failed: ' + (e.message || e));
                    }}
                    if (!postedDirect) {{
                        if (typeof window.optimizeAllYears !== 'function') {{
                            throw new Error('cannot reach simulationWorker or optimizeAllYears');
                        }}
                        console.log('[harness] FALLBACK to optimizeAllYears (slow path)');
                        await window.optimizeAllYears();
                    }}
                    if (typeof window.waitForWorkerIdle === 'function') {{
                        await window.waitForWorkerIdle({timeout_ms});
                    }} else {{
                        await new Promise((resolve, reject) => {{
                            const start = Date.now();
                            const t = setInterval(() => {{
                                const btn = document.getElementById('optimizeAllYearsButton');
                                if (btn && !btn.disabled) {{ clearInterval(t); resolve(); }}
                                else if (Date.now() - start > {timeout_ms}) {{ clearInterval(t); reject(new Error('button never re-enabled')); }}
                            }}, 500);
                        }});
                    }}
                    window.__runDone = true;
                }} catch (e) {{
                    window.__runError = String(e && e.stack || e);
                    window.__runDone = true;
                }}
            }})();
            return true;
        }}"""
    )

    # Poll for completion with progress logging.
    start = time.time()
    last_progress_log = start
    last_persist_count = 0
    while True:
        elapsed = time.time() - start
        if elapsed * 1000 > timeout_ms:
            raise PWTimeoutError(f"[{iso}] timed out after {elapsed:.0f}s")

        state = page.evaluate(
            """() => ({
                done: !!window.__runDone,
                err: window.__runError || null,
                persistCount: window.__persistCount || 0,
                lastPersistAt: window.__lastPersistAt || 0,
            })"""
        )
        if state["err"]:
            raise RuntimeError(f"[{iso}] page-side error: {state['err']}")
        if state["done"]:
            return state

        # Progress every 30s, or whenever a new persistence happened.
        now = time.time()
        if state["persistCount"] != last_persist_count:
            log(f"  [{iso}] localStorage persisted (count={state['persistCount']}, t+{elapsed:.0f}s)")
            last_persist_count = state["persistCount"]
            last_progress_log = now
        elif now - last_progress_log >= 30:
            log(f"  [{iso}] still running... t+{elapsed:.0f}s, persists={state['persistCount']}")
            last_progress_log = now

        time.sleep(2.0)


def read_saved_data(page: Page) -> dict:
    raw = page.evaluate(f"() => localStorage.getItem({json.dumps(SAVED_DATA_KEY)})")
    if not raw:
        return {}
    return json.loads(raw)


def extract_gas_burn(saved_data: dict) -> dict:
    """Build per-ISO/year gas-burn map from savedData."""
    out = {}
    for iso, years in saved_data.items():
        if not isinstance(years, dict):
            continue
        out[iso] = {}
        for year, blob in years.items():
            metrics = (blob or {}).get("metrics") or {}
            v = metrics.get("annualGasFuelMMBtu")
            if v is not None:
                try:
                    out[iso][year] = float(v)
                except Exception:
                    pass
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    # CLI: --hr-mult 1.40
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--hr-mult", type=float, default=DEFAULT_HR_MULTIPLIER,
                   help="Per-asset gas Heat_Rate multiplier applied at each ISO/Year rebuild")
    args = p.parse_args()
    hr_mult = float(args.hr_mult)
    global _CURRENT_HR_MULT
    _CURRENT_HR_MULT = hr_mult

    if not HTML_FILE.exists():
        log(f"FATAL: HTML not found at {HTML_FILE}")
        return 2
    if not INPUT_DIR.is_dir():
        log(f"FATAL: input dir not found at {INPUT_DIR}")
        return 2

    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    console_buf: list[str] = []

    log(f"opening {HTML_FILE.name} in headless Chromium")
    log(f"HR multiplier: {hr_mult}")
    file_url = HTML_FILE.as_uri()

    overall_start = time.time()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(accept_downloads=True)
        # Inject our hooks before any page script runs.
        ctx.add_init_script(INIT_SCRIPT)
        page = ctx.new_page()

        def on_console(m):
            line = f"[{m.type}] {m.text}"
            console_buf.append(line)
            # Forward important lines to our log so we can see worker progress.
            t = m.text or ""
            if (
                "Year " in t
                or "All years completed" in t
                or "Diag" in t
                or "harness" in t
                or "[applyAssumptions]" in t
                or "Worker error" in t
                or t.startswith("✓")
                or m.type == "error"
            ):
                log(f"  [browser:{m.type}] {t}")
            # Track worker readiness via the 'ready' message the worker logs.
            if "Simulation worker initialized" in t:
                page.evaluate("() => { window.__workerReady = true; }")

        page.on("console", on_console)
        page.on("pageerror", lambda e: (console_buf.append(f"[pageerror] {e}"), log(f"  [browser:pageerror] {e}")))

        try:
            page.goto(file_url, wait_until="domcontentloaded")
            log("page loaded")

            # Set the calibration multiplier BEFORE any project DB upload triggers
            # updateSystemFromProjectDB. The wrapper installed via init script will
            # read this each time it runs.
            page.evaluate(f"() => {{ window.__hrMultiplier = {hr_mult}; }}")

            # Clear stale savedData from any prior run in this profile.
            page.evaluate(f"() => localStorage.removeItem({json.dumps(SAVED_DATA_KEY)})")

            log("attaching input CSVs")
            attach_inputs(page)

            log("waiting for model to be ready (buttons enabled, worker ready, ISO list populated)")
            wait_for_ready(page)
            log("model is ready")

            # Sanity: confirm the export patch landed.
            patched = page.evaluate("() => !!window.__exportPatched")
            log(f"  exportResultsToCSV patched on window: {patched}")

            isos = list_isos(page)
            years = list_years(page)
            log(f"detected {len(isos)} ISOs: {isos}")
            log(f"detected {len(years)} years: {years[:3]}..{years[-3:] if len(years)>3 else years}")

            missing = [i for i in EXPECTED_ISOS if i not in isos]
            if missing:
                log(f"WARNING: expected ISOs not present: {missing}")

            for idx, iso in enumerate(isos, start=1):
                if time.time() - overall_start > TOTAL_BATCH_TIMEOUT_S:
                    log(f"BUDGET EXCEEDED ({TOTAL_BATCH_TIMEOUT_S}s); stopping after {idx-1}/{len(isos)} ISOs")
                    break

                log(f"==== ISO {idx}/{len(isos)}: {iso} ====")
                t0 = time.time()
                try:
                    run_iso(page, iso)
                except PWTimeoutError as e:
                    log(f"  TIMEOUT on {iso}: {e}; dumping debug")
                    dump_debug(page, console_buf, f"timeout-{iso}")
                    raise
                except Exception as e:
                    log(f"  ERROR on {iso}: {e}; dumping debug")
                    dump_debug(page, console_buf, f"error-{iso}")
                    raise
                dt = time.time() - t0
                log(f"  [{iso}] done in {dt:.1f}s")

                partial = extract_gas_burn(read_saved_data(page))
                iso_years_saved = sorted((partial.get(iso) or {}).keys())
                log(f"  [{iso}] saved {len(iso_years_saved)} year(s): {iso_years_saved[:6]}{'...' if len(iso_years_saved) > 6 else ''}")
                if "2024" in iso_years_saved or "2025" in iso_years_saved:
                    v24 = partial[iso].get("2024")
                    v25 = partial[iso].get("2025")
                    log(f"  [{iso}] 2024={v24}  2025={v25}")

                # Persist intermediate JSON so a later ISO failure doesn't lose work.
                _write_results(partial, isos)

            log("collecting final savedData")
            saved_data = read_saved_data(page)
            per_iso_year_full = extract_gas_burn(saved_data)
            _write_results(per_iso_year_full, isos)

            # Friendly summary to stdout.
            log("---- SUMMARY (Annual Gas Fuel, MMBtu) ----")
            totals = {y: 0.0 for y in TARGET_YEARS}
            for iso in EXPECTED_ISOS:
                vals = per_iso_year_full.get(iso, {})
                v24 = vals.get("2024")
                v25 = vals.get("2025")
                if v24 is not None:
                    totals["2024"] += v24
                if v25 is not None:
                    totals["2025"] += v25
                f24 = f"{v24:>15,.0f}" if v24 is not None else " " * 14 + "-"
                f25 = f"{v25:>15,.0f}" if v25 is not None else " " * 14 + "-"
                log(f"  {iso:<6}  2024 {f24}   2025 {f25}")
            log(f"  TOTAL   2024 {totals['2024']:>15,.0f}   2025 {totals['2025']:>15,.0f}")

            return 0

        except Exception as e:
            log(f"FATAL: {e}")
            traceback.print_exc()
            try:
                dump_debug(page, console_buf, "fatal")
            except Exception:
                pass
            # still try to flush whatever we have
            try:
                partial_full = extract_gas_burn(read_saved_data(page))
                _write_results(partial_full, [])
                log("wrote partial results before exit")
            except Exception:
                pass
            return 1
        finally:
            ctx.close()
            browser.close()


def _write_results(per_iso_year_full: dict, isos_detected: list) -> None:
    per_iso_year = {
        iso: {y: v for y, v in years_map.items() if y in TARGET_YEARS}
        for iso, years_map in per_iso_year_full.items()
    }
    totals: dict[str, float] = {y: 0.0 for y in TARGET_YEARS}
    for iso, years_map in per_iso_year.items():
        for y in TARGET_YEARS:
            if y in years_map:
                totals[y] += years_map[y]
    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "per_iso_year": per_iso_year,
        "totals": totals,
        "params_snapshot": HEAT_RATE_PARAMS,
        "hr_multiplier": _CURRENT_HR_MULT,
        "all_years_per_iso": per_iso_year_full,
        "isos_detected": isos_detected,
    }
    OUT_FILE.write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
