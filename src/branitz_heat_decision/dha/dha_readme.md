# DHA (District Heating Analysis - LV Grid Hosting) Module Documentation

Complete documentation for the DHA module implementing low-voltage (LV) electrical grid hosting capacity analysis for heat pumps, according to VDE-AR-N 4100 standards.

**Module Location**: `src/branitz_heat_decision/dha/`  
**Total Lines of Code**: ~1,912 lines  
**Primary Language**: Python 3.9+  
**Dependencies**: pandapower, networkx, geopandas, shapely, pandas, numpy, folium, pyproj

---

## Module Overview

The DHA (District Heating Analysis - LV Grid Hosting) module implements LV electrical grid hosting capacity analysis for heat pump deployment:

1. **Grid Building**: Creates LV grid topology from GIS data or legacy JSON (Option 2: MV bus + MV/LV transformers)
2. **Building Mapping**: Maps buildings to nearest LV buses
3. **Base Load Loading**: Loads base electrical demand (normal household consumption) from scenarios or BDEW time-series
4. **HP Load Assignment**: Converts heat demand to HP electrical load (`P_el = Q_th / COP`)
5. **Total Load Computation**: Combines base + HP loads (`P_total = P_base + P_hp`)
6. **Loadflow Simulation**: Runs pandapower powerflows for design + TopN hours
7. **Violation Detection**: Detects voltage violations and line overloads (VDE-AR-N 4100)
8. **KPI Extraction**: Extracts auditable hosting capacity metrics
9. **Visualization**: Generates GeoJSON, CSV, and interactive HTML map

### Architecture

The module follows a pipeline architecture with clear separation of concerns:

```
GIS Input (buildings, LV grid lines/substations)
    ↓
[grid_builder.py] → LV Grid Topology (Option 2: MV + transformers)
    ↓
[mapping.py] → Building-to-Bus Mapping
    ↓
[base_loads.py | bdew_base_loads.py] → Base Electrical Loads
    ↓
[loadflow.py] → HP Load Assignment + Powerflow Simulation
    ↓
[kpi_extractor.py] → Violation Detection + KPI Extraction
    ↓
[export.py] → GeoJSON + CSV + Interactive Map
```

---

## Module Files & Functions

### `__init__.py` (8 lines)
**Purpose**: Module initialization and public API  
**Exports**:
- `DHAConfig`, `get_default_config()` from `.config`
- `build_lv_grid_option2`, `build_lv_grid_from_nodes_ways_json` from `.grid_builder`
- `map_buildings_to_lv_buses` from `.mapping`
- `assign_hp_loads`, `run_loadflow` from `.loadflow`
- `extract_dha_kpis` from `.kpi_extractor`
- `export_dha_outputs` from `.export`

**Usage**:
```python
from branitz_heat_decision.dha import (
    DHAConfig, build_lv_grid_option2, map_buildings_to_lv_buses,
    assign_hp_loads, run_loadflow, extract_dha_kpis, export_dha_outputs
)
from branitz_heat_decision.dha.mitigations import recommend_mitigations
```

---

### `config.py` (50 lines)
**Purpose**: Centralized configuration for DHA pipeline  
**Classes**: 
- `DHAConfig`: Dataclass with all DHA parameters

**Key Configuration Parameters**:

#### Electrical Boundary (Option 2)
- `mv_vn_kv: float = 20.0` - Medium voltage level (20 kV)
- `lv_vn_kv: float = 0.4` - Low voltage level (0.4 kV)
- `ext_grid_vm_pu: float = 1.02` - External grid voltage setpoint (1.02 pu)

#### Transformer Parameters (MV/LV)
- `trafo_sn_mva: float = 0.63` - Transformer rated power (0.63 MVA = 630 kVA)
- `trafo_vk_percent: float = 6.0` - Short-circuit voltage (6%)
- `trafo_vkr_percent: float = 0.5` - Resistive component of short-circuit voltage (0.5%)
- `trafo_pfe_kw: float = 1.0` - No-load losses (1 kW)
- `trafo_i0_percent: float = 0.1` - No-load current (0.1%)
- `trafo_vector_group: str = "Dyn"` - Vector group (Dyn11 typical)
- `trafo_tap_min: int = -2` - Minimum tap position
- `trafo_tap_max: int = 2` - Maximum tap position
- `trafo_tap_step_percent: float = 2.5` - Tap step (2.5% per step)
- `trafo_tap_pos: int = 0` - Neutral tap position
- `trafo_tap_side: str = "hv"` - Tap side (high voltage)

#### Line Parameters (LV Cables - Fallback)
- `line_r_ohm_per_km: float = 0.206` - Resistance per km (Ω/km)
- `line_x_ohm_per_km: float = 0.080` - Reactance per km (Ω/km)
- `line_c_nf_per_km: float = 210.0` - Capacitance per km (nF/km)
- `line_max_i_ka: float = 0.27` - Maximum current (0.27 kA = 270 A)

**Note**: These are generic LV cable parameters. For real studies, use DSO standard types from `pandapower.std_types`.

#### Mapping Parameters
- `max_mapping_dist_m: float = 1000.0` - Maximum distance for building-to-bus mapping (1000 m)

#### KPI Thresholds (VDE-AR-N 4100)
- `v_min_pu: float = 0.90` - Minimum voltage limit (0.90 pu = 90% of nominal)
- `v_max_pu: float = 1.10` - Maximum voltage limit (1.10 pu = 110% of nominal)
- `loading_limit_pct: float = 100.0` - Line loading limit (100% = operational limit)
- `planning_warning_pct: float = 80.0` - Planning warning threshold (80% = planning alert)

**Usage**:
```python
from branitz_heat_decision.dha.config import DHAConfig, get_default_config
cfg = get_default_config()
cfg.v_min_pu = 0.90  # VDE-AR-N 4100: ±10% voltage tolerance
cfg.loading_limit_pct = 100.0  # Operational limit
```

**Interactions**:
- Used by all DHA modules (grid builder, loadflow, KPI extractor, export)

---

### `grid_builder.py` (396 lines) ⭐ **PRIMARY GRID MODULE**
**Purpose**: Build LV electrical grid topology (Option 2: MV bus + MV/LV transformers)

**Main Functions**:

#### `build_lv_grid_option2()` ⭐ **PRIMARY GRID BUILDER**
```python
def build_lv_grid_option2(
    lines_gdf: gpd.GeoDataFrame,
    substations_gdf: gpd.GeoDataFrame,
    cfg: Optional[DHAConfig] = None,
    *,
    endpoint_snap_tol_m: float = 1.0,
) -> pp.pandapowerNet
```

**Workflow**:
1. **MV Boundary**: Create MV bus (20 kV) + `ext_grid` at MV (`vm_pu = 1.02`)
2. **LV Bus Deduplication**: Snap endpoint coordinates (tolerance: 1.0 m) to avoid duplicate buses
3. **LV Lines**: Create lines from LineString geometries (length from geometry, parameters from config)
4. **Transformers**: Create MV/LV transformer for each substation point (connects MV bus to nearest LV bus)
5. **Validation**: Check Option 2 boundary (exactly one `ext_grid` at MV, ≥1 transformer) + no unsupplied buses

**Grid Structure**:
```
MV Bus (20 kV) ← ext_grid (vm_pu=1.02)
    │
    ├─ Transformer 1 (MV → LV)
    │     └─ LV Bus 1 (0.4 kV)
    │           └─ LV Line → LV Bus 2 → ... → LV Bus N
    │
    ├─ Transformer 2 (MV → LV)
    │     └─ LV Bus N+1 (0.4 kV)
    │           └─ LV Line → ...
    │
    └─ ...
```

**Helper Functions**:
- `_round_xy()`: Round coordinates for bus deduplication
- `_validate_boundary_option2()`: Validate Option 2 boundary (one `ext_grid` at MV, ≥1 transformer)
- `_validate_no_unsupplied_buses()`: Check for disconnected components (unsupplied buses)
- `_connect_transformers_to_lv_graph_if_needed()`: Bridge transformers to LV graph if isolated

#### `build_lv_grid_from_nodes_ways_json()` (Legacy Adapter)
```python
def build_lv_grid_from_nodes_ways_json(
    json_path: Path,
    cfg: Optional[DHAConfig] = None,
    *,
    dedup_coord_tol_deg: float = 0.0,
) -> pp.pandapowerNet
```

**Purpose**: Build LV grid from legacy nodes/ways JSON format (OSM-like structure)

**JSON Format**:
```json
{
  "nodes": [
    {"id": "node_1", "lat": 51.76, "lon": 14.34, "tags": {"power": "substation"}},
    ...
  ],
  "ways": [
    {"id": "way_1", "nodes": ["node_1", "node_2"], "tags": {"power": "line"}, "length_km": 0.15},
    ...
  ]
}
```

**Workflow**:
1. Create LV bus for each node (deduplicate by coordinate tolerance if enabled)
2. Create transformer at each node tagged `power=substation`
3. Create LV lines from ways tagged `power=line` or `power=cable`
4. Connect transformers to LV graph if isolated
5. Validate Option 2 boundary + no unsupplied buses

**Helper Functions**:
- `nodes_by_id()`: Find node by ID in nodes list
- `_haversine_m()`: Calculate distance between WGS84 coordinates (for length_km if missing)

**Interactions**:
- **Called by**: `02_run_dha.py` (when `--grid-source legacy_json`)
- **Uses**: `DHAConfig` for transformer/line parameters
- **Outputs**: `pandapowerNet` → mapping, loadflow

**Example Usage**:
```python
from branitz_heat_decision.dha.grid_builder import build_lv_grid_option2
lines_gdf = gpd.read_file("data/processed/power_lines.geojson")
subs_gdf = gpd.read_file("data/processed/power_substations.geojson")
net = build_lv_grid_option2(lines_gdf, subs_gdf, cfg=cfg)
# Option 2 boundary: MV bus + ext_grid at MV + transformers to LV
```

---

### `mapping.py` (130 lines) ⭐ **BUILDING MAPPING**
**Purpose**: Map buildings to nearest LV buses

**Main Functions**:

#### `map_buildings_to_lv_buses()` ⭐ **PRIMARY MAPPING FUNCTION**
```python
def map_buildings_to_lv_buses(
    buildings_gdf: gpd.GeoDataFrame,
    net: pp.pandapowerNet,
    max_dist_m: float = 1000.0,
    *,
    source_crs: Optional[str] = None,
    bus_crs: Optional[str] = "EPSG:4326",
    lv_vn_kv: float = 0.4,
) -> pd.DataFrame
```

**Workflow**:
1. **Filter LV Buses**: Select buses with `vn_kv <= 0.4 kV`
2. **Extract Bus Coordinates**: Get `(x, y)` from `net.bus_geodata`
3. **Building Centroids**: Compute building centroids for distance calculation
4. **CRS Conversion**: Convert both to projected CRS (EPSG:25833) for meter distances
5. **Nearest Neighbor**: Brute-force nearest neighbor search (chunked for performance)
6. **Distance Validation**: Mark mappings with `distance_m > max_dist_m` as unmapped

**Returns**:
- `DataFrame` with columns: `[building_id, bus_id, distance_m, mapped]`
- `mapped=True`: `distance_m <= max_dist_m`
- `mapped=False`: `distance_m > max_dist_m` (bus_id set to NaN)

**CRS Handling**:
- Buildings: Must have CRS (defaults to `source_crs` if provided)
- Buses: Infers CRS from coordinates (if `|x| > 180` or `|y| > 90`, assumes projected)
- Target: EPSG:25833 (UTM Zone 33N) for meter-distance calculations

**Interactions**:
- **Called by**: `02_run_dha.py` (after grid building)
- **Uses**: `net.bus_geodata`, `net.bus` (LV buses only)
- **Outputs**: Building-bus mapping DataFrame → loadflow

**Example Usage**:
```python
from branitz_heat_decision.dha.mapping import map_buildings_to_lv_buses
building_bus_map = map_buildings_to_lv_buses(
    buildings_gdf=buildings,
    net=net,
    max_dist_m=1000.0,
    bus_crs="EPSG:25833",
    lv_vn_kv=0.4
)
# Result: DataFrame with [building_id, bus_id, distance_m, mapped]
```

---

### `base_loads.py` (90 lines)
**Purpose**: Load base electrical loads from scenario JSON

**Main Functions**:

#### `load_base_loads_from_gebaeude_lastphasen()`
```python
def load_base_loads_from_gebaeude_lastphasen(
    json_path: Path,
    *,
    scenario: str,
    unit: str = "AUTO",
    auto_unit_sample_size: int = 500,
) -> pd.Series
```

**Purpose**: Load base electrical demand (`P_base`) from `gebaeude_lastphasenV2.json` for a specific scenario

**JSON Format**:
```json
{
  "<building_id>": {
    "winter_werktag_abendspitze": 2.5,  // kW or MW (auto-detected)
    "winter_werktag_mittag": 1.8,
    "sommer_werktag_abendspitze": 1.2,
    ...
  },
  ...
}
```

**Unit Auto-Detection**:
- Samples first 500 buildings
- If median absolute value < 0.1: assumes MW (multiply by 1000)
- Otherwise: assumes kW (no conversion)
- Returns Series in **kW** (always)

**Scenarios**:
- `winter_werktag_abendspitze`: Winter weekday evening peak (default, worst-case)
- `winter_werktag_mittag`: Winter weekday midday
- `sommer_werktag_abendspitze`: Summer weekday evening peak
- Additional scenarios as available

**Returns**:
- `pd.Series`: index=`building_id` (str), values=`P_base_kw` (float)
- Metadata: `s.attrs["source_unit"]` = detected unit (if AUTO)

**Interactions**:
- **Called by**: `02_run_dha.py` (when `--base-load-source scenario_json`)
- **Uses**: `gebaeude_lastphasenV2.json` from `data/raw/`
- **Outputs**: Base load Series → loadflow (combines with HP loads)

**Example Usage**:
```python
from branitz_heat_decision.dha.base_loads import load_base_loads_from_gebaeude_lastphasen
base_series = load_base_loads_from_gebaeude_lastphasen(
    Path("data/raw/gebaeude_lastphasenV2.json"),
    scenario="winter_werktag_abendspitze",
    unit="AUTO"
)
# Returns: Series(building_id → P_base_kw)
```

---

### `bdew_base_loads.py` (396 lines) ⭐ **BDEW TIME-SERIES BASE LOADS**
**Purpose**: Generate time-varying base electrical loads using BDEW Standardized Load Profiles (SLP)

**Classes**:

#### `BDEWPaths` (Dataclass)
```python
@dataclass(frozen=True)
class BDEWPaths:
    bdew_profiles_csv: Path
    building_function_mapping_json: Optional[Path] = None
    building_population_json: Optional[Path] = None
```

**Main Functions**:

#### `compute_bdew_base_loads_for_hours_and_assumptions()` ⭐ **PRIMARY BDEW FUNCTION**
```python
def compute_bdew_base_loads_for_hours_and_assumptions(
    buildings_df: pd.DataFrame,
    *,
    hours: Iterable[int],
    year: int = 2023,
    paths: Optional[BDEWPaths] = None,
    require_population: bool = True,
) -> Tuple[pd.DataFrame, pd.DataFrame]
```

**Purpose**: Generate hourly base electrical profiles using BDEW SLP

**BDEW Profile Types**:
- **H0**: Household (residential)
- **G0-G6**: Commercial/industrial (G0=small, G1-G6=various)
- **L0**: Agriculture
- **Y1**: Special cases
- **MIXED**: Blended 50% H0 + 50% G0 (fallback)

**Workflow**:
1. **Load BDEW Shapes**: Load 96-sample profiles from CSV (`profile_id × period × day → 96 watts`)
2. **Infer Profile Type**: Map building code/id to BDEW profile (H0/G0/G1/etc.) via mapping JSON
3. **Compute Yearly Consumption**: Scale by population (H0) or floor area (G0-G6)
4. **Apply H0 Dynamic Factor**: Polynomial scaling for H0 profiles (day-of-year dependent)
5. **Interpolate to Hours**: Map 96 quarter-hourly samples to hourly indices
6. **Generate Hourly Profiles**: `P_base(hour) = shape(hour) × (yearly_kWh / 1000.0)`

**Yearly Consumption Calculation**:
- **H0**: `yearly_kWh = household_consumption_kWh(residents)` from population JSON
- **G0-G6**: `yearly_kWh = floor_area_m2 × consumption_per_m2` (commercial defaults)
- **MIXED**: `0.5 × H0_consumption + 0.5 × G0_consumption`

**H0 Dynamic Factor** (Day-of-Year Polynomial):
```
f(doy) = a×doy⁴ + b×doy³ + c×doy² + d×doy + e
where: a=-3.92e-10, b=3.20e-7, c=-7.02e-5, d=2.10e-3, e=1.24
```

**Returns**:
- `base_df`: DataFrame (index=`hour`, columns=`building_id`, values=`kW`)
- `assumptions_df`: DataFrame with per-building metadata (profile_type, yearly_kwh, inputs used)

**Helper Functions**:
- `_default_bdew_paths()`: Resolve BDEW input paths (CSV, mapping JSON, population JSON)
- `_load_bdew_shapes()`: Load BDEW profile shapes from CSV (96 samples per profile/period/day)
- `_load_population()`: Load building population from JSON (for H0 scaling)
- `_infer_profile_type()`: Map building code/id to BDEW profile type (H0/G0/etc.)
- `_yearly_consumption_kwh()`: Compute yearly consumption (population-based for H0, area-based for G0-G6)
- `_household_consumption_kwh()`: BDEW household standards (1p=1900, 2p=2890, 3p=3720, 4p=4085, 5+p=5430+1020×(n-5))
- `_day_type()`: Classify day (workday/saturday/sunday)
- `_period()`: Classify period (winter/summer/transition)
- `_h0_dynamic_factor()`: H0 day-of-year scaling polynomial

#### `compute_bdew_base_loads_for_hours()` (Convenience Wrapper)
```python
def compute_bdew_base_loads_for_hours(
    buildings_df: pd.DataFrame,
    *,
    hours: Iterable[int],
    year: int = 2023,
    paths: Optional[BDEWPaths] = None,
) -> pd.DataFrame
```
Convenience wrapper (returns only `base_df`, no assumptions).

**Interactions**:
- **Called by**: `02_run_dha.py` (when `--base-load-source bdew_timeseries`)
- **Uses**: 
  - `bdew_profiles.csv` (BDEW SLP shapes)
  - `bdew_slp_gebaeudefunktionen.json` (building function → profile type mapping)
  - `building_population_resultsV6.json` (population for H0 scaling) - **REQUIRED**
- **Outputs**: Hourly base load DataFrame → loadflow

**Example Usage**:
```python
from branitz_heat_decision.dha.bdew_base_loads import compute_bdew_base_loads_for_hours_and_assumptions, BDEWPaths
paths = BDEWPaths(
    bdew_profiles_csv=Path("data/raw/bdew_profiles.csv"),
    building_function_mapping_json=Path("data/raw/bdew_slp_gebaeudefunktionen.json"),
    building_population_json=Path("data/raw/building_population_resultsV6.json")
)
base_df, assumptions_df = compute_bdew_base_loads_for_hours_and_assumptions(
    buildings_df=buildings,
    hours=[6667, 6434, ...],  # design + TopN hours
    year=2023,
    paths=paths,
    require_population=True
)
# Returns: (base_df: hour×building_id → kW, assumptions_df: building_id → metadata)
```

---

### `loadflow.py` (308 lines) ⭐ **LOADFLOW MODULE**
**Purpose**: Assign HP loads to buses and run pandapower powerflows

**Main Functions**:

#### `assign_hp_loads()` ⭐ **HP LOAD ASSIGNMENT**
```python
def assign_hp_loads(
    hourly_heat_profiles_df: pd.DataFrame,
    building_bus_map: pd.DataFrame,
    design_hour: int,
    topn_hours: List[int],
    cop: float,
    pf: float = 0.95,
    hp_three_phase: bool = True,
    base_profiles_kw: Optional[Union[pd.Series, pd.DataFrame]] = None,
    pf_base: float = 0.95,
    pf_hp: float = 0.95,
    use_pf_split: bool = False,
) -> Dict[int, pd.DataFrame]
```

**Purpose**: Create per-hour aggregated electrical loads per LV bus from base + HP loads

**Load Computation**:
1. **Heat Demand**: Extract `Q_th_kw` from `hourly_heat_profiles_df` (per building, per hour)
2. **HP Electrical Load**: `P_hp_kw = Q_th_kw / COP`
3. **Base Load**: 
   - If `base_profiles_kw` is `DataFrame`: extract per-building, per-hour base loads
   - If `base_profiles_kw` is `Series`: constant per-building base loads (scalar)
4. **Total Load**: `P_total_kw = P_base_kw + P_hp_kw`
5. **Reactive Power**:
   - Option A (`use_pf_split=False`): `Q_total = P_total × tan(arccos(pf))` (single power factor)
   - Option B (`use_pf_split=True`): `Q_total = P_base×tan(arccos(pf_base)) + P_hp×tan(arccos(pf_hp))` (split power factors)
6. **Aggregation**: Group by `bus_id` and sum `P_base`, `P_hp`, `P_total`, `Q_base`, `Q_hp`, `Q_total`
7. **Unit Conversion**: `P_mw = P_total_kw / 1000.0`, `Q_mvar = Q_total_kvar / 1000.0`

**Returns**:
- `Dict[int, pd.DataFrame]`: `{hour: DataFrame(bus_id, p_base_kw, p_hp_kw, p_total_kw, q_base_kvar, q_hp_kvar, q_total_kvar, p_mw, q_mvar)}`

#### `run_loadflow()` ⭐ **POWERFLOW SIMULATION**
```python
def run_loadflow(
    net: pp.pandapowerNet,
    loads_by_hour: Dict[int, pd.DataFrame],
    *,
    hp_three_phase: bool = True,
    run_3ph_if_available: bool = False,
) -> Dict[int, Dict[str, object]]
```

**Purpose**: Run pandapower powerflow for each hour

**Workflow**:
1. **Load Creation**: Create one load per bus (balanced `pp.create_load`) or asymmetric load (`pp.create_asymmetric_load`) if 3-phase
2. **Per-Hour Loop**:
   - Update load `p_mw` and `q_mvar` from `loads_by_hour[hour]`
   - If 3-phase imbalance: allocate HP power to phase A (worst-case)
   - Run `pp.runpp()` (balanced) or `pp.runpp_3ph()` (3-phase, if available)
   - Extract results: `res_bus` (voltages), `res_line` (loading)
3. **Result Snapshot**: Store `{hour, converged, error, solver, bus_results, line_results}`

**Load Element Management**:
- **Balanced Mode** (default): Uses `pp.create_load` (balanced 3-phase load)
- **3-Phase Imbalance Mode** (`hp_three_phase=False`): Uses `pp.create_asymmetric_load` (if available), allocates HP power to phase A
- **Performance**: Loads created once, updated per hour (not recreated)

**Returns**:
- `Dict[int, Dict[str, object]]`: `{hour: {converged, error, solver, bus_results, line_results}}`
- `bus_results`: DataFrame with `vm_pu` (balanced) or `vm_a_pu`, `vm_b_pu`, `vm_c_pu`, `v_min_pu` (3-phase)
- `line_results`: DataFrame with `loading_percent` (or `loading_pct`), `i_ka`, `p_from_mw`, `p_to_mw`

**Interactions**:
- **Called by**: `02_run_dha.py` (after building mapping and base load loading)
- **Uses**: `net` (pandapower network), `building_bus_map`, `hourly_heat_profiles_df`, `base_profiles_kw`
- **Outputs**: Per-hour powerflow results → KPI extractor

**Example Usage**:
```python
from branitz_heat_decision.dha.loadflow import assign_hp_loads, run_loadflow
# Assign loads
loads_by_hour = assign_hp_loads(
    hourly_heat_profiles_df=hourly_profiles,
    building_bus_map=building_bus_map,
    design_hour=6667,
    topn_hours=[6434, 6543, ...],
    cop=2.8,
    pf=0.95,
    hp_three_phase=True,
    base_profiles_kw=base_df  # DataFrame (hour × building_id → kW)
)
# Run powerflows
results_by_hour = run_loadflow(
    net=net,
    loads_by_hour=loads_by_hour,
    hp_three_phase=True
)
# Returns: {hour: {converged, bus_results, line_results}}
```

---

### `kpi_extractor.py` (307 lines) ⭐ **KPI EXTRACTION**
**Purpose**: Extract auditable DHA KPIs and violations from per-hour powerflow results

**Main Functions**:

#### `extract_dha_kpis()` ⭐ **PRIMARY KPI FUNCTION**
```python
def extract_dha_kpis(
    results_by_hour: Dict[int, Dict[str, object]],
    cfg: DHAConfig | None = None,
    net: Optional[pp.pandapowerNet] = None,
) -> Tuple[Dict[str, object], pd.DataFrame]
```

**Purpose**: Extract KPIs and violations from per-hour results

**KPI Categories**:

1. **Convergence**:
   - `hours_total`: Total hours simulated
   - `hours_converged`: Hours with converged powerflows
   - `non_convergence` violations: Hours where `converged=False`

2. **Voltage Violations**:
   - `worst_vmin_pu`: Minimum voltage across all hours (pu)
   - `worst_vmin_bus`: Bus ID with worst voltage
   - `worst_vmin_hour`: Hour with worst voltage
   - `voltage_violations_total`: Count of voltage violations
   - `voltage_violated_hours`: Number of unique hours with voltage violations (frequency analysis)
   - Violations: `v_min_pu < cfg.v_min_pu` (critical) or `v_min_pu > cfg.v_max_pu` (warning)

3. **Line Overload Violations**:
   - `max_feeder_loading_pct`: Maximum line loading across all hours (%)
   - `max_loading_line`: Line ID with maximum loading
   - `max_feeder_loading_hour`: Hour with maximum loading
   - `line_violations_total`: Count of overload violations (loading > 100%)
   - `line_overload_hours`: Number of unique hours with line overloads (frequency analysis)
   - `planning_warnings_total`: Count of planning warnings (loading > 80%)

4. **Transformer Overload Violations** (NEW):
   - `max_trafo_loading_pct`: Maximum transformer loading across all hours (%)
   - `max_loading_trafo`: Transformer ID with maximum loading
   - `max_loading_trafo_hour`: Hour with maximum transformer loading
   - `trafo_violations_total`: Count of transformer overload violations
   - `trafo_overload_hours`: Number of unique hours with transformer overloads (frequency analysis)

5. **Critical Hours Analysis** (NEW):
   - `critical_hours_count`: Number of unique hours with any critical violation
   - `critical_hours_fraction`: Fraction of simulated hours with critical violations

6. **Feeder Distance Metrics** (NEW):
   - `feeder_metrics`: Dictionary with:
     - `distance_km`: Distance from transformer to worst-case voltage bus (km)
     - `long_feeder`: Boolean flag (True if distance >= `cfg.long_feeder_km_threshold`)
     - `threshold_km`: Threshold used for classification

7. **Feasibility**:
   - `feasible`: `True` if no critical violations (voltage + overload + non_convergence)

**Violation Detection**:
- **Voltage**: `v_min_pu < cfg.v_min_pu` (critical) or `v_min_pu > cfg.v_max_pu` (warning)
- **Line Overload**: `loading_percent > cfg.loading_limit_pct` (critical if >120%, warning if 100-120%)
- **Transformer Overload**: `loading_percent > cfg.trafo_loading_limit_pct` (critical if >120%, warning if 100-120%)
- **Planning Warning**: `loading_percent > cfg.planning_warning_pct` (warning if 80-100%)

**Helper Functions**:
- `_compute_feeder_distance()`: Compute distance from transformer to worst-case voltage bus using NetworkX shortest path

**Returns**:
- `kpis`: Dict with KPIs (feasible, hours_converged, worst_vmin_pu, max_feeder_loading_pct, violations counts, frequency analysis, feeder metrics)
- `violations_df`: DataFrame with columns `[hour, type, element, name, value, limit, severity]`

**Interactions**:
- **Called by**: `02_run_dha.py` (after powerflow simulation)
- **Uses**: `results_by_hour` (from `run_loadflow`), `DHAConfig` for thresholds
- **Outputs**: KPIs + violations → export, decision pipeline

**Example Usage**:
```python
from branitz_heat_decision.dha.kpi_extractor import extract_dha_kpis
kpis, violations_df = extract_dha_kpis(results_by_hour, cfg=cfg)
# kpis['feasible'] → True/False
# kpis['worst_vmin_pu'] → minimum voltage
# kpis['line_violations_total'] → overload count
# violations_df → detailed violations table
```

---

### `mitigations.py` (196 lines) ⭐ **MITIGATION RECOMMENDATION ENGINE** (NEW)
**Purpose**: Deterministic mitigation recommendation engine for DHA violations. Maps violation patterns to structured, auditable mitigation strategies.

**Classes**:

#### `MitigationRecommendation` (Dataclass)
```python
@dataclass
class MitigationRecommendation:
    code: str  # e.g., "MIT_UNDERVOLTAGE_LONG_FEEDER"
    severity: str  # "low" | "moderate" | "high"
    category: str  # "operational" | "reinforcement" | "expansion"
    title: str
    actions: List[str]
    evidence: Dict[str, Any]
    estimated_cost_class: str  # "low" | "medium" | "high" | "very_high"
```

**Main Functions**:

#### `recommend_mitigations()` ⭐ **PRIMARY MITIGATION FUNCTION**
```python
def recommend_mitigations(
    net: pp.pandapowerNet,
    kpis: Dict[str, Any],
    violations_df: pd.DataFrame,
    cfg: DHAConfig,
) -> Dict[str, Any]
```

**Purpose**: Generate mitigation recommendations based on violation patterns

**Mitigation Rules**:

1. **Rule 1: Undervoltage + Long Feeder** → Infrastructure upgrade
   - **Trigger**: `has_voltage_vio AND long_feeder AND feeder_distance >= cfg.long_feeder_km_threshold`
   - **Category**: `reinforcement`
   - **Actions**:
     - Feeder reinforcement: upgrade cable to larger cross-section
     - Feeder splitting: divide load across multiple parallel feeders
     - New substation: install transformer closer to load center
   - **Cost Class**: `high` if `feeder_distance > 1.0 km`, else `medium`

2. **Rule 2: Line Overload** → Parallel cable or upgrade
   - **Trigger**: `has_line_vio`
   - **Category**: `reinforcement`
   - **Actions**:
     - Install parallel cable on overloaded segments
     - Upgrade to higher-capacity cable
     - Implement feeder meshing (connect multiple feeders)
   - **Cost Class**: `medium`

3. **Rule 3: Transformer Overload** → Critical expansion needed
   - **Trigger**: `has_trafo_vio`
   - **Category**: `expansion`
   - **Actions**:
     - Upgrade to higher-capacity transformer
     - Install additional transformer in parallel
     - Redistribute load to adjacent transformers (if available)
   - **Cost Class**: `very_high`

4. **Rule 4: Infrequent Violations** → Operational control sufficient
   - **Trigger**: `violation_fraction <= cfg.operational_control_max_fraction AND NOT (severe_voltage OR severe_trafo OR severe_line)`
   - **Category**: `operational`
   - **Actions**:
     - Smart charging control: shift heat pump load outside peak hours
     - Thermal storage: buffer tanks to time-shift heating demand
     - Demand response: coordinate heat pump operation across cluster
     - Load curtailment: temporary power reduction during extreme peaks
   - **Cost Class**: `low`

**Severity Assessment**:
- **Severe Voltage**: `worst_vmin_pu < cfg.voltage_severe_threshold` (default: 0.88 pu)
- **Severe Transformer**: `max_trafo_loading_pct > cfg.loading_severe_threshold` (default: 120%)
- **Severe Line**: `max_line_loading_pct > cfg.loading_severe_threshold` (default: 120%)

**Mitigation Classification**:
- **`expansion`**: Major grid expansion required (transformer and/or feeder capacity insufficient)
- **`reinforcement`**: Grid reinforcement needed for specific components
- **`operational`**: Grid hosting possible with operational controls
- **`none`**: No violations detected - grid can host heat pumps without modifications

**Returns**:
```python
{
    "mitigation_class": "operational" | "reinforcement" | "expansion" | "none",
    "recommendations": [MitigationRecommendation, ...],  # List of recommendation dicts
    "feasible_with_mitigation": bool,
    "summary": str  # Human-readable summary
}
```

**Interactions**:
- **Called by**: `02_run_dha.py` (after KPI extraction)
- **Uses**: `kpis` (from `extract_dha_kpis`), `violations_df`, `DHAConfig` (thresholds)
- **Outputs**: Mitigation analysis → stored in `kpis["mitigations"]` → exported to `dha_kpis.json` → UI display

**Example Usage**:
```python
from branitz_heat_decision.dha.mitigations import recommend_mitigations

mitigation_analysis = recommend_mitigations(net, kpis, violations_df, cfg)
kpis["mitigations"] = mitigation_analysis

# Access results
print(f"Class: {mitigation_analysis['mitigation_class']}")
print(f"Feasible: {mitigation_analysis['feasible_with_mitigation']}")
for rec in mitigation_analysis["recommendations"]:
    print(f"  - {rec['title']}: {rec['category']} ({rec['severity']} severity)")
```

---

### `export.py` (393 lines) ⭐ **VISUALIZATION MODULE**
**Purpose**: Export DHA outputs (GeoJSON, CSV, HTML map)

**Main Functions**:

#### `export_dha_outputs()` ⭐ **PRIMARY EXPORT FUNCTION**
```python
def export_dha_outputs(
    net: pp.pandapowerNet,
    results_by_hour: Dict[int, Dict[str, object]],
    kpis: Dict[str, object],
    violations_df: pd.DataFrame,
    output_dir: Path,
    *,
    title: str = "HP LV Grid Hosting",
    geodata_crs: str = "EPSG:25833",
    focus_bus_ids: Optional[Set[int]] = None,
) -> Dict[str, Path]
```

**Purpose**: Export all DHA outputs to files

**Exported Files**:
1. **`dha_kpis.json`**: KPIs + worst-case hour metadata
2. **`network.pickle`**: Pickled pandapower network
3. **`buses_results.geojson`**: Bus voltage results (worst-case hour)
4. **`lines_results.geojson`**: Line loading results (worst-case hour)
5. **`violations.csv`**: Detailed violations table
6. **`hp_lv_map.html`**: Interactive Folium map

**Worst-Case Hour Selection**:
- Prioritizes worst voltage (`v_min_pu` minimum)
- If tied, prioritizes maximum loading
- Falls back to first hour if no converged results

**Focus Subgraph**:
- If `focus_bus_ids` provided: restricts GeoJSON/map to subgraph containing focus buses + shortest paths to transformers
- Useful for cluster-level visualization (show only relevant network portion)

**Helper Functions**:
- `_buses_geojson()`: Generate bus GeoJSON with voltage properties
- `_lines_geojson()`: Generate line GeoJSON with loading properties
- `_make_transformer_to_wgs84()`: CRS transformer (geodata CRS → WGS84 for map)
- `_compute_focus_subgraph()`: Compute focused subgraph (NetworkX shortest paths)
- `_create_map()`: Generate interactive Folium map (lines colored by loading, buses colored by voltage)

#### `_create_map()` (Interactive Map Generator)

**Map Features**:
- **LV Lines**: Colored by loading % (green → yellow → orange → red, 0-120%)
- **LV Buses**: Colored by voltage (green ≥1.00 pu, yellow 0.95-1.00, orange 0.90-0.95, red <0.90)
- **Legend**: Voltage legend (colors + thresholds)
- **Colormap**: Line loading colormap (0-120%)
- **Tooltips**: Line name, loading %, hour | Bus ID, voltage

**Interactions**:
- **Called by**: `02_run_dha.py` (after KPI extraction)
- **Uses**: `net`, `results_by_hour`, `kpis`, `violations_df`, `DHAConfig` for CRS
- **Outputs**: Files in `output_dir/` → UHDC report (maps embedded)

**Example Usage**:
```python
from branitz_heat_decision.dha.export import export_dha_outputs
output_files = export_dha_outputs(
    net=net,
    results_by_hour=results_by_hour,
    kpis=kpis,
    violations_df=violations_df,
    output_dir=Path("results/dha/ST010"),
    title="HP LV Grid Hosting - Heinrich Zille Strasse",
    geodata_crs="EPSG:25833",
    focus_bus_ids=set(building_bus_map["bus_id"].dropna().astype(int))
)
# Returns: {kpis, network, buses_geojson, lines_geojson, violations, map}
```

---

## Complete Workflow

### End-to-End Pipeline

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. INPUT: Buildings, LV Grid (lines/substations or nodes/ways)  │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 2. GRID BUILDING (grid_builder.py)                              │
│    - Build LV grid (Option 2: MV bus + ext_grid at MV)         │
│    - Create MV/LV transformers                                  │
│    - Create LV lines from geometry                              │
│    - Validate boundary (one ext_grid at MV, ≥1 transformer)     │
│    - Check connectivity (no unsupplied buses)                   │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 3. BUILDING MAPPING (mapping.py)                                │
│    - Map buildings to nearest LV buses                          │
│    - Distance validation (max_dist_m = 1000 m)                  │
│    - Mark unmapped buildings                                    │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 4. BASE LOAD LOADING                                            │
│    Option A (base_loads.py):                                    │
│      - Load from gebaeude_lastphasenV2.json (scenario-based)   │
│    Option B (bdew_base_loads.py):                               │
│      - Generate BDEW time-series profiles                       │
│      - Infer profile type (H0/G0/etc.)                          │
│      - Scale by population (H0) or floor area (G0-G6)           │
│      - Apply H0 dynamic factor                                  │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 5. HP LOAD ASSIGNMENT (loadflow.py)                             │
│    - Extract heat demand from hourly profiles                   │
│    - Convert to HP electrical load: P_hp = Q_th / COP           │
│    - Combine with base load: P_total = P_base + P_hp            │
│    - Compute reactive power: Q = P × tan(arccos(pf))           │
│    - Aggregate per bus (sum all buildings on same bus)          │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 6. POWERFLOW SIMULATION (loadflow.py)                           │
│    - Create loads on network (balanced or 3-phase asymmetric)   │
│    - For each hour (design + TopN):                             │
│      - Update load p_mw, q_mvar                                 │
│      - Run pp.runpp() (balanced) or pp.runpp_3ph() (3-phase)   │
│      - Extract results: voltages, line loading                  │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 7. KPI EXTRACTION (kpi_extractor.py)                            │
│    - Detect voltage violations (v_min < 0.90 pu or v_max > 1.10)│
│    - Detect line overloads (loading > 100%)                     │
│    - Detect planning warnings (loading > 80%)                   │
│    - Extract worst-case metrics (worst_vmin_pu, max_loading_pct)│
│    - Generate violations table                                  │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 8. EXPORT (export.py)                                           │
│    - Export dha_kpis.json                                       │
│    - Export network.pickle                                      │
│    - Export buses_results.geojson (worst-case hour)             │
│    - Export lines_results.geojson (worst-case hour)             │
│    - Export violations.csv                                      │
│    - Generate hp_lv_map.html (interactive map)                  │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ OUTPUT: KPIs (JSON), Network (pickle), GeoJSON, CSV, HTML Map   │
└─────────────────────────────────────────────────────────────────┘
```

---

## File Interactions & Dependencies

### Internal Dependencies (Within DHA Module)

```
config.py
  └─→ Used by ALL modules (DHAConfig)

grid_builder.py (PRIMARY)
  ├─→ uses DHAConfig (transformer/line parameters, boundary settings)
  └─→ outputs: pandapowerNet → mapping, loadflow

mapping.py
  ├─→ uses: net (pandapowerNet), buildings_gdf
  └─→ outputs: building_bus_map DataFrame → loadflow

base_loads.py
  └─→ uses: gebaeude_lastphasenV2.json
  └─→ outputs: base_series (pd.Series) → loadflow

bdew_base_loads.py
  ├─→ uses: bdew_profiles.csv, bdew_slp_gebaeudefunktionen.json, building_population_resultsV6.json
  └─→ outputs: base_df (pd.DataFrame, hour × building_id → kW) → loadflow

loadflow.py (PRIMARY)
  ├─→ uses: net (pandapowerNet), building_bus_map, hourly_heat_profiles_df, base_profiles_kw
  ├─→ uses: DHAConfig (via function parameters, not directly)
  └─→ outputs: results_by_hour Dict → kpi_extractor

kpi_extractor.py
  ├─→ uses: results_by_hour (from loadflow), DHAConfig (thresholds)
  └─→ outputs: kpis Dict + violations_df DataFrame → export, decision pipeline

export.py
  ├─→ uses: net, results_by_hour, kpis, violations_df, DHAConfig (CRS)
  └─→ outputs: files (JSON, pickle, GeoJSON, CSV, HTML) → UHDC report
```

### External Dependencies (Outside DHA Module)

```
DHA Module
  ├─→ uses pandapower (pp.create_empty_network, pp.runpp, ...)
  ├─→ uses geopandas (GeoDataFrame, spatial operations)
  └─→ uses pyproj (CRS transformations)

Called by:
  └─→ src/scripts/02_run_dha.py (main pipeline script)

Inputs from other modules:
  ├─→ hourly_heat_profiles_df (from CHA: hourly heat demand profiles)
  ├─→ buildings (from data/processed: filtered residential buildings)
  └─→ LV grid data (from data/processed or Legacy: lines/substations)

Outputs to other modules:
  └─→ dha_kpis.json → Decision pipeline (kpi_contract.py)
```

---

## Key Algorithms & Methods

### 1. Building-to-Bus Mapping (`map_buildings_to_lv_buses()`)

**Algorithm**: Brute-force nearest neighbor search

```python
# Filter LV buses
lv_buses = net.bus[net.bus["vn_kv"] <= 0.4]

# Extract coordinates
bus_coords = net.bus_geodata.loc[lv_buses.index][["x", "y"]]
building_coords = buildings_gdf.geometry.centroid

# Convert to projected CRS (EPSG:25833) for meter distances
bus_proj = bus_coords.to_crs("EPSG:25833")
building_proj = building_coords.to_crs("EPSG:25833")

# Brute-force nearest neighbor (chunked for performance)
for chunk in chunks(buildings, 256):
    dx = building_coords[:, None] - bus_coords[None, :]
    dy = building_coords[:, None] - bus_coords[None, :]
    distances = np.sqrt(dx**2 + dy**2)
    nearest_bus_idx = np.argmin(distances, axis=1)
    nearest_distance = distances[np.arange(len(chunk)), nearest_bus_idx]

# Validate: distance <= max_dist_m
mapped = nearest_distance <= max_dist_m
```

**Result**:
- DataFrame with `[building_id, bus_id, distance_m, mapped]`
- `mapped=True`: `distance_m <= max_dist_m`
- `mapped=False`: `distance_m > max_dist_m` (bus_id = NaN)

---

### 2. BDEW Profile Generation (`compute_bdew_base_loads_for_hours_and_assumptions()`)

**Algorithm**: Time-series interpolation with profile scaling

```python
# Load BDEW shapes (96 quarter-hourly samples per profile/period/day)
shapes = _load_bdew_shapes(csv_path)  # shapes[profile_id][period][day] → 96 watts

# Infer profile type per building
profile_type = _infer_profile_type(building_id, building_code, mapping)

# Compute yearly consumption
if profile_type == "H0":
    residents = population_json[building_id]["residents"]
    yearly_kwh = _household_consumption_kwh(residents)  # 1p=1900, 2p=2890, ...
elif profile_type in ["G0", "G1", ...]:
    floor_area = buildings_df[building_id]["floor_area_m2"]
    yearly_kwh = floor_area × consumption_per_m2  # Commercial defaults
scale = yearly_kwh / 1000.0  # BDEW shapes normalized to 1000 kWh/a

# For each hour:
for hour in hours:
    dt = datetime(year, 1, 1) + timedelta(hours=hour)
    period = _period(dt)  # winter/summer/transition
    day = _day_type(dt)  # workday/saturday/sunday
    doy = dt.timetuple().tm_yday
    
    # Quarter-hour indices within the day (0-95)
    q0 = dt.hour * 4
    qs = [q0, q0+1, q0+2, q0+3]
    
    # Interpolate from 96 samples to hourly
    watts = shapes[profile_type][period][day][qs].mean() * scale
    
    # Apply H0 dynamic factor (day-of-year polynomial)
    if profile_type == "H0":
        watts *= _h0_dynamic_factor(doy)
    
    P_base_kw[hour, building_id] = watts / 1000.0  # W → kW
```

**Result**:
- DataFrame (index=`hour`, columns=`building_id`, values=`kW`)
- Time-varying base loads matching BDEW SLP profiles

---

### 3. Total Load Computation (`assign_hp_loads()`)

**Algorithm**: Aggregation with power factor handling

```python
# For each hour:
for hour in hours:
    # Extract heat demand
    Q_th_kw = hourly_heat_profiles_df.loc[hour, building_id]  # per building
    
    # Convert to HP electrical load
    P_hp_kw = Q_th_kw / COP  # per building
    
    # Get base load (scalar or time-varying)
    if base_profiles_kw is DataFrame:
        P_base_kw = base_profiles_kw.loc[hour, building_id]  # per building, per hour
    else:
        P_base_kw = base_profiles_kw[building_id]  # per building, constant
    
    # Total load
    P_total_kw = P_base_kw + P_hp_kw  # per building
    
    # Reactive power
    if use_pf_split:
        Q_total_kvar = P_base_kw × tan(arccos(pf_base)) + P_hp_kw × tan(arccos(pf_hp))
    else:
        Q_total_kvar = P_total_kw × tan(arccos(pf))  # single power factor
    
    # Aggregate per bus
    loads_by_bus = df.groupby("bus_id")[["p_base_kw", "p_hp_kw", "p_total_kw", "q_total_kvar"]].sum()
    loads_by_bus["p_mw"] = loads_by_bus["p_total_kw"] / 1000.0
    loads_by_bus["q_mvar"] = loads_by_bus["q_total_kvar"] / 1000.0
```

**Result**:
- Dict `{hour: DataFrame(bus_id, p_base_kw, p_hp_kw, p_total_kw, q_total_kvar, p_mw, q_mvar)}`

---

### 4. Violation Detection (`extract_dha_kpis()`)

**Algorithm**: Per-hour result scanning

```python
violations = []
worst_vmin = inf
max_loading = 0.0

for hour, res in results_by_hour.items():
    if not res["converged"]:
        violations.append({"hour": hour, "type": "non_convergence", ...})
        continue
    
    # Voltage violations
    bus_df = res["bus_results"]
    for bus_idx, row in bus_df.iterrows():
        v = row["v_min_pu"]  # or row["vm_pu"] for balanced
        if v < cfg.v_min_pu:  # critical
            violations.append({
                "hour": hour,
                "type": "voltage",
                "element": f"bus_{bus_idx}",
                "value": f"{v:.4f} pu",
                "limit": f"[{cfg.v_min_pu:.2f}, {cfg.v_max_pu:.2f}] pu",
                "severity": "critical"
            })
        elif v > cfg.v_max_pu:  # warning
            violations.append({...})
        worst_vmin = min(worst_vmin, v)
    
    # Line overload violations
    line_df = res["line_results"]
    for line_idx, row in line_df.iterrows():
        loading = row["loading_percent"]
        if loading > cfg.loading_limit_pct:  # critical if >120%, warning if 100-120%
            violations.append({
                "hour": hour,
                "type": "line_overload",
                "element": f"line_{line_idx}",
                "value": f"{loading:.1f}%",
                "limit": f"{cfg.loading_limit_pct:.1f}%",
                "severity": "critical" if loading > 120.0 else "warning"
            })
        elif loading > cfg.planning_warning_pct:  # warning (80-100%)
            violations.append({...})
        max_loading = max(max_loading, loading)

feasible = len([v for v in violations if v["severity"] == "critical"]) == 0
```

**Result**:
- `kpis`: Dict with aggregated metrics (worst_vmin_pu, max_loading_pct, violation counts)
- `violations_df`: DataFrame with detailed violations (hour, type, element, value, limit, severity)

---

## Configuration Parameters Reference

### `DHAConfig` Complete Parameter List

#### Electrical Boundary (Option 2)
| Parameter | Default | Description |
|-----------|---------|-------------|
| `mv_vn_kv` | 20.0 | Medium voltage level (20 kV) |
| `lv_vn_kv` | 0.4 | Low voltage level (0.4 kV) |
| `ext_grid_vm_pu` | 1.02 | External grid voltage setpoint (1.02 pu) |

#### Transformer Parameters
| Parameter | Default | Description |
|-----------|---------|-------------|
| `trafo_sn_mva` | 0.63 | Rated power (630 kVA) |
| `trafo_vk_percent` | 6.0 | Short-circuit voltage (6%) |
| `trafo_vkr_percent` | 0.5 | Resistive component (0.5%) |
| `trafo_pfe_kw` | 1.0 | No-load losses (1 kW) |
| `trafo_i0_percent` | 0.1 | No-load current (0.1%) |
| `trafo_vector_group` | "Dyn" | Vector group (Dyn11) |
| `trafo_tap_min` | -2 | Minimum tap position |
| `trafo_tap_max` | 2 | Maximum tap position |
| `trafo_tap_step_percent` | 2.5 | Tap step (2.5% per step) |
| `trafo_tap_pos` | 0 | Neutral tap position |
| `trafo_tap_side` | "hv" | Tap side (high voltage) |

#### Line Parameters (Fallback)
| Parameter | Default | Description |
|-----------|---------|-------------|
| `line_r_ohm_per_km` | 0.206 | Resistance (Ω/km) |
| `line_x_ohm_per_km` | 0.080 | Reactance (Ω/km) |
| `line_c_nf_per_km` | 210.0 | Capacitance (nF/km) |
| `line_max_i_ka` | 0.27 | Maximum current (270 A) |

#### Mapping Parameters
| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_mapping_dist_m` | 1000.0 | Maximum distance for building-to-bus mapping (m) |

#### KPI Thresholds (VDE-AR-N 4100)
| Parameter | Default | Description |
|-----------|---------|-------------|
| `v_min_pu` | 0.90 | Minimum voltage limit (0.90 pu = 90%) |
| `v_max_pu` | 1.10 | Maximum voltage limit (1.10 pu = 110%) |
| `line_loading_limit_pct` | 100.0 | Line loading limit (100% = operational) |
| `trafo_loading_limit_pct` | 100.0 | Transformer loading limit (100% = operational) |
| `planning_warning_pct` | 80.0 | Planning warning threshold (80%) |

#### Feeder Analysis Thresholds
| Parameter | Default | Description |
|-----------|---------|-------------|
| `long_feeder_km_threshold` | 0.8 | Threshold for "long feeder" classification (km) |

#### Operational Control Feasibility Thresholds
| Parameter | Default | Description |
|-----------|---------|-------------|
| `operational_control_max_fraction` | 0.2 | Max violation fraction (20% of hours) for operational mitigation |

#### Severity Classification Thresholds
| Parameter | Default | Description |
|-----------|---------|-------------|
| `voltage_severe_threshold` | 0.88 | Below this is "severe" undervoltage (pu) |
| `loading_severe_threshold` | 120.0 | Above this is "severe" overload (%) |

---

## Integration with Other Modules

### DHA → Decision Pipeline

```
DHA Output (results/dha/<cluster_id>/dha_kpis.json)
    ↓
Decision Module (src/branitz_heat_decision/decision/kpi_contract.py)
    └─→ Builds KPI contract with DHA LV grid metrics
    └─→ Includes: feasible, voltage_violations_total, line_violations_total, worst_vmin_pu
    ↓
Decision Rules (src/branitz_heat_decision/decision/rules.py)
    └─→ Evaluates feasibility (HP_OK, HP_VOLTAGE_VIOLATION, HP_LINE_VIOLATION, etc.)
    ↓
UHDC Report (src/branitz_heat_decision/uhdc/report_builder.py)
    └─→ Embeds DHA map (hp_lv_map.html) in HTML dashboard
    └─→ Displays violations table (sortable, filterable)
```

### DHA ← CHA Pipeline

```
CHA Output (hourly_heat_profiles.parquet)
    ↓
DHA Module (src/branitz_heat_decision/dha/loadflow.py)
    └─→ Converts heat demand to HP electrical load: P_el = Q_th / COP
    └─→ Injects HP loads into LV grid for hosting capacity analysis
```

### DHA → Economics Pipeline

```
DHA KPIs (voltage violations, line overloads, feasible)
    ↓
Economics Module (src/branitz_heat_decision/economics/monte_carlo.py)
    └─→ Uses DHA feasibility in cost/CO₂ robustness analysis
    └─→ Violations → grid upgrade costs (CAPEX) for HP scenarios
```

---

## Usage Examples

### Complete Pipeline Execution

```python
from branitz_heat_decision.dha import (
    DHAConfig, build_lv_grid_option2, map_buildings_to_lv_buses,
    assign_hp_loads, run_loadflow, extract_dha_kpis, export_dha_outputs
)
from branitz_heat_decision.dha.bdew_base_loads import (
    compute_bdew_base_loads_for_hours_and_assumptions, BDEWPaths
)
from branitz_heat_decision.dha.mitigations import recommend_mitigations
import geopandas as gpd
import pandas as pd
from pathlib import Path

# 1. Load data
buildings = gpd.read_parquet("data/processed/buildings.parquet")
lines_gdf = gpd.read_file("data/processed/power_lines.geojson")
subs_gdf = gpd.read_file("data/processed/power_substations.geojson")
hourly_profiles = pd.read_parquet("data/processed/hourly_heat_profiles.parquet")

# 2. Configure
cfg = DHAConfig()
cfg.v_min_pu = 0.90  # VDE-AR-N 4100
cfg.loading_limit_pct = 100.0

# 3. Build grid (Option 2: MV + transformers)
net = build_lv_grid_option2(lines_gdf, subs_gdf, cfg=cfg)

# 4. Map buildings to buses
building_bus_map = map_buildings_to_lv_buses(
    buildings_gdf=buildings,
    net=net,
    max_dist_m=1000.0,
    bus_crs="EPSG:25833"
)

# 5. Load base loads (BDEW time-series)
paths = BDEWPaths(
    bdew_profiles_csv=Path("data/raw/bdew_profiles.csv"),
    building_function_mapping_json=Path("data/raw/bdew_slp_gebaeudefunktionen.json"),
    building_population_json=Path("data/raw/building_population_resultsV6.json")
)
hours = [design_hour] + topn_hours
base_df, assumptions_df = compute_bdew_base_loads_for_hours_and_assumptions(
    buildings_df=buildings,
    hours=hours,
    year=2023,
    paths=paths,
    require_population=True
)

# 6. Assign HP loads and run powerflows
loads_by_hour = assign_hp_loads(
    hourly_heat_profiles_df=hourly_profiles,
    building_bus_map=building_bus_map,
    design_hour=design_hour,
    topn_hours=topn_hours,
    cop=2.8,
    pf=0.95,
    hp_three_phase=True,
    base_profiles_kw=base_df
)

results_by_hour = run_loadflow(
    net=net,
    loads_by_hour=loads_by_hour,
    hp_three_phase=True
)

# 7. Extract KPIs and violations
kpis, violations_df = extract_dha_kpis(results_by_hour, cfg=cfg, net=net)

# 8. Generate mitigation recommendations
mitigation_analysis = recommend_mitigations(net, kpis, violations_df, cfg)
kpis["mitigations"] = mitigation_analysis

# 9. Export outputs
output_files = export_dha_outputs(
    net=net,
    results_by_hour=results_by_hour,
    kpis=kpis,
    violations_df=violations_df,
    output_dir=Path("results/dha/ST010"),
    title="HP LV Grid Hosting",
    geodata_crs="EPSG:25833",
    focus_bus_ids=set(building_bus_map["bus_id"].dropna().astype(int))
)
```

### Custom Configuration

```python
from branitz_heat_decision.dha.config import DHAConfig

# Custom config for tight voltage limits
cfg = DHAConfig(
    v_min_pu=0.92,  # Stricter than VDE-AR-N 4100 (0.90)
    v_max_pu=1.08,  # Stricter than VDE-AR-N 4100 (1.10)
    loading_limit_pct=100.0,  # Operational limit
    planning_warning_pct=80.0,  # Planning alert
    trafo_sn_mva=1.0,  # Larger transformer (1 MVA)
    max_mapping_dist_m=500.0,  # Tighter mapping (500 m)
)
```

### Base Load Options Comparison

```python
# Option A: Scenario-based (constant per building, scalar)
from branitz_heat_decision.dha.base_loads import load_base_loads_from_gebaeude_lastphasen
base_series = load_base_loads_from_gebaeude_lastphasen(
    Path("data/raw/gebaeude_lastphasenV2.json"),
    scenario="winter_werktag_abendspitze"
)
# Returns: Series(building_id → P_base_kw) - constant per building

# Option B: BDEW time-series (time-varying per building, DataFrame)
from branitz_heat_decision.dha.bdew_base_loads import compute_bdew_base_loads_for_hours_and_assumptions
base_df, assumptions_df = compute_bdew_base_loads_for_hours_and_assumptions(
    buildings_df=buildings,
    hours=[6667, 6434, ...],
    year=2023,
    paths=bdew_paths
)
# Returns: DataFrame(hour × building_id → kW) - time-varying
```

---

## Testing & Validation

### Unit Tests
- `tests/dha/test_grid_builder.py`: Grid building tests (Option 2 boundary validation)
- `tests/dha/test_mapping.py`: Building-to-bus mapping tests
- `tests/dha/test_loadflow.py`: Load assignment and powerflow tests
- `tests/dha/test_kpi_extractor.py`: KPI extraction and violation detection tests

### Integration Tests
- `tests/integration/test_dha_pipeline.py`: End-to-end DHA pipeline tests

### Validation Checks
- **Boundary**: Exactly one `ext_grid` at MV (vn_kv >= 5 kV), ≥1 transformer
- **Connectivity**: No unsupplied buses (all LV buses reachable from transformers)
- **Mapping**: All buildings mapped (`distance_m <= max_dist_m`)
- **Convergence**: All powerflows converged (`converged=True`)
- **Voltage**: All voltages within limits (`v_min_pu >= 0.90`, `v_max_pu <= 1.10`)
- **Loading**: All lines within limits (`loading_percent <= 100.0`)

---

## Troubleshooting

### Common Issues

#### 1. Grid Not Building (No ext_grid or Transformers)
**Symptoms**: `_validate_boundary_option2()` raises `ValueError`

**Solutions**:
- Check substations GeoDataFrame: Must contain at least one point
- Check substation tags: In nodes/ways JSON, must have `tags.power == "substation"`
- Verify CRS: Both `lines_gdf` and `substations_gdf` must have CRS (preferably projected)

#### 2. Unsupplied Buses
**Symptoms**: `_validate_no_unsupplied_buses()` raises `ValueError`

**Solutions**:
- Check grid connectivity: Ensure all LV lines connect to transformer LV buses
- Bridge isolated components: Use `_connect_transformers_to_lv_graph_if_needed()` (automatic)
- Verify line geometry: All lines must have valid LineString geometries

#### 3. No Buildings Mapped
**Symptoms**: `building_bus_map["mapped"].sum() == 0`

**Solutions**:
- Increase `max_mapping_dist_m`: Default 1000 m may be too small
- Check CRS: Buildings and buses must be transformable to same CRS
- Verify bus geodata: `net.bus_geodata` must contain `(x, y)` coordinates
- Check distance calculation: Ensure both use projected CRS (EPSG:25833) for meters

#### 4. Powerflow Not Converging
**Symptoms**: `results_by_hour[hour]["converged"] == False`

**Solutions**:
- Check grid topology: Ensure no islands or unsupplied buses
- Verify load magnitudes: Very large loads may cause convergence issues
- Check transformer capacity: `trafo_sn_mva` may be too small for aggregated loads
- Reduce load: Try lower COP or fewer buildings

#### 5. High Voltage Violations
**Symptoms**: `voltage_violations_total > 0`

**Solutions**:
- Increase transformer capacity: `trafo_sn_mva = 1.0` MVA (larger)
- Reduce HP penetration: Lower COP or fewer HP-equipped buildings
- Check base load: High base loads + HP loads may exceed hosting capacity
- Verify grid resistance: High `line_r_ohm_per_km` increases voltage drop

#### 6. Line Overloads
**Symptoms**: `line_violations_total > 0`

**Solutions**:
- Increase line capacity: `line_max_i_ka = 0.4` kA (larger)
- Reduce HP penetration: Lower COP or fewer HP-equipped buildings
- Check base load: High base loads + HP loads may exceed line capacity
- Verify grid topology: Redistribute loads across multiple feeders if possible

---

## Performance Considerations

### Large Networks (>1000 buses)
- **Mapping**: Brute-force nearest neighbor is O(N×M) but chunked for memory efficiency
- **Powerflow**: Pandapower `runpp()` typically <1 second per hour for <500 buses, ~5-10 seconds for 500-1000 buses
- **BDEW Generation**: Profile generation is O(N×H) where N=buildings, H=hours (typically <10 seconds)

### Large Hour Sets (>100 hours)
- **Base Load Generation**: BDEW generation scales linearly with hours
- **Powerflow**: Runs sequentially per hour (parallelization possible but not implemented)

---

## Standards Compliance

### VDE-AR-N 4100 Compliance

The module implements VDE-AR-N 4100 standard limits:

- **Voltage Limits**: `v_min >= 0.90 pu` (90% of nominal), `v_max <= 1.10 pu` (110% of nominal)
- **Line Loading**: `loading_percent <= 100.0%` (operational limit), `> 80.0%` (planning warning)

**Compliance Checking** (`kpi_extractor.extract_dha_kpis()`):
- `voltage_ok`: `worst_vmin_pu >= v_min_pu AND worst_vmax_pu <= v_max_pu`
- `loading_ok`: `max_feeder_loading_pct <= loading_limit_pct`
- `feasible`: `voltage_ok AND loading_ok AND all_hours_converged`

---

## References & Standards

- **VDE-AR-N 4100:2022**: LV grid connection rules (voltage limits ±10%, line loading 100%)
- **BDEW Standardized Load Profiles (SLP)**: German standard load profiles (H0, G0-G6, L0, Y1)
- **IEC 60038**: Standard voltages (LV: 400 V, MV: 20 kV)

---

**Last Updated**: 2026-01-19  
**Module Version**: v1.1  
**Primary Maintainer**: DHA Development Team

## Recent Updates (2026-01-19)

- **Mitigations Module**: Added `mitigations.py` for deterministic mitigation recommendation engine
- **Enhanced KPI Fields**: Added frequency analysis (critical_hours_count, voltage_violated_hours, etc.)
- **Transformer Metrics**: Added max_trafo_loading_pct, trafo_overload_hours tracking
- **Feeder Distance Analysis**: Added feeder_metrics with distance_km and long_feeder flag
- **UI Integration**: Mitigation analysis now displayed in UI Feasibility tab
