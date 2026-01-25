# Decision Module Documentation

Complete documentation for the Decision module implementing KPI contract building, decision rules, and schema validation for the Branitz Heat Decision pipeline.

**Module Location**: `src/branitz_heat_decision/decision/`  
**Total Lines of Code**: ~896 lines  
**Primary Language**: Python 3.9+  
**Dependencies**: dataclasses, typing, json, logging, subprocess, datetime, pathlib

---

## Module Overview

The Decision module provides the core decision-making logic for the Branitz Heat Decision pipeline:

1. **KPI Contract Builder** (`kpi_contract.py`): Builds canonical KPI contracts from CHA/DHA/economics outputs
2. **Decision Rules Engine** (`rules.py`): Applies deterministic decision rules to choose between DH/HP/UNDECIDED
3. **Schema Definitions** (`schemas.py`): Defines canonical KPI contract schema and reason codes

### Architecture

The Decision module follows a modular architecture with clear separation of concerns:

```
Decision Module
├─ schemas.py → Schema Definitions & Validation
├─ kpi_contract.py → KPI Contract Builder
└─ rules.py → Decision Rules Engine
```

---

## Module Files & Functions

### `__init__.py` (Empty)
**Purpose**: Module initialization (currently empty)  
**Usage**: Python package marker

---

### `schemas.py` (240 lines) ⭐ **SCHEMA DEFINITIONS**
**Purpose**: Defines canonical KPI contract schema, reason codes, and validation logic

**Main Components**:

#### `REASON_CODES` ⭐ **REASON CODE DICTIONARY**
```python
REASON_CODES: Dict[str, str]
```

**Purpose**: Complete taxonomy of reason codes used in decision-making

**Categories**:

1. **Feasibility Codes**:
   - `DH_OK`: District heating meets all EN 13941-1 constraints
   - `DH_VELOCITY_VIOLATION`: DH velocity exceeds 1.5 m/s limit
   - `DH_DP_VIOLATION`: DH pressure drop per 100m exceeds envelope
   - `DH_HARD_VIOLATION`: DH has hard constraint violations (e.g., negative pressures)
   - `DH_HIGH_LOSSES_WARNING`: DH thermal losses exceed 5% threshold
   - `HP_OK`: Heat pumps meet all VDE-AR-N 4100 LV grid constraints
   - `HP_UNDERVOLTAGE`: HP rollout causes voltage < 0.95 pu
   - `HP_OVERCURRENT_OR_OVERLOAD`: HP rollout causes line loading > 100%
   - `HP_PLANNING_WARNING_80PCT`: HP rollout exceeds 80% planning headroom

2. **Decision Logic Codes**:
   - `ONLY_DH_FEASIBLE`: Only district heating is technically feasible
   - `ONLY_HP_FEASIBLE`: Only heat pumps are technically feasible
   - `NONE_FEASIBLE`: Neither option meets technical constraints
   - `COST_DOMINANT_DH`: DH LCOH is >5% lower than HP (clear economic winner)
   - `COST_DOMINANT_HP`: HP LCOH is >5% lower than DH (clear economic winner)
   - `COST_CLOSE_USE_CO2`: LCOH difference ≤5% → using CO₂ as tie-breaker
   - `CO2_TIEBREAKER_DH`: DH chosen due to lower CO₂ emissions (costs close)
   - `CO2_TIEBREAKER_HP`: HP chosen due to lower CO₂ emissions (costs close)

3. **Robustness Codes**:
   - `ROBUST_DECISION`: Monte Carlo win fraction ≥70% → decision stable
   - `SENSITIVE_DECISION`: Monte Carlo win fraction 55-70% → decision sensitive

4. **Data Quality Codes**:
   - `CHA_MISSING_KPIS`: Missing critical CHA KPIs (cannot assess DH feasibility)
   - `DHA_MISSING_KPIS`: Missing critical DHA KPIs (cannot assess HP feasibility)
   - `MC_MISSING`: Monte Carlo data missing → robustness cannot be assessed
   - `CHA_DATA_INCOMPLETE`: CHA: Missing envelope or typology data
   - `DHA_SYNTHETIC_GRID_WARNING`: DHA: LV grid is synthetic/approximated
   - `ECON_DATA_ESTIMATED`: Economics: Annual heat demand estimated
   - `MC_SAMPLE_WARNING_LT100`: Monte Carlo: <100 samples

5. **Economics Edge Cases**:
   - `COST_RATIO_EXTREME_GT3X`: LCOH ratio >3x between options
   - `CO2_NEGATIVE_HP`: HP emissions negative (grid factor <0)
   - `LCOH_EQUALITY`: LCOH tie (costs identical)

6. **Technical Warnings**:
   - `DH_OVERSIZED_MINOR`: DH network slightly oversized (v_avg <0.3 m/s)
   - `HP_LOADING_MARGINAL_80_85`: HP max feeder loading 80-85%

7. **Export/Map Issues**:
   - `CHOROPLETH_MISSING`: Interactive map missing

**Total**: 30+ reason codes covering all decision paths and edge cases

---

#### `LCOHMetrics` ⭐ **LCOH METRICS DATACLASS**
```python
@dataclass
class LCOHMetrics:
    median: float  # EUR/MWh
    p05: float     # 5th percentile
    p95: float     # 95th percentile
    mean: Optional[float] = None
    std: Optional[float] = None
```

**Purpose**: Levelized Cost of Heat with uncertainty quantiles (from Monte Carlo)

---

#### `CO2Metrics` ⭐ **CO2 METRICS DATACLASS**
```python
@dataclass
class CO2Metrics:
    median: float  # kg CO₂/MWh
    p05: float
    p95: float
    mean: Optional[float] = None
    std: Optional[float] = None
```

**Purpose**: CO₂ emissions with uncertainty quantiles (from Monte Carlo)

---

#### `HydraulicsKPIs` ⭐ **HYDRAULICS KPIs DATACLASS**
```python
@dataclass
class HydraulicsKPIs:
    velocity_ok: bool
    dp_ok: bool
    v_max_ms: float
    v_min_ms: float
    v_share_within_limits: float  # 0-1
    dp_per_100m_max: float
    hard_violations: List[str]
```

**Purpose**: EN 13941-1 hydraulic performance metrics

---

#### `LossesKPIs` ⭐ **LOSSES KPIs DATACLASS**
```python
@dataclass
class LossesKPIs:
    total_length_m: float
    trunk_length_m: float
    service_length_m: float
    loss_share_pct: float  # % of delivered heat
    pump_power_kw: float
```

**Purpose**: Thermal losses and pumping energy metrics

---

#### `LVGridKPIs` ⭐ **LV GRID KPIs DATACLASS**
```python
@dataclass
class LVGridKPIs:
    planning_warning: bool
    max_feeder_loading_pct: float
    voltage_violations_total: int
    line_violations_total: int
    worst_bus_id: Optional[str]
    worst_line_id: Optional[str]
```

**Purpose**: VDE-AR-N 4100 LV grid performance metrics

---

#### `DistrictHeatingBlock` ⭐ **DH BLOCK DATACLASS**
```python
@dataclass
class DistrictHeatingBlock:
    feasible: bool
    reasons: List[str]  # From REASON_CODES
    lcoh: LCOHMetrics
    co2: CO2Metrics
    hydraulics: HydraulicsKPIs
    losses: LossesKPIs
```

**Purpose**: Complete District Heating assessment block

---

#### `HeatPumpsBlock` ⭐ **HP BLOCK DATACLASS**
```python
@dataclass
class HeatPumpsBlock:
    feasible: bool
    reasons: List[str]
    lcoh: LCOHMetrics
    co2: CO2Metrics
    lv_grid: LVGridKPIs
    hp_system: Dict[str, float]
```

**Purpose**: Complete Heat Pumps assessment block

---

#### `MonteCarloBlock` ⭐ **MC BLOCK DATACLASS**
```python
@dataclass
class MonteCarloBlock:
    dh_wins_fraction: float  # 0-1
    hp_wins_fraction: float
    n_samples: int
    seed: Optional[int]
```

**Purpose**: Uncertainty propagation results (Monte Carlo win fractions)

---

#### `KPIContract` ⭐ **KPI CONTRACT DATACLASS**
```python
@dataclass
class KPIContract:
    cluster_id: str
    metadata: Dict[str, Any]  # created_utc, inputs, notes
    district_heating: DistrictHeatingBlock
    heat_pumps: HeatPumpsBlock
    monte_carlo: Optional[MonteCarloBlock]
    version: str = "1.0"
```

**Purpose**: Canonical KPI contract (root object)

---

#### `ContractValidator` ⭐ **SCHEMA VALIDATOR**
```python
class ContractValidator:
    @staticmethod
    def validate(contract: Dict[str, Any]) -> None:
        """Validate entire contract. Raises ValueError with detailed message."""
```

**Purpose**: Strict schema validation for KPI contracts

**Validation Rules**:

1. **Top-Level Keys**: Must have `version`, `cluster_id`, `metadata`, `district_heating`, `heat_pumps`
2. **Version Check**: Must be `"1.0"` (raises on unsupported versions)
3. **Metadata Validation**: Must contain `created_utc` timestamp
4. **DH Block Validation**:
   - `feasible` must be boolean
   - `reasons` must be non-empty list
   - All reason codes must exist in `REASON_CODES`
   - `lcoh` must have `median`, `p05`, `p95` (numeric)
   - `hydraulics.velocity_ok` must be boolean
   - `hydraulics.v_share_within_limits` must be 0-1
5. **HP Block Validation**:
   - `feasible` must be boolean
   - `reasons` must be non-empty list
   - `lv_grid.max_feeder_loading_pct` must be 0-1000%
   - `lv_grid.voltage_violations_total` must be int or None
6. **MC Block Validation** (optional):
   - `dh_wins_fraction` and `hp_wins_fraction` must be 0-1
   - `n_samples` must be positive integer

**Raises**: `ValueError` with detailed message on validation failure

---

**Interactions**:
- **Used by**: `kpi_contract.py` (for validation), `rules.py` (for reason code lookups), CLI scripts (for contract validation)
- **Outputs**: Schema definitions (dataclasses), reason code dictionary, validation logic

---

### `kpi_contract.py` (383 lines) ⭐ **KPI CONTRACT BUILDER**
**Purpose**: Builds canonical KPI contracts from CHA/DHA/economics outputs

**Main Functions**:

#### `build_kpi_contract()` ⭐ **PRIMARY CONTRACT BUILDER**
```python
def build_kpi_contract(
    cluster_id: str,
    cha_kpis: Dict[str, Any],
    dha_kpis: Dict[str, Any],
    econ_summary: Dict[str, Any],
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]
```

**Purpose**: Build canonical KPI contract from CHA, DHA, and Economics outputs

**Workflow**:

1. **Metadata Normalization**:
   - Uses provided metadata or creates minimal metadata
   - Adds `created_utc` timestamp (UTC ISO Z format)
   - Records git commit hash (best-effort via `_get_git_commit_hash()`)

2. **Block Building**:
   - **DH Block**: `_build_dh_block()` (CHA KPIs + economics)
   - **HP Block**: `_build_hp_block()` (DHA KPIs + economics)
   - **MC Block**: `_build_mc_block()` (Monte Carlo summary)

3. **Contract Assembly**:
   - Assembles contract dictionary with `version`, `cluster_id`, `metadata`, `district_heating`, `heat_pumps`, `monte_carlo`

4. **Validation**:
   - Validates contract schema via `ContractValidator.validate()`
   - Raises `ValueError` if validation fails

**Returns**: Validated KPI contract dictionary

**Helper Functions**:

#### `_build_dh_block()` ⭐ **DH BLOCK BUILDER**
```python
def _build_dh_block(cluster_id: str, cha_kpis: Dict[str, Any], econ_summary: Dict[str, Any]) -> Dict[str, Any]
```

**Purpose**: Build DistrictHeatingBlock with fallback logic

**Workflow**:

1. **Feasibility Inference**:
   - Extracts `feasible` from `en13941_compliance.feasible` or `_infer_dh_feasibility()`
   - **Fallback**: Checks `v_share_within_limits >= 0.95` (defaults to `False` if missing)

2. **Reason Code Inference**:
   - Extracts `reasons` from `en13941_compliance.reasons` or `_infer_dh_reasons()`
   - **Fallback**: Infers from feasibility and violation flags

3. **LCOH/CO₂ Extraction**:
   - Extracts LCOH metrics via `_extract_lcoh_metrics()` (Monte Carlo quantiles)
   - Extracts CO₂ metrics via `_extract_co2_metrics()` (Monte Carlo quantiles)

4. **Hydraulics KPIs**:
   - `velocity_ok`: From `hydraulics.velocity_ok` or `v_share_within_limits >= 0.95`
   - `dp_ok`: From `hydraulics.dp_ok` or `dp_max_bar_per_100m < 0.3`
   - Velocity/pressure metrics with fallbacks

5. **Losses KPIs**:
   - Lengths: `total_length_m`, `trunk_length_m`, `service_length_m`
   - `loss_share_pct`: Percentage of delivered heat lost
   - `pump_power_kw`: Pump power consumption

**Returns**: DistrictHeatingBlock dictionary

---

#### `_build_hp_block()` ⭐ **HP BLOCK BUILDER**
```python
def _build_hp_block(cluster_id: str, dha_kpis: Dict[str, Any], econ_summary: Dict[str, Any]) -> Dict[str, Any]
```

**Purpose**: Build HeatPumpsBlock with fallback logic

**Workflow**:

1. **Feasibility Inference**:
   - Extracts `feasible` from `kpis.feasible` or `_infer_hp_feasibility()`
   - **Fallback**: Checks `voltage_violations_total == 0 AND line_violations_total == 0` (defaults to `False` if missing)

2. **Reason Code Inference**:
   - Extracts `reasons` from `kpis.reasons` or `_infer_hp_reasons()`
   - **Fallback**: Infers from feasibility and violation counts

3. **LCOH/CO₂ Extraction**:
   - Extracts LCOH metrics via `_extract_lcoh_metrics()` (Monte Carlo quantiles)
   - Extracts CO₂ metrics via `_extract_co2_metrics()` (Monte Carlo quantiles)

4. **LV Grid KPIs**:
   - `planning_warning`: From `planning_warnings_total > 0` or `planning_warning`
   - `max_feeder_loading_pct`: Maximum feeder loading percentage
   - `voltage_violations_total`: Count of voltage violations
   - `line_violations_total`: Count of line overload violations
   - `worst_bus_id`, `worst_line_id`: Worst-performing elements

5. **HP System KPIs**:
   - `hp_total_kw_design`: Peak HP power at design hour
   - `hp_total_kw_topn_max`: Peak HP power across top-N hours

**Returns**: HeatPumpsBlock dictionary

---

#### `_build_mc_block()` ⭐ **MC BLOCK BUILDER**
```python
def _build_mc_block(econ_summary: Dict[str, Any]) -> Optional[Dict[str, Any]]
```

**Purpose**: Build MonteCarloBlock if data available

**Extracts**:
- `dh_wins_fraction`: Fraction of MC samples where DH wins (cost)
- `hp_wins_fraction`: Fraction of MC samples where HP wins (cost)
- `n_samples`: Number of Monte Carlo samples
- `seed`: Random seed (from metadata)

**Returns**: MonteCarloBlock dictionary, or `None` if Monte Carlo data missing

---

#### `_infer_dh_feasibility()` ⭐ **DH FEASIBILITY INFERENCE**
```python
def _infer_dh_feasibility(cha_kpis: Dict[str, Any]) -> bool
```

**Purpose**: Infer DH feasibility from available metrics

**Logic**:
1. If `feasible` flag exists → use it
2. Else if `v_share_within_limits` exists → `v_share >= 0.95`
3. Else → `False` (safe default)

---

#### `_infer_hp_feasibility()` ⭐ **HP FEASIBILITY INFERENCE**
```python
def _infer_hp_feasibility(dha_kpis: Dict[str, Any]) -> bool
```

**Purpose**: Infer HP feasibility from violation counts

**Logic**:
1. If `feasible` flag exists → use it
2. Else if `voltage_violations_total` and `line_violations_total` exist → `(volt_viol == 0 AND line_viol == 0)`
3. Else → `False` (safe default)

**Note**: `None` means missing data, not zero violations

---

#### `_infer_dh_reasons()` ⭐ **DH REASON INFERENCE**
```python
def _infer_dh_reasons(cha_kpis: Dict[str, Any], feasible: bool) -> List[str]
```

**Purpose**: Infer reason codes for DH

**Logic**:
- If `data_quality == "incomplete"` → add `CHA_DATA_INCOMPLETE`
- If `feasible`:
  - Add `DH_OK`
- Else:
  - If `v_share_within_limits < 0.95` → add `DH_VELOCITY_VIOLATION`
  - If `dp_max_bar_per_100m >= 0.3` → add `DH_DP_VIOLATION`
  - If `hard_violations` exist → add `DH_HARD_VIOLATION`
- If no reasons → add `CHA_MISSING_KPIS`

---

#### `_infer_hp_reasons()` ⭐ **HP REASON INFERENCE**
```python
def _infer_hp_reasons(dha_kpis: Dict[str, Any], feasible: bool) -> List[str]
```

**Purpose**: Infer reason codes for HP

**Logic**:
- If `grid_source == "synthetic"` → add `DHA_SYNTHETIC_GRID_WARNING`
- If `feasible`:
  - Add `HP_OK`
  - If `planning_warning` → add `HP_PLANNING_WARNING_80PCT`
  - If `80 <= max_feeder_loading_pct <= 85` → add `HP_LOADING_MARGINAL_80_85`
- Else:
  - If `voltage_violations_total > 0` → add `HP_UNDERVOLTAGE`
  - If `line_violations_total > 0` → add `HP_OVERCURRENT_OR_OVERLOAD`
- If no reasons → add `DHA_MISSING_KPIS`

---

#### `_extract_lcoh_metrics()` ⭐ **LCOH EXTRACTION**
```python
def _extract_lcoh_metrics(econ_summary: Dict[str, Any], system: str) -> Dict[str, Any]
```

**Purpose**: Extract LCOH metrics from economics summary

**Priority**:
1. **Monte Carlo Quantiles**: `econ_summary['lcoh'][system]` with `p50`/`p05`/`p95`/`mean`/`std`
2. **Fallback**: Single values `lcoh_dh_eur_per_mwh` or `lcoh_hp_eur_per_mwh`

**Returns**: `LCOHMetrics` dictionary (`median`, `p05`, `p95`, `mean`, `std`)

---

#### `_extract_co2_metrics()` ⭐ **CO2 EXTRACTION**
```python
def _extract_co2_metrics(econ_summary: Dict[str, Any], system: str) -> Dict[str, Any]
```

**Purpose**: Extract CO₂ metrics from economics summary

**Priority**:
1. **Monte Carlo Quantiles**: `econ_summary['co2'][system]` with `p50`/`p05`/`p95`/`mean`/`std`
2. **Fallback**: Single values `co2_dh_kg_per_mwh` or `co2_hp_kg_per_mwh`

**Returns**: `CO2Metrics` dictionary (`median`, `p05`, `p95`, `mean`, `std`)

---

#### `_get()` ⭐ **DOT-PATH GETTER**
```python
def _get(d: Dict[str, Any], path: str, default: Any = None) -> Any
```

**Purpose**: Dot-path getter for nested dicts (e.g., `"en13941_compliance.feasible"`)

**Returns**: Value at path, or `default` if path doesn't exist

---

#### `_get_git_commit_hash()` ⭐ **GIT COMMIT HASH**
```python
def _get_git_commit_hash() -> str
```

**Purpose**: Best-effort git commit hash for auditability

**Returns**: Git commit hash (short), or `"unknown"` if git unavailable or not a git repo

---

#### `_utc_now_iso_z()` ⭐ **UTC TIMESTAMP**
```python
def _utc_now_iso_z() -> str
```

**Purpose**: Generate UTC timestamp in ISO Z format

**Returns**: `"2026-01-16T12:00:00Z"` format string

---

**Interactions**:
- **Uses**: CHA KPIs (`cha_kpis.json`), DHA KPIs (`dha_kpis.json`), Economics summary (`monte_carlo_summary.json`)
- **Used by**: CLI decision pipeline (`cli/decision.py`), UHDC orchestrator (`uhdc/orchestrator.py`)
- **Outputs**: Validated KPI contract dictionary (saved as `kpi_contract_<cluster_id>.json`)

---

### `rules.py` (277 lines) ⭐ **DECISION RULES ENGINE**
**Purpose**: Applies deterministic decision rules to choose between DH/HP/UNDECIDED

**Main Functions**:

#### `decide_from_contract()` ⭐ **PRIMARY DECISION FUNCTION**
```python
def decide_from_contract(
    contract: Dict[str, Any],
    config: Optional[Dict[str, Any]] = None,
) -> DecisionResult
```

**Purpose**: Make deterministic decision from KPI contract

**Decision Logic** (in order):

1. **Feasibility Gate**:
   - If only DH feasible → choose `"DH"`, reason `"ONLY_DH_FEASIBLE"`
   - If only HP feasible → choose `"HP"`, reason `"ONLY_HP_FEASIBLE"`
   - If neither feasible → choose `"UNDECIDED"`, reason `"NONE_FEASIBLE"`
   - If both feasible → proceed to cost comparison

2. **Cost Comparison**:
   - Calculate relative difference: `rel_diff = abs(lcoh_dh - lcoh_hp) / min(lcoh_dh, lcoh_hp)`
   - Calculate absolute difference: `abs_diff = abs(lcoh_dh - lcoh_hp)`
   - **If costs are close** (`rel_diff <= 5%` OR `abs_diff <= 5 EUR/MWh`):
     - Proceed to CO₂ tie-breaker
   - **Else** (costs not close):
     - Choose cheaper option (`"DH"` or `"HP"`)
     - Reason: `"COST_DOMINANT_DH"` or `"COST_DOMINANT_HP"`

3. **CO₂ Tie-Breaker** (if costs close):
   - Choose option with lower CO₂ emissions
   - Reason: `"COST_CLOSE_USE_CO2"` + `"CO2_TIEBREAKER_DH"` or `"CO2_TIEBREAKER_HP"`
   - If CO₂ equal → default to `"DH"` for determinism

4. **Robustness Check**:
   - If Monte Carlo data available:
     - Check win fraction for chosen option
     - If `win_fraction >= 70%` → `robust = True`, reason `"ROBUST_DECISION"`
     - Else if `win_fraction >= 55%` → `robust = False`, reason `"SENSITIVE_DECISION"`
   - Else → `robust = False`, reason `"MC_MISSING"`

**Returns**: `DecisionResult` with `choice`, `robust`, `reason_codes`, `metrics_used`

---

#### `DecisionResult` ⭐ **DECISION RESULT DATACLASS**
```python
@dataclass
class DecisionResult:
    choice: str                # "DH", "HP", or "UNDECIDED"
    robust: bool
    reason_codes: List[str]
    metrics_used: Dict[str, float]
    
    def to_dict(self) -> Dict[str, Any]:
        return {...}
```

**Purpose**: Structured decision output

**Fields**:
- `choice`: Decision (`"DH"`, `"HP"`, or `"UNDECIDED"`)
- `robust`: Whether decision is robust (Monte Carlo win fraction ≥70%)
- `reason_codes`: List of reason codes explaining the decision
- `metrics_used`: Dictionary of metrics used (LCOH, CO₂, MC win fractions)

---

#### `validate_config()` ⭐ **CONFIG VALIDATOR**
```python
def validate_config(config: Dict[str, Any]) -> Dict[str, Any]
```

**Purpose**: Validate decision configuration parameters and fill defaults

**Configuration Parameters**:
- `close_cost_rel_threshold`: Relative cost difference threshold (default: 0.05 = 5%)
- `close_cost_abs_threshold`: Absolute cost difference threshold (default: 5.0 EUR/MWh)
- `robust_win_fraction`: Win fraction threshold for robust decision (default: 0.70 = 70%)
- `sensitive_win_fraction`: Win fraction threshold for sensitive decision (default: 0.55 = 55%)

**Validation Rules**:
- `robust_win_fraction` must be in `(0, 1]`
- `sensitive_win_fraction` must be in `(0, robust_win_fraction)`
- `close_cost_rel_threshold` must be in `[0, 1]`
- `close_cost_abs_threshold` must be positive

**Raises**: `TypeError` if config is not a dict, `ValueError` if parameters invalid

**Returns**: Validated config dictionary with defaults filled

---

#### `decide_cluster()` ⭐ **LEGACY WRAPPER**
```python
def decide_cluster(
    contract: Dict[str, Any],
    strategy: str = "cost_first",
) -> Dict[str, Any]
```

**Purpose**: Legacy interface (kept for backward compatibility)

**Strategy Parameter**: Ignored (all decisions use cost-first with CO₂ tie-breaker)

**Returns**: Legacy format dictionary:
- `decision`: `"district_heating"`, `"heat_pumps"`, or `"infeasible"`
- `rationale`: List of reason codes
- `confidence`: `"high"`, `"medium"`, or `"low"`
- `metrics_used`: Dictionary of metrics

---

#### `DEFAULT_DECISION_CONFIG` ⭐ **DEFAULT CONFIG**
```python
DEFAULT_DECISION_CONFIG = {
    'close_cost_rel_threshold': 0.05,  # 5% relative difference
    'close_cost_abs_threshold': 5.0,   # 5 EUR/MWh absolute difference
    'robust_win_fraction': 0.70,       # ≥70% MC wins → robust
    'sensitive_win_fraction': 0.55,    # ≥55% MC wins → sensitive
}
```

**Purpose**: Default decision configuration thresholds

---

**Interactions**:
- **Uses**: KPI contract (from `kpi_contract.py`), decision config (optional, from `config/decision_config_*.json`)
- **Used by**: CLI decision pipeline (`cli/decision.py`), UHDC orchestrator (`uhdc/orchestrator.py`)
- **Outputs**: `DecisionResult` (saved as `decision_<cluster_id>.json`)

---

## Complete Workflow

### Decision Pipeline

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. Load KPIs (CLI)                                               │
│    - Load CHA KPIs: results/cha/<cluster_id>/cha_kpis.json      │
│    - Load DHA KPIs: results/dha/<cluster_id>/dha_kpis.json      │
│    - Load Economics: results/economics/<cluster_id>/monte_carlo_summary.json│
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 2. Build KPI Contract (kpi_contract.py)                         │
│    - build_kpi_contract(cluster_id, cha_kpis, dha_kpis, econ_summary)│
│    - Build DH block: _build_dh_block()                           │
│    - Build HP block: _build_hp_block()                           │
│    - Build MC block: _build_mc_block()                           │
│    - Add metadata (created_utc, git_commit)                      │
│    - Validate schema: ContractValidator.validate()               │
│    Output: Validated KPI contract                                │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 3. Apply Decision Rules (rules.py)                               │
│    - decide_from_contract(contract, config)                      │
│    - Step 1: Feasibility gate (ONLY_DH_FEASIBLE, ONLY_HP_FEASIBLE, etc.)│
│    - Step 2: Cost comparison (COST_DOMINANT_DH/HP, COST_CLOSE_USE_CO2)│
│    - Step 3: CO₂ tie-breaker (CO2_TIEBREAKER_DH/HP)             │
│    - Step 4: Robustness check (ROBUST_DECISION, SENSITIVE_DECISION)│
│    Output: DecisionResult (choice, robust, reason_codes)         │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 4. Save Outputs (CLI)                                            │
│    - Save contract: kpi_contract_<cluster_id>.json               │
│    - Save decision: decision_<cluster_id>.json                   │
│    - Generate explanation: explanation_<cluster_id>.md/html      │
│    Output: results/decision/<cluster_id>/                        │
└─────────────────────────────────────────────────────────────────┘
```

---

## File Interactions & Dependencies

### Internal Dependencies (Within Decision Module)

```
Decision Module
├─ schemas.py (SCHEMA DEFINITIONS)
│  ├─ Defines: REASON_CODES, KPIContract, DistrictHeatingBlock, HeatPumpsBlock, etc.
│  └─ Used by: kpi_contract.py (validation), rules.py (reason code lookups)
│
├─ kpi_contract.py (KPI CONTRACT BUILDER)
│  ├─ Uses: schemas.py (ContractValidator, REASON_CODES)
│  └─ Used by: rules.py (for contract input), CLI decision pipeline
│
└─ rules.py (DECISION RULES ENGINE)
   ├─ Uses: schemas.py (REASON_CODES), kpi_contract.py (contract structure)
   └─ Used by: CLI decision pipeline, UHDC orchestrator
```

### External Dependencies (Outside Decision Module)

```
Decision Module
  ├─ Uses:
  │  ├─ CHA KPIs: results/cha/<cluster_id>/cha_kpis.json
  │  ├─ DHA KPIs: results/dha/<cluster_id>/dha_kpis.json
  │  ├─ Economics summary: results/economics/<cluster_id>/monte_carlo_summary.json
  │  └─ Decision config: config/decision_config_*.json (optional)
  │
  ├─ Called by:
  │  ├─ CLI decision pipeline: cli/decision.py
  │  └─ UHDC orchestrator: uhdc/orchestrator.py
  │
  └─ Outputs:
     ├─ KPI contract: results/decision/<cluster_id>/kpi_contract_<cluster_id>.json
     └─ Decision result: results/decision/<cluster_id>/decision_<cluster_id>.json
```

---

## Key Workflows & Patterns

### 1. Dot-Path Getter Pattern (`_get()`)

**Pattern**: Safe nested dictionary access with fallback

```python
def _get(d: Dict[str, Any], path: str, default: Any = None) -> Any:
    """Dot-path getter for nested dicts."""
    cur = d
    try:
        for k in path.split("."):
            if isinstance(cur, dict) and k in cur:
                cur = cur[k]
            else:
                return default
        return cur
    except Exception:
        return default
```

**Usage**:
```python
# Safe access: contract["district_heating"]["hydraulics"]["velocity_ok"]
velocity_ok = _get(contract, "district_heating.hydraulics.velocity_ok", False)
```

**Benefits**:
- Prevents `KeyError` exceptions
- Supports fallback values
- Handles missing nested keys gracefully

---

### 2. Feasibility Inference Pattern (`_infer_dh_feasibility()`, `_infer_hp_feasibility()`)

**Pattern**: Multi-tier feasibility inference with safe defaults

```python
def _infer_dh_feasibility(cha_kpis: Dict[str, Any]) -> bool:
    # Priority 1: Explicit flag
    if 'feasible' in cha_kpis:
        return bool(cha_kpis['feasible'])
    
    # Priority 2: Infer from metrics
    v_share = _get(cha_kpis, "aggregate.v_share_within_limits")
    if v_share is not None:
        return float(v_share) >= 0.95
    
    # Priority 3: Safe default (assume not feasible)
    return False
```

**Benefits**:
- Handles missing data gracefully
- Safe defaults (assume not feasible)
- Supports explicit flags and metric inference

---

### 3. Decision Logic Pattern (`decide_from_contract()`)

**Pattern**: Hierarchical decision-making with clear precedence

```python
# Step 1: Feasibility gate
if dh['feasible'] and not hp['feasible']:
    choice = "DH"
    reasons.append("ONLY_DH_FEASIBLE")

# Step 2: Cost comparison
elif dh['feasible'] and hp['feasible']:
    if not is_close:
        choice = "DH" if lcoh_dh < lcoh_hp else "HP"
    else:
        # Step 3: CO₂ tie-breaker
        choice = "DH" if co2_dh <= co2_hp else "HP"
        reasons.append("COST_CLOSE_USE_CO2")

# Step 4: Robustness check
if choice == "DH" and mc.get('dh_wins_fraction') >= 0.70:
    robust = True
    reasons.append("ROBUST_DECISION")
```

**Benefits**:
- Clear decision precedence (feasibility → cost → CO₂ → robustness)
- Transparent reason codes (auditable decision path)
- Deterministic logic (same inputs → same output)

---

### 4. Config Validation Pattern (`validate_config()`)

**Pattern**: Validate and fill defaults for configuration

```python
def validate_config(config: Dict[str, Any]) -> Dict[str, Any]:
    validated = {}
    
    # Validate and set default
    robust = config.get('robust_win_fraction', DEFAULT_DECISION_CONFIG['robust_win_fraction'])
    if not (0 < robust <= 1.0):
        raise ValueError(f"robust_win_fraction must be in (0, 1], got {robust}")
    validated['robust_win_fraction'] = float(robust)
    
    # ... validate other parameters
    
    return validated
```

**Benefits**:
- Type validation (catches errors early)
- Range validation (ensures reasonable values)
- Default filling (backward compatible)

---

## Usage Examples

### Build KPI Contract

```python
from branitz_heat_decision.decision.kpi_contract import build_kpi_contract
from branitz_heat_decision.decision.schemas import ContractValidator
import json

# Load KPIs
with open("results/cha/ST010/cha_kpis.json") as f:
    cha_kpis = json.load(f)
with open("results/dha/ST010/dha_kpis.json") as f:
    dha_kpis = json.load(f)
with open("results/economics/ST010/monte_carlo_summary.json") as f:
    econ_summary = json.load(f)

# Build contract
metadata = {
    "created_utc": "2026-01-16T12:00:00Z",
    "inputs": {
        "cha_kpis_path": "results/cha/ST010/cha_kpis.json",
        "dha_kpis_path": "results/dha/ST010/dha_kpis.json",
        "econ_summary_path": "results/economics/ST010/monte_carlo_summary.json",
    },
    "notes": [],
}

contract = build_kpi_contract(
    cluster_id="ST010_HEINRICH_ZILLE_STRASSE",
    cha_kpis=cha_kpis,
    dha_kpis=dha_kpis,
    econ_summary=econ_summary,
    metadata=metadata,
)

# Validate
ContractValidator.validate(contract)

# Save
with open("results/decision/ST010/kpi_contract_ST010.json", "w") as f:
    json.dump(contract, f, indent=2)
```

### Apply Decision Rules

```python
from branitz_heat_decision.decision.rules import decide_from_contract, validate_config

# Load contract
with open("results/decision/ST010/kpi_contract_ST010.json") as f:
    contract = json.load(f)

# Optional: Custom config
config = {
    "close_cost_rel_threshold": 0.10,  # 10% threshold
    "robust_win_fraction": 0.75,       # 75% threshold
}
config = validate_config(config)

# Apply decision rules
result = decide_from_contract(contract, config=config)

# Access results
print(f"Choice: {result.choice}")
print(f"Robust: {result.robust}")
print(f"Reasons: {result.reason_codes}")
print(f"Metrics: {result.metrics_used}")

# Save
with open("results/decision/ST010/decision_ST010.json", "w") as f:
    json.dump(result.to_dict(), f, indent=2)
```

### Use Default Config

```python
from branitz_heat_decision.decision.rules import decide_from_contract, DEFAULT_DECISION_CONFIG

# Use defaults
result = decide_from_contract(contract, config=None)

# Or explicitly use defaults
result = decide_from_contract(contract, config=DEFAULT_DECISION_CONFIG)
```

---

## Error Handling & Validation

### Contract Validation

#### Schema Validation (`ContractValidator.validate()`)
- **Top-Level Keys**: Raises `ValueError` if required keys missing
- **Version Check**: Raises `ValueError` if unsupported version
- **Type Validation**: Raises `ValueError` if types don't match schema
- **Range Validation**: Raises `ValueError` if values out of range (e.g., `v_share_within_limits` not 0-1)

#### Missing Data Handling (`_infer_*()` functions)
- **Graceful Degradation**: Infers feasibility/reasons from available metrics
- **Safe Defaults**: Assumes not feasible if data missing
- **Warning Logs**: Logs warnings when inference is used

---

### Config Validation

#### Parameter Validation (`validate_config()`)
- **Type Check**: Raises `TypeError` if config is not a dict
- **Range Check**: Raises `ValueError` if parameters out of valid range
- **Default Filling**: Fills missing parameters with defaults

---

## Standards Compliance

### EN 13941-1 Compliance (District Heating)

- **Velocity Limits**: `v_max <= 1.5 m/s` (design), `v_abs_max <= 2.5 m/s` (hard cap)
- **Pressure Drop**: `dp_per_100m <= 0.3 bar` (recommended)
- **Thermal Losses**: `loss_share_pct <= 5%` (planning threshold)

### VDE-AR-N 4100 Compliance (Heat Pumps / LV Grid)

- **Voltage Limits**: `0.95 pu <= V <= 1.05 pu` (operational range)
- **Line Loading**: `loading_pct <= 100%` (operational limit)
- **Planning Warning**: `loading_pct >= 80%` (planning headroom threshold)

---

## References & Standards

- **EN 13941-1**: District heating pipes — Design and installation
- **VDE-AR-N 4100**: Low-voltage electrical installations
- **DIN EN ISO 13790**: Thermal performance of buildings
- **IEEE 1547**: Standard for interconnecting distributed energy resources

---

**Last Updated**: 2026-01-19  
**Module Version**: v1.1

## Recent Updates (2026-01-19)

- **UI Integration**: LLM explanations now displayed in UI "Compare & Decide" tab
- **Error Handling**: Improved ZeroDivisionError handling for invalid LCOH values
- **File Discovery**: Enhanced economics summary file discovery (prioritizes `economics_monte_carlo.json`)  
**Primary Maintainer**: Decision Module Development Team
