# ETR Capacity Expansion Model — Price Post-Processing Algorithm
### Technical Whitepaper for Cross-Workflow Implementation
**Version 1.0 | June 2026**

---

## 1. Executive Summary

The dispatch stack at the core of the capacity expansion model produces *fundamental* electricity prices: prices derived mechanically from the marginal cost of the last unit dispatched. These prices are correct on average but structurally too flat — they underestimate peak-hour scarcity spikes and overestimate off-peak floors, because a deterministic dispatch stack cannot reproduce the stochastic variance of a real power market.

The post-processing algorithm corrects both deficiencies:

1. **Shape correction** — a binned error curve learned from historical data reshapes the diurnal and seasonal price distribution while preserving the model's structural dispatch logic.
2. **Stretch amplification** — a log-normal geometric stretch around the daily mean exaggerates within-day price spread to match observed volatility.
3. **Level anchoring** — a scalar ties the annual average modeled price to the observed historical average for the base calibration year, then freezes that scalar for all future years.

The result is a final hourly price series that is simultaneously grounded in dispatch fundamentals and calibrated to match real market price distributions.

---

## 2. Conceptual Framework

### 2.1 Why Fundamental Prices Are Too Flat

A dispatch stack sets price equal to the variable cost of the marginal generator. In a deterministic simulation:
- Every hour with the same net load level produces the same price.
- There is no generator outage variance, no weather uncertainty, no gas supply uncertainty.
- Scarcity spikes above the cost of the last unit are zero by construction.

Real markets exhibit a strongly right-skewed price distribution: most hours cluster near marginal gas cost, but a small fraction of hours (high-demand, low-wind, high-gas days) spike to 5–20× the average. The post-processing algorithm learns this mapping from historical data.

### 2.2 Key Insight: Reserve Margin as the Correction Signal

The correction magnitude depends on how tight the system is at any given hour. The reserve margin (available generation capacity minus load, divided by load) is the natural signal: the tighter the margin, the larger the upward correction needed. The algorithm bins the historical prediction error by reserve margin and learns a non-parametric correction curve.

---

## 3. Inputs

### 3.1 Required Inputs

| Input | Type | Description |
|---|---|---|
| `fundamental_prices` | `float[8760]` | Hourly dispatch-stack prices ($/MWh), one per hour of the simulation year |
| `hourly_reserve_margins` | `float[8760]` | Hourly reserve margin = `(available_capacity / load) - 1.0` |
| `hourly_gas_prices` | `float[8760]` | Hourly gas prices ($/MMBtu); use daily or annual scalar if hourly unavailable |
| `historical_prices` | `float[8760]` | Actual observed hourly LMP ($/MWh) for the calibration year |
| `historical_gas_prices` | `float[8760]` | Gas prices ($/MMBtu) corresponding to each historical price hour |
| `year` | `int` | Simulation year (e.g. 2025) |
| `base_years` | `list[int]` | Years with complete historical data used for calibration (e.g. [2024, 2025]) |

### 3.2 Optional / Configuration Inputs

| Input | Default | Description |
|---|---|---|
| `stretch_factor` | `1.5` (auto-optimized) | Exponent controlling within-day price spread amplification |
| `price_floor` | `-150` $/MWh | Hard floor applied to all output prices |
| `price_cap` | `5000` $/MWh | Hard cap applied to all output prices |
| `default_gas_price` | `3.50` $/MMBtu | Fallback when hourly gas price is missing or ≤ 0.10 |
| `normal_price_threshold_mult` | `15×` | Gas price multiplier above which hours are excluded from the level scalar calculation (screens out scarcity hours) |
| `min_price_filter` | `-500` $/MWh | Floor for including hours in the `historicalAvgPrice` calculation |
| `num_bins` | `100` | Number of reserve margin bins in the correction curve |
| `gaussian_sigma` | `3` | Smoothing parameter for the binned correction curve |
| `calibration_scalar_min` | `0.2` | Minimum allowed level scalar |
| `calibration_scalar_max` | `3.0` | Maximum allowed level scalar |

### 3.3 Historical Price CSV Format

The historical price file should have one row per hour with at minimum:

```
Snapshots,           LMP ($/MWh),    Gas Price ($/MMBtu)
2024-01-01 00:00,    28.41,          2.85
2024-01-01 01:00,    24.17,          2.85
...
```

- **Date column**: recognized as `Snapshots`, `Date`, `DateTime`, or `Timestamp` (case-insensitive).
- **Gas price column**: optional. If absent, `default_gas_price` is used for all hours.
- **Completeness**: a year must have exactly 8760 rows (or 8784 for leap years, with Feb 29 auto-removed) to be used in calibration. Incomplete years are ignored.
- **Missing gas prices**: if the gas column is present but a row has value 0 or blank, `default_gas_price` is substituted. This is internally consistent but reduces accuracy of the heat-rate correction — see Section 6.3.

---

## 4. Algorithm

The algorithm runs in four sequential phases:

```
Phase 1: Parse historical data → compute historicalAvgPrice
Phase 2: Train FundamentalCalibrator (learn error curve from backtest year)
Phase 3: Optimize stretch factor (minimize MSE to historical)
Phase 4: Apply post-processing to produce final hourly prices
```

Phases 1–3 run **once** when the model is initialized with a zone and historical file. Phase 4 runs **every time** the model produces a price series (each year, each scenario).

---

### Phase 1: Historical Data Parsing

**Goal**: parse the historical price CSV, filter to complete years, and extract two things:
- `historicalAvgPrice`: the annual average LMP, used as the level anchor in Phase 4.
- `heat_rate_tables`: seasonal peak/off-peak implied heat rates, used for diagnostics.

**Steps**:

1. Parse each row; extract `(timestamp, lmp, gas_price)`.
2. Count rows per calendar year. Flag a year as *complete* if it has exactly 8760 rows (non-leap) or 8784 rows with Feb 29 removed to yield 8760.
3. Filter `parsed` to complete years only.
4. Compute `historicalAvgPrice = mean(lmp)` for all rows where `min_price_filter < lmp < price_cap`.

Note: `historicalAvgPrice` is computed over **all complete years in the file**. If the file contains 2024 and 2025, the average is the pooled two-year average. When running the model on a specific year (e.g. 2025), `extractHistoricalPricesByYear(2025)` is called to get only that year's 8760 hours for Phase 2–3 training.

---

### Phase 2: Train the FundamentalCalibrator

**Goal**: learn a non-parametric correction curve mapping reserve margin → heat rate error.

**Inputs to training**:
- `simulated_rm[8760]`: hourly reserve margins from the base-year simulation run.
- `raw_prices[8760]`: fundamental dispatch-stack prices from the base-year run.
- `actual_prices[8760]`: historical observed LMP for that same year.
- `gas_prices[8760]`: hourly gas prices used in simulation.

**Steps**:

1. Convert prices to heat rate equivalent:
   ```
   raw_HR[i]    = raw_prices[i]    / gas_prices[i]
   actual_HR[i] = actual_prices[i] / gas_prices[i]
   hr_error[i]  = actual_HR[i] - raw_HR[i]
   ```
   Hours where either heat rate falls outside `[CALIBRATOR_MIN_HR, CALIBRATOR_MAX_HR]` are excluded as outliers.

2. Bin the errors by reserve margin:
   ```
   bin_width  = (max(simulated_rm) - min(simulated_rm)) / num_bins
   bin_edges  = [rm_min + i * bin_width for i in range(num_bins + 1)]
   bin_errors[k] = mean(hr_error[i] for all i where simulated_rm[i] falls in bin k)
   ```

3. Fill any empty bins using linear interpolation between neighboring non-empty bins. Extend flat to boundaries.

4. Apply Gaussian smoothing with `sigma = 3` bins to remove noise.

5. Store as `binnedCurve[100]` and `binEdges[101]`.

**What this curve means**: for a given reserve margin level, `binnedCurve[k]` is the average heat rate units (BTU/kWh) by which the fundamental model *underestimates* the actual market price (expressed as a heat rate). Tight reserve margins → large positive error (model too cheap). Loose reserve margins → near-zero or negative error (model approximately correct or slightly high).

---

### Phase 3: Optimize Stretch Factor

**Goal**: find the `stretch_factor` that minimizes MSE between calibrated and actual prices.

The stretch factor controls within-day price dispersion amplification (see Phase 4, Step 2). It is optimized via gradient descent (Adam optimizer) over the range [0.1, 5.0].

**Objective function**: for a given `stretch_factor`, apply the full calibration (Phase 4 Steps 1–2) and compute:
```
MSE = mean((calibrated_price[i] - actual_price[i])^2)
```
The optimizer minimizes MSE. Typical converged values are in the range 1.2–2.5 depending on ISO and market structure.

The optimized `stretch_factor` is stored and used as the default for all subsequent Phase 4 calls.

---

### Phase 4: Apply Post-Processing (per simulation run)

This is the main runtime function. It takes raw fundamental prices and produces final calibrated prices.

**Step 4a — Binned curve correction** (only when calibrator is trained):

For each hour `i`:
```
gas = gas_prices[i] if gas_prices[i] > 0.10 else default_gas_price
raw_HR = raw_prices[i] / gas
hr_error = binnedCurve[lookup_bin(simulated_rm[i])]
corrected_HR = raw_HR + hr_error
corrected_price[i] = corrected_HR * gas
```

Where `lookup_bin(rm)` clamps `rm` to `[rm_min, rm_max]` and returns the index into `binnedCurve`.

**Step 4b — Log-normal geometric shape stretch** (applied per calendar day):

For each day `d` (24-hour block):
```
day_mean = mean(corrected_price[d*24 : (d+1)*24])

# Geometric stretch around daily mean (exaggerates spread)
for each hour i in day d:
    stretched[i] = day_mean * (max(EPSILON, corrected_price[i]) / max(EPSILON, day_mean)) ^ stretch_factor

# Re-normalize to preserve original daily mean (stretch changes shape, not level)
new_day_mean = mean(stretched[d*24 : (d+1)*24])
ratio = day_mean / new_day_mean if new_day_mean > 0 else 1.0

for each hour i in day d:
    if raw_prices[i] < 0:
        final_prices[i] = raw_prices[i]        # preserve negative prices as-is
    else:
        final_prices[i] = stretched[i] * ratio
```

The `^ stretch_factor` operation amplifies deviations from the daily mean in log space. A stretch of 1.0 is identity. A stretch of 2.0 roughly doubles the within-day spread. The re-normalization step ensures no net energy revenue shift from the shape change alone.

**Step 4c — Level scalar** (calibrate annual average to historical):

Applies only for base calibration years. For future years, the scalar computed from the most recent base year is reused frozen.

```
if year in base_years or base_scalar is None:
    # Compute model average, excluding scarcity hours
    model_avg = mean(
        final_prices[i]
        for i in range(8760)
        if final_prices[i] > price_floor
        and final_prices[i] < gas_price * normal_price_threshold_mult
    )

    if model_avg > 1.0 and historicalAvgPrice > 0:
        scalar = historicalAvgPrice / model_avg
        scalar = clamp(scalar, calibration_scalar_min, calibration_scalar_max)
    else:
        scalar = 1.0

    base_scalar = scalar   # freeze for reuse in future years

else:
    scalar = base_scalar   # reuse frozen scalar from most recent base year

final_prices = [p * scalar for p in final_prices]
```

**Step 4d — Hard clamp**:

```
final_prices[i] = clamp(final_prices[i], price_floor, price_cap)
```

---

### Fallback: Calibrator Not Trained

If Phase 2 training fails (insufficient data, incomplete historical year, or post-processing disabled), Phase 4 skips Step 4a and applies only the shape stretch directly to `fundamental_prices` without the binned correction. The level scalar (Step 4c) still applies if `historicalAvgPrice` is available.

---

## 5. Outputs

| Output | Type | Description |
|---|---|---|
| `final_prices` | `float[8760]` | Final calibrated hourly prices ($/MWh), ready for revenue/IRR calculations |
| `calibration_scalar` | `float` | Level scalar applied (`historicalAvgPrice / modelAvgPrice`) |
| `stretch_factor` | `float` | Shape stretch exponent used |
| `calibrator_trained` | `bool` | Whether the binned curve correction was applied |

---

## 6. Edge Cases and Fallbacks

### 6.1 Year Not Complete in Historical Data
If the requested year has fewer than 8760 rows, it is excluded from calibration. The algorithm falls back to the most recent complete year's prices for training (Phase 2–3) and uses the frozen `base_scalar` for the level anchor.

### 6.2 No Historical Data at All
Post-processing can still run with `stretch_factor` applied (shape only, no binned correction) and no level scalar. Prices will have the correct dispatch-stack shape but will not be anchored to observed markets.

### 6.3 Missing or Incomplete Gas Prices
Any hour where `gas_price ≤ 0.10` substitutes `default_gas_price = $3.50/MMBtu`.
- If the gas column is entirely absent from the CSV, every hour uses $3.50 — internally consistent.
- If gas prices are partially missing (some months present, some not), the error bins for reserve margin ranges clustering in the missing-gas months will be computed at the wrong scale. This reduces accuracy of the binned correction but does not break the algorithm.
- **Recommendation**: if 2025 gas prices are unavailable, remove the gas column entirely from the CSV rather than leaving zeros, to ensure uniform substitution.

### 6.4 High Scarcity Hour Fraction
If more than 30% of simulation hours hit `PRICE_CAP`, the level scalar calculation will be corrupted because most non-scarcity hours are filtered out. This indicates missing dispatchable capacity in the inputs (typically hydro or geothermal not included in the installed capacity file). The scalar is still computed but a warning is logged.

### 6.5 Leap Years
Feb 29 is automatically detected (hours 1416–1439 of the year) and removed before any calibration or comparison, yielding a consistent 8760-hour basis.

---

## 7. Python Pseudocode

```python
import numpy as np
from scipy.ndimage import gaussian_filter1d

# ─── Constants ────────────────────────────────────────────────────────────────
DEFAULT_GAS_PRICE = 3.50          # $/MMBtu
PRICE_CAP         = 5000.0        # $/MWh
PRICE_FLOOR       = -150.0        # $/MWh
MIN_PRICE_FILTER  = -500.0        # $/MWh  (excludes extreme negatives from avg)
NORMAL_PRICE_MULT = 15.0          # × gas price: above this = scarcity, excluded from scalar
NUM_BINS          = 100
GAUSSIAN_SIGMA    = 3.0
CALIBRATOR_MIN_HR = 0.5           # BTU/kWh  (screens nonsense heat rates)
CALIBRATOR_MAX_HR = 500.0
LOG_STRETCH_EPS   = 0.01          # prevents log(0) in stretch step
SCALAR_MIN        = 0.2
SCALAR_MAX        = 3.0
BASE_YEARS        = [2024, 2025]  # years with complete historical data


# ─── Phase 1: Parse Historical Data ──────────────────────────────────────────

def parse_historical_csv(filepath: str) -> dict:
    """
    Read the historical price CSV, filter to complete years (8760 hrs),
    and return:
        historical_avg_price : float — pooled average over all complete years
        prices_by_year       : dict[int, np.ndarray] — 8760-hr arrays per year
        gas_by_year          : dict[int, np.ndarray] — 8760-hr gas price arrays per year
    """
    import csv, datetime

    rows = []
    with open(filepath, newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    # Auto-detect columns
    date_col = _find_column(rows[0].keys(), ['snapshots', 'date', 'datetime', 'timestamp'])
    lmp_col  = _find_column(rows[0].keys(), ['lmp'])
    gas_col  = _find_column(rows[0].keys(), ['gas'])  # may be None

    # Group by year
    year_rows = {}
    for row in rows:
        ts  = _parse_date(row[date_col])
        if ts is None:
            continue
        yr  = ts.year
        lmp = float(row[lmp_col] or 0)
        gas = float(row[gas_col] or 0) if gas_col else 0.0
        year_rows.setdefault(yr, []).append((ts, lmp, gas))

    # Identify complete years
    def _is_complete(yr, row_list):
        n = len(row_list)
        if _is_leap(yr):
            return n in (8760, 8784)
        return n == 8760

    complete_years = {yr: rows for yr, rows in year_rows.items()
                      if _is_complete(yr, rows)}

    prices_by_year = {}
    gas_by_year    = {}
    all_prices     = []

    for yr, yr_rows in complete_years.items():
        yr_rows.sort(key=lambda r: r[0])           # sort by timestamp
        lmps = np.array([r[1] for r in yr_rows])
        gas  = np.array([r[2] for r in yr_rows])

        # Strip Feb 29 from leap years
        if len(lmps) == 8784:
            lmps = np.concatenate([lmps[:1416], lmps[1440:]])
            gas  = np.concatenate([gas[:1416],  gas[1440:]])

        # Substitute missing gas prices
        gas = np.where(gas > 0.10, gas, DEFAULT_GAS_PRICE)

        prices_by_year[yr] = lmps
        gas_by_year[yr]    = gas
        all_prices.extend(lmps)

    # Pooled average (used for level scalar anchor)
    valid = [p for p in all_prices if MIN_PRICE_FILTER < p < PRICE_CAP]
    historical_avg_price = float(np.mean(valid)) if valid else None

    return {
        'historical_avg_price': historical_avg_price,
        'prices_by_year':       prices_by_year,
        'gas_by_year':          gas_by_year,
        'complete_years':       sorted(complete_years.keys()),
    }


def _find_column(keys, keywords):
    """Case-insensitive column name search."""
    keys = list(keys)
    for k in keywords:
        for col in keys:
            if col.strip().lower().startswith(k):
                return col
    return None


def _parse_date(s):
    import datetime
    for fmt in ('%Y-%m-%d %H:%M', '%Y-%m-%d %H', '%m/%d/%Y %H:%M', '%Y-%m-%dT%H:%M:%S'):
        try:
            return datetime.datetime.strptime(s.strip(), fmt)
        except ValueError:
            pass
    return None


def _is_leap(yr):
    return (yr % 4 == 0 and yr % 100 != 0) or (yr % 400 == 0)


# ─── Phase 2 & 3: FundamentalCalibrator ──────────────────────────────────────

class FundamentalCalibrator:
    """
    Learns a reserve-margin-indexed heat rate error correction curve from
    historical backtest data, then applies it to future simulation prices.
    """

    def __init__(self):
        self.binned_curve  = None   # shape: (NUM_BINS,)  — HR error per RM bin
        self.bin_edges     = None   # shape: (NUM_BINS+1,)
        self.best_stretch  = 1.5
        self.is_trained    = False
        self.is_optimized  = False
        self.fit_quality   = 0.0    # R² of optimized fit

    # ── Training ──────────────────────────────────────────────────────────────

    def train(
        self,
        simulated_rm:  np.ndarray,   # (8760,) reserve margins from simulation
        raw_prices:    np.ndarray,   # (8760,) fundamental dispatch-stack prices
        actual_prices: np.ndarray,   # (8760,) historical observed prices
        gas_prices:    np.ndarray,   # (8760,) gas prices $/MMBtu
    ):
        gas = np.where(gas_prices > 0.10, gas_prices, DEFAULT_GAS_PRICE)

        raw_hr    = raw_prices    / gas
        actual_hr = actual_prices / gas
        hr_error  = actual_hr - raw_hr

        # Filter out outlier hours
        valid = (
            (raw_hr    > CALIBRATOR_MIN_HR) & (raw_hr    < CALIBRATOR_MAX_HR) &
            (actual_hr > CALIBRATOR_MIN_HR) & (actual_hr < CALIBRATOR_MAX_HR)
        )
        rm_v  = simulated_rm[valid]
        err_v = hr_error[valid]

        if len(rm_v) < 100:
            print("FundamentalCalibrator: insufficient valid data points")
            return

        # Bin errors by reserve margin
        rm_min, rm_max = rm_v.min(), rm_v.max()
        bin_width = (rm_max - rm_min) / NUM_BINS
        self.bin_edges = np.linspace(rm_min, rm_max, NUM_BINS + 1)

        bin_sums   = np.zeros(NUM_BINS)
        bin_counts = np.zeros(NUM_BINS, dtype=int)
        bin_idx    = np.clip(
            ((rm_v - rm_min) / bin_width).astype(int), 0, NUM_BINS - 1
        )
        np.add.at(bin_sums,   bin_idx, err_v)
        np.add.at(bin_counts, bin_idx, 1)

        bin_means = np.where(bin_counts > 0, bin_sums / bin_counts, np.nan)

        # Fill gaps and smooth
        filled  = _interpolate_gaps(bin_means)
        smoothed = gaussian_filter1d(filled, sigma=GAUSSIAN_SIGMA)

        self.binned_curve = smoothed
        self.is_trained   = True
        print("FundamentalCalibrator: training complete")

    # ── Optimization ──────────────────────────────────────────────────────────

    def optimize(
        self,
        simulated_rm:  np.ndarray,
        raw_prices:    np.ndarray,
        actual_prices: np.ndarray,
        gas_prices:    np.ndarray,
        iterations:    int = 200,
        lr:            float = 0.05,
    ):
        """Adam optimizer over stretch_factor to minimize MSE vs actual prices."""
        if not self.is_trained:
            print("FundamentalCalibrator: must train before optimizing")
            return

        actual = actual_prices.copy()
        stretch = self.best_stretch
        m, v, beta1, beta2, eps = 0.0, 0.0, 0.9, 0.999, 1e-8

        best_mse   = np.inf
        best_s     = stretch
        delta      = 0.01   # finite-difference step for gradient estimate

        for t in range(1, iterations + 1):
            cal_lo = self._apply_with_params(simulated_rm, raw_prices, gas_prices, stretch - delta)
            cal_hi = self._apply_with_params(simulated_rm, raw_prices, gas_prices, stretch + delta)
            mse_lo = float(np.mean((cal_lo - actual) ** 2))
            mse_hi = float(np.mean((cal_hi - actual) ** 2))
            grad   = (mse_hi - mse_lo) / (2 * delta)

            m = beta1 * m + (1 - beta1) * grad
            v = beta2 * v + (1 - beta2) * grad ** 2
            m_hat = m / (1 - beta1 ** t)
            v_hat = v / (1 - beta2 ** t)
            stretch -= lr * m_hat / (np.sqrt(v_hat) + eps)
            stretch  = float(np.clip(stretch, 0.1, 5.0))

            cal = self._apply_with_params(simulated_rm, raw_prices, gas_prices, stretch)
            mse = float(np.mean((cal - actual) ** 2))
            if mse < best_mse:
                best_mse = mse
                best_s   = stretch

        self.best_stretch  = best_s
        self.is_optimized  = True
        ss_res = best_mse * len(actual)
        ss_tot = float(np.sum((actual - actual.mean()) ** 2))
        self.fit_quality = max(0.0, 1.0 - ss_res / ss_tot) if ss_tot > 0 else 0.0
        print(f"FundamentalCalibrator: optimized stretch={best_s:.3f}  R²={self.fit_quality:.3f}")

    # ── Application ───────────────────────────────────────────────────────────

    def apply(
        self,
        simulated_rm: np.ndarray,
        raw_prices:   np.ndarray,
        gas_prices:   np.ndarray,
    ) -> np.ndarray:
        if not self.is_trained:
            return raw_prices.copy()
        calibrated = self._apply_with_params(
            simulated_rm, raw_prices, gas_prices, self.best_stretch
        )
        return np.clip(calibrated, PRICE_FLOOR, PRICE_CAP)

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _lookup_bin(self, rm_values: np.ndarray) -> np.ndarray:
        rm_min, rm_max = self.bin_edges[0], self.bin_edges[-1]
        bin_width = (rm_max - rm_min) / NUM_BINS
        idx = np.clip(
            ((rm_values - rm_min) / bin_width).astype(int), 0, NUM_BINS - 1
        )
        return self.binned_curve[idx]

    def _apply_with_params(
        self,
        simulated_rm: np.ndarray,
        raw_prices:   np.ndarray,
        gas_prices:   np.ndarray,
        stretch:      float,
    ) -> np.ndarray:
        gas = np.where(gas_prices > 0.10, gas_prices, DEFAULT_GAS_PRICE)

        # Step 1: binned HR error correction
        raw_hr       = raw_prices / gas
        hr_error     = self._lookup_bin(simulated_rm)
        corrected_hr = raw_hr + hr_error
        corrected    = corrected_hr * gas

        # Step 2: log-normal geometric stretch, day by day
        n_hours    = len(corrected)
        calibrated = np.empty(n_hours)
        n_days     = int(np.ceil(n_hours / 24))

        for d in range(n_days):
            s = d * 24
            e = min(s + 24, n_hours)
            day_slice    = corrected[s:e]
            raw_slice    = raw_prices[s:e]
            day_mean     = day_slice.mean()

            if day_mean <= 0:
                calibrated[s:e] = day_slice
                continue

            # Geometric stretch: exaggerate deviations from daily mean
            ratio_in  = np.maximum(LOG_STRETCH_EPS, day_slice) / max(LOG_STRETCH_EPS, day_mean)
            stretched = day_mean * (ratio_in ** stretch)

            # Re-normalize to preserve daily mean (shape change only)
            new_mean  = stretched.mean()
            norm      = (day_mean / new_mean) if new_mean > 0 else 1.0

            # Preserve negative raw prices unchanged
            neg_mask         = raw_slice < 0
            calibrated[s:e]  = np.where(neg_mask, raw_slice, stretched * norm)

        return calibrated


def _interpolate_gaps(arr: np.ndarray) -> np.ndarray:
    """Linear interpolation over NaN gaps; extend flat to boundaries."""
    result = arr.copy()
    n      = len(result)
    valid  = np.where(~np.isnan(result))[0]
    if len(valid) == 0:
        return np.zeros(n)

    # Extend flat to boundaries
    result[:valid[0]]  = result[valid[0]]
    result[valid[-1]:] = result[valid[-1]]

    # Linear interpolation for interior gaps
    x = np.arange(n)
    mask = np.isnan(result)
    result[mask] = np.interp(x[mask], x[~mask], result[~mask])
    return result


# ─── Phase 4: postprocess_prices (runtime — called per simulation year) ───────

def postprocess_prices(
    fundamental_prices:    np.ndarray,        # (8760,) dispatch-stack prices
    hourly_reserve_margins: np.ndarray,       # (8760,) reserve margins
    hourly_gas_prices:     np.ndarray,        # (8760,) gas prices $/MMBtu
    year:                  int,
    calibrator:            FundamentalCalibrator,
    historical_avg_price:  float | None,
    base_scalar:           float | None,      # pass None for first base year run
    stretch_factor:        float = 1.5,
    price_floor:           float = PRICE_FLOOR,
    price_cap:             float = PRICE_CAP,
) -> dict:
    """
    Apply the full post-processing pipeline to raw fundamental prices.

    Returns
    -------
    dict with keys:
        final_prices       : np.ndarray (8760,)
        calibration_scalar : float
        stretch_factor     : float
        calibrator_trained : bool
        base_scalar        : float  (updated; pass back in for future years)
    """

    # ── Step 4a + 4b: Shape correction (binned curve + stretch) ──────────────
    if calibrator.is_trained:
        calibrator.best_stretch = stretch_factor   # allow manual override
        shaped_prices = calibrator.apply(
            hourly_reserve_margins,
            fundamental_prices,
            hourly_gas_prices,
        )
    else:
        # Fallback: stretch only, no binned correction
        shaped_prices = _apply_stretch_only(
            fundamental_prices, stretch_factor
        )

    # ── Step 4c: Level scalar ─────────────────────────────────────────────────
    is_base_year = (year in BASE_YEARS)

    if is_base_year or base_scalar is None:
        scalar = _compute_level_scalar(
            shaped_prices,
            hourly_gas_prices,
            historical_avg_price,
            price_floor,
        )
        base_scalar = scalar   # freeze for future years
    else:
        scalar = base_scalar   # reuse frozen base-year scalar

    # ── Step 4d: Apply scalar and hard clamp ──────────────────────────────────
    final_prices = np.clip(shaped_prices * scalar, price_floor, price_cap)

    return {
        'final_prices':       final_prices,
        'calibration_scalar': scalar,
        'stretch_factor':     stretch_factor,
        'calibrator_trained': calibrator.is_trained,
        'base_scalar':        base_scalar,
    }


def _apply_stretch_only(prices: np.ndarray, stretch: float) -> np.ndarray:
    """Fallback shape stretch without binned correction."""
    n_hours = len(prices)
    result  = np.empty(n_hours)
    n_days  = int(np.ceil(n_hours / 24))

    for d in range(n_days):
        s = d * 24
        e = min(s + 24, n_hours)
        day_slice = prices[s:e]
        day_mean  = day_slice.mean()

        if day_mean <= 0:
            result[s:e] = day_slice
            continue

        ratio_in  = np.maximum(LOG_STRETCH_EPS, day_slice) / max(LOG_STRETCH_EPS, day_mean)
        stretched = day_mean * (ratio_in ** stretch)
        new_mean  = stretched.mean()
        norm      = (day_mean / new_mean) if new_mean > 0 else 1.0

        neg_mask      = day_slice < 0
        result[s:e]   = np.where(neg_mask, day_slice, stretched * norm)

    return result


def _compute_level_scalar(
    shaped_prices:     np.ndarray,
    hourly_gas_prices: np.ndarray,
    historical_avg:    float | None,
    price_floor:       float,
) -> float:
    """
    Compute historicalAvgPrice / modelAvgPrice, excluding scarcity hours
    and clamped to [SCALAR_MIN, SCALAR_MAX].
    """
    if historical_avg is None or historical_avg <= 0:
        print("[Calibration] No historical average price — scalar stays 1.0")
        return 1.0

    gas = np.where(hourly_gas_prices > 0.10, hourly_gas_prices, DEFAULT_GAS_PRICE)
    normal_ceiling = gas * NORMAL_PRICE_MULT

    mask = (shaped_prices > price_floor) & (shaped_prices < normal_ceiling)
    model_avg = shaped_prices[mask].mean() if mask.any() else 0.0

    if model_avg <= 1.0:
        print(f"[Calibration] modelAvgPrice={model_avg:.4f} ≤ 1.0 — scalar stays 1.0")
        return 1.0

    scalar = float(np.clip(historical_avg / model_avg, SCALAR_MIN, SCALAR_MAX))
    print(f"[Calibration] histAvg=${historical_avg:.2f}  modelAvg=${model_avg:.2f}  scalar={scalar:.4f}")
    return scalar


# ─── Top-level orchestration example ─────────────────────────────────────────

def run_postprocessing_pipeline(
    historical_csv_path:     str,
    simulation_year:         int,
    fundamental_prices:      np.ndarray,
    hourly_reserve_margins:  np.ndarray,
    hourly_gas_prices:       np.ndarray,
    calibrator:              FundamentalCalibrator | None = None,
    base_scalar:             float | None = None,
) -> dict:
    """
    Full pipeline entry point. Call once per simulation year.

    Parameters
    ----------
    historical_csv_path : str
        Path to CEM_Hist_Prices.csv (or equivalent).
    simulation_year : int
        The year being simulated (e.g. 2026).
    fundamental_prices : np.ndarray (8760,)
        Raw dispatch-stack prices for this year.
    hourly_reserve_margins : np.ndarray (8760,)
        Hourly (available_capacity / load) - 1.0 for this year.
    hourly_gas_prices : np.ndarray (8760,)
        Hourly gas prices ($/MMBtu) for this year.
    calibrator : FundamentalCalibrator, optional
        Pass in a previously trained calibrator to avoid re-training each year.
        If None, a new one is trained on the most recent complete base year.
    base_scalar : float, optional
        Scalar from a previous base-year run. If None, recomputed from historical data.

    Returns
    -------
    dict:
        final_prices, calibration_scalar, stretch_factor,
        calibrator_trained, base_scalar, calibrator (for reuse)
    """
    # Phase 1: parse historical data (could be cached across years)
    hist = parse_historical_csv(historical_csv_path)

    # Phase 2 & 3: train calibrator if not already trained
    if calibrator is None or not calibrator.is_trained:
        calibrator = FundamentalCalibrator()

        # Use the most recent complete base year for training
        base_training_year = max(
            (yr for yr in hist['complete_years'] if yr in BASE_YEARS),
            default=None
        )
        if base_training_year is not None:
            act_prices  = hist['prices_by_year'][base_training_year]
            act_gas     = hist['gas_by_year'][base_training_year]
            calibrator.train(
                hourly_reserve_margins,   # NOTE: ideally use base-year sim RM
                fundamental_prices,       # NOTE: ideally use base-year sim prices
                act_prices,
                act_gas,
            )
            if calibrator.is_trained:
                calibrator.optimize(
                    hourly_reserve_margins,
                    fundamental_prices,
                    act_prices,
                    act_gas,
                )

    # Phase 4: apply post-processing
    result = postprocess_prices(
        fundamental_prices      = fundamental_prices,
        hourly_reserve_margins  = hourly_reserve_margins,
        hourly_gas_prices       = hourly_gas_prices,
        year                    = simulation_year,
        calibrator              = calibrator,
        historical_avg_price    = hist['historical_avg_price'],
        base_scalar             = base_scalar,
        stretch_factor          = calibrator.best_stretch,
    )

    result['calibrator'] = calibrator   # return for reuse in subsequent years
    return result
```

---

## 8. Implementation Notes for Cross-Workflow Use

### 8.1 Calibrator Lifecycle

Train and optimize **once per ISO/zone** using the base calibration year(s). Reuse the trained `FundamentalCalibrator` object across all subsequent simulation years without re-training. Re-training is only needed if the installed capacity mix changes significantly or a new historical year becomes available.

### 8.2 Reserve Margin Definition

The correction curve is indexed by reserve margin. Use a **consistent definition** across training and application:

```
RM[t] = (total_dispatchable_capacity + firm_renewable_output[t]) / load[t] - 1.0
```

Storage is typically excluded from firm capacity in the ELCC-weighted sense. Whatever definition you use in training must match what you use in application — the binned curve is meaningless if the RM scale shifts.

### 8.3 Base Scalar Freeze

Once a base-year scalar is computed (`historicalAvgPrice / modelAvgPrice`), it is frozen for all future years. This intentionally preserves the relative price trajectory from the dispatch model — only the base-year level is pinned to history. Do **not** re-anchor to history for every future year; that would suppress structural price trends driven by capacity additions.

### 8.4 Multi-Year Workflows

For multi-year capacity expansion (2025–2040), the recommended call sequence is:

```python
calibrator   = None
base_scalar  = None

for year in range(2025, 2041):
    result = run_postprocessing_pipeline(
        historical_csv_path    = HIST_PRICES_CSV,
        simulation_year        = year,
        fundamental_prices     = dispatch_results[year]['prices'],
        hourly_reserve_margins = dispatch_results[year]['reserve_margins'],
        hourly_gas_prices      = dispatch_results[year]['gas_prices'],
        calibrator             = calibrator,    # reuse across years
        base_scalar            = base_scalar,   # reuse after first base year
    )
    calibrator  = result['calibrator']          # persist trained calibrator
    base_scalar = result['base_scalar']         # persist frozen scalar
    final_prices[year] = result['final_prices']
```

### 8.5 Gas Price Availability

| Situation | Recommended approach |
|---|---|
| Full hourly gas prices available | Use them directly |
| Only annual average gas price | Tile it as a constant 8760-length array |
| Daily gas prices only | Repeat each daily value × 24 |
| No gas prices at all | Pass `np.full(8760, DEFAULT_GAS_PRICE)` |

Constant gas prices reduce the accuracy of the heat-rate correction (the curve assumes gas variability contributes to price spread) but do not break the algorithm.

### 8.6 Dependencies

```
numpy >= 1.24
scipy >= 1.10   (for gaussian_filter1d)
```

No other external dependencies required.

---

## 9. Glossary

| Term | Definition |
|---|---|
| Fundamental price | Dispatch-stack price: variable cost of the marginal generator at each hour |
| Reserve margin (RM) | `(available_capacity / load) - 1.0`; positive = surplus, negative = shortage |
| Heat rate | Price divided by gas price ($/MWh ÷ $/MMBtu); a gas-normalized price measure |
| HR error | `actual_HR - simulated_HR`; the calibrator learns this as a function of RM |
| Binned curve | Non-parametric lookup table: for each RM bin, the mean HR error observed historically |
| Stretch factor | Exponent in the log-normal geometric stretch; controls within-day price spread |
| Level scalar | `historicalAvgPrice / modelAvgPrice`; anchors the annual price level to observed markets |
| Base year | A year with complete historical data used for calibration (e.g. 2024, 2025) |
| ELCC | Effective Load Carrying Capability; capacity credit for variable resources |
