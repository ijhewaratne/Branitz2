# Economics Module Documentation

Complete documentation for the Economics module implementing LCOH (Levelized Cost of Heat) calculation, CO₂ emissions analysis, and Monte Carlo uncertainty propagation for the Branitz Heat Decision pipeline.

**Module Location**: `src/branitz_heat_decision/economics/`  
**Total Lines of Code**: ~1,104 lines  
**Primary Language**: Python 3.9+  
**Dependencies**: dataclasses, typing, numpy, pandas, yaml, logging, math, multiprocessing, concurrent.futures

---

## Module Overview

The Economics module provides economic and environmental analysis for the Branitz Heat Decision pipeline:

1. **Parameters** (`params.py`): Economic parameters and Monte Carlo configuration
2. **LCOH Calculation** (`lcoh.py`): Levelized Cost of Heat using CRF method
3. **CO₂ Analysis** (`co2.py`): CO₂ emissions calculation for DH and HP
4. **Monte Carlo** (`monte_carlo.py`): Uncertainty propagation via Monte Carlo simulation
5. **Utilities** (`utils.py`): Financial calculation helpers (CRF, NPV, etc.)

### Architecture

The Economics module follows a modular architecture with clear separation of concerns:

```
Economics Module
├─ params.py → Economic Parameters & Configuration
├─ utils.py → Financial Calculation Utilities
├─ lcoh.py → Levelized Cost of Heat Calculation
├─ co2.py → CO₂ Emissions Analysis
└─ monte_carlo.py → Monte Carlo Uncertainty Propagation
```

---

## Module Files & Functions

### `__init__.py` (44 lines) ⭐ **MODULE EXPORTS**
**Purpose**: Module initialization and public API exports

**Exports**:
- `EconomicParameters`, `EconomicsParams`, `MonteCarloParams`
- `get_default_economics_params()`, `get_default_monte_carlo_params()`
- `load_default_params()`, `load_params_from_yaml()`
- `DHInputs`, `HPInputs`
- `compute_lcoh_dh()`, `compute_lcoh_hp()`, `lcoh_dh_crf()`, `lcoh_hp_crf()`
- `compute_co2_dh()`, `compute_co2_hp()`, `co2_dh()`, `co2_hp()`
- `run_monte_carlo()`, `run_monte_carlo_for_cluster()`, `compute_mc_summary()`

---

### `params.py` (175 lines) ⭐ **ECONOMIC PARAMETERS**
**Purpose**: Defines economic parameters and Monte Carlo configuration

**Main Classes**:

#### `EconomicParameters` ⭐ **ECONOMIC PARAMETERS DATACLASS**
```python
@dataclass(frozen=True)
class EconomicParameters:
    # Time value
    lifetime_years: int = 20
    discount_rate: float = 0.04  # 4%
    
    # Energy prices (EUR/MWh)
    electricity_price_eur_per_mwh: float = 250.0
    gas_price_eur_per_mwh: float = 80.0
    biomass_price_eur_per_mwh: float = 110.0
    
    # Emission factors (kg CO2/MWh)
    ef_electricity_kg_per_mwh: float = 350.0  # German grid mix
    ef_gas_kg_per_mwh: float = 200.0
    ef_biomass_kg_per_mwh: float = 25.0
    
    # CAPEX parameters
    pipe_cost_eur_per_m: Dict[str, float] = {...}  # DN20-DN200
    plant_cost_base_eur: float = 1500000.0
    pump_cost_per_kw: float = 500.0
    
    # HP parameters
    hp_cost_eur_per_kw_th: float = 900.0
    cop_default: float = 2.8
    
    # LV upgrade cost
    lv_upgrade_cost_eur_per_kw_el: float = 200.0
    feeder_loading_planning_limit: float = 0.8  # 80%
    
    # O&M fractions
    dh_om_frac_per_year: float = 0.02  # 2%
    hp_om_frac_per_year: float = 0.02  # 2%
    
    # DH generation type
    dh_generation_type: str = "biomass"  # 'gas' | 'biomass' | 'electric'
```

**Purpose**: Economic parameters for LCOH and CO₂ calculations

**Validation** (in `__post_init__`):
- `discount_rate` must be in `(0, 1)`
- `lifetime_years` must be positive
- `dh_generation_type` must be `"gas"`, `"biomass"`, or `"electric"`
- `feeder_loading_planning_limit` must be in `(0, 1]`

**Helper Methods**:

#### `dh_energy_price_eur_per_mwh()` ⭐ **DH ENERGY PRICE**
```python
def dh_energy_price_eur_per_mwh(self) -> float
```

**Purpose**: Get energy price for DH generation type

**Returns**: `gas_price_eur_per_mwh`, `biomass_price_eur_per_mwh`, or `electricity_price_eur_per_mwh` based on `dh_generation_type`

#### `dh_emission_factor_kg_per_mwh()` ⭐ **DH EMISSION FACTOR**
```python
def dh_emission_factor_kg_per_mwh(self) -> float
```

**Purpose**: Get emission factor for DH generation type

**Returns**: `ef_gas_kg_per_mwh`, `ef_biomass_kg_per_mwh`, or `ef_electricity_kg_per_mwh` based on `dh_generation_type`

---

#### `MonteCarloParams` ⭐ **MONTE CARLO PARAMETERS DATACLASS**
```python
@dataclass(frozen=True)
class MonteCarloParams:
    n: int = 500
    seed: int = 42
    
    # Bounded multipliers / ranges (MVP)
    capex_mult_min: float = 0.8
    capex_mult_max: float = 1.2
    elec_price_mult_min: float = 0.7
    elec_price_mult_max: float = 1.3
    fuel_price_mult_min: float = 0.7
    fuel_price_mult_max: float = 1.3
    grid_co2_mult_min: float = 0.7
    grid_co2_mult_max: float = 1.3
    hp_cop_min: float = 2.0
    hp_cop_max: float = 3.5
    discount_rate_min: float = 0.02
    discount_rate_max: float = 0.08
```

**Purpose**: Monte Carlo simulation parameters (bounded ranges for MVP)

---

#### `load_default_params()` ⭐ **DEFAULT PARAMS LOADER**
```python
def load_default_params() -> EconomicParameters
```

**Purpose**: Load default economic parameters

**Returns**: `EconomicParameters()` with default values

---

#### `load_params_from_yaml()` ⭐ **YAML PARAMS LOADER**
```python
def load_params_from_yaml(path: str) -> EconomicParameters
```

**Purpose**: Load economic parameters from YAML file

**YAML Format**:
```yaml
lifetime_years: 20
discount_rate: 0.04
electricity_price_eur_per_mwh: 250.0
gas_price_eur_per_mwh: 80.0
biomass_price_eur_per_mwh: 110.0
dh_generation_type: "biomass"
# ... other parameters
```

**Returns**: `EconomicParameters` with values from YAML

---

#### `apply_multipliers()` ⭐ **PARAMETER MULTIPLIER APPLIER**
```python
def apply_multipliers(
    base: EconomicsParams,
    *,
    capex_mult: float,
    elec_price_mult: float,
    fuel_price_mult: float,
    grid_co2_mult: float,
    hp_cop: float,
    discount_rate: float,
) -> EconomicsParams
```

**Purpose**: Apply simple multipliers for Monte Carlo (MVP)

**Multipliers Applied**:
- **CAPEX**: `pipe_cost_eur_per_m`, `plant_cost_base_eur`, `pump_cost_per_kw`, `hp_cost_eur_per_kw_th`
- **Electricity**: `electricity_price_eur_per_mwh`, `ef_electricity_kg_per_mwh`
- **Fuel**: `gas_price_eur_per_mwh`, `biomass_price_eur_per_mwh`
- **HP**: `cop_default`
- **Time Value**: `discount_rate`

**Returns**: New `EconomicParameters` with multipliers applied

---

**Interactions**:
- **Used by**: `lcoh.py`, `co2.py`, `monte_carlo.py` (for parameter access)
- **Outputs**: Parameter dataclasses (used throughout economics module)

---

### `utils.py` (97 lines) ⭐ **FINANCIAL UTILITIES**
**Purpose**: Financial calculation helpers (CRF, NPV, etc.)

**Main Functions**:

#### `crf()` ⭐ **CAPITAL RECOVERY FACTOR**
```python
def crf(discount_rate: float, lifetime_years: int) -> float
```

**Purpose**: Calculate Capital Recovery Factor (CRF)

**Formula**:
```
CRF = r(1+r)^n / ((1+r)^n - 1)
```

**Special Case**: If `r = 0`, `CRF = 1/n`

**Returns**: CRF value (annualization factor)

**Usage**: Convert CAPEX (EUR) to equivalent annual cost (EUR/a)

---

#### `calculate_crf()` ⭐ **CRF ALIAS**
```python
def calculate_crf(discount_rate: float, lifetime_years: int) -> float
```

**Purpose**: Alias for `crf()` (backward compatibility)

---

#### `calculate_pv_factor()` ⭐ **PRESENT VALUE FACTOR**
```python
def calculate_pv_factor(discount_rate: float, lifetime_years: int) -> float
```

**Purpose**: Calculate present value factor for annuity

**Formula**:
```
PV = Σ(1/(1+r)^t) for t=1..n
Closed form: PV = (1 - (1+r)^(-n)) / r
```

**Special Case**: If `r = 0`, `PV = n`

**Returns**: Present value factor

---

#### `calculate_npv()` ⭐ **NET PRESENT VALUE**
```python
def calculate_npv(cash_flows: List[float], discount_rate: float) -> float
```

**Purpose**: Calculate Net Present Value (NPV) of cash flow series

**Formula**:
```
NPV = Σ(CF_t / (1+r)^t) for t=0..n
```

**Args**:
- `cash_flows`: Annual cash flows (EUR), starting with year 0
- `discount_rate`: Annual discount rate

**Returns**: NPV (EUR)

---

#### `annualize_capex()` ⭐ **CAPEX ANNUALIZATION**
```python
def annualize_capex(capex_eur: float, discount_rate: float, lifetime_years: int) -> float
```

**Purpose**: Convert CAPEX (EUR) into equivalent annual cost (EUR/a) using CRF

**Formula**: `annual_cost = CAPEX × CRF`

**Returns**: Annualized CAPEX (EUR/a)

---

#### `clamp()` ⭐ **VALUE CLAMPING**
```python
def clamp(x: float, lo: float, hi: float) -> float
```

**Purpose**: Clamp value to range `[lo, hi]`

**Returns**: Clamped value

---

#### `safe_div()` ⭐ **SAFE DIVISION**
```python
def safe_div(numer: float, denom: float, default: float = 0.0) -> float
```

**Purpose**: Safe division (returns `default` if denominator is near zero)

**Returns**: `numer / denom` if `abs(denom) >= 1e-18`, else `default`

---

#### `percentile()` ⭐ **PERCENTILE CALCULATION**
```python
def percentile(values: list[float], q: float) -> float
```

**Purpose**: Simple percentile helper without numpy dependency

**Algorithm**: Linear interpolation between adjacent values

**Returns**: Percentile value (q-th percentile, 0-1)

---

**Interactions**:
- **Used by**: `lcoh.py` (for CRF calculation), `monte_carlo.py` (for percentile calculation)
- **Outputs**: Financial calculation results (CRF, NPV, etc.)

---

### `lcoh.py` (184 lines) ⭐ **LCOH CALCULATION**
**Purpose**: Levelized Cost of Heat (LCOH) calculation using CRF method

**Main Functions**:

#### `compute_lcoh_dh()` ⭐ **DH LCOH CALCULATOR**
```python
def compute_lcoh_dh(
    annual_heat_mwh: float,
    pipe_lengths_by_dn: Optional[Dict[str, float]],
    total_pipe_length_m: float,
    pump_power_kw: float,
    params: EconomicParameters,
    plant_cost_override: Optional[float] = None,
) -> Tuple[float, Dict]
```

**Purpose**: Compute LCOH for District Heating using CRF method

**Workflow**:

1. **CAPEX Calculation**:
   - **Pipe CAPEX**: Sum of `length_m × pipe_cost_eur_per_m[DN]` for each DN
     - If `pipe_lengths_by_dn` provided: Detailed per-DN costing
     - Else: Fallback to average pipe cost × `total_pipe_length_m`
   - **Pump CAPEX**: `pump_power_kw × pump_cost_per_kw`
   - **Plant CAPEX**: `plant_cost_override` (if provided) or `plant_cost_base_eur`
   - **Total CAPEX**: `capex_pipes + capex_pump + capex_plant`

2. **OPEX Calculation**:
   - **O&M OPEX**: `total_capex × dh_om_frac_per_year` (2% default)
   - **Energy OPEX**: Based on `dh_generation_type`:
     - **Gas**: `(annual_heat_mwh / 0.90) × gas_price_eur_per_mwh` (90% efficiency)
     - **Biomass**: `(annual_heat_mwh / 0.85) × biomass_price_eur_per_mwh` (85% efficiency)
     - **Electric**: `(annual_heat_mwh / 3.0) × electricity_price_eur_per_mwh` (COP=3.0)
   - **Total OPEX**: `opex_om + opex_energy`

3. **CRF Calculation**:
   - `CRF = crf(discount_rate, lifetime_years)`

4. **LCOH Calculation**:
   - `LCOH = (total_capex × CRF + total_opex_annual) / annual_heat_mwh`

**Returns**: `(lcoh_eur_per_mwh, breakdown_dict)`

**Breakdown Dictionary**:
- `capex_total`, `capex_pipes`, `capex_pump`, `capex_plant`
- `opex_annual`, `opex_om`, `opex_energy`
- `crf`, `annual_heat_mwh`, `generation_type`

---

#### `compute_lcoh_hp()` ⭐ **HP LCOH CALCULATOR**
```python
def compute_lcoh_hp(
    annual_heat_mwh: float,
    hp_total_capacity_kw_th: float,
    cop_annual_average: float,
    max_feeder_loading_pct: float,
    params: EconomicParameters,
) -> Tuple[float, Dict]
```

**Purpose**: Compute LCOH for Heat Pump system using CRF method

**Workflow**:

1. **CAPEX Calculation**:
   - **HP CAPEX**: `hp_total_capacity_kw_th × hp_cost_eur_per_kw_th`
   - **LV Upgrade CAPEX** (if needed):
     - If `max_feeder_loading_pct > feeder_loading_planning_limit × 100`:
       - `overload_factor = (max_feeder_loading_pct - loading_threshold) / 100.0`
       - `hp_el_capacity_kw = hp_total_capacity_kw_th / cop_annual_average`
       - `upgrade_kw_el = overload_factor × hp_el_capacity_kw × 1.5` (safety factor)
       - `capex_lv_upgrade = upgrade_kw_el × lv_upgrade_cost_eur_per_kw_el`
     - Else: `capex_lv_upgrade = 0.0`
   - **Total CAPEX**: `capex_hp + capex_lv_upgrade`

2. **OPEX Calculation**:
   - **O&M OPEX**: `capex_hp × hp_om_frac_per_year` (2% default)
   - **Energy OPEX**: `(annual_heat_mwh / cop_annual_average) × electricity_price_eur_per_mwh`
   - **Total OPEX**: `opex_om + opex_energy`

3. **CRF Calculation**:
   - `CRF = crf(discount_rate, lifetime_years)`

4. **LCOH Calculation**:
   - `LCOH = (total_capex × CRF + total_opex_annual) / annual_heat_mwh`

**Returns**: `(lcoh_eur_per_mwh, breakdown_dict)`

**Breakdown Dictionary**:
- `capex_total`, `capex_hp`, `capex_lv_upgrade`
- `opex_annual`, `opex_om`, `opex_energy`
- `crf`, `annual_heat_mwh`, `annual_el_mwh`, `cop_used`
- `max_feeder_loading_pct`, `loading_threshold_pct`

---

#### `DHInputs` ⭐ **DH INPUTS DATACLASS**
```python
@dataclass(frozen=True)
class DHInputs:
    heat_mwh_per_year: float
    pipe_lengths_by_dn: Optional[Dict[str, float]]
    total_pipe_length_m: float
    pump_power_kw: float
```

**Purpose**: Input parameters for DH LCOH calculation

---

#### `HPInputs` ⭐ **HP INPUTS DATACLASS**
```python
@dataclass(frozen=True)
class HPInputs:
    heat_mwh_per_year: float
    hp_total_capacity_kw_th: float
    cop_annual_average: float
    max_feeder_loading_pct: float
```

**Purpose**: Input parameters for HP LCOH calculation

---

#### `lcoh_dh_crf()` ⭐ **DH LCOH BACK-COMPAT**
```python
def lcoh_dh_crf(inputs: DHInputs, params: EconomicsParams) -> float
```

**Purpose**: Backward-compatible wrapper (returns only LCOH, no breakdown)

**Returns**: LCOH (EUR/MWh)

---

#### `lcoh_hp_crf()` ⭐ **HP LCOH BACK-COMPAT**
```python
def lcoh_hp_crf(inputs: HPInputs, params: EconomicsParams) -> float
```

**Purpose**: Backward-compatible wrapper (returns only LCOH, no breakdown)

**Returns**: LCOH (EUR/MWh)

---

**Interactions**:
- **Uses**: `params.py` (EconomicParameters), `utils.py` (crf)
- **Used by**: `monte_carlo.py` (for LCOH calculation in MC samples)
- **Outputs**: LCOH values and breakdown dictionaries

---

### `co2.py` (114 lines) ⭐ **CO2 EMISSIONS ANALYSIS**
**Purpose**: CO₂ emissions calculation for DH and HP systems

**Main Functions**:

#### `compute_co2_dh()` ⭐ **DH CO2 CALCULATOR**
```python
def compute_co2_dh(
    annual_heat_mwh: float,
    params: EconomicParameters,
    generation_type: Optional[str] = None,
) -> Tuple[float, Dict]
```

**Purpose**: Compute specific CO₂ emissions for District Heating

**Workflow**:

1. **Generation Type**: Use `generation_type` parameter or `params.dh_generation_type`

2. **Emission Calculation**:
   - **Gas**:
     - Efficiency: 90%
     - `co2_per_mwh = ef_gas_kg_per_mwh / 0.90`
     - `annual_co2 = (annual_heat_mwh / 0.90) × ef_gas_kg_per_mwh`
   - **Biomass**:
     - Efficiency: 85%
     - `co2_per_mwh = ef_biomass_kg_per_mwh / 0.85`
     - `annual_co2 = (annual_heat_mwh / 0.85) × ef_biomass_kg_per_mwh`
   - **Electric**:
     - COP: 3.0 (central heat pump)
     - `co2_per_mwh = ef_electricity_kg_per_mwh / 3.0`
     - `annual_co2 = annual_heat_mwh × co2_per_mwh`

**Returns**: `(co2_kg_per_mwh, breakdown_dict)`

**Breakdown Dictionary**:
- `co2_kg_per_mwh`, `annual_co2_kg`
- `generation_type`, `efficiency` (if applicable), `emission_factor_kg_per_mwh`

---

#### `compute_co2_hp()` ⭐ **HP CO2 CALCULATOR**
```python
def compute_co2_hp(
    annual_heat_mwh: float,
    cop_annual_average: float,
    params: EconomicParameters,
) -> Tuple[float, Dict]
```

**Purpose**: Compute specific CO₂ emissions for Heat Pump system

**Workflow**:

1. **Electrical Energy**: `annual_el_mwh = annual_heat_mwh / cop_annual_average`

2. **CO₂ Calculation**:
   - `annual_co2 = annual_el_mwh × ef_electricity_kg_per_mwh`
   - `co2_per_mwh = annual_co2 / annual_heat_mwh`

**Returns**: `(co2_kg_per_mwh, breakdown_dict)`

**Breakdown Dictionary**:
- `co2_kg_per_mwh`, `annual_co2_kg`
- `annual_el_mwh`, `cop_used`, `ef_electricity_kg_per_mwh`

---

#### `DHCO2Inputs` ⭐ **DH CO2 INPUTS DATACLASS**
```python
@dataclass(frozen=True)
class DHCO2Inputs:
    heat_mwh_per_year: float
```

**Purpose**: Input parameters for DH CO₂ calculation

---

#### `HPCO2Inputs` ⭐ **HP CO2 INPUTS DATACLASS**
```python
@dataclass(frozen=True)
class HPCO2Inputs:
    heat_mwh_per_year: float
```

**Purpose**: Input parameters for HP CO₂ calculation

---

#### `co2_dh()` ⭐ **DH CO2 BACK-COMPAT**
```python
def co2_dh(inputs: DHCO2Inputs, params: EconomicsParams) -> float
```

**Purpose**: Backward-compatible wrapper (returns annual CO₂ in t/a)

**Returns**: Annual CO₂ (t/a) = `annual_co2_kg / 1000.0`

---

#### `co2_hp()` ⭐ **HP CO2 BACK-COMPAT**
```python
def co2_hp(inputs: HPCO2Inputs, params: EconomicsParams) -> float
```

**Purpose**: Backward-compatible wrapper (returns annual CO₂ in t/a, uses `params.cop_default`)

**Returns**: Annual CO₂ (t/a) = `annual_co2_kg / 1000.0`

---

**Interactions**:
- **Uses**: `params.py` (EconomicParameters), `utils.py` (safe_div)
- **Used by**: `monte_carlo.py` (for CO₂ calculation in MC samples)
- **Outputs**: CO₂ emissions (kg/MWh) and breakdown dictionaries

---

### `monte_carlo.py` (496 lines) ⭐ **MONTE CARLO SIMULATION**
**Purpose**: Monte Carlo uncertainty propagation for LCOH and CO₂

**Main Functions**:

#### `run_monte_carlo_for_cluster()` ⭐ **PRIMARY MC FUNCTION**
```python
def run_monte_carlo_for_cluster(
    cluster_id: str,
    cha_kpis: Dict[str, Any],
    dha_kpis: Dict[str, Any],
    cluster_summary: Dict[str, float],
    n_samples: int = 500,
    randomness_config: Optional[Dict[str, Any]] = None,
    base_params: Optional[EconomicParameters] = None,
    seed: int = 42,
    n_jobs: int = 1,
) -> pd.DataFrame
```

**Purpose**: Run Monte Carlo simulation for a single cluster

**Workflow**:

1. **Input Extraction**:
   - Calls `_extract_mc_inputs_from_kpis()` to extract:
     - `annual_heat_mwh` (from `cluster_summary`)
     - `total_length_m`, `pump_power_kw`, `pipe_dn_lengths` (from CHA KPIs)
     - `hp_capacity_kw`, `max_loading_pct` (from DHA KPIs)

2. **Randomness Configuration**:
   - If `randomness_config` not provided, uses default:
     ```python
     {
         "discount_rate": {"dist": "normal", "mean": 0.04, "std": 0.01, "clip": [0.01, 0.08]},
         "electricity_price": {"dist": "normal", "mean": 250.0, "std": 50.0, "clip": [150, 400]},
         "gas_price": {"dist": "triangular", "low": 40, "mode": 80, "high": 140},
         "pipe_cost_multiplier": {"dist": "triangular", "low": 0.8, "mode": 1.0, "high": 1.2},
         "cop": {"dist": "normal", "mean": 2.8, "std": 0.3, "clip": [2.0, 4.0]},
         "ef_electricity": {"dist": "normal", "mean": 350.0, "std": 80.0, "clip": [200, 500]},
     }
     ```

3. **Sample Generation**:
   - Generates deterministic per-sample seeds (for reproducibility in parallel mode)
   - For each sample:
     - Calls `_run_one_sample_for_cluster()` to:
       - Sample parameters from distributions
       - Compute LCOH (DH and HP)
       - Compute CO₂ (DH and HP)
       - Determine winners (`dh_cheaper`, `dh_lower_co2`)

4. **Parallelization**:
   - **Sequential** (`n_jobs=1`): Processes samples sequentially with progress bar
   - **Parallel** (`n_jobs>1` or `n_jobs=-1`): Uses `ProcessPoolExecutor` for parallel processing
     - macOS: Prefers `fork` context (if available)
     - Restores sample ordering after parallel execution

**Returns**: DataFrame with columns:
- `sample_id`, `lcoh_dh`, `lcoh_hp`, `co2_dh`, `co2_hp`
- `dh_cheaper`, `dh_lower_co2`
- `param_*` (sampled parameter values)

---

#### `_run_one_sample_for_cluster()` ⭐ **SINGLE SAMPLE RUNNER**
```python
def _run_one_sample_for_cluster(
    *,
    sample_id: int,
    seed_i: int,
    randomness_config: Dict[str, Any],
    base_params: EconomicParameters,
    annual_heat_mwh: float,
    total_length_m: float,
    pump_power_kw: float,
    pipe_dn_lengths: Optional[Dict[str, float]],
    hp_capacity_kw: float,
    max_loading_pct: float,
) -> Dict[str, Any]
```

**Purpose**: Run one Monte Carlo sample for a cluster

**Workflow**:

1. **Parameter Sampling**:
   - For each parameter in `randomness_config`:
     - Calls `sample_param()` to sample from distribution
     - Stores in `sampled_params` dictionary

2. **Parameter Application**:
   - Creates `EconomicParameters` with sampled values:
     - `discount_rate`, `electricity_price_eur_per_mwh`, `gas_price_eur_per_mwh`
     - `ef_electricity_kg_per_mwh`, `cop_default`
   - Applies `pipe_cost_multiplier` if sampled (scales all pipe costs)

3. **LCOH Calculation**:
   - Calls `compute_lcoh_dh()` (handles exceptions, sets NaN on failure)
   - Calls `compute_lcoh_hp()` (handles exceptions, sets NaN on failure)

4. **CO₂ Calculation**:
   - Calls `compute_co2_dh()` (handles exceptions, sets NaN on failure)
   - Calls `compute_co2_hp()` (handles exceptions, sets NaN on failure)

5. **Winner Determination**:
   - `dh_cheaper = (lcoh_dh < lcoh_hp) AND both finite`
   - `dh_lower_co2 = (co2_dh < co2_hp) AND both finite`

**Returns**: Dictionary with sample results

---

#### `sample_param()` ⭐ **PARAMETER SAMPLER**
```python
def sample_param(spec: Dict[str, Any], rng: np.random.Generator) -> float
```

**Purpose**: Sample a single parameter from a distribution specification

**Supported Distributions**:

1. **Normal**: `{'dist': 'normal', 'mean': float, 'std': float, 'clip': [min, max]}`
2. **Lognormal**: `{'dist': 'lognormal', 'mean': float, 'std': float, 'clip': [min, max]}`
   - Approximates: `mu = log(mean)`, `sigma = std / mean`
3. **Triangular**: `{'dist': 'triangular', 'low': float, 'mode': float, 'high': float}`
4. **Uniform**: `{'dist': 'uniform', 'low': float, 'high': float}`

**Clipping**: If `clip` specified, clamps value to `[min, max]`

**Returns**: Sampled parameter value

---

#### `_extract_mc_inputs_from_kpis()` ⭐ **INPUT EXTRACTOR**
```python
def _extract_mc_inputs_from_kpis(
    *,
    cha_kpis: Dict[str, Any],
    dha_kpis: Dict[str, Any],
    cluster_summary: Dict[str, float],
) -> Tuple[float, float, Optional[Dict[str, float]], float, float, float]
```

**Purpose**: Extract Monte Carlo inputs from CHA/DHA KPIs and cluster summary

**Returns**: `(total_length_m, pump_power_kw, pipe_dn_lengths_or_none, hp_capacity_kw, max_loading_pct, annual_heat_mwh)`

**Schema Support**:
- **Preferred**: `cha_kpis['network']`, `dha_kpis['hp_system']`, `dha_kpis['lv_grid']`
- **Fallback**: `cha_kpis['losses']` or `cha_kpis['aggregate']`, `cha_kpis['pump']`, `dha_kpis['kpis']`, `cluster_summary['design_load_kw']`

---

#### `compute_mc_summary()` ⭐ **MC SUMMARY CALCULATOR**
```python
def compute_mc_summary(mc_results: pd.DataFrame) -> Dict[str, Any]
```

**Purpose**: Compute summary statistics from Monte Carlo results DataFrame

**Workflow**:

1. **Validation**:
   - Validates `mc_results` is a pandas DataFrame
   - Drops NaN samples (keeps only valid samples)
   - Logs warning if `n_valid < n_total`

2. **LCOH Statistics**:
   - For each system (`dh`, `hp`):
     - Computes quantiles: `p05`, `p50` (median), `p95`
     - Computes `mean`, `std`

3. **CO₂ Statistics**:
   - For each system (`dh`, `hp`):
     - Computes quantiles: `p05`, `p50` (median), `p95`
     - Computes `mean`, `std`

4. **Win Fractions**:
   - `dh_wins_fraction = mean(dh_cheaper)` (fraction of samples where DH cheaper)
   - `hp_wins_fraction = 1 - dh_wins_fraction`
   - `dh_wins_co2_fraction = mean(dh_lower_co2)` (fraction where DH lower CO₂)
   - `hp_wins_co2_fraction = 1 - dh_wins_co2_fraction`

**Returns**: Dictionary with structure:
```python
{
    "lcoh": {
        "dh": {"p05": ..., "p50": ..., "p95": ..., "mean": ..., "std": ...},
        "hp": {"p05": ..., "p50": ..., "p95": ..., "mean": ..., "std": ...}
    },
    "co2": {
        "dh": {"p05": ..., "p50": ..., "p95": ..., "mean": ..., "std": ...},
        "hp": {"p05": ..., "p50": ..., "p95": ..., "mean": ..., "std": ...}
    },
    "monte_carlo": {
        "dh_wins_fraction": ...,
        "hp_wins_fraction": ...,
        "dh_wins_co2_fraction": ...,
        "hp_wins_co2_fraction": ...,
        "n_samples": ...,
        "n_valid": ...
    }
}
```

---

#### `run_monte_carlo()` ⭐ **LEGACY MC FUNCTION**
```python
def run_monte_carlo(
    *,
    dh_inputs: DHInputs,
    hp_inputs: HPInputs,
    base_params: EconomicsParams,
    mc: MonteCarloParams,
) -> MonteCarloResult
```

**Purpose**: Legacy Monte Carlo simulation (MVP: bounded ranges)

**Workflow**:
- Uses `MonteCarloParams` for bounded uniform sampling
- Applies multipliers via `apply_multipliers()`
- Computes LCOH and CO₂ for each sample
- Returns `MonteCarloResult` with samples and summary

**Note**: Superseded by `run_monte_carlo_for_cluster()` (supports distribution-based sampling)

---

#### `MonteCarloResult` ⭐ **MC RESULT DATACLASS**
```python
@dataclass(frozen=True)
class MonteCarloResult:
    samples: List[Dict[str, float]]
    summary: Dict[str, float]
```

**Purpose**: Monte Carlo result structure (legacy)

---

#### `_tqdm()` ⭐ **PROGRESS BAR WRAPPER**
```python
def _tqdm(iterable, **kwargs):
```

**Purpose**: Optional tqdm wrapper (tqdm may not be installed)

**Returns**: `tqdm(iterable)` if tqdm available, else `iterable`

---

**Interactions**:
- **Uses**: `params.py` (EconomicParameters), `lcoh.py` (compute_lcoh_*), `co2.py` (compute_co2_*), `utils.py` (percentile)
- **Used by**: CLI economics pipeline (`cli/economics.py`)
- **Outputs**: Monte Carlo samples DataFrame (`monte_carlo_samples.parquet`), summary dictionary (`monte_carlo_summary.json`)

---

## Complete Workflow

### Economics Pipeline

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. Load Parameters (params.py)                                    │
│    - load_default_params() or load_params_from_yaml()            │
│    - EconomicParameters: prices, CAPEX, O&M, emission factors      │
│    - MonteCarloParams: sampling ranges (optional)                 │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 2. Extract Inputs (monte_carlo.py)                              │
│    - _extract_mc_inputs_from_kpis(cha_kpis, dha_kpis, cluster_summary)│
│    - annual_heat_mwh, total_length_m, pump_power_kw, etc.        │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 3. Run Monte Carlo (monte_carlo.py)                              │
│    - run_monte_carlo_for_cluster(...)                            │
│    - For each sample (N=500):                                    │
│      a) Sample parameters from distributions                     │
│      b) Compute LCOH (DH and HP) via compute_lcoh_*()            │
│      c) Compute CO₂ (DH and HP) via compute_co2_*()              │
│      d) Determine winners (dh_cheaper, dh_lower_co2)             │
│    - Parallel processing (n_jobs)                                 │
│    Output: monte_carlo_samples.parquet [N × metrics]              │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 4. Compute Summary (monte_carlo.py)                              │
│    - compute_mc_summary(mc_results)                               │
│    - Quantiles: p05, p50, p95 for LCOH and CO₂                   │
│    - Win fractions: dh_wins_fraction, hp_wins_fraction            │
│    Output: monte_carlo_summary.json                               │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 5. Use in Decision Pipeline (decision/kpi_contract.py)           │
│    - Extract LCOH/CO₂ metrics from monte_carlo_summary.json        │
│    - Build KPI contract with economics block                     │
│    - Apply decision rules (cost comparison, CO₂ tie-breaker)      │
└─────────────────────────────────────────────────────────────────┘
```

---

## File Interactions & Dependencies

### Internal Dependencies (Within Economics Module)

```
Economics Module
├─ params.py (ECONOMIC PARAMETERS)
│  ├─ Defines: EconomicParameters, MonteCarloParams
│  └─ Used by: lcoh.py, co2.py, monte_carlo.py
│
├─ utils.py (FINANCIAL UTILITIES)
│  ├─ Defines: crf(), calculate_npv(), percentile(), etc.
│  └─ Used by: lcoh.py (crf), monte_carlo.py (percentile)
│
├─ lcoh.py (LCOH CALCULATION)
│  ├─ Uses: params.py (EconomicParameters), utils.py (crf)
│  └─ Used by: monte_carlo.py (for LCOH in MC samples)
│
├─ co2.py (CO2 ANALYSIS)
│  ├─ Uses: params.py (EconomicParameters), utils.py (safe_div)
│  └─ Used by: monte_carlo.py (for CO₂ in MC samples)
│
└─ monte_carlo.py (MONTE CARLO)
   ├─ Uses: params.py, lcoh.py, co2.py, utils.py
   └─ Used by: CLI economics pipeline
```

### External Dependencies (Outside Economics Module)

```
Economics Module
  ├─ Uses:
  │  ├─ CHA KPIs: results/cha/<cluster_id>/cha_kpis.json
  │  ├─ DHA KPIs: results/dha/<cluster_id>/dha_kpis.json
  │  ├─ Cluster summary: data/processed/cluster_load_summary.parquet
  │  └─ Scenario files: scripts/scenarios/*.yaml (optional)
  │
  ├─ Called by:
  │  ├─ CLI economics pipeline: cli/economics.py
  │  └─ Decision pipeline: decision/kpi_contract.py (extracts MC summary)
  │
  └─ Outputs:
     ├─ Monte Carlo samples: results/economics/<cluster_id>/monte_carlo_samples.parquet
     └─ Monte Carlo summary: results/economics/<cluster_id>/monte_carlo_summary.json
```

---

## Key Workflows & Patterns

### 1. CRF Method Pattern (`compute_lcoh_*()`)

**Pattern**: Levelized Cost of Heat using Capital Recovery Factor

```python
# 1. Calculate CAPEX (one-time investment)
total_capex = capex_pipes + capex_pump + capex_plant

# 2. Calculate OPEX (annual operating costs)
total_opex_annual = opex_om + opex_energy

# 3. Calculate CRF (annualization factor)
crf_val = crf(discount_rate, lifetime_years)

# 4. Calculate LCOH
lcoh = (total_capex * crf_val + total_opex_annual) / annual_heat_mwh
```

**Formula**: `LCOH = (CAPEX × CRF + OPEX) / Annual_Heat`

**Benefits**:
- Standardized method (CRF is industry standard)
- Accounts for time value of money (discount rate)
- Annualizes CAPEX over lifetime

---

### 2. Monte Carlo Sampling Pattern (`run_monte_carlo_for_cluster()`)

**Pattern**: Uncertainty propagation via random sampling

```python
# 1. Generate deterministic seeds (for reproducibility)
rng = np.random.default_rng(seed)
seeds = rng.integers(low=0, high=2**31-1, size=n_samples)

# 2. For each sample
for sample_id in range(n_samples):
    # Sample parameters from distributions
    sampled_params = {}
    for param_name, spec in randomness_config.items():
        sampled_params[param_name] = sample_param(spec, rng_i)
    
    # Apply sampled parameters
    sample_params = EconomicParameters(**sampled_params)
    
    # Compute metrics
    lcoh_dh = compute_lcoh_dh(..., params=sample_params)
    lcoh_hp = compute_lcoh_hp(..., params=sample_params)
    co2_dh = compute_co2_dh(..., params=sample_params)
    co2_hp = compute_co2_hp(..., params=sample_params)
    
    # Determine winners
    dh_cheaper = (lcoh_dh < lcoh_hp)
    dh_lower_co2 = (co2_dh < co2_hp)
```

**Benefits**:
- Propagates uncertainty through calculations
- Generates probabilistic distributions (quantiles)
- Enables robustness assessment (win fractions)

---

### 3. Distribution-Based Sampling Pattern (`sample_param()`)

**Pattern**: Flexible parameter sampling from various distributions

```python
def sample_param(spec: Dict[str, Any], rng: np.random.Generator) -> float:
    dist_type = spec["dist"]
    
    if dist_type == "normal":
        value = rng.normal(loc=spec["mean"], scale=spec["std"])
    elif dist_type == "lognormal":
        mu = np.log(spec["mean"])
        sigma = spec["std"] / spec["mean"]
        value = rng.lognormal(mean=mu, sigma=sigma)
    elif dist_type == "triangular":
        value = rng.triangular(left=spec["low"], mode=spec["mode"], right=spec["high"])
    elif dist_type == "uniform":
        value = rng.uniform(low=spec["low"], high=spec["high"])
    
    # Clip if specified
    if "clip" in spec:
        value = np.clip(value, spec["clip"][0], spec["clip"][1])
    
    return value
```

**Benefits**:
- Supports multiple distribution types (normal, lognormal, triangular, uniform)
- Clipping prevents unrealistic values
- Flexible configuration (JSON/YAML)

---

### 4. Parallel Processing Pattern (`run_monte_carlo_for_cluster()`)

**Pattern**: Parallel Monte Carlo with deterministic seeds

```python
# Generate deterministic seeds (one per sample)
seeds = rng.integers(low=0, high=2**31-1, size=n_samples)

# Parallel processing
with ProcessPoolExecutor(max_workers=max_workers) as ex:
    futs = [
        ex.submit(
            _run_one_sample_for_cluster,
            sample_id=i,
            seed_i=int(seeds[i]),  # Deterministic seed per sample
            ...
        )
        for i in range(n_samples)
    ]
    for fut in as_completed(futs):
        results.append(fut.result())

# Restore ordering
results.sort(key=lambda d: d["sample_id"])
```

**Benefits**:
- Reproducible (deterministic seeds per sample)
- Scalable (parallel processing)
- Maintains sample ordering (for auditability)

---

## Usage Examples

### Complete Economics Analysis

```python
from branitz_heat_decision.economics.params import load_params_from_yaml, EconomicParameters
from branitz_heat_decision.economics.monte_carlo import run_monte_carlo_for_cluster, compute_mc_summary
import json
import pandas as pd

# 1. Load parameters
params = load_params_from_yaml("scripts/scenarios/2030_scenario.yaml")
# Or use defaults:
# params = EconomicParameters()

# 2. Load KPIs
with open("results/cha/ST010/cha_kpis.json") as f:
    cha_kpis = json.load(f)
with open("results/dha/ST010/dha_kpis.json") as f:
    dha_kpis = json.load(f)

# 3. Load cluster summary
cluster_summary = pd.read_parquet("data/processed/cluster_load_summary.parquet")
cluster_row = cluster_summary[cluster_summary["cluster_id"] == "ST010_HEINRICH_ZILLE_STRASSE"].iloc[0].to_dict()

# 4. Optional: Custom randomness config
randomness_config = {
    "discount_rate": {"dist": "normal", "mean": 0.04, "std": 0.01, "clip": [0.01, 0.08]},
    "electricity_price": {"dist": "normal", "mean": 250.0, "std": 50.0, "clip": [150, 400]},
    "gas_price": {"dist": "triangular", "low": 40, "mode": 80, "high": 140},
    "pipe_cost_multiplier": {"dist": "triangular", "low": 0.8, "mode": 1.0, "high": 1.2},
    "cop": {"dist": "normal", "mean": 2.8, "std": 0.3, "clip": [2.0, 4.0]},
    "ef_electricity": {"dist": "normal", "mean": 350.0, "std": 80.0, "clip": [200, 500]},
}

# 5. Run Monte Carlo
mc_results = run_monte_carlo_for_cluster(
    cluster_id="ST010_HEINRICH_ZILLE_STRASSE",
    cha_kpis=cha_kpis,
    dha_kpis=dha_kpis,
    cluster_summary=cluster_row,
    n_samples=500,
    randomness_config=randomness_config,
    base_params=params,
    seed=42,
    n_jobs=-1,  # Use all CPU cores
)

# 6. Save samples
mc_results.to_parquet("results/economics/ST010/monte_carlo_samples.parquet", index=False)

# 7. Compute summary
summary = compute_mc_summary(mc_results)

# 8. Save summary
with open("results/economics/ST010/monte_carlo_summary.json", "w") as f:
    json.dump(summary, f, indent=2)

print(f"DH wins: {summary['monte_carlo']['dh_wins_fraction']:.1%}")
print(f"HP wins: {summary['monte_carlo']['hp_wins_fraction']:.1%}")
```

### Direct LCOH Calculation (No Monte Carlo)

```python
from branitz_heat_decision.economics.lcoh import compute_lcoh_dh, compute_lcoh_hp
from branitz_heat_decision.economics.params import EconomicParameters

params = EconomicParameters()

# DH LCOH
lcoh_dh, breakdown_dh = compute_lcoh_dh(
    annual_heat_mwh=1000.0,
    pipe_lengths_by_dn={"DN50": 500.0, "DN100": 200.0},
    total_pipe_length_m=700.0,
    pump_power_kw=10.0,
    params=params,
)

print(f"DH LCOH: {lcoh_dh:.2f} EUR/MWh")
print(f"CAPEX: {breakdown_dh['capex_total']:.2f} EUR")
print(f"OPEX: {breakdown_dh['opex_annual']:.2f} EUR/a")

# HP LCOH
lcoh_hp, breakdown_hp = compute_lcoh_hp(
    annual_heat_mwh=1000.0,
    hp_total_capacity_kw_th=200.0,
    cop_annual_average=2.8,
    max_feeder_loading_pct=75.0,
    params=params,
)

print(f"HP LCOH: {lcoh_hp:.2f} EUR/MWh")
print(f"CAPEX: {breakdown_hp['capex_total']:.2f} EUR")
print(f"OPEX: {breakdown_hp['opex_annual']:.2f} EUR/a")
```

### CO₂ Calculation

```python
from branitz_heat_decision.economics.co2 import compute_co2_dh, compute_co2_hp
from branitz_heat_decision.economics.params import EconomicParameters

params = EconomicParameters()

# DH CO₂
co2_dh, breakdown_dh = compute_co2_dh(
    annual_heat_mwh=1000.0,
    params=params,
    generation_type="biomass",  # or "gas", "electric"
)

print(f"DH CO₂: {co2_dh:.2f} kg/MWh")
print(f"Annual CO₂: {breakdown_dh['annual_co2_kg']:.2f} kg/a")

# HP CO₂
co2_hp, breakdown_hp = compute_co2_hp(
    annual_heat_mwh=1000.0,
    cop_annual_average=2.8,
    params=params,
)

print(f"HP CO₂: {co2_hp:.2f} kg/MWh")
print(f"Annual CO₂: {breakdown_hp['annual_co2_kg']:.2f} kg/a")
```

---

## Error Handling & Validation

### Parameter Validation

#### EconomicParameters Validation (`__post_init__`)
- **Discount Rate**: Must be in `(0, 1)` (raises `ValueError` if out of range)
- **Lifetime**: Must be positive (raises `ValueError` if <= 0)
- **Generation Type**: Must be `"gas"`, `"biomass"`, or `"electric"` (raises `ValueError` if invalid)
- **Feeder Loading Limit**: Must be in `(0, 1]` (raises `ValueError` if out of range)

---

### Calculation Error Handling

#### LCOH Calculation (`compute_lcoh_*()`)
- **Annual Heat**: Must be positive (raises `ValueError` if <= 0)
- **COP**: Must be positive (raises `ValueError` if <= 0, HP only)
- **Generation Type**: Must be valid (raises `ValueError` if unknown, DH only)

#### CO₂ Calculation (`compute_co2_*()`)
- **Annual Heat**: Must be positive (raises `ValueError` if <= 0)
- **COP**: Must be positive (raises `ValueError` if <= 0, HP only)
- **Generation Type**: Must be valid (raises `ValueError` if unknown, DH only)

#### Monte Carlo (`_run_one_sample_for_cluster()`)
- **Exception Handling**: Catches exceptions in LCOH/CO₂ calculations, sets NaN on failure
- **Logging**: Logs debug messages for failed samples
- **Validation**: Validates `mc_results` is DataFrame in `compute_mc_summary()`

---

## Performance Considerations

### Monte Carlo Parallelization

- **Sequential Mode** (`n_jobs=1`): O(N) where N = number of samples
- **Parallel Mode** (`n_jobs>1`): O(N/M) where M = number of workers (with overhead)
- **Deterministic Seeds**: Each sample uses deterministic seed (reproducible in parallel)

### Memory Usage

- **Samples DataFrame**: Stores N × (metrics + parameters) rows
- **Summary Dictionary**: Compact (quantiles, win fractions only)

---

## Standards Compliance

### Financial Standards

- **CRF Method**: Standardized LCOH calculation (IEA, NREL)
- **Discount Rate**: Industry-standard range (2-8% for energy projects)
- **Lifetime**: Typical DH/HP system lifetime (20 years)

### Emission Factor Standards

- **German Grid Mix**: 350 kg CO₂/MWh (reference year 2023)
- **Gas**: 200 kg CO₂/MWh (natural gas combustion)
- **Biomass**: 25 kg CO₂/MWh (sustainable biomass, carbon-neutral)

---

## References & Standards

- **IEA**: International Energy Agency LCOH methodology
- **NREL**: National Renewable Energy Laboratory cost analysis
- **DIN EN ISO 13790**: Thermal performance of buildings
- **IPCC**: Intergovernmental Panel on Climate Change emission factors

---

**Last Updated**: 2026-01-19  
**Module Version**: v1.1  
**Primary Maintainer**: Economics Module Development Team

## Recent Updates (2026-01-19)

- **Parameter Updates**:
  - `biomass_price_eur_per_mwh`: Updated from 60.0 to **110.0 EUR/MWh**
  - `plant_cost_base_eur`: Updated from 50,000 to **1,500,000 EUR**
- **Impact**: Significantly increases DH costs (higher biomass price + much higher plant CAPEX)
