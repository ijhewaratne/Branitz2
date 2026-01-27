# Validation Methods Implemented in Branitz Heat Decision

This document catalogues all **validation methods** implemented across the Branitz Heat Decision pipeline. Validation ensures data integrity, schema compliance, feasibility gates, and correctness of outputs at each stage.

---

## 1. Data Layer Validation

### 1.1 `DataValidationError` and Loaders

**Location**: `src/branitz_heat_decision/data/loader.py`

**Exception**:
```python
class DataValidationError(Exception):
    """Custom exception for data validation failures."""
```

**Used by**: `load_buildings_geojson`, `load_streets_geojson`, and related loaders when validation fails.

---

### 1.2 Buildings GeoJSON Validation (`load_buildings_geojson`)

**Location**: `src/branitz_heat_decision/data/loader.py`

| Check | Method | On Failure |
|-------|--------|------------|
| **File exists** | `Path(path).exists()` | `FileNotFoundError` |
| **`building_id` present** | Column exists or inferred from `id`/`gid`/`objectid`/`gebaeude` | Synthetic IDs generated; warning logged |
| **Unique `building_id`** | `gdf['building_id'].duplicated().any()` | `DataValidationError` |
| **Geometry column** | `gdf.geometry is not None` | `DataValidationError` |
| **Geometry type** | All `Polygon` or `MultiPolygon` | `DataValidationError` |
| **CRS** | Defined; if geographic, convert to EPSG:25833 | Warning + conversion |
| **Required numerics** | `floor_area_m2`, `year_of_construction`, `annual_heat_demand_kwh_a`: no NaN/inf, no negatives | `DataValidationError` |

**Metadata**: `gdf.attrs['validated_at']`, `gdf.attrs['validation_rules'] = 'phase1_buildings_v1'`.

---

### 1.3 Streets GeoJSON Validation (`load_streets_geojson`)

**Location**: `src/branitz_heat_decision/data/loader.py`

| Check | Method | On Failure |
|-------|--------|------------|
| **File exists** | `Path(path).exists()` | `FileNotFoundError` |
| **Street identifier** | `street_name` or `street_id` (or `strasse`/`street` renamed) | Synthetic `street_id`; warning |
| **Geometry type** | All `LineString` or `MultiLineString` | `DataValidationError` |
| **CRS** | Defined; **must be projected** (not geographic) | `DataValidationError` if geographic |
| **Length** | `length_m > 0` for all segments | `DataValidationError` |
| **Unique `street_id`** | Synthetic if missing | Warning |

**Metadata**: `gdf.attrs['validated_at']`, `gdf.attrs['validation_rules'] = 'phase1_streets_v1'`.

---

### 1.4 Hourly Profile Validation (`generate_hourly_profiles`)

**Location**: `src/branitz_heat_decision/data/profiles.py`

| Check | Method | On Failure |
|-------|--------|------------|
| **Weather length** | `len(weather_df) == 8760` | `ValueError` |
| **Temperature column** | `temperature_c` or `temp_C` present | `ValueError` |
| **Buildings columns** | `building_id`, `use_type` present | `ValueError` |
| **Sum vs annual demand** | `abs(annual_sum - expected) <= expected * 0.01` (1% tolerance) | `logger.warning` (no raise) |

---

## 2. CHA (Central Heating Analysis) Validation

### 2.1 Design Validation System (`DHNetworkDesignValidator`)

**Location**: `src/branitz_heat_decision/cha/design_validator.py`

**Orchestrator**: Runs four validation categories and produces a `ValidationReport`.

| Category | Validator | Result |
|----------|-----------|--------|
| **Geospatial** | `GeospatialValidator` | `GeospatialResult` |
| **Hydraulic** | `HydraulicValidator` | `HydraulicResult` |
| **Thermal** | `ThermalValidator` | `ThermalResult` |
| **Robustness** | `RobustnessValidator` | `RobustnessResult` |

**Overall**: `validation_level` ∈ `{"PASS", "PASS_WITH_WARNINGS", "FAIL"}`.  
**Outputs**: `design_validation.json`, `design_validation_summary.txt`, `design_validation_metrics.csv`.

---

### 2.2 Geospatial Validation (`GeospatialValidator`)

**Location**: `src/branitz_heat_decision/cha/geospatial_checks.py`

| Check | Method | Description |
|-------|--------|-------------|
| **Street alignment** | `_check_street_alignment(net, streets_gdf)` | Pipes follow streets / rights-of-way |
| **Building connectivity** | `_check_building_connectivity(net, buildings_gdf)` | All buildings connected to network |
| **Topology sanity** | `_check_topology_sanity(net)` | No unrealistic pipe routing |

**Result**: `GeospatialResult(passed, issues, warnings, metrics)`.

---

### 2.3 Hydraulic Validation (`HydraulicValidator`)

**Location**: `src/branitz_heat_decision/cha/hydraulic_checks.py`

**Standards**: EN 13941-1. Config from `validation_standards.ValidationConfig.en13941`.

| Check | Method | Description |
|-------|--------|-------------|
| **Convergence** | `net.converged` | Simulation must have converged |
| **Velocity** | `_check_velocities(net)` | Max velocity ≤ limit; min velocity; context-aware warnings (trunk-spur) |
| **Pressure** | `_check_pressures(net)` | Pressure drops within EN 13941-1 envelope |
| **Pump power** | `_check_pump_power(net)` | Pump within limits |
| **Flow distribution** | `_check_flow_distribution(net)` | Flow balance; context-aware warnings |

**Result**: `HydraulicResult(passed, issues, warnings, metrics)`.

---

### 2.4 Thermal Validation (`ThermalValidator`)

**Location**: `src/branitz_heat_decision/cha/thermal_checks.py`

| Check | Method | Description |
|-------|--------|-------------|
| **Heat losses** | `_check_heat_losses(net)` | Loss share, loss per 100 m |
| **Temperatures** | `_check_temperatures(net)` | Supply/return temperatures, decay |

**Result**: `ThermalResult(passed, issues, warnings, metrics)`.

---

### 2.5 Robustness Validation (`RobustnessValidator`)

**Location**: `src/branitz_heat_decision/cha/robustness_checks.py`

| Check | Method | Description |
|-------|--------|-------------|
| **Monte Carlo scenarios** | `validate(net)` | N scenarios (config) with demand/temperature/flow variation |
| **Per-scenario** | `_check_scenario_constraints(net_copy)` | Pipeflow convergence + velocity/pressure limits |

**Result**: `RobustnessResult(passed, issues, warnings, metrics, scenario_results)`.

---

### 2.6 CHA KPI Extractor Pre-Conditions (`_validate_converged`)

**Location**: `src/branitz_heat_decision/cha/kpi_extractor.py`

| Check | Method | On Failure |
|-------|--------|------------|
| **Convergence** | `net.converged is not None and net.converged` | `ValueError` |
| **Pipe results** | `net.res_pipe` exists and non-empty | `ValueError` |
| **Junction results** | `net.res_junction` exists | `ValueError` |

---

### 2.7 CHA Feasibility Gate (EN 13941-1)

**Location**: `src/branitz_heat_decision/cha/kpi_extractor.py` → `_check_en13941_compliance`

| Condition | Implementation |
|-----------|----------------|
| **`velocity_ok`** | `v_share_within_limits >= 0.95` |
| **`dp_ok`** | `dp_max_bar_per_100m <= 0.3` |
| **`feasible`** | `velocity_ok and dp_ok` |
| **Loss warning** | `loss_share_percent > 5.0` → `DH_HIGH_LOSSES_WARNING` |

**Reason codes**: `DH_OK`, `DH_VELOCITY_VIOLATION`, `DH_DP_VIOLATION`, etc.

---

### 2.8 Convergence Optimizer Validation (`_validate_all`)

**Location**: `src/branitz_heat_decision/cha/convergence_optimizer.py`

| Check | Method | Description |
|-------|--------|-------------|
| **Parallel paths** | `_check_parallel_paths()` | Score 0–1; issue if > 0.1 |
| **Loops** | `_check_loops()` | Cycle count; warning if > 0 |
| **Connectivity** | `_check_connectivity()` | All nodes reachable from plant; issue if disconnected |
| **Short pipes** | `_check_short_pipes()` | Pipes < `min_length_m`; warning |
| **Pressure consistency** | `_check_pressure_consistency()` | All junction pressures > 0 |

**Result**: `{ is_valid, issues, warnings, metrics }`. Used during `optimize_for_convergence`.

---

## 3. DHA (Decentralized Heating Analysis) Validation

### 3.1 LV Grid CRS Validation

**Location**: `src/branitz_heat_decision/dha/grid_builder.py` (`build_lv_grid_option2`)

| Check | Method | On Failure |
|-------|--------|------------|
| **Lines CRS** | `lines_gdf.crs` defined | `ValueError` |
| **Substations CRS** | `substations_gdf.crs` defined | `ValueError` |
| **CRS match** | Same CRS; else `substations_gdf.to_crs(lines_gdf.crs)` | Auto-transform |

---

### 3.2 LV Grid Boundary Validation (`_validate_boundary_option2`)

**Location**: `src/branitz_heat_decision/dha/grid_builder.py`

| Check | Method | On Failure |
|-------|--------|------------|
| **ext_grid** | Exists, exactly one | `ValueError` |
| **ext_grid at MV** | `vn_kv >= 5.0` at ext_grid bus | `ValueError` |
| **Transformers** | `net.trafo` non-empty | `ValueError` |

---

### 3.3 Unsupplied Buses Validation (`_validate_no_unsupplied_buses`)

**Location**: `src/branitz_heat_decision/dha/grid_builder.py`

| Check | Method | On Failure |
|-------|--------|------------|
| **Unsupplied buses** | `pandapower.topology.unsupplied_buses(net)` | `ValueError` if any |

Ensures no disconnected LV islands.

---

### 3.4 Building–Bus Mapping Validation

**Location**: `src/branitz_heat_decision/dha/mapping.py`, `loadflow.py`

| Check | Method | On Failure |
|-------|--------|------------|
| **Max distance** | `distance_m <= max_dist_m` (default 1000 m) | Rows with `mapped=False`, `bus_id=NaN` |
| **No unmapped when using map** | `assign_hp_loads` filters `mapped == True` | `ValueError("No buildings mapped to LV buses (all unmapped)")` |
| **Columns** | `building_id`, `bus_id` in `building_bus_map` | `ValueError` |

---

### 3.5 DHA Feasibility Gate (VDE-AR-N 4100)

**Location**: `src/branitz_heat_decision/dha/kpi_extractor.py` → `extract_dha_kpis`

| Condition | Implementation |
|-----------|----------------|
| **Voltage** | No `voltage` violations (v within [v_min_pu, v_max_pu]) |
| **Line overload** | No `line_overload` violations |
| **Trafo overload** | No `trafo_overload` violations |
| **Convergence** | No `non_convergence` |
| **`feasible`** | `feasible = (voltage_violations == 0) and (line_overloads == 0) and (trafo_overloads == 0) and (non_convergence == 0)` |

Violations collected in `violations_df`; KPIs include `feasible`, `voltage_violated_hours`, `line_overload_hours`, etc.

---

### 3.6 Loadflow Input Validation (`assign_hp_loads`)

**Location**: `src/branitz_heat_decision/dha/loadflow.py`

| Check | On Failure |
|-------|------------|
| `cop > 0` | `ValueError` |
| `hourly_heat_profiles_df` non-empty | `ValueError` |
| `building_bus_map` has `building_id`, `bus_id` | `ValueError` |
| At least one mapped building | `ValueError` |
| `pf`, `pf_base`, `pf_hp` in (0, 1] | `ValueError` |

---

## 4. Decision & KPI Contract Validation

### 4.1 KPI Contract Schema (`ContractValidator`)

**Location**: `src/branitz_heat_decision/decision/schemas.py`

**Entry point**: `ContractValidator.validate(contract)` → raises `ValueError` on failure.

| Check | Method | On Failure |
|-------|--------|------------|
| **Top-level keys** | `version`, `cluster_id`, `metadata`, `district_heating`, `heat_pumps` | `ValueError` |
| **Version** | `contract['version'] == "1.0"` | `ValueError` |
| **Metadata** | `metadata['created_utc']` present | `ValueError` |
| **DH block** | `_validate_dh_block` | `ValueError` |
| **HP block** | `_validate_hp_block` | `ValueError` |
| **MC block** | `_validate_mc_block` (if present) | `ValueError` |

**DH block**: `feasible` bool; `reasons` non-empty list; each reason in `REASON_CODES`; `lcoh`/`co2` have `median`, `p05`, `p95` numeric; `hydraulics.velocity_ok` bool; `v_share_within_limits` ∈ [0, 1].

**HP block**: `feasible` bool; `reasons` non-empty; `lv_grid.max_feeder_loading_pct` ∈ [0, 1000]; `voltage_violations_total` int or None.

**MC block**: `dh_wins_fraction`, `hp_wins_fraction` ∈ [0, 1]; `n_samples` positive int.

---

### 4.2 Decision Config Validation (`validate_config`)

**Location**: `src/branitz_heat_decision/decision/rules.py`

| Parameter | Constraint | On Failure |
|-----------|------------|------------|
| `config` | `isinstance(config, dict)` | `TypeError` |
| `robust_win_fraction` | `0 < x <= 1` | `ValueError` |
| `sensitive_win_fraction` | `0 < x < robust_win_fraction` | `ValueError` |
| `close_cost_rel_threshold` | `0 <= x <= 1` | `ValueError` |
| `close_cost_abs_threshold` | `> 0` | `ValueError` |

Returns validated config dict with defaults filled.

---

## 5. Economics Validation

### 5.1 Economic Parameters (`EconomicParameters.__post_init__`)

**Location**: `src/branitz_heat_decision/economics/params.py`

| Check | On Failure |
|-------|------------|
| `0 < discount_rate < 1` | `ValueError` |
| `lifetime_years > 0` | `ValueError` |
| `dh_generation_type` ∈ `{"gas","biomass","electric"}` | `ValueError` |
| `0 < feeder_loading_planning_limit <= 1` | `ValueError` |

---

### 5.2 LCOH / CO₂ Input Validation

**Location**: `src/branitz_heat_decision/economics/lcoh.py`, `co2.py`

| Check | On Failure |
|-------|------------|
| `annual_heat_mwh > 0` | `ValueError` |
| `cop_annual_average > 0` (HP) | `ValueError` |

---

## 6. UHDC (Explanation) Validation

### 6.1 LLM Explanation Safety (`_validate_explanation_safety`)

**Location**: `src/branitz_heat_decision/uhdc/explainer.py`

**Purpose**: Detect hallucination; ensure LLM output only cites contract-derived values.

| Check | Method | On Failure |
|-------|--------|------------|
| **Numbers in text** | Extract via regex; compare to allowed set from contract | `ValueError` |
| **Tolerance** | ±1% for metrics; standard identifiers (e.g. 13941, 4100, 95) skipped | — |
| **Choice mentioned** | Decision choice referenced in explanation | `ValueError` |

**Allowed numbers**: LCOH/CO₂ medians and quantiles, loss share, velocity, loading, violation counts, MC fractions, etc. Built from contract only.

---

## 7. ADK (Agent Development Kit) Validation

### 7.1 Agent Action Validation (`validate_agent_action`)

**Location**: `src/branitz_heat_decision/adk/policies.py`

| Check | Method | On Failure |
|-------|--------|------------|
| **Policy checks** | Each registered policy validates `(action, context)` | `(False, reason)` if blocked |
| **Exceptions** | Policy raises → validation error | `(False, "...")` |

**Returns**: `(allowed: bool, reason: Optional[str])`.

---

### 7.2 Trajectory Validation (`validate_trajectory`)

**Location**: `src/branitz_heat_decision/adk/evals.py`

| Check | Method | On Failure |
|-------|--------|------------|
| **Non-empty** | `trajectory` not empty | Issue |
| **Required phases** | `data`, `cha`, `dha`, `economics`, `decision`, `uhdc` present | Issue |
| **Phase order** | data → cha → dha → economics → decision → uhdc | Issue |
| **Action success** | No `status == "error"` | Issue |

**Returns**: `(valid: bool, issues: List[str])`.

---

### 7.3 Artifact Validation (`validate_artifacts`)

**Location**: `src/branitz_heat_decision/adk/evals.py`

| Check | Method | On Failure |
|-------|--------|------------|
| **Phase dirs** | Expected result dirs exist per phase | Issue |
| **KPI contract** | `ContractValidator.validate(contract)` on `kpi_contract_{id}.json` | Issue |

**Returns**: `(all_valid: bool, issues_by_phase: Dict[str, List[str]])`.

---

## 8. TNLI / Logic Auditor Validation

**Location**: `src/branitz_heat_decision/validation/logic_auditor.py`, `claims.py`, `tnli_model.py`

| Method | Purpose |
|--------|---------|
| **`validate_rationale`** | Validate natural-language rationale against KPI table; optional feedback/regeneration |
| **`_validate_once`** | Parse rationale into statements; batch-validate via TNLI model |
| **`validate_structured_claims`** | Validate structured claims (e.g. from LLM) against KPIs |
| **`validate_decision_explanation`** | Validate full decision explanation |
| **`ClaimValidator.validate_claim`** | Validate a single claim against KPI dict |
| **`TNLIModel.validate_statement`** | Rule-based or LLM-based statement vs table validation |

**Output**: `ValidationReport` with contradictions, warnings, verified/unverified counts.

---

## 9. Summary Table

| Layer | Validation | Location | Output / Exception |
|-------|------------|----------|--------------------|
| **Data** | Buildings GeoJSON | `data/loader.py` | `DataValidationError` |
| **Data** | Streets GeoJSON | `data/loader.py` | `DataValidationError` |
| **Data** | Hourly profiles | `data/profiles.py` | `ValueError` / warnings |
| **CHA** | Design (geo, hydraulic, thermal, robustness) | `cha/design_validator.py` | `ValidationReport` |
| **CHA** | KPI preconditions | `cha/kpi_extractor.py` | `ValueError` |
| **CHA** | Convergence optimizer | `cha/convergence_optimizer.py` | `_validate_all` dict |
| **DHA** | CRS, boundary, unsupplied buses | `dha/grid_builder.py` | `ValueError` |
| **DHA** | Building–bus mapping, loadflow inputs | `dha/mapping.py`, `loadflow.py` | `ValueError` |
| **DHA** | Feasibility (VDE-AR-N 4100) | `dha/kpi_extractor.py` | `feasible` + violations |
| **Decision** | KPI contract schema | `decision/schemas.py` | `ValueError` |
| **Decision** | Config | `decision/rules.py` | `TypeError` / `ValueError` |
| **Economics** | Parameters, LCOH/CO₂ inputs | `economics/params.py`, `lcoh.py`, `co2.py` | `ValueError` |
| **UHDC** | Explanation safety | `uhdc/explainer.py` | `ValueError` |
| **ADK** | Agent action, trajectory, artifacts | `adk/policies.py`, `evals.py` | `(bool, issues)` |
| **Validation** | TNLI / Logic Auditor | `validation/logic_auditor.py`, etc. | `ValidationReport` |

---

## 10. References

- **CHA design validation**: `DESIGN_VALIDATION_EXPLAINED.md`, `VALIDATION_WARNINGS_EXPLAINED.md`, `HOW_TO_FIX_VALIDATION_ISSUES.md`
- **Validation config**: `src/branitz_heat_decision/config/validation_standards.py`
- **Reason codes**: `src/branitz_heat_decision/decision/schemas.py` → `REASON_CODES`
