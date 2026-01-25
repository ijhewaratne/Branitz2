# Tests Module Documentation

Complete documentation for the Tests module categorizing tests relevant for final workflow validation vs. tests that can be removed or separated for final delivery.

**Module Location**: `tests/`  
**Total Test Files**: 27 Python files  
**Primary Test Framework**: pytest  
**Dependencies**: pytest, pandas, geopandas, numpy, pandapipes, pandapower

---

## Module Overview

The Tests module provides comprehensive testing coverage for the Branitz Heat Decision system, including:

1. **Integration Tests** (`integration/`): End-to-end workflow tests
2. **Unit Tests** (per-module): Component-level tests
3. **Performance Tests** (`performance/`): Benchmark tests
4. **Smoke Tests**: Quick validation tests
5. **Placeholder Tests**: Empty/placeholder tests to be removed

### Test Categories

```
Tests Module
├─ integration/ → End-to-End Workflow Tests (CRITICAL FOR FINAL DELIVERY)
├─ decision/ → Decision Module Tests (CRITICAL FOR FINAL DELIVERY)
├─ economics/test_full_pipeline.py → Economics E2E Test (CRITICAL FOR FINAL DELIVERY)
├─ uhdc/test_orchestrator_discovery.py → Artifact Discovery Tests (CRITICAL FOR FINAL DELIVERY)
├─ uhdc/test_report_builder_smoke.py → Report Builder Smoke Tests (CRITICAL FOR FINAL DELIVERY)
├─ test_data_pipeline.py → Data Pipeline Validation (CRITICAL FOR FINAL DELIVERY)
├─ test_kpi_extractor_integration.py → KPI Extraction Integration (CRITICAL FOR FINAL DELIVERY)
│
├─ Unit Tests (can be separated) →
│  ├─ cha/test_heat_loss*.py → Heat Loss Unit Tests
│  ├─ economics/test_*.py (except full_pipeline) → Economics Unit Tests
│  ├─ uhdc/test_explainer_*.py → Explainer Unit Tests
│  ├─ decision/test_config_validation.py → Config Validation Unit Tests
│  └─ test_convergence_optimizer.py → Convergence Optimizer Unit Tests
│
├─ Performance Tests (can be separated) →
│  └─ performance/ → Performance Benchmarks
│
└─ Placeholder Tests (should be removed) →
   ├─ test_cha_network.py → Empty placeholder
   └─ test_dha_grid.py → Empty placeholder
```

---

## 1. Relevant Tests for Final Workflow Testing

These tests validate the **complete end-to-end workflow** and are **critical for final delivery**. They ensure the entire pipeline works correctly from data preparation through report generation.

### `tests/integration/test_full_pipeline.py` ⭐ **CRITICAL - END-TO-END WORKFLOW**
**Purpose**: End-to-end integration tests for the complete workflow

**Test Functions**:

#### `test_decision_cli_on_real_cluster()` ⭐ **E2E DECISION PIPELINE TEST**
```python
def test_decision_cli_on_real_cluster(tmp_path: Path)
```

**Purpose**: End-to-end Phase 5 - run decision CLI on real (precomputed) CHA/DHA/Economics artifacts

**Workflow**:
1. **Prerequisites Check**: Validates that CHA, DHA, and Economics artifacts exist for a cluster
2. **CLI Execution**: Runs `python -m branitz_heat_decision.cli.decision` with explicit artifact paths
3. **Output Validation**:
   - Verifies contract JSON file exists and validates against schema
   - Verifies decision JSON file exists with correct structure
   - Validates `choice` is in `["DH", "HP", "UNDECIDED"]`
   - Validates `robust` is boolean
   - Validates `reason_codes` is non-empty list
4. **Schema Validation**: Validates contract against `ContractValidator`

**Why Critical**: Tests the **complete decision pipeline** from artifacts → contract → decision → outputs

---

#### `test_decision_is_deterministic_on_real_cluster()` ⭐ **DETERMINISM TEST**
```python
def test_decision_is_deterministic_on_real_cluster(tmp_path: Path)
```

**Purpose**: Run decision twice with identical inputs and verify stable output (no LLM)

**Workflow**:
1. **Run Decision Twice**: Executes decision CLI twice with identical inputs
2. **Compare Outputs**: Verifies `choice`, `reason_codes`, and `metrics_used` are identical

**Why Critical**: Ensures **deterministic behavior** (no random variations between runs)

---

#### `test_uhdc_cli_generates_reports_from_real_cluster()` ⭐ **E2E REPORT GENERATION TEST**
```python
def test_uhdc_cli_generates_reports_from_real_cluster(tmp_path: Path)
```

**Purpose**: End-to-end UHDC report generation on real artifacts

**Workflow**:
1. **Prerequisites Check**: Validates that CHA, DHA, and Economics artifacts exist
2. **CLI Execution**: Runs `python -m branitz_heat_decision.cli.uhdc` with artifact discovery
3. **Output Validation**:
   - Verifies HTML report exists: `uhdc_report_{cluster_id}.html`
   - Verifies Markdown report exists: `uhdc_explanation_{cluster_id}.md`
   - Verifies JSON report exists: `uhdc_report_{cluster_id}.json`

**Why Critical**: Tests the **complete report generation pipeline** from artifacts → discovery → contract → decision → explanation → reports

---

**Interactions**:
- **Uses**: Real artifacts from `results/cha/`, `results/dha/`, `results/economics/`
- **Tests**: Complete decision and report generation workflows
- **Outputs**: Validated contract/decision/report files

---

### `tests/integration/test_report_outputs.py` ⭐ **CRITICAL - REPORT OUTPUT VALIDATION**
**Purpose**: Validate report outputs (HTML structure, JSON roundtrip)

**Test Functions**:

#### `test_report_html_validates_offline()` ⭐ **HTML VALIDATION TEST**
```python
def test_report_html_validates_offline(tmp_path: Path) -> None
```

**Purpose**: Offline HTML validation - ensures HTML is parseable and has correct structure

**Workflow**:
1. **Create Minimal Report**: Builds minimal report payload
2. **Generate HTML**: Calls `save_reports()` to generate HTML report
3. **Structure Validation**:
   - Verifies `<!DOCTYPE html>` present
   - Verifies `<html>`, `<head>`, `<body>` tags present
4. **Parser Validation**: Uses `HTMLParser` to validate HTML is parseable

**Why Critical**: Ensures **HTML reports are valid and viewable** in browsers

---

#### `test_report_json_roundtrip()` ⭐ **JSON ROUNDTRIP TEST**
```python
def test_report_json_roundtrip(tmp_path: Path) -> None
```

**Purpose**: Ensure JSON export/import fidelity - save_reports() should write a JSON file that round-trips identically

**Workflow**:
1. **Create Minimal Report**: Builds minimal report payload
2. **Save JSON**: Calls `save_reports()` with `include_json=True`
3. **Roundtrip Validation**: Loads JSON and verifies it equals the original report dictionary

**Why Critical**: Ensures **JSON export/import is lossless** (no data corruption)

---

**Interactions**:
- **Uses**: `uhdc/report_builder.py` (`save_reports`, `render_html_report`)
- **Tests**: Report output format validation
- **Outputs**: Validated HTML/JSON/Markdown reports

---

### `tests/test_data_pipeline.py` ⭐ **CRITICAL - DATA PREPARATION VALIDATION**
**Purpose**: Validate data preparation pipeline outputs

**Test Functions**:

#### `test_buildings_file_exists()` ⭐ **BUILDINGS FILE VALIDATION**
```python
@pytest.mark.data
def test_buildings_file_exists()
```

**Purpose**: Test that buildings.parquet file exists and can be loaded

**Validation**:
- File exists: `data/processed/buildings.parquet`
- File is non-empty
- Contains `building_id` column
- Has valid CRS

**Why Critical**: Ensures **data preparation produces valid buildings file** required by CHA/DHA

---

#### `test_weather_file_exists()` ⭐ **WEATHER FILE VALIDATION**
```python
@pytest.mark.data
def test_weather_file_exists()
```

**Purpose**: Test that weather.parquet file exists and has correct structure

**Validation**:
- File exists: `data/processed/weather.parquet`
- Has 8760 hours (one year)
- Contains `temperature_c` column

**Why Critical**: Ensures **weather data exists** for profile generation

---

#### `test_hourly_profiles_file_exists()` ⭐ **PROFILES FILE VALIDATION**
```python
@pytest.mark.data
def test_hourly_profiles_file_exists()
```

**Purpose**: Test that hourly profiles file exists and has correct structure

**Validation**:
- File exists: `data/processed/hourly_heat_profiles.parquet`
- Has 8760 hours (one year)
- Has at least one building column

**Why Critical**: Ensures **hourly profiles exist** required by CHA/DHA/Economics

---

#### `test_building_cluster_map_exists()` ⭐ **CLUSTER MAP VALIDATION**
```python
@pytest.mark.data
def test_building_cluster_map_exists()
```

**Purpose**: Test that building-cluster map file exists

**Validation**:
- File exists: `data/processed/building_cluster_map.parquet`
- Contains `building_id` and `cluster_id` columns

**Why Critical**: Ensures **cluster mapping exists** required by all pipelines

---

#### `test_design_topn_file_exists()` ⭐ **DESIGN/TOPN FILE VALIDATION**
```python
@pytest.mark.data
def test_design_topn_file_exists()
```

**Purpose**: Test that design topn JSON file exists

**Validation**:
- File exists: `data/processed/cluster_design_topn.json`
- Is valid JSON dictionary
- Contains at least one cluster

**Why Critical**: Ensures **design/top-N hours exist** required by CHA/DHA

---

**Interactions**:
- **Uses**: `data/processed/` directory files
- **Tests**: Data preparation pipeline outputs
- **Outputs**: Validated processed data files

---

### `tests/test_kpi_extractor_integration.py` ⭐ **CRITICAL - KPI EXTRACTION INTEGRATION**
**Purpose**: Integration tests for KPI extraction (EN 13941-1 compliance logic)

**Test Functions**:

#### `test_kpi_extraction_basic()` ⭐ **BASIC KPI EXTRACTION TEST**
```python
@pytest.mark.cha
def test_kpi_extraction_basic()
```

**Purpose**: Test basic KPI extraction structure

**Validation**:
- `feasible` in `en13941_compliance` (boolean)
- `v_max_ms` in `aggregate`
- `en13941_compliance` and `detailed` blocks exist

**Why Critical**: Ensures **KPI extraction produces valid structure** required by Decision pipeline

---

#### `test_en13941_compliance_logic()` ⭐ **COMPLIANCE LOGIC TEST**
```python
@pytest.mark.cha
def test_en13941_compliance_logic()
```

**Purpose**: Test EN 13941-1 compliance logic

**Validation**:
- `feasible = velocity_ok AND dp_ok`
- `velocity_ok = (velocity_share >= 0.95)`
- `dp_ok = (dp_max <= 0.3 bar/100m)`
- Reason codes match violations (`DH_OK`, `DH_VELOCITY_VIOLATION`, `DH_DP_VIOLATION`)

**Why Critical**: Ensures **EN 13941-1 compliance logic is correct** (standards compliance)

---

#### `test_pipe_level_extraction()` ⭐ **PIPE-LEVEL EXTRACTION TEST**
```python
@pytest.mark.cha
def test_pipe_level_extraction()
```

**Purpose**: Test pipe-level KPI extraction

**Validation**:
- Pipe KPIs count matches network pipes
- Each pipe KPI has required fields: `velocity_ms`, `pressure_drop_bar`, `pressure_drop_per_100m_bar`

**Why Critical**: Ensures **detailed pipe-level KPIs are extracted** (required for auditability)

---

#### `test_aggregate_structure()` ⭐ **AGGREGATE STRUCTURE TEST**
```python
@pytest.mark.cha
def test_aggregate_structure()
```

**Purpose**: Test aggregate KPI structure

**Validation**:
- Required aggregate fields exist: `v_max_ms`, `v_mean_ms`, `v_min_ms`, `dp_max_bar_per_100m`, `dp_mean_bar_per_100m`, `t_supply_c`, `t_return_c`, `delta_t_k`, `length_total_m`, `length_supply_m`, `length_service_m`

**Why Critical**: Ensures **aggregate KPI structure is complete** (required for Decision pipeline)

---

**Interactions**:
- **Uses**: `cha/kpi_extractor.py` (`extract_kpis`)
- **Tests**: KPI extraction integration with pandapipes networks
- **Outputs**: Validated KPI dictionaries

---

### `tests/decision/test_contract_builder.py` ⭐ **CRITICAL - CONTRACT BUILDING INTEGRATION**
**Purpose**: Integration tests for KPI contract building

**Test Functions**:

#### `test_build_contract_minimal_inputs_validates()` ⭐ **CONTRACT BUILDING TEST**
```python
def test_build_contract_minimal_inputs_validates()
```

**Purpose**: Test that contract building with minimal inputs produces a valid contract

**Workflow**:
1. **Create Minimal Inputs**: Builds minimal CHA/DHA/Economics KPI dictionaries
2. **Build Contract**: Calls `build_kpi_contract()` with minimal inputs
3. **Schema Validation**: Validates contract against `ContractValidator`

**Why Critical**: Ensures **contract building produces valid contracts** from partial KPIs

---

#### `test_missing_violation_counts_marks_hp_infeasible_and_reason_missing()` ⭐ **MISSING KPIS HANDLING TEST**
```python
def test_missing_violation_counts_marks_hp_infeasible_and_reason_missing()
```

**Purpose**: Test that missing DHA violation counts mark HP as infeasible with `DHA_MISSING_KPIS` reason

**Workflow**:
1. **Create Contract**: Builds contract with missing `voltage_violations_total` and `line_violations_total`
2. **Validate Behavior**: Verifies `heat_pumps.feasible = False` and `DHA_MISSING_KPIS` in reasons
3. **Schema Validation**: Contract still validates (violation counts allowed to be None)

**Why Critical**: Ensures **missing KPIs are handled gracefully** (robustness)

---

#### `test_missing_dh_kpis_marks_dh_infeasible_and_reason_missing()` ⭐ **MISSING CHA KPIS HANDLING TEST**
```python
def test_missing_dh_kpis_marks_dh_infeasible_and_reason_missing()
```

**Purpose**: Test that missing CHA KPIs mark DH as infeasible with `CHA_MISSING_KPIS` reason

**Workflow**:
1. **Create Contract**: Builds contract with empty CHA KPIs
2. **Validate Behavior**: Verifies `district_heating.feasible = False` and `CHA_MISSING_KPIS` in reasons

**Why Critical**: Ensures **missing CHA KPIs are handled gracefully** (robustness)

---

**Interactions**:
- **Uses**: `decision/kpi_contract.py` (`build_kpi_contract`), `decision/schemas.py` (`ContractValidator`)
- **Tests**: Contract building integration with CHA/DHA/Economics KPIs
- **Outputs**: Validated KPI contracts

---

### `tests/decision/test_rules.py` ⭐ **CRITICAL - DECISION RULES EXHAUSTIVE TESTS**
**Purpose**: Exhaustive tests for decision rules (all decision paths)

**Test Functions**:

#### `test_decide_all_paths()` ⭐ **EXHAUSTIVE DECISION PATHS TEST**
```python
def test_decide_all_paths()
```

**Purpose**: Covers all critical feasibility/cost/CO₂/robustness/MC-missing branches in one parametrized test

**Test Cases** (16 critical decision paths):
1. **Feasibility-only paths**:
   - `only_dh_feasible_mc_missing`: DH feasible, HP infeasible → `DH`
   - `only_hp_feasible_mc_missing`: HP feasible, DH infeasible → `HP`
   - `neither_feasible_mc_missing`: Neither feasible → `UNDECIDED`

2. **Cost-dominant paths**:
   - `cost_dominant_dh_robust`: DH clearly cheaper (>5%) with robust MC → `DH` (robust)
   - `cost_dominant_hp_robust`: HP clearly cheaper (>5%) with robust MC → `HP` (robust)

3. **CO₂ tie-breaker paths** (costs within 5%):
   - `cost_close_co2_dh_robust`: Costs close, DH lower CO₂, robust MC → `DH` (robust)
   - `cost_close_co2_hp_robust`: Costs close, HP lower CO₂, robust MC → `HP` (robust)
   - `cost_close_co2_equal_defaults_dh_mc_missing`: Costs close, equal CO₂ → `DH` (default)

4. **Monte Carlo sensitivity paths**:
   - `cost_dominant_dh_sensitive`: DH cheaper but MC sensitive (55-70%) → `DH` (sensitive)
   - `cost_dominant_hp_sensitive`: HP cheaper but MC sensitive (55-70%) → `HP` (sensitive)
   - `cost_close_co2_dh_sensitive`: Costs close, DH lower CO₂, sensitive MC → `DH` (sensitive)
   - `cost_close_co2_hp_sensitive`: Costs close, HP lower CO₂, sensitive MC → `HP` (sensitive)

5. **MC missing paths**:
   - `cost_dominant_dh_mc_missing`: DH cheaper but MC missing → `DH` (MC_MISSING)
   - `cost_dominant_hp_mc_missing`: HP cheaper but MC missing → `HP` (MC_MISSING)
   - `cost_close_co2_dh_mc_missing`: Costs close, DH lower CO₂, MC missing → `DH` (MC_MISSING)
   - `cost_close_co2_hp_mc_missing`: Costs close, HP lower CO₂, MC missing → `HP` (MC_MISSING)

**Why Critical**: Ensures **all decision paths work correctly** (complete coverage of decision logic)

---

#### `test_only_dh_feasible()`, `test_only_hp_feasible()`, `test_neither_feasible()` ⭐ **FEASIBILITY TESTS**
**Purpose**: Test feasibility-only decision paths

**Why Critical**: Ensures **feasibility logic is correct** (core decision rule)

---

#### `test_cost_dominant_dh()`, `test_cost_close_use_co2_tiebreaker()` ⭐ **COST TESTS**
**Purpose**: Test cost-based decision paths

**Why Critical**: Ensures **cost comparison logic is correct** (core decision rule)

---

#### `test_robust_threshold_70()`, `test_sensitive_threshold_55_to_70()` ⭐ **ROBUSTNESS TESTS**
**Purpose**: Test robustness threshold logic (70% = robust, 55-70% = sensitive)

**Why Critical**: Ensures **robustness classification is correct** (uncertainty handling)

---

**Interactions**:
- **Uses**: `decision/rules.py` (`decide_from_contract`)
- **Tests**: Decision rules logic with various contract configurations
- **Outputs**: Validated decision results

---

### `tests/decision/test_schemas.py` ⭐ **CRITICAL - SCHEMA VALIDATION**
**Purpose**: Schema validation tests (ensures contract structure is correct)

**Test Functions**:

#### `test_schema_validates_correct_contract()` ⭐ **VALID CONTRACT TEST**
```python
def test_schema_validates_correct_contract()
```

**Purpose**: Test that valid contracts pass schema validation

**Why Critical**: Ensures **schema validation works correctly** (contract integrity)

---

#### `test_schema_rejects_missing_keys()` ⭐ **MISSING KEYS TEST**
```python
def test_schema_rejects_missing_keys()
```

**Purpose**: Test that contracts with missing required keys are rejected

**Why Critical**: Ensures **schema validation catches structural errors** (data integrity)

---

#### `test_schema_rejects_invalid_reason_code()` ⭐ **INVALID REASON CODE TEST**
```python
def test_schema_rejects_invalid_reason_code()
```

**Purpose**: Test that contracts with invalid reason codes are rejected

**Why Critical**: Ensures **reason codes are validated** (decision integrity)

---

#### `test_schema_allows_missing_mc_block()` ⭐ **OPTIONAL MC BLOCK TEST**
```python
def test_schema_allows_missing_mc_block()
```

**Purpose**: Test that contracts without Monte Carlo block are still valid

**Why Critical**: Ensures **schema allows optional Monte Carlo block** (backward compatibility)

---

**Interactions**:
- **Uses**: `decision/schemas.py` (`ContractValidator`)
- **Tests**: Schema validation logic
- **Outputs**: Validated contracts

---

### `tests/economics/test_full_pipeline.py` ⭐ **CRITICAL - ECONOMICS E2E TEST**
**Purpose**: End-to-end test for economics pipeline

**Test Functions**:

#### `test_economics_cli_pipeline_end_to_end()` ⭐ **ECONOMICS E2E TEST**
```python
@pytest.mark.economics
def test_economics_cli_pipeline_end_to_end(tmp_path)
```

**Purpose**: Test complete economics CLI pipeline with minimal inputs

**Workflow**:
1. **Create Minimal KPIs**: Builds minimal CHA/DHA KPI files (JSON)
2. **Create Cluster Summary**: Builds cluster summary parquet with annual heat demand
3. **Run Economics CLI**: Calls `run_economics_for_cluster()` with minimal inputs (N=10 for speed)
4. **Output Validation**:
   - Verifies `monte_carlo_samples.parquet` exists
   - Verifies `monte_carlo_summary.json` exists
   - Validates summary structure: `lcoh`, `co2`, `monte_carlo` blocks
   - Validates win fractions sum to 1.0

**Why Critical**: Ensures **economics pipeline works end-to-end** (LCOH/CO₂/Monte Carlo)

---

**Interactions**:
- **Uses**: `cli/economics.py` (`run_economics_for_cluster`)
- **Tests**: Complete economics pipeline from KPIs → Monte Carlo → Summary
- **Outputs**: Validated Monte Carlo results

---

### `tests/uhdc/test_orchestrator_discovery.py` ⭐ **CRITICAL - ARTIFACT DISCOVERY INTEGRATION**
**Purpose**: Integration tests for artifact discovery (path finding)

**Test Functions**:

#### `test_discover_artifact_paths_finds_expected_layout()` ⭐ **PATH DISCOVERY TEST**
```python
def test_discover_artifact_paths_finds_expected_layout(tmp_path: Path)
```

**Purpose**: Test that artifact discovery finds expected nested layout

**Workflow**:
1. **Create Nested Layout**: Creates `results/cha/{cluster}/cha_kpis.json`, `results/dha/{cluster}/dha_kpis.json`, `results/economics/{cluster}/monte_carlo_summary.json`
2. **Discover Paths**: Calls `discover_artifact_paths()`
3. **Validate**: Verifies all three artifacts are found

**Why Critical**: Ensures **artifact discovery works correctly** (required for UHDC pipeline)

---

#### `test_discover_flat_structure()` ⭐ **FLAT STRUCTURE TEST**
```python
def test_discover_flat_structure(tmp_path: Path)
```

**Purpose**: Test that artifact discovery supports flat structure (artifacts directly under base_dir)

**Why Critical**: Ensures **artifact discovery handles different directory structures** (flexibility)

---

#### `test_discover_fallback_order_prefers_more_specific()` ⭐ **FALLBACK ORDER TEST**
```python
def test_discover_fallback_order_prefers_more_specific(tmp_path: Path)
```

**Purpose**: Ensure the first matching pattern wins (order matters in SEARCH_PATTERNS)

**Why Critical**: Ensures **pattern matching order is correct** (deterministic discovery)

---

#### `test_no_artifacts_raises_error()` ⭐ **ERROR HANDLING TEST**
```python
def test_no_artifacts_raises_error(tmp_path: Path)
```

**Purpose**: Test that `build_uhdc_report()` raises a clear error when nothing exists

**Why Critical**: Ensures **error handling is clear** (user experience)

---

**Interactions**:
- **Uses**: `uhdc/orchestrator.py` (`discover_artifact_paths`, `build_uhdc_report`)
- **Tests**: Artifact discovery logic with various directory structures
- **Outputs**: Discovered artifact paths

---

### `tests/uhdc/test_report_builder_smoke.py` ⭐ **CRITICAL - REPORT BUILDER SMOKE TEST**
**Purpose**: Smoke test for report builder (quick validation)

**Test Functions**:

#### `test_save_reports_writes_html_and_md()` ⭐ **REPORT GENERATION SMOKE TEST**
```python
def test_save_reports_writes_html_and_md(tmp_path: Path)
```

**Purpose**: Quick smoke test that report builder generates HTML, Markdown, and JSON files

**Workflow**:
1. **Create Minimal Report**: Builds minimal report payload
2. **Generate Reports**: Calls `save_reports()` with map placeholder
3. **Output Validation**:
   - Verifies HTML, Markdown, and JSON files exist
   - Validates JSON is readable
   - Validates HTML contains source hints (`data-source` attributes)
   - Validates HTML contains standards references (EN 13941-1 ×3, VDE-AR-N 4100 ×2)
   - Validates Markdown contains standards references

**Why Critical**: Ensures **report generation works end-to-end** (HTML/Markdown/JSON outputs)

---

**Interactions**:
- **Uses**: `uhdc/report_builder.py` (`save_reports`)
- **Tests**: Report generation with minimal inputs
- **Outputs**: Validated HTML/Markdown/JSON reports

---

## 2. Tests to Remove or Separate for Final Delivery

These tests are **unit tests, implementation details, placeholders, or performance benchmarks** that are **not critical for final workflow validation**. They can be:
- **Separated** into a separate `tests/unit/` or `tests/development/` directory
- **Removed** if they are placeholders or redundant

### ⚠️ **PLACEHOLDER TESTS** (Should Be Removed)

#### `tests/test_cha_network.py` (1 line) ⚠️ **EMPTY PLACEHOLDER**
```python
def test_cha_placeholder():
    """Placeholder for CHA tests."""
    assert True
```

**Status**: **EMPTY PLACEHOLDER** - Contains only `assert True`

**Recommendation**: **DELETE** - No actual test logic

---

#### `tests/test_dha_grid.py` (1 line) ⚠️ **EMPTY PLACEHOLDER**
```python
def test_dha_placeholder():
    """Placeholder for DHA tests."""
    assert True
```

**Status**: **EMPTY PLACEHOLDER** - Contains only `assert True`

**Recommendation**: **DELETE** - No actual test logic

---

### ⚠️ **UNIT TESTS - IMPLEMENTATION DETAILS** (Can Be Separated)

#### `tests/cha/test_heat_loss.py` ⚠️ **UNIT TEST - HEAT LOSS CALCULATION**
**Status**: **UNIT TEST** - Tests specific heat loss calculation functions

**Test Functions**:
- `test_linear_method_dn50_trunk_default()` - Linear heat loss method
- `test_linear_method_temperature_scaling()` - Temperature scaling
- `test_w_per_m_to_u_conversion_pandapipes_convention()` - U-value conversion
- `test_outer_diameter_computation_priority()` - Outer diameter computation
- `test_thermal_resistance_method_basic()` - Thermal resistance method
- `test_temperature_drop_helper()` - Temperature drop calculation
- `test_temperature_profile_exponential()` - Temperature profile
- `test_catalog_lookup_with_temperature_scaling()` - Catalog lookup

**Recommendation**: **SEPARATE** to `tests/unit/cha/test_heat_loss.py` (not critical for workflow)

---

#### `tests/cha/test_heat_loss_mapping.py` ⚠️ **UNIT TEST - HEAT LOSS MAPPING**
**Status**: **UNIT TEST** - Tests heat loss mapping to pandapipes

**Test Functions**:
- `test_linear_loss_maps_to_pandapipes_qext()` - Linear loss → pandapipes mapping
- `test_linear_loss_area_convention_comparison()` - Area convention comparison

**Recommendation**: **SEPARATE** to `tests/unit/cha/test_heat_loss_mapping.py` (not critical for workflow)

---

#### `tests/test_convergence_optimizer.py` ⚠️ **UNIT TEST - CONVERGENCE OPTIMIZER**
**Status**: **UNIT TEST** - Tests specific convergence optimizer component

**Test Functions**:
- `test_tree_network_adds_loop()` - Tree network loop addition
- `test_convergence_improves_with_iterations()` - Convergence improvement
- `test_roughness_variations_are_reproducible()` - Roughness variations
- `test_initial_pressures_distance_based()` - Initial pressure calculation
- `test_connectivity_check_finds_disconnected()` - Connectivity check
- `test_short_pipe_fix()` - Short pipe fix

**Recommendation**: **SEPARATE** to `tests/unit/cha/test_convergence_optimizer.py` (not critical for workflow)

---

#### `tests/test_cha_typology_uwerte3.py` ⚠️ **UNIT TEST - TYPOLOGY/U-VALUES**
**Status**: **UNIT TEST** - Tests specific typology/U-value implementation detail

**Test Functions**:
- `test_estimate_envelope_uses_sanierungszustand_and_uwerte3_if_available()` - Typology estimation with U-values

**Recommendation**: **SEPARATE** to `tests/unit/data/test_typology.py` (implementation detail)

---

#### `tests/test_dha_bdew_base_loads.py` ⚠️ **UNIT TEST - BDEW BASE LOADS**
**Status**: **UNIT TEST** - Tests specific BDEW implementation detail

**Test Functions**:
- `test_bdew_base_loads_for_hours_shape_and_nonnegativity()` - BDEW base load generation

**Recommendation**: **SEPARATE** to `tests/unit/dha/test_bdew_base_loads.py` (implementation detail)

---

#### `tests/economics/test_lcoh.py` ⚠️ **UNIT TEST - LCOH CALCULATION**
**Status**: **UNIT TEST** - Tests LCOH calculation functions

**Test Functions**:
- `test_compute_lcoh_dh_gas_matches_formula()` - DH LCOH formula validation
- `test_compute_lcoh_hp_lv_upgrade_triggers()` - HP LCOH with LV upgrade

**Recommendation**: **SEPARATE** to `tests/unit/economics/test_lcoh.py` (not critical for workflow)

---

#### `tests/economics/test_co2.py` ⚠️ **UNIT TEST - CO2 CALCULATION**
**Status**: **UNIT TEST** - Tests CO₂ calculation functions

**Test Functions**:
- `test_compute_co2_dh_gas_acceptance()` - DH CO₂ (gas)
- `test_compute_co2_dh_biomass_acceptance()` - DH CO₂ (biomass)
- `test_compute_co2_hp_acceptance()` - HP CO₂
- `test_compute_co2_zero_heat_raises()` - Error handling (zero heat)

**Recommendation**: **SEPARATE** to `tests/unit/economics/test_co2.py` (not critical for workflow)

---

#### `tests/economics/test_monte_carlo.py` ⚠️ **UNIT TEST - MONTE CARLO**
**Status**: **UNIT TEST** - Tests Monte Carlo sampling functions

**Test Functions**:
- `test_sample_param_normal_clip()` - Parameter sampling
- `test_run_monte_carlo_for_cluster_reproducible_seed()` - Reproducibility
- `test_compute_mc_summary_basic()` - Summary calculation

**Recommendation**: **SEPARATE** to `tests/unit/economics/test_monte_carlo.py` (not critical for workflow)

---

#### `tests/economics/test_params.py` ⚠️ **UNIT TEST - PARAMETER VALIDATION**
**Status**: **UNIT TEST** - Tests economic parameter validation

**Test Functions**:
- `test_economic_parameters_validation_discount_rate()` - Discount rate validation
- `test_economic_parameters_validation_generation_type()` - Generation type validation
- `test_economic_parameters_validation_feeder_loading_limit()` - Feeder loading limit validation
- `test_load_params_from_yaml()` - YAML loading

**Recommendation**: **SEPARATE** to `tests/unit/economics/test_params.py` (not critical for workflow)

---

#### `tests/decision/test_config_validation.py` ⚠️ **UNIT TEST - CONFIG VALIDATION**
**Status**: **UNIT TEST** - Tests decision config validation

**Test Functions**:
- `test_valid_config_passes()` - Valid config
- `test_robust_out_of_range()` - Robust threshold validation
- `test_sensitive_greater_than_robust()` - Sensitive threshold validation
- `test_negative_abs_threshold()` - Absolute threshold validation
- `test_non_dict_config()` - Type validation

**Recommendation**: **SEPARATE** to `tests/unit/decision/test_config_validation.py` (not critical for workflow)

---

#### `tests/uhdc/test_explainer_fallback.py` ⚠️ **UNIT TEST - EXPLAINER FALLBACK**
**Status**: **UNIT TEST** - Tests explainer fallback logic

**Test Functions**:
- `test_llm_fallback_on_api_error()` - API error fallback
- `test_llm_fallback_on_hallucination()` - Hallucination fallback
- `test_all_template_styles_use_only_contract_data()` - Template data usage
- `test_llm_fallback_on_missing_kpis()` - Missing KPIs fallback

**Recommendation**: **SEPARATE** to `tests/unit/uhdc/test_explainer_fallback.py` (not critical for workflow)

---

#### `tests/uhdc/test_explainer_safety.py` ⚠️ **UNIT TEST - EXPLAINER SAFETY**
**Status**: **UNIT TEST** - Tests explainer safety validation

**Test Functions**:
- `test_fallback_template_is_safe_and_validates()` - Template safety
- `test_validate_explanation_safety_rejects_hallucinated_number()` - Hallucination detection
- `test_llm_safety_allows_rounding()` - Rounding tolerance

**Recommendation**: **SEPARATE** to `tests/unit/uhdc/test_explainer_safety.py` (not critical for workflow)

---

#### `tests/uhdc/test_llm_integration.py` ⚠️ **UNIT TEST - LLM INTEGRATION**
**Status**: **UNIT TEST** - Tests LLM integration (requires API key)

**Test Functions**:
- `test_llm_ready_reflects_key_and_force_template()` - LLM availability check

**Recommendation**: **SEPARATE** to `tests/unit/uhdc/test_llm_integration.py` (not critical for workflow, requires API key)

---

### ⚠️ **PERFORMANCE TESTS** (Can Be Separated)

#### `tests/performance/test_decision_speed.py` ⚠️ **PERFORMANCE BENCHMARK**
**Status**: **PERFORMANCE TEST** - Measures decision logic performance

**Test Functions**:
- `test_decision_speed()` - Decision logic must be <10ms per cluster (1000 iterations)
- `test_batch_processing_overhead()` - Placeholder for batch overhead benchmark

**Recommendation**: **SEPARATE** to `tests/performance/` (not critical for workflow, environment-dependent)

---

#### `tests/performance/test_path_discovery_speed.py` ⚠️ **PERFORMANCE BENCHMARK**
**Status**: **PERFORMANCE TEST** - Measures path discovery performance

**Test Functions**:
- `test_path_discovery_handles_1000_clusters()` - Path discovery should be <250ms for 1000 clusters
- `test_path_discovery_cache_avoids_exists_calls()` - Cache prevents repeated filesystem checks

**Recommendation**: **SEPARATE** to `tests/performance/` (not critical for workflow, environment-dependent)

---

## Summary: Relevant Tests for Final Workflow Testing

### ✅ **CRITICAL TESTS** (Must Keep for Final Delivery)

| Test File | Purpose | Why Critical |
|-----------|---------|--------------|
| `integration/test_full_pipeline.py` | End-to-end workflow tests | Tests complete pipeline from artifacts → decision → reports |
| `integration/test_report_outputs.py` | Report output validation | Ensures HTML/JSON reports are valid and viewable |
| `test_data_pipeline.py` | Data preparation validation | Ensures processed data files exist and are valid |
| `test_kpi_extractor_integration.py` | KPI extraction integration | Ensures KPIs are extracted correctly from networks |
| `decision/test_contract_builder.py` | Contract building integration | Ensures contracts are built correctly from KPIs |
| `decision/test_rules.py` | Decision rules exhaustive tests | Ensures all decision paths work correctly (16 paths) |
| `decision/test_schemas.py` | Schema validation tests | Ensures contract structure is validated correctly |
| `economics/test_full_pipeline.py` | Economics E2E test | Ensures economics pipeline works end-to-end |
| `uhdc/test_orchestrator_discovery.py` | Artifact discovery integration | Ensures artifact discovery works correctly |
| `uhdc/test_report_builder_smoke.py` | Report builder smoke test | Ensures report generation works end-to-end |

**Total Critical Tests**: **10 test files** covering the complete workflow

---

## Summary: Tests to Remove or Separate

### ⚠️ **PLACEHOLDER TESTS** (Should Be Removed - 2 files)

| Test File | Status | Recommendation |
|-----------|--------|----------------|
| `test_cha_network.py` | Empty placeholder (`assert True`) | **DELETE** |
| `test_dha_grid.py` | Empty placeholder (`assert True`) | **DELETE** |

---

### ⚠️ **UNIT TESTS** (Can Be Separated - 11 files)

| Test File | Purpose | Recommendation |
|-----------|---------|----------------|
| `cha/test_heat_loss.py` | Heat loss calculation unit tests | **SEPARATE** to `tests/unit/cha/` |
| `cha/test_heat_loss_mapping.py` | Heat loss mapping unit tests | **SEPARATE** to `tests/unit/cha/` |
| `test_convergence_optimizer.py` | Convergence optimizer unit tests | **SEPARATE** to `tests/unit/cha/` |
| `test_cha_typology_uwerte3.py` | Typology/U-value unit tests | **SEPARATE** to `tests/unit/data/` |
| `test_dha_bdew_base_loads.py` | BDEW base loads unit tests | **SEPARATE** to `tests/unit/dha/` |
| `economics/test_lcoh.py` | LCOH calculation unit tests | **SEPARATE** to `tests/unit/economics/` |
| `economics/test_co2.py` | CO₂ calculation unit tests | **SEPARATE** to `tests/unit/economics/` |
| `economics/test_monte_carlo.py` | Monte Carlo unit tests | **SEPARATE** to `tests/unit/economics/` |
| `economics/test_params.py` | Parameter validation unit tests | **SEPARATE** to `tests/unit/economics/` |
| `decision/test_config_validation.py` | Config validation unit tests | **SEPARATE** to `tests/unit/decision/` |
| `uhdc/test_explainer_fallback.py` | Explainer fallback unit tests | **SEPARATE** to `tests/unit/uhdc/` |
| `uhdc/test_explainer_safety.py` | Explainer safety unit tests | **SEPARATE** to `tests/unit/uhdc/` |
| `uhdc/test_llm_integration.py` | LLM integration unit tests | **SEPARATE** to `tests/unit/uhdc/` |

**Total Unit Tests**: **13 test files** that can be separated

---

### ⚠️ **PERFORMANCE TESTS** (Can Be Separated - 2 files)

| Test File | Purpose | Recommendation |
|-----------|---------|----------------|
| `performance/test_decision_speed.py` | Decision logic performance benchmarks | **KEEP IN** `tests/performance/` (already separated) |
| `performance/test_path_discovery_speed.py` | Path discovery performance benchmarks | **KEEP IN** `tests/performance/` (already separated) |

**Total Performance Tests**: **2 test files** (already in separate directory)

---

## Recommended Test Structure for Final Delivery

### ✅ **CRITICAL TESTS** (Keep in Main `tests/` Directory)

```
tests/
├─ integration/ → End-to-End Workflow Tests (CRITICAL)
│  ├─ test_full_pipeline.py → Complete pipeline E2E tests
│  └─ test_report_outputs.py → Report output validation
│
├─ decision/ → Decision Module Integration Tests (CRITICAL)
│  ├─ test_contract_builder.py → Contract building integration
│  ├─ test_rules.py → Decision rules exhaustive tests
│  └─ test_schemas.py → Schema validation tests
│
├─ economics/test_full_pipeline.py → Economics E2E test (CRITICAL)
├─ uhdc/ → UHDC Module Integration Tests (CRITICAL)
│  ├─ test_orchestrator_discovery.py → Artifact discovery integration
│  └─ test_report_builder_smoke.py → Report builder smoke test
│
├─ test_data_pipeline.py → Data preparation validation (CRITICAL)
└─ test_kpi_extractor_integration.py → KPI extraction integration (CRITICAL)
```

---

### ⚠️ **UNIT TESTS** (Separate to `tests/unit/`)

```
tests/
└─ unit/ → Unit Tests (Development/Component-Level)
   ├─ cha/
   │  ├─ test_heat_loss.py
   │  ├─ test_heat_loss_mapping.py
   │  └─ test_convergence_optimizer.py
   ├─ data/
   │  └─ test_typology.py (from test_cha_typology_uwerte3.py)
   ├─ dha/
   │  └─ test_bdew_base_loads.py
   ├─ economics/
   │  ├─ test_lcoh.py
   │  ├─ test_co2.py
   │  ├─ test_monte_carlo.py
   │  └─ test_params.py
   ├─ decision/
   │  └─ test_config_validation.py
   └─ uhdc/
      ├─ test_explainer_fallback.py
      ├─ test_explainer_safety.py
      └─ test_llm_integration.py
```

---

### ⚠️ **PERFORMANCE TESTS** (Keep in `tests/performance/`)

```
tests/
└─ performance/ → Performance Benchmarks (Optional)
   ├─ test_decision_speed.py
   └─ test_path_discovery_speed.py
```

---

## Running Relevant Tests for Final Workflow

### Run All Critical Integration Tests

```bash
# Run all integration tests (end-to-end workflow)
pytest tests/integration/ -v

# Run all decision module integration tests
pytest tests/decision/ -v

# Run economics E2E test
pytest tests/economics/test_full_pipeline.py -v

# Run UHDC integration tests
pytest tests/uhdc/test_orchestrator_discovery.py tests/uhdc/test_report_builder_smoke.py -v

# Run data pipeline validation
pytest tests/test_data_pipeline.py -v

# Run KPI extraction integration
pytest tests/test_kpi_extractor_integration.py -v
```

### Run All Critical Tests (Combined)

```bash
# Run all critical tests for final workflow validation
pytest tests/integration/ \
       tests/decision/test_contract_builder.py \
       tests/decision/test_rules.py \
       tests/decision/test_schemas.py \
       tests/economics/test_full_pipeline.py \
       tests/uhdc/test_orchestrator_discovery.py \
       tests/uhdc/test_report_builder_smoke.py \
       tests/test_data_pipeline.py \
       tests/test_kpi_extractor_integration.py \
       -v
```

### Run Unit Tests Separately (Development)

```bash
# Run all unit tests (if separated to tests/unit/)
pytest tests/unit/ -v

# Run specific unit test categories
pytest tests/unit/cha/ -v  # CHA unit tests
pytest tests/unit/economics/ -v  # Economics unit tests
```

### Run Performance Tests (Optional)

```bash
# Run performance benchmarks (requires RUN_PERFORMANCE_TESTS=1)
RUN_PERFORMANCE_TESTS=1 pytest tests/performance/ -v
```

---

## Migration Plan

### Step 1: Remove Placeholder Tests

```bash
# Delete empty placeholder tests
rm tests/test_cha_network.py
rm tests/test_dha_grid.py
```

---

### Step 2: Separate Unit Tests

```bash
# Create unit test directory structure
mkdir -p tests/unit/{cha,data,dha,economics,decision,uhdc}

# Move unit tests to separate directory
mv tests/cha/test_heat_loss.py tests/unit/cha/
mv tests/cha/test_heat_loss_mapping.py tests/unit/cha/
mv tests/test_convergence_optimizer.py tests/unit/cha/
mv tests/test_cha_typology_uwerte3.py tests/unit/data/test_typology.py
mv tests/test_dha_bdew_base_loads.py tests/unit/dha/
mv tests/economics/test_lcoh.py tests/unit/economics/
mv tests/economics/test_co2.py tests/unit/economics/
mv tests/economics/test_monte_carlo.py tests/unit/economics/
mv tests/economics/test_params.py tests/unit/economics/
mv tests/decision/test_config_validation.py tests/unit/decision/
mv tests/uhdc/test_explainer_fallback.py tests/unit/uhdc/
mv tests/uhdc/test_explainer_safety.py tests/unit/uhdc/
mv tests/uhdc/test_llm_integration.py tests/unit/uhdc/
```

---

### Step 3: Update pytest Configuration (Optional)

Add to `pytest.ini`:

```ini
[pytest]
# Markers for test categorization
markers =
    integration: End-to-end integration tests (critical for workflow)
    unit: Unit tests (component-level, can be separated)
    performance: Performance benchmarks (optional)

# Run only integration tests by default
testpaths = tests/integration tests/decision tests/economics/test_full_pipeline.py tests/uhdc/test_orchestrator_discovery.py tests/uhdc/test_report_builder_smoke.py tests/test_data_pipeline.py tests/test_kpi_extractor_integration.py

# Include unit tests only with --unit flag
# Include performance tests only with --performance flag
```

---

## Test Execution Summary

### Final Workflow Validation Test Suite

**10 Critical Test Files** covering:

1. **End-to-End Workflow**: `integration/test_full_pipeline.py` (3 tests)
2. **Report Outputs**: `integration/test_report_outputs.py` (2 tests)
3. **Data Preparation**: `test_data_pipeline.py` (5 tests)
4. **KPI Extraction**: `test_kpi_extractor_integration.py` (4 tests)
5. **Contract Building**: `decision/test_contract_builder.py` (3 tests)
6. **Decision Rules**: `decision/test_rules.py` (16+ tests, including `test_decide_all_paths`)
7. **Schema Validation**: `decision/test_schemas.py` (4 tests)
8. **Economics Pipeline**: `economics/test_full_pipeline.py` (1 test)
9. **Artifact Discovery**: `uhdc/test_orchestrator_discovery.py` (4 tests)
10. **Report Builder**: `uhdc/test_report_builder_smoke.py` (1 test)

**Total Critical Tests**: **~43 test functions** validating the complete workflow

---

## References & Standards

- **pytest**: https://docs.pytest.org/
- **EN 13941-1**: District heating pipes - Design and installation (compliance validation)
- **VDE-AR-N 4100**: Technical connection rules for low-voltage grids (compliance validation)

---

**Last Updated**: 2026-01-19  
**Module Version**: v1.1  
**Primary Maintainer**: Tests Module Development Team

## Recent Updates (2026-01-19)

- **Documentation**: Comprehensive test categorization and organization
- **Test Structure**: Clear separation of critical workflow tests vs. unit/performance tests
