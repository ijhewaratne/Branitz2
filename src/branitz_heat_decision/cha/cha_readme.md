# CHA (Central Heating Analysis) Module Documentation

Complete documentation for the CHA module implementing district heating network analysis, simulation, and evaluation according to EN 13941-1 standards.

**Module Location**: `src/branitz_heat_decision/cha/`  
**Total Lines of Code**: ~6,476 lines  
**Primary Language**: Python 3.9+  
**Dependencies**: pandapipes, networkx, geopandas, shapely, pandas, numpy, folium

**Last Updated**: 2026-01-24  
**Recent Updates**:
- ✅ Added context-aware validation warnings for trunk-spur networks (`hydraulic_checks.py`)
- ✅ Added 25% design margin to pipe sizing for robustness (`network_builder_trunk_spur.py`)
- ✅ Added comprehensive design validation system (`design_validator.py`)
- ✅ Added validation documentation (`DESIGN_VALIDATION_EXPLAINED.md`, `VALIDATION_WARNINGS_EXPLAINED.md`, `HOW_TO_FIX_VALIDATION_ISSUES.md`, `WARNING_MITIGATION_OPTIONS.md`)

---

## Module Overview

The CHA (Central Heating Analysis) module implements a complete pipeline for district heating (DH) network analysis:

1. **Network Building**: Creates trunk-spur topology from GIS data
2. **Pipe Sizing**: Selects appropriate DN (diameter nominal) based on flow rates
3. **Heat Loss Modeling**: Computes thermal losses (linear or thermal resistance method)
4. **Convergence Optimization**: Ensures numerical stability for hydraulic-thermal simulation
5. **Simulation**: Runs pandapipes pipeflow (hydraulic + thermal)
6. **KPI Extraction**: Extracts EN 13941-1 compliant performance metrics
7. **Visualization**: Generates interactive maps (velocity, temperature, pressure) and CSVs

### Architecture

The module follows a pipeline architecture with clear separation of concerns:

```
GIS Input (buildings, streets)
    ↓
[network_builder_trunk_spur.py] → Network Topology (trunk + spurs)
    ↓
[sizing_catalog.py] → Pipe Sizing (DN selection)
    ↓
[heat_loss.py] → Thermal Loss Parameters (u_w_per_m2k, text_k)
    ↓
[convergence_optimizer_spur.py] → Numerical Stability
    ↓
[pandapipes.pipeflow()] → Hydraulic-Thermal Simulation
    ↓
[kpi_extractor.py] → Performance Metrics (EN 13941-1 KPIs)
    ↓
[qgis_export.py] → Interactive Maps + CSVs
```

---

## Module Files & Functions

### `__init__.py`
**Purpose**: Module initialization (currently empty)  
**Functions**: None  
**Usage**: Python package marker

---

### `config.py` (84 lines)
**Purpose**: Centralized configuration for CHA pipeline  
**Classes**: 
- `CHAConfig`: Dataclass with all CHA parameters

**Key Configuration Parameters**:

#### Hydraulic Parameters
- `system_pressure_bar: float = 8.0` - Plant supply pressure (DH-realistic: 6-10 bar)
- `pump_plift_bar: float = 3.0` - Circulation pump differential pressure (2-4 bar)
- `p_min_bar_allowed: float = 1.5` - Minimum absolute pressure sanity gate (1.5-2.0 bar)

#### Thermal Parameters
- `supply_temp_k: float = 363.15` - Supply temperature (90°C)
- `return_temp_k: float = 323.15` - Return temperature (50°C)
- `delta_t_k: float` - Temperature difference (40 K, computed property)
- `soil_temp_k: float = 285.15` - Soil/ambient temperature (12°C)

#### Heat Loss Configuration
- `heat_loss_method: str = "linear"` - Method: `"linear"` | `"thermal_resistance"`
- `heat_loss_area_convention: str = "d"` - Pandapipes mapping: `"d"` (verified) | `"pi_d"`
- `default_q_linear_trunk_w_per_m: float = 30.0` - Default trunk heat loss (W/m)
- `default_q_linear_service_w_per_m: float = 25.0` - Default service heat loss (W/m)
- `t_linear_ref_k: float = 353.15` - Catalog reference fluid temp (80°C)
- `t_soil_ref_k: float = 285.15` - Catalog reference soil temp (12°C)
- `supply_return_interaction: bool = True` - TwinPipe correction (EN 13941)
- `twinpipe_loss_factor: float = 0.9` - TwinPipe reduction factor (0.9 = 10% reduction)

#### Sizing Parameters
- `v_limit_trunk_ms: float = 1.5` - Target trunk velocity (≤1.5 m/s)
- `v_limit_service_ms: float = 1.5` - Target service velocity (≤1.5 m/s)
- `v_abs_max_ms: float = 2.5` - Hard cap (erosion/noise limit)
- `dp_per_m_max_pa: float = 200.0` - Pressure loss limit (Pa/m)
- `sizing_eco_mode: bool = False` - Conservative sizing (v_eco_mode_ms = 1.2 m/s)

#### Topology Parameters
- `crs: str = "EPSG:25833"` - Coordinate reference system (UTM Zone 33N)
- `prune_trunk_to_service_subtree: bool = True` - Remove dead-end trunk stubs

**Usage**:
```python
from branitz_heat_decision.cha.config import CHAConfig, get_default_config
cfg = get_default_config()
cfg.system_pressure_bar = 8.0
cfg.heat_loss_method = "linear"
```

**Interactions**:
- Used by all CHA modules (network builder, sizing, heat loss, KPI extractor)
- Default values validated against EN 13941-1 and engineering practice

---

### `network_builder_trunk_spur.py` (1,817 lines) ⭐ **PRIMARY MODULE**
**Purpose**: Build complete trunk-spur district heating network from GIS data

**Main Functions**:

#### `build_trunk_spur_network()` (Primary Entry Point)
```python
def build_trunk_spur_network(
    cluster_id: str,
    buildings: gpd.GeoDataFrame,
    streets: gpd.GeoDataFrame,
    plant_coords: Tuple[float, float],
    selected_street_name: Optional[str],
    design_loads_kw: Dict[str, float],
    pipe_catalog: pd.DataFrame,
    config: Optional[CHAConfig] = None,
    street_buffer_m: float = 15.0,
    max_spur_length_m: float = 50.0,
    attach_mode: str = 'split_edge_per_building',
    disable_auto_plant_siting: bool = False,
) -> Tuple[pp.pandapipesNet, Dict[str, Any]]
```

**Workflow**:
1. **Plant Siting**: Optionally re-site plant to nearby different street (if not disabled)
2. **Street Filtering**: Filter streets to cluster area (with progressive buffer expansion)
3. **Street Graph**: Build NetworkX graph from street centerlines
4. **Building Attachment**: Project buildings to nearest street edges (attach points)
5. **Trunk Topology**: Build radial (tree) trunk from plant to all attach points
6. **Spur Assignment**: Assign exclusive spur points for each building
7. **Edge Splitting**: Split trunk edges at attach points (tee-on-main)
8. **Pandapipes Creation**: Create dual-network (supply + return) with heat_consumers
9. **Pipe Sizing**: Size trunk and service pipes from catalog
10. **Heat Loss**: Apply per-pipe thermal loss parameters
11. **Trunk Pruning**: Remove dead-end trunk stubs (zero-flow branches)
12. **Plant Connection**: Connect plant (ext_grid + circulation pump)
13. **Convergence Optimization**: Run spur-specific optimizer
14. **Simulation**: Execute pandapipes.pipeflow() (hydraulic + thermal)

**Returns**:
- `pandapipesNet`: Converged network with all results
- `Dict[str, Any]`: Topology metadata (trunk edges, nodes, spurs, etc.)

**Helper Functions**:

- `_filter_streets_to_cluster()`: Filter streets by cluster bounding box
- `_build_street_graph()`: Create NetworkX graph from street GeoDataFrame
- `_nearest_graph_node_to_point()`: Find nearest graph node to coordinates
- `_compute_building_attach_nodes()`: Project buildings to street edges
- `_building_attach_targets()`: Collect unique attach target nodes
- `_bridge_disconnected_target_components()`: Bridge disconnected street components
- `_build_radial_trunk_edges()`: Build shortest-path tree (SPT) from plant
- `_choose_plant_coords_on_nearby_other_street()`: Re-site plant to different street
- `_build_main_trunk()`: Build trunk through all buildings (alternative method)
- `_assign_exclusive_spur_points()`: Assign unique spur points per building
- `_split_trunk_edges_at_attach_points()`: Split trunk edges at attach points (tee-on-main)
- `_create_trunk_spur_pandapipes()`: Create pandapipes network (junctions, pipes, heat_consumers)
- `_prune_trunk_to_service_subtree()`: Remove unused trunk edges
- `_apply_pipe_sizes()`: Apply DN sizes to network pipes
- `_apply_pipe_thermal_losses()`: Apply heat loss parameters per pipe

**Key Features**:
- **Radial Trunk**: Single-source shortest-path tree (no loops, ensures convergence)
- **Tee-on-Main**: Splits trunk edges at attach points (no trunk_conn artifacts)
- **Dual Network**: Separate supply and return circuits
- **Heat Consumers**: Uses `pp.create_heat_consumer()` (not sinks/sources)
- **TwinPipe Pairing**: Assigns `pair_id` to geometrically adjacent supply/return pipes
- **Automatic Plant Siting**: Places plant on nearby different street (if enabled)
- **Design Margin (NEW)**: Applies 25% design margin to pipe sizing loads for robustness
  - Ensures pipes can handle ±20% demand variation in Monte Carlo scenarios
  - Uses more conservative velocity limits (1.2 m/s instead of 1.5 m/s) for robustness
  - Results in larger pipe diameters, improving robustness validation success rate

**Interactions**:
- **Imports**: `sizing_catalog.size_trunk_and_spurs()`, `heat_loss.compute_heat_loss()`, `convergence_optimizer_spur.optimize_network_for_convergence()`
- **Uses**: `CHAConfig` for all parameters
- **Outputs**: Converged pandapipes network → KPI extractor, map generator

**Example Usage**:
```python
from branitz_heat_decision.cha.network_builder_trunk_spur import build_trunk_spur_network
net, topology = build_trunk_spur_network(
    cluster_id="ST010_HEINRICH_ZILLE_STRASSE",
    buildings=buildings_gdf,
    streets=streets_gdf,
    plant_coords=(455730.0, 5734773.0),
    selected_street_name="Heinrich Zille Strasse",
    design_loads_kw={"DEBBAL520000w9EL": 37.0, ...},
    pipe_catalog=catalog_df,
    config=cfg
)
# Network is already converged and simulated
```

---

### `network_builder.py` (352 lines)
**Purpose**: Legacy/alternative network builder (simpler topology)

**Main Functions**:
- `build_dh_network_for_cluster()`: Build network with simpler topology
- `build_street_graph()`: Create street graph
- `snap_plant_to_graph()`: Find nearest street node to plant
- `attach_buildings_to_street()`: Attach buildings to street graph
- `build_trunk_topology()`: Build trunk topology (paths_to_buildings mode)
- `create_pandapipes_network()`: Create pandapipes network

**Usage**: 
- Alternative to `network_builder_trunk_spur.py`
- Simpler but less robust (no tee-on-main, no spur-specific optimizer)
- **Recommended**: Use `network_builder_trunk_spur.py` instead

**Interactions**:
- Legacy workflow compatibility
- Superseded by `network_builder_trunk_spur.py`

---

### `sizing_catalog.py` (497 lines)
**Purpose**: Pipe sizing based on technical catalog and downstream demand

**Main Functions**:

#### `load_technical_catalog()`
```python
def load_technical_catalog(catalog_path: Path) -> pd.DataFrame
```
Loads DN catalog from Excel file (Technikkatalog Wärmeplanung) or default catalog.

**Catalog Format**:
- Excel sheets: `DN_Catalog`, `Rohrkatalog`, `Pipe_Catalog`
- OR: Technikkatalog Tab 45 ("Wärmenetze Kalte Nahwärme")
- Columns: `DN`, `inner_diameter_mm`, `inner_diameter_m`, `cost_eur_per_m`

#### `size_trunk_and_spurs()` ⭐ **PRIMARY SIZING FUNCTION**
```python
def size_trunk_and_spurs(
    net: pp.pandapipesNet,
    trunk_edges: List[Tuple],
    spur_assignments: Dict[str, Dict],
    design_loads_kw: Dict[str, float],
    pipe_catalog: pd.DataFrame,
    config: CHAConfig,
    plant_attach_node: Tuple[float, float],
) -> Dict[str, Any]
```

**Sizing Logic**:
1. **Downstream Demand Calculation**: 
   - Build tree structure from plant to buildings
   - For each trunk edge: `Q_down(edge) = Σ(design_loads_kw of downstream buildings)`
2. **Design Mass Flow**:
   - `mdot_design = Q_down / (cp × ΔT)` where `cp = 4.186 kJ/(kg·K)`, `ΔT = 40 K`
3. **DN Selection**:
   - Compute required diameter: `D_req = sqrt(4 × mdot / (π × ρ × v_target))`
   - Select smallest DN from catalog where `inner_diameter_m >= D_req`
   - Validate: `v_calc <= v_limit_ms` (trunk: 1.5 m/s, service: 1.5 m/s)
   - Hard fail if `v_calc > v_abs_max_ms` (2.5 m/s)
4. **Pressure Loss Check** (optional):
   - Estimate `dp_per_m_pa` using Darcy-Weisbach
   - Warn if `dp_per_m_pa > dp_per_m_max_pa` (200 Pa/m)
5. **Service Sizing**:
   - `mdot_service = building_q_kw / (cp × ΔT)`
   - Select DN satisfying `v <= v_limit_service_ms`

**Returns**:
- `pipe_sizes`: Dict mapping pipe names to DN labels
- `sizing_rationale_df`: DataFrame with Q_down, mdot_design, chosen_DN, v_calc, dp/L

**Helper Functions**:
- `_get_downstream_buildings()`: Compute downstream building set per trunk edge
- `_select_dn_from_catalog()`: Select smallest suitable DN from catalog
- `apply_pipe_sizes_to_network()`: Apply DN sizes to network (sets `diameter_m`, `std_type`)

**Interactions**:
- **Called by**: `network_builder_trunk_spur.py` (Step 5.5: Pipe Sizing)
- **Uses**: `CHAConfig` for velocity limits, catalog from Excel or default
- **Outputs**: Sized network → heat loss calculation, simulation

**Example Usage**:
```python
from branitz_heat_decision.cha.sizing_catalog import size_trunk_and_spurs
pipe_sizes, rationale_df = size_trunk_and_spurs(
    net=net,
    trunk_edges=trunk_edges,
    spur_assignments=spur_assignments,
    design_loads_kw={"B1": 37.0, "B2": 25.0, ...},
    pipe_catalog=catalog_df,
    config=cfg,
    plant_attach_node=plant_node
)
```

---

### `sizing.py` (131 lines)
**Purpose**: Legacy/alternative pipe sizing (simpler catalog-based)

**Main Functions**:
- `size_pipes_from_catalog()`: Legacy sizing function
- `load_pipe_catalog()`: Load default EN 10255 catalog

**Usage**: 
- Legacy compatibility
- **Recommended**: Use `sizing_catalog.py` instead (supports downstream-demand sizing)

**Interactions**:
- Alternative to `sizing_catalog.py`
- Superseded by `sizing_catalog.size_trunk_and_spurs()`

---

### `heat_loss.py` (546 lines) ⭐ **CRITICAL MODULE**
**Purpose**: Pipe heat loss modeling (linear W/m or thermal resistance U·A·ΔT)

**Classes**:

#### `HeatLossInputs` (Dataclass)
```python
@dataclass(frozen=True)
class HeatLossInputs:
    dn_mm: float
    length_m: float
    t_fluid_k: float
    t_soil_k: float
    role: str  # "trunk" | "service"
    circuit: str  # "supply" | "return"
    std_type: str | None = None
    outer_diameter_m: float | None = None
    insulation_thickness_m: float | None = None
    burial_depth_m: float = 1.0
    soil_k_w_mk: float = 1.5
    velocity_m_s: float | None = None
    pair_id: int | None = None  # For TwinPipe pairing
```

#### `HeatLossResult` (Dataclass)
```python
@dataclass(frozen=True)
class HeatLossResult:
    method: str  # "linear" | "thermal_resistance"
    q_loss_w_per_m: float  # Linear heat loss [W/m]
    q_loss_w: float  # Total segment loss [W] = q' × L
    u_w_per_m2k: float  # Overall heat transfer coefficient [W/m²K]
    text_k: float  # External temperature [K]
    delta_t_k: float | None = None
    diagnostics: Dict[str, float] | None = None
```

**Main Functions**:

#### `compute_heat_loss()` ⭐ **PRIMARY ENTRY POINT**
```python
def compute_heat_loss(
    in_: HeatLossInputs,
    cfg: CHAConfig,
    catalog: Optional[Dict[str, Any]] = None
) -> HeatLossResult
```

**Method Selection**:
- **Method 1 (linear)**: `q' [W/m]` from catalog/datasheet (planning method)
  - Formula: `q' = q_catalog × (T_fluid - T_soil) / (T_ref - T_soil_ref)`
  - Conversion to `u_w_per_m2k`: `u = q' / (A_eff × ΔT)` where `A_eff = d_o` (pandapipes convention)
- **Method 2 (thermal_resistance)**: `U` from thermal resistances → `q'`
  - Formula: `1/U = R = R_conv_int + R_pipe + R_insulation + R_soil`
  - `q' = U × A_eff × (T_fluid - T_soil)`

**Helper Functions**:
- `_make_cache_key()`: Create hashable cache key for `@lru_cache`
- `_compute_heat_loss_cached()`: Cached version (for large networks >1000 pipes)
- `_compute_heat_loss_impl()`: Internal implementation (routes to linear/thermal_resistance)
- `_compute_linear_heat_loss()`: Linear W/m method with temperature scaling
- `_compute_thermal_resistance_heat_loss()`: U-value from thermal resistances
- `adjust_for_pairing()`: TwinPipe correction factor (applies `q_adj' = q' × twinpipe_loss_factor`)
- `compute_temperature_drop_along_pipe()`: Temperature drop from heat loss
- `compute_temperature_profile_exponential()`: Exponential temperature profile

**Key Features**:
- **Temperature Scaling**: Linear method scales `q'` by actual vs. reference temperatures
- **Effective Area Convention**: `A_eff = d_o` (verified via integration test, not `π × d_o`)
- **TwinPipe Correction**: Applies reduction factor (default 0.9 = 10% reduction) for paired pipes
- **Caching**: Optional `@lru_cache` for large networks (configurable via `_enable_heat_loss_cache`)

**Interactions**:
- **Called by**: `network_builder_trunk_spur._apply_pipe_thermal_losses()` (per-pipe application)
- **Uses**: `CHAConfig` for method, reference temps, TwinPipe settings
- **Outputs**: `u_w_per_m2k`, `text_k` → stored in `net.pipe` for pandapipes simulation

**Example Usage**:
```python
from branitz_heat_decision.cha.heat_loss import compute_heat_loss, HeatLossInputs
result = compute_heat_loss(
    HeatLossInputs(
        dn_mm=50.0,
        length_m=100.0,
        t_fluid_k=353.15,  # 80°C
        t_soil_k=285.15,   # 12°C
        role="trunk",
        circuit="supply",
        pair_id="trunk_seg_0"
    ),
    cfg=config,
    catalog={"DN50": {"q_linear_w_per_m": 30.0}}
)
# result.u_w_per_m2k → stored in net.pipe['u_w_per_m2k']
# result.text_k → stored in net.pipe['text_k']
```

---

### `convergence_optimizer_spur.py` (266 lines) ⭐ **CRITICAL FOR CONVERGENCE**
**Purpose**: Convergence optimization for trunk-spur networks

**Classes**:

#### `SpurConvergenceOptimizer`
```python
class SpurConvergenceOptimizer:
    def __init__(self, net: pp.pandapipesNet, config: Optional[CHAConfig] = None)
    def optimize_with_spur_checks(
        self,
        max_iterations: int = 3,
        ensure_spur_diversity: bool = True,
        add_trunk_loops: bool = True,
        max_junction_degree: int = 4
    ) -> Tuple[bool, Dict[str, Any]]
```

**Optimization Steps**:
1. **Topology Validation**:
   - Building junctions: degree must be exactly 2 (supply + return)
   - Spur junctions: degree must be 3 (trunk + supply + return)
   - Trunk junctions: degree ≤ 4 (for radial, typically ≤3)
2. **Connectivity Check**: Ensure all junctions are connected
3. **Short Pipe Fix**: Replace pipes <1m with minimum length (1m)
4. **Pressure Initialization**: Improve initial pressures based on distance from plant
5. **Simulation**: Run `pp.pipeflow()` and check convergence

**Helper Functions**:
- `_validate_spur_topology()`: Validate trunk-spur topology rules
- `_apply_spur_fixes()`: Apply fixes based on validation issues
- `_bridge_disconnected_components()`: Bridge disconnected graph components

#### `optimize_network_for_convergence()` (Convenience Wrapper)
```python
def optimize_network_for_convergence(
    net: pp.pandapipesNet,
    config: Optional[CHAConfig] = None,
    **kwargs
) -> Tuple[bool, pp.pandapipesNet, Dict[str, Any]]
```

**Interactions**:
- **Called by**: `network_builder_trunk_spur.build_trunk_spur_network()` (Step 5.6)
- **Uses**: `CHAConfig` for min pipe length, pressure settings
- **Outputs**: Converged network → KPI extractor

**Example Usage**:
```python
from branitz_heat_decision.cha.convergence_optimizer_spur import optimize_network_for_convergence
converged, net, summary = optimize_network_for_convergence(net, config=cfg)
```

---

### `convergence_optimizer.py` (327 lines)
**Purpose**: Legacy/alternative convergence optimizer (general topology)

**Classes**:
- `ConvergenceOptimizer`: General-purpose optimizer (adds loops, roughness variations, etc.)

**Usage**: 
- Legacy compatibility
- **Recommended**: Use `convergence_optimizer_spur.py` for trunk-spur networks

**Interactions**:
- Alternative to `convergence_optimizer_spur.py`
- Superseded for trunk-spur networks

---

### `kpi_extractor.py` (550 lines) ⭐ **KPI GENERATION**
**Purpose**: Extract EN 13941-1 compliant KPIs from converged networks

**Classes**:

#### `KPIExtractor`
```python
class KPIExtractor:
    def __init__(self, net: pp.pandapipesNet, config: Optional[CHAConfig] = None)
    def extract_kpis(
        self,
        cluster_id: str,
        design_hour: int,
        detailed: bool = True
    ) -> Dict[str, Any]
```

**KPI Categories**:

1. **Hydraulics**:
   - `v_max_ms`: Maximum velocity (must be ≤1.5 m/s per EN 13941-1)
   - `v_min_ms`: Minimum velocity
   - `v_mean_ms`: Mean velocity
   - `v_share_within_limits`: Share of pipes ≤1.5 m/s (must be ≥95%)
   - `dp_per_100m_max`: Maximum pressure drop per 100m (must be ≤0.3 bar/100m)

2. **Thermal**:
   - `supply_temp_c`: Supply temperature (°C)
   - `return_temp_c`: Return temperature (°C)
   - `temp_diff_k`: Temperature difference (K)
   - `max_temp_drop_c`: Maximum temperature drop along pipes (°C)

3. **Losses**:
   - `total_thermal_loss_kw`: Total heat loss (kW) - computed from temperature drop
   - `loss_share_percent`: Loss share (%) = `100 × Q_loss / Q_delivered`
   - `loss_per_100m_kw`: Heat loss per 100m (kW/100m)
   - `length_total_m`, `length_trunk_m`, `length_service_m`: Pipe lengths

4. **Pump**:
   - `pump_power_kw`: Circulation pump power (kW)
   - `pump_power_per_kwth`: Pump power per kW thermal delivered

5. **EN 13941-1 Compliance**:
   - `feasible`: Overall feasibility (velocity + pressure drop compliance)
   - `velocity_ok`: Velocity compliance (≥95% within limits)
   - `dp_ok`: Pressure drop compliance (≤0.3 bar/100m)
   - `reasons`: Reason codes (`DH_OK`, `DH_VELOCITY_VIOLATION`, `DH_DP_VIOLATION`)

**Helper Functions**:
- `_extract_pipe_kpis()`: Extract pipe-level KPIs (velocity, pressure, temperature, heat loss)
- `_extract_network_kpis()`: Extract network-level KPIs (total heat, mass flow, pump power)
- `_compute_aggregate_kpis()`: Compute aggregate statistics (min/max/mean/std)
- `_check_en13941_compliance()`: Check EN 13941-1 standard compliance
- `_extract_junction_kpis()`: Extract junction-level KPIs (pressure, temperature)
- `_extract_heat_consumer_kpis()`: Extract heat consumer KPIs (heat demand per building)
- `_extract_sink_kpis()`: Extract sink KPIs (legacy compatibility)

**Heat Loss Calculation**:
- **Method**: Computed from temperature drop (pandapipes doesn't store `qext_w` in `res_pipe`)
- **Formula**: `Q_loss = mdot × cp × (T_from - T_to)` where `cp = 4.186 kJ/(kg·K)`
- **Per-Pipe**: `heat_loss_kw = (mdot × cp × ΔT) / 1000.0`
- **Total**: Sum of all pipe losses

**Interactions**:
- **Called by**: `01_run_cha.py` (after simulation)
- **Uses**: `CHAConfig` for physical constants, `res_pipe`, `res_junction`, `res_heat_consumer`
- **Outputs**: KPI dictionary → Decision pipeline, UHDC report

**Example Usage**:
```python
from branitz_heat_decision.cha.kpi_extractor import KPIExtractor
extractor = KPIExtractor(net, config=cfg)
kpis = extractor.extract_kpis(cluster_id="ST010", design_hour=6667, detailed=True)
# kpis['hydraulics']['v_max_ms'] → maximum velocity
# kpis['losses']['loss_share_percent'] → 18.62%
# kpis['en13941_compliance']['feasible'] → True/False
```

---

### `hydraulic_checks.py` (343 lines) ⭐ **VALIDATION MODULE**
**Purpose**: Hydraulic validation based on EN 13941-1 standards with context-aware warnings

**Classes**:

#### `HydraulicValidator`
```python
class HydraulicValidator:
    def __init__(self, config)
    def validate(self, net: pp.pandapipesNet) -> HydraulicResult
```

**Validation Checks**:

1. **Velocity Checks** (`_check_velocities()`):
   - Maximum velocity: Must be ≤1.5 m/s (recommended) or ≤3.0 m/s (absolute)
   - Minimum velocity: Warns if <0.2 m/s (sedimentation risk)
   - **Context-Aware (NEW)**: Automatically detects trunk-spur networks and provides context-aware warnings
     - Explains that low velocity in return pipes and spurs is expected
     - Only flags as warning if >50% of pipes have low velocity in trunk-spur networks
     - Provides mitigation guidance (periodic flushing)

2. **Pressure Checks** (`_check_pressures()`):
   - Maximum pressure: Must be ≤16 bar (typical PN16 limit)
   - Minimum pressure: Must be ≥1.0 bar (cavitation prevention)
   - Pressure drops: Warns if >1.0 bar/km or >2.0 bar total

3. **Pump Power Checks** (`_check_pump_power()`):
   - Specific pump power: Must be ≤30 W/kW_th (efficiency check)
   - Absolute pump power: Heuristic check for excessive power

4. **Flow Distribution Checks** (`_check_flow_distribution()`) ⭐ **NEW**:
   - Calculates coefficient of variation (CV) of flow rates
   - Warns if CV > 1.0 (high variation)
   - **Context-Aware (NEW)**: For trunk-spur networks, explains that high CV is expected
     - Trunk pipes carry aggregated high flow
     - Spur pipes carry single-building low flow
     - This is a design feature, not a flaw

**Context-Aware Detection**:
- Detects trunk-spur networks by checking for:
  - Dual pipes (supply "S" + return "R" naming convention)
  - Pipe names containing "spur" or "trunk"
- Adjusts warning messages to explain expected behavior
- Maintains strict checks for critical issues (high velocity, pressure problems)

**Returns**:
- `HydraulicResult` with:
  - `passed`: bool (True if no issues)
  - `issues`: List[str] (critical problems)
  - `warnings`: List[str] (context-aware warnings)
  - `metrics`: Dict with velocity, pressure, pump power, flow CV

**Interactions**:
- **Called by**: `design_validator.py` (design validation system)
- **Uses**: `ValidationConfig.en13941` for thresholds
- **Outputs**: Validation results → design validation report

**Example Usage**:
```python
from branitz_heat_decision.cha.hydraulic_checks import HydraulicValidator
from branitz_heat_decision.config.validation_standards import get_default_validation_config

validator = HydraulicValidator(get_default_validation_config())
result = validator.validate(net)
# result.passed → True/False
# result.warnings → ["230 pipes have velocity < 0.2 m/s (expected in trunk-spur networks: ...)"]
```

---

### `design_validator.py` (334 lines) ⭐ **DESIGN VALIDATION SYSTEM**
**Purpose**: Comprehensive design validation orchestrator

**Classes**:

#### `DHNetworkDesignValidator`
```python
class DHNetworkDesignValidator:
    def __init__(self, config: ValidationConfig)
    def validate_design(
        self,
        net: pp.pandapipesNet,
        cluster_id: str,
        streets_gdf: Optional[gpd.GeoDataFrame] = None,
        buildings_gdf: Optional[gpd.GeoDataFrame] = None,
        run_robustness: bool = False
    ) -> ValidationReport
```

**Validation Categories**:
1. **Geospatial Validation**: Building connectivity, network topology, street alignment
2. **Hydraulic Validation**: Velocity, pressure, flow distribution (EN 13941-1) with context-aware warnings
3. **Thermal Validation**: Temperature distribution, heat losses
4. **Robustness Validation**: Monte Carlo uncertainty analysis (50 scenarios with ±20% demand variation)

**Output**:
- `ValidationReport` with:
  - Overall status: `PASS`, `PASS_WITH_WARNINGS`, or `FAIL`
  - Individual check results (geospatial, hydraulic, thermal, robustness)
  - All issues and warnings (with context-aware explanations)
  - Comprehensive metrics

**Interactions**:
- **Called by**: `01_run_cha_with_validation.py` (validation pipeline)
- **Uses**: `GeospatialValidator`, `HydraulicValidator`, `ThermalValidator`, `RobustnessValidator`
- **Outputs**: `design_validation.json`, `design_validation_summary.txt`, `design_validation_metrics.csv`

**Documentation**:
- See `DESIGN_VALIDATION_EXPLAINED.md` for detailed validation process
- See `VALIDATION_WARNINGS_EXPLAINED.md` for context-aware warning explanations
- See `HOW_TO_FIX_VALIDATION_ISSUES.md` for troubleshooting guide
- See `WARNING_MITIGATION_OPTIONS.md` for options to address warnings

---

### `qgis_export.py` (1,501 lines) ⭐ **VISUALIZATION MODULE**
**Purpose**: Generate interactive maps and CSV exports for CHA results

**Main Functions**:

#### `create_interactive_map()` ⭐ **PRIMARY MAP FUNCTION**
```python
def create_interactive_map(
    net: pp.pandapipesNet,
    buildings: gpd.GeoDataFrame,
    cluster_id: str,
    output_path: Path,
    map_type: str = "velocity",  # "velocity" | "temperature" | "pressure"
    config: Optional[CHAConfig] = None,
) -> None
```

**Map Types**:
1. **Velocity Map** (`interactive_map.html`):
   - Colors: Cascading red shades for supply, blue shades for return
   - Scale: Based on actual min/max velocity values
   - Thickness: Proportional to DN (trunk: 4-12px, service: 2-7px)
2. **Temperature Map** (`interactive_map_temperature.html`):
   - Colors: Red shades (hot) to blue shades (cold)
   - Shows: `t_from_k`, `t_to_k`, cascading along flow direction
3. **Pressure Map** (`interactive_map_pressure.html`):
   - Colors: Red shades (high pressure) to blue shades (low pressure)
   - Shows: `p_from_bar`, `p_to_bar`, `p_mean_bar` (flow-aligned)

**Map Features**:
- **Pipe Visualization**:
  - Trunk pipes: Thick lines (weight: 4-12px based on DN)
  - Service pipes: Thin dashed lines (weight: 2-7px based on DN)
  - Colors: Fixed (supply=red `#d73027`, return=blue `#2166ac`) with cascading shades
- **Buildings**: CircleMarkers with heat demand as radius
- **Plant**: Red Marker at plant location
- **Pump**: Indicated near plant (if present)
- **Legend**: Colorbar with min/max values and DN thickness scale
- **Layer Control**: Toggle trunk, service, buildings, plant
- **Tooltips**: DN, velocity, temperature, pressure per pipe

#### `export_pipe_velocity_csvs()`
```python
def export_pipe_velocity_csvs(
    net: pp.pandapipesNet,
    cluster_id: str,
    output_dir: Path,
    config: Optional[CHAConfig] = None,
) -> List[Path]
```

**Generated CSVs**:
1. `pipe_velocities_supply_return.csv`: All pipes (supply + return) with velocities
2. `pipe_velocities_supply_return_with_temp.csv`: Velocities + temperatures
3. `pipe_velocities_plant_to_plant_main_path.csv`: Main path from plant to plant
4. `pipe_pressures_supply_return.csv`: Pressures (p_from, p_to, p_mean, color)

**CSV Columns**:
- `pipe_name`, `from_junction`, `to_junction`, `length_m`
- `velocity_ms`, `velocity_vmin_ms`, `velocity_vmax_ms`, `color_velocity_hex`
- `t_from_k`, `t_to_k`, `temperature_vmin_k`, `temperature_vmax_k`, `color_temperature_hex`
- `p_from_bar`, `p_to_bar`, `p_mean_bar`, `pressure_vmin_bar`, `pressure_vmax_bar`, `color_pressure_hex`

**Helper Functions**:
- `pipe_weight()`: Map DN to folium line weight (trunk: 4-12px, service: 2-7px)
- `_parse_dn_from_std_type()`: Extract DN from std_type string
- `_identify_circulation_pump()`: Find circulation pump junction
- `_identify_plant_junction()`: Find plant supply junction
- `_get_junction_coordinates()`: Get junction coordinates from geodata
- `_extract_pipe_geometries()`: Extract pipe LineString geometries
- `_extract_junction_geometries()`: Extract junction Point geometries
- `export_network_to_qgis()`: Export to GeoPackage (QGIS format)

**Interactions**:
- **Called by**: `01_run_cha.py` (after KPI extraction)
- **Uses**: `net.res_pipe`, `net.pipe`, `net.junction`, `CHAConfig` for color scales
- **Outputs**: HTML maps + CSVs → UHDC report (maps embedded)

**Example Usage**:
```python
from branitz_heat_decision.cha.qgis_export import create_interactive_map, export_pipe_velocity_csvs
create_interactive_map(net, buildings, "ST010", Path("results/cha/ST010/interactive_map.html"), map_type="velocity")
create_interactive_map(net, buildings, "ST010", Path("results/cha/ST010/interactive_map_temperature.html"), map_type="temperature")
create_interactive_map(net, buildings, "ST010", Path("results/cha/ST010/interactive_map_pressure.html"), map_type="pressure")
csvs = export_pipe_velocity_csvs(net, "ST010", Path("results/cha/ST010"))
```

---

## Complete Workflow

### End-to-End Pipeline

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. INPUT: GIS Data (buildings, streets, design loads)          │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 2. NETWORK BUILDING (network_builder_trunk_spur.py)            │
│    - Filter streets to cluster area                             │
│    - Build street graph (NetworkX)                              │
│    - Project buildings to streets (attach points)               │
│    - Build radial trunk (shortest-path tree)                    │
│    - Assign exclusive spurs                                     │
│    - Split trunk edges at attach points (tee-on-main)           │
│    - Create pandapipes network (dual: supply + return)          │
│    - Create heat_consumers (not sinks/sources)                  │
│    - Assign pair_id for TwinPipe                                │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 3. PIPE SIZING (sizing_catalog.py)                             │
│    - Compute downstream demand per trunk edge                   │
│    - Calculate design mass flow: mdot = Q / (cp × ΔT)          │
│    - Select DN from catalog: D >= sqrt(4×mdot/(π×ρ×v))         │
│    - Validate: v <= v_limit (1.5 m/s target, 2.5 m/s cap)     │
│    - Apply DN to network (diameter_m, std_type)                 │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 4. HEAT LOSS MODELING (heat_loss.py)                           │
│    - For each pipe: compute_heat_loss()                        │
│    - Method 1 (linear): q' = q_catalog × T_scaling             │
│    - Method 2 (thermal_resistance): U from resistances          │
│    - Convert to u_w_per_m2k: u = q' / (A_eff × ΔT)            │
│    - Apply TwinPipe correction: q_adj' = q' × 0.9              │
│    - Store: net.pipe['u_w_per_m2k'], net.pipe['text_k']        │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 5. TOPOLOGY PRUNING (network_builder_trunk_spur.py)            │
│    - Prune trunk to minimal service subtree                     │
│    - Remove dead-end trunk stubs (zero-flow branches)           │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 6. PLANT CONNECTION (network_builder_trunk_spur.py)            │
│    - Create ext_grid at plant supply (p_bar, t_k)              │
│    - Create circulation pump (return → supply, Δp only)        │
│    - NO ext_grid at return (avoid over-constraint)              │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 7. CONVERGENCE OPTIMIZATION (convergence_optimizer_spur.py)    │
│    - Validate topology (degree checks)                          │
│    - Fix short pipes (<1m → 1m minimum)                        │
│    - Improve initial pressures                                  │
│    - Bridge disconnected components (if needed)                 │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 8. SIMULATION (pandapipes.pipeflow)                            │
│    - Hydraulic simulation (pressure, velocity, mass flow)       │
│    - Thermal simulation (temperature, heat loss)                │
│    - Check convergence: net.converged == True                   │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 9. KPI EXTRACTION (kpi_extractor.py)                           │
│    - Extract pipe-level KPIs (velocity, pressure, temp, loss)  │
│    - Compute network-level aggregates                           │
│    - Check EN 13941-1 compliance                                │
│    - Calculate heat losses from temperature drop                │
│    - Generate detailed pipe/junction/consumer KPIs              │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 10. VISUALIZATION (qgis_export.py)                             │
│     - Generate velocity map (cascading colors)                  │
│     - Generate temperature map (cascading colors)               │
│     - Generate pressure map (cascading colors)                  │
│     - Export CSVs (velocities, temperatures, pressures)         │
│     - Export GeoPackage (QGIS format)                           │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ OUTPUT: KPIs (JSON), Network (pickle), Maps (HTML), CSVs       │
└─────────────────────────────────────────────────────────────────┘
```

---

## File Interactions & Dependencies

### Internal Dependencies (Within CHA Module)

```
config.py
  └─→ Used by ALL modules (CHAConfig)

network_builder_trunk_spur.py (PRIMARY)
  ├─→ imports sizing_catalog.size_trunk_and_spurs()
  ├─→ imports heat_loss.compute_heat_loss()
  ├─→ imports convergence_optimizer_spur.optimize_network_for_convergence()
  ├─→ imports sizing.load_pipe_catalog() [fallback]
  └─→ uses CHAConfig for all parameters

sizing_catalog.py
  ├─→ uses CHAConfig (velocity limits, sizing parameters)
  └─→ uses pipe_catalog (Excel or default DataFrame)

heat_loss.py
  ├─→ uses CHAConfig (method, reference temps, TwinPipe settings)
  └─→ uses pipe_catalog (for q' lookup in linear method)

convergence_optimizer_spur.py
  └─→ uses CHAConfig (min pipe length, pressure settings)

kpi_extractor.py
  ├─→ uses CHAConfig (physical constants, delta_t_k)
  └─→ reads: net.res_pipe, net.res_junction, net.res_heat_consumer

qgis_export.py
  ├─→ uses CHAConfig (color scales, DN scales)
  └─→ reads: net.pipe, net.res_pipe, net.junction, net.res_junction
```

### External Dependencies (Outside CHA Module)

```
CHA Module
  ├─→ imports from ..config (resolve_cluster_path, DATA_PROCESSED)
  ├─→ imports from ..data.cluster (normalize_street_name)
  └─→ uses pandapipes (pp.create_empty_network, pp.pipeflow, ...)

Called by:
  └─→ src/scripts/01_run_cha.py (main pipeline script)
```

### Data Flow

```
Input (01_run_cha.py):
  ├─→ buildings.parquet (GeoDataFrame)
  ├─→ streets.geojson (GeoDataFrame)
  ├─→ hourly_heat_profiles.parquet (8760 × N_buildings)
  ├─→ cluster_design_topn.json (design hour + TopN)
  └─→ pipe_catalog (Excel or default DataFrame)

Processing (CHA modules):
  └─→ network_builder_trunk_spur.py orchestrates all steps

Output (results/cha/<cluster_id>/):
  ├─→ cha_kpis.json (KPIExtractor output)
  ├─→ network.pickle (pandapipesNet)
  ├─→ interactive_map.html (velocity)
  ├─→ interactive_map_temperature.html (temperature)
  ├─→ interactive_map_pressure.html (pressure)
  ├─→ pipe_velocities_supply_return.csv
  ├─→ pipe_velocities_supply_return_with_temp.csv
  ├─→ pipe_velocities_plant_to_plant_main_path.csv
  ├─→ pipe_pressures_supply_return.csv
  └─→ pipe_sizing_rationale.csv (from sizing_catalog)
```

---

## Key Algorithms & Methods

### 1. Radial Trunk Topology (`_build_radial_trunk_edges()`)

**Algorithm**: Single-Source Shortest-Path Tree (SPT)

```python
# Build SPT from plant to all target nodes
G = street_graph  # NetworkX graph with edge weights (length_m)
plant_node = plant_attach_node
target_nodes = building_attach_targets

# Compute shortest paths
paths = {}
for target in target_nodes:
    if nx.has_path(G, plant_node, target):
        paths[target] = nx.shortest_path(G, plant_node, target, weight="length_m")

# Extract unique edges from all paths (union of shortest paths)
trunk_edges = []
edge_set = set()
for path in paths.values():
    for i in range(len(path) - 1):
        edge = tuple(sorted([path[i], path[i+1]]))
        if edge not in edge_set:
            edge_set.add(edge)
            trunk_edges.append((path[i], path[i+1]))

# Result: Radial tree (no cycles, |E| = |V| - 1)
```

**Properties**:
- Acyclic (no loops) → ensures convergence
- Minimal length (shortest paths) → cost-optimal
- Single plant root → physically correct

---

### 2. Tee-on-Main Splitting (`_split_trunk_edges_at_attach_points()`)

**Algorithm**: Edge splitting at projection points

```python
# For each trunk edge (u, v) with attach points:
for edge, attach_points in edge_to_points.items():
    # Sort attach points along edge geometry
    line = edge.geometry  # LineString
    sorted_points = sorted(attach_points, key=lambda p: line.project(p))
    
    # Replace edge (u, v) with chain: u → a1 → a2 → ... → v
    chain_nodes = [u]
    for point in sorted_points:
        new_node = (round(point.x, 2), round(point.y, 2))
        chain_nodes.append(new_node)
        attach_node_for_building[building_id] = new_node
    chain_nodes.append(v)
    
    # Create edges: (u, a1), (a1, a2), ..., (a_n, v)
    for i in range(len(chain_nodes) - 1):
        new_trunk_edges.append((chain_nodes[i], chain_nodes[i+1]))
```

**Result**:
- Each building has its own trunk tee node (no trunk_conn artifacts)
- Service pipes connect directly to trunk (no intermediate junctions)

---

### 3. Downstream-Demand Sizing (`size_trunk_and_spurs()`)

**Algorithm**: Tree accumulation from leaves to root

```python
# Build tree structure (directed graph from plant to buildings)
G_tree = nx.DiGraph()
for edge in trunk_edges:
    G_tree.add_edge(edge[0], edge[1])  # Plant → leaves

# For each trunk edge: compute downstream building set
def get_downstream_buildings(edge, G_tree, spur_assignments):
    v = edge[1]  # Downstream node
    downstream = set()
    for successor in nx.descendants(G_tree, v):
        # Find buildings attached to successor or its descendants
        for bid, assignment in spur_assignments.items():
            if assignment['trunk_node'] == successor:
                downstream.add(bid)
    return downstream

# Accumulate demand
for edge in trunk_edges:
    downstream_buildings = get_downstream_buildings(edge, G_tree, spur_assignments)
    Q_down_kw = sum(design_loads_kw[bid] for bid in downstream_buildings)
    mdot_design = Q_down_kw / (cp * delta_t_k)  # kg/s
    # Select DN: smallest where inner_diameter_m >= sqrt(4×mdot/(π×ρ×v))
```

**Result**:
- Trunk pipes taper: larger near plant, smaller toward periphery
- Matches real DH behavior (downstream demand accumulation)

---

### 4. Heat Loss Calculation (`compute_heat_loss()`)

**Method 1 (Linear)**:
```python
# Catalog lookup: q' at reference temperatures
q_catalog_w_per_m = catalog.get(dn_mm, default_q_w_per_m)

# Temperature scaling
T_ref = cfg.t_linear_ref_k  # 80°C
T_soil_ref = cfg.t_soil_ref_k  # 12°C
T_fluid = in_.t_fluid_k  # Actual fluid temp
T_soil = in_.t_soil_k  # Actual soil temp

if T_fluid > T_soil and T_ref > T_soil_ref:
    q_scaled = q_catalog_w_per_m * (T_fluid - T_soil) / (T_ref - T_soil_ref)
else:
    q_scaled = q_catalog_w_per_m

# TwinPipe correction
if in_.pair_id is not None and cfg.supply_return_interaction:
    q_scaled *= cfg.twinpipe_loss_factor  # 0.9 = 10% reduction

# Convert to u_w_per_m2k (pandapipes convention: A_eff = d_o)
d_o_m = in_.outer_diameter_m or (dn_mm / 1000.0 + 0.1)
A_eff_per_m = d_o_m  # "d" convention (verified via integration test)
delta_t_k = T_fluid - T_soil
u_w_per_m2k = q_scaled / (A_eff_per_m * delta_t_k) if delta_t_k > 0 else 0.0
```

**Method 2 (Thermal Resistance)**:
```python
# Thermal resistances
R_conv_int = 1 / (h_i × π × d_i)  # Internal convection
R_pipe = ln(d_o/d_i) / (2π × k_pipe × L)  # Pipe wall
R_insulation = ln((d_o + 2×t_ins)/d_o) / (2π × k_ins × L)  # Insulation
R_soil = ln(2×h/d_o) / (2π × k_soil × L)  # Soil (burial)

R_total = R_conv_int + R_pipe + R_insulation + R_soil
U = 1 / R_total  # W/m²K

# Heat loss
A_eff_per_m = d_o_m  # "d" convention
q_loss_w_per_m = U × A_eff_per_m × (T_fluid - T_soil)
u_w_per_m2k = U
```

---

### 5. Heat Loss from Simulation (`kpi_extractor._extract_network_kpis()`)

**Problem**: Pandapipes doesn't store `qext_w` in `res_pipe`

**Solution**: Compute from temperature drop

```python
# For each pipe:
for pipe_idx, pipe in net.pipe.iterrows():
    res = net.res_pipe.loc[pipe_idx]
    t_from_k = res['t_from_k']
    t_to_k = res['t_to_k']
    mdot = abs(res['mdot_from_kg_per_s'])
    
    if t_from_k is not np.nan and t_to_k is not np.nan and mdot > 0:
        delta_t_k = abs(t_from_k - t_to_k)
        cp_j_per_kgk = 4.186 * 1000.0  # J/(kg·K)
        pipe_loss_kw = (mdot * cp_j_per_kgk * delta_t_k) / 1000.0
        total_heat_loss_kw += pipe_loss_kw

# Total loss share
loss_share_percent = 100 * total_heat_loss_kw / total_heat_demand_kw
```

**Result**:
- Accurate heat loss from actual simulation results
- Accounts for both linear loss (u_w_per_m2k) and temperature-dependent effects

---

## Configuration Parameters Reference

### `CHAConfig` Complete Parameter List

#### Hydraulic Settings
| Parameter | Default | Range | Description |
|-----------|---------|-------|-------------|
| `system_pressure_bar` | 8.0 | 6-10 | Plant supply pressure (DH-realistic) |
| `pump_plift_bar` | 3.0 | 2-4 | Circulation pump differential pressure |
| `p_min_bar_allowed` | 1.5 | 1.5-2.0 | Minimum absolute pressure sanity gate |

#### Thermal Settings
| Parameter | Default | Description |
|-----------|---------|-------------|
| `supply_temp_k` | 363.15 | Supply temperature (90°C) |
| `return_temp_k` | 323.15 | Return temperature (50°C) |
| `delta_t_k` | 40.0 | Temperature difference (computed: supply - return) |
| `soil_temp_k` | 285.15 | Soil/ambient temperature (12°C) |

#### Heat Loss Settings
| Parameter | Default | Options | Description |
|-----------|---------|---------|-------------|
| `heat_loss_method` | `"linear"` | `"linear"` \| `"thermal_resistance"` | Heat loss calculation method |
| `heat_loss_area_convention` | `"d"` | `"d"` \| `"pi_d"` | Pandapipes A_eff convention (`"d"` verified) |
| `default_q_linear_trunk_w_per_m` | 30.0 | - | Default trunk heat loss (W/m) |
| `default_q_linear_service_w_per_m` | 25.0 | - | Default service heat loss (W/m) |
| `t_linear_ref_k` | 353.15 | - | Catalog reference fluid temp (80°C) |
| `t_soil_ref_k` | 285.15 | - | Catalog reference soil temp (12°C) |
| `supply_return_interaction` | True | True \| False | Enable TwinPipe correction |
| `twinpipe_loss_factor` | 0.9 | 0.9-1.0 | TwinPipe reduction factor (0.9 = 10% reduction) |

#### Sizing Settings
| Parameter | Default | Description |
|-----------|---------|-------------|
| `v_limit_trunk_ms` | 1.5 | Target trunk velocity (≤1.5 m/s) |
| `v_limit_service_ms` | 1.5 | Target service velocity (≤1.5 m/s) |
| `v_abs_max_ms` | 2.5 | Hard cap (erosion/noise limit) |
| `dp_per_m_max_pa` | 200.0 | Pressure loss limit (Pa/m) |
| `sizing_eco_mode` | False | Conservative sizing (v_eco_mode_ms = 1.2 m/s) |

#### Topology Settings
| Parameter | Default | Description |
|-----------|---------|-------------|
| `crs` | `"EPSG:25833"` | Coordinate reference system (UTM Zone 33N) |
| `prune_trunk_to_service_subtree` | True | Remove dead-end trunk stubs |

---

## Integration with Other Modules

### CHA → Decision Pipeline

```
CHA Output (results/cha/<cluster_id>/cha_kpis.json)
    ↓
Decision Module (src/branitz_heat_decision/decision/kpi_contract.py)
    └─→ Builds KPI contract with CHA hydraulics, losses, compliance
    ↓
Decision Rules (src/branitz_heat_decision/decision/rules.py)
    └─→ Evaluates feasibility (DH_OK, DH_VELOCITY_VIOLATION, etc.)
    ↓
UHDC Report (src/branitz_heat_decision/uhdc/report_builder.py)
    └─→ Embeds CHA maps (velocity, temperature, pressure) in HTML dashboard
```

### CHA → DHA Pipeline

```
CHA Output (heat demand profiles)
    ↓
DHA Module (src/branitz_heat_decision/dha/loadflow.py)
    └─→ Converts heat demand to HP electrical load: P_el = Q_th / COP
    └─→ Injects HP loads into LV grid for hosting capacity analysis
```

### CHA → Economics Pipeline

```
CHA KPIs (pump_power_kw, total_losses_kw, length_total_m)
    ↓
Economics Module (src/branitz_heat_decision/economics/lcoh.py)
    └─→ Computes DH LCOH: CAPEX (pipes) + OPEX (pump + losses) / CRF
    └─→ Uses losses for annual energy loss cost calculation
```

---

## Usage Examples

### Complete Pipeline Execution

```python
from branitz_heat_decision.cha.config import get_default_config
from branitz_heat_decision.cha.network_builder_trunk_spur import build_trunk_spur_network
from branitz_heat_decision.cha.sizing_catalog import load_technical_catalog
from branitz_heat_decision.cha.kpi_extractor import KPIExtractor
from branitz_heat_decision.cha.qgis_export import create_interactive_map, export_pipe_velocity_csvs
import pandas as pd
import geopandas as gpd

# 1. Load data
buildings = gpd.read_parquet("data/processed/buildings.parquet")
streets = gpd.read_file("data/processed/streets.geojson")
hourly_profiles = pd.read_parquet("data/processed/hourly_heat_profiles.parquet")
design_loads = {bid: hourly_profiles.loc[design_hour, bid] for bid in hourly_profiles.columns}

# 2. Load pipe catalog
catalog = load_technical_catalog(Path("data/raw/Technikkatalog_Wärmeplanung_Version_1.1_August24_CC-BY (1).xlsx"))

# 3. Configure
cfg = get_default_config()
cfg.system_pressure_bar = 8.0
cfg.heat_loss_method = "linear"

# 4. Build network (includes sizing, heat loss, optimization, simulation)
net, topology = build_trunk_spur_network(
    cluster_id="ST010_HEINRICH_ZILLE_STRASSE",
    buildings=buildings,
    streets=streets,
    plant_coords=(51.76274, 14.3453979),  # WGS84 (converted internally)
    selected_street_name="Heinrich Zille Strasse",
    design_loads_kw=design_loads,
    pipe_catalog=catalog,
    config=cfg
)

# 5. Extract KPIs
extractor = KPIExtractor(net, config=cfg)
kpis = extractor.extract_kpis("ST010_HEINRICH_ZILLE_STRASSE", design_hour=6667)

# 6. Generate maps
output_dir = Path("results/cha/ST010_HEINRICH_ZILLE_STRASSE")
create_interactive_map(net, buildings, "ST010", output_dir / "interactive_map.html", map_type="velocity")
create_interactive_map(net, buildings, "ST010", output_dir / "interactive_map_temperature.html", map_type="temperature")
create_interactive_map(net, buildings, "ST010", output_dir / "interactive_map_pressure.html", map_type="pressure")

# 7. Export CSVs
export_pipe_velocity_csvs(net, "ST010", output_dir)
```

### Custom Configuration

```python
from branitz_heat_decision.cha.config import CHAConfig

# Custom config for high-pressure system
cfg = CHAConfig(
    system_pressure_bar=10.0,  # High pressure
    pump_plift_bar=4.0,  # Large pump head
    supply_temp_k=363.15,  # 90°C
    return_temp_k=313.15,  # 40°C (lower return temp)
    heat_loss_method="thermal_resistance",  # Physics-based method
    supply_return_interaction=True,  # Enable TwinPipe
    twinpipe_loss_factor=0.85,  # 15% reduction (tight pairing)
    v_limit_trunk_ms=1.2,  # Conservative velocity
    v_limit_service_ms=1.2,
    sizing_eco_mode=True,  # Eco-mode sizing
)
```

### Heat Loss Method Comparison

```python
from branitz_heat_decision.cha.heat_loss import compute_heat_loss, HeatLossInputs

# Method 1: Linear (catalog-based)
cfg_linear = CHAConfig(heat_loss_method="linear", t_linear_ref_k=353.15)
catalog = {"DN50": {"q_linear_w_per_m": 30.0}}
result_linear = compute_heat_loss(
    HeatLossInputs(dn_mm=50, length_m=100, t_fluid_k=353.15, t_soil_k=285.15, role="trunk", circuit="supply"),
    cfg_linear,
    catalog=catalog
)
# result_linear.q_loss_w_per_m ≈ 30.0 W/m (scaled by temperature)

# Method 2: Thermal Resistance (physics-based)
cfg_thermal = CHAConfig(heat_loss_method="thermal_resistance", default_insulation_thickness_mm=50.0)
result_thermal = compute_heat_loss(
    HeatLossInputs(dn_mm=50, length_m=100, t_fluid_k=353.15, t_soil_k=285.15, role="trunk", circuit="supply",
                   outer_diameter_m=0.055, insulation_thickness_m=0.05, burial_depth_m=1.0),
    cfg_thermal
)
# result_thermal.q_loss_w_per_m computed from U-value
```

---

## Documentation Files

The CHA module includes comprehensive documentation:

- **`cha_readme.md`** (this file): Complete module reference with all functions and workflows
- **`DESIGN_VALIDATION_EXPLAINED.md`**: Detailed explanation of the design validation system, validation categories, and metrics
- **`VALIDATION_WARNINGS_EXPLAINED.md`**: Context-aware warning explanations for trunk-spur networks (why low velocity and flow imbalance are expected)
- **`HOW_TO_FIX_VALIDATION_ISSUES.md`**: Step-by-step troubleshooting guide for validation issues (disconnected components, robustness failures, etc.)
- **`WARNING_MITIGATION_OPTIONS.md`**: Options for addressing validation warnings (accept, suppress, optimize)

---

## Testing & Validation

### Unit Tests
- `tests/cha/test_heat_loss.py`: Heat loss calculation tests
- `tests/cha/test_heat_loss_mapping.py`: Pandapipes mapping verification
- `tests/cha/test_sizing_catalog.py`: Pipe sizing tests

### Integration Tests
- `tests/integration/test_cha_pipeline.py`: End-to-end pipeline tests

### Validation Checks
- **Topology**: Trunk is a tree (|E| = |V| - 1), single plant root
- **Hydraulics**: All velocities ≤2.5 m/s, pressures >1.5 bar
- **Thermal**: Temperatures finite, losses computed from temperature drop
- **Convergence**: `net.converged == True`
- **EN 13941-1**: Velocity compliance (≥95% within limits), pressure drop (≤0.3 bar/100m)

### Design Validation System
The CHA module includes a comprehensive design validation system (`design_validator.py`) that performs:
- **Geospatial Validation**: Building connectivity, network topology, street alignment
- **Hydraulic Validation**: Velocity, pressure, flow distribution (EN 13941-1) with **context-aware warnings** for trunk-spur networks
- **Thermal Validation**: Temperature distribution, heat losses
- **Robustness Validation**: Monte Carlo uncertainty analysis (50 scenarios)

**Context-Aware Validation** (NEW):
- Automatically detects trunk-spur networks
- Provides context-aware warnings explaining why certain conditions are expected
- Low velocity pipes: Explains that return pipes and spurs naturally have lower flow
- Flow distribution imbalance: Explains that high CV is a design feature, not a flaw

See `DESIGN_VALIDATION_EXPLAINED.md`, `VALIDATION_WARNINGS_EXPLAINED.md`, and `HOW_TO_FIX_VALIDATION_ISSUES.md` for details.

---

## Troubleshooting

### Common Issues

#### 1. Network Not Converging
**Symptoms**: `net.converged == False`, NaNs in results

**Solutions**:
- Check topology: Ensure tree structure (no accidental loops)
- Verify plant boundaries: One `ext_grid` at supply, pump at return→supply
- Increase pressure: `system_pressure_bar = 8-10 bar`, `pump_plift_bar = 3-4 bar`
- Check short pipes: Replace <1m pipes with minimum length (1m)
- Use spur optimizer: `convergence_optimizer_spur.py` (not general optimizer)

#### 2. Negative Pressures
**Symptoms**: `p_from_bar < 0` or `p_to_bar < 0`

**Solutions**:
- Increase system pressure: `system_pressure_bar = 8-10 bar`
- Increase pump head: `pump_plift_bar = 3-4 bar`
- Check pipe sizes: Upsize pipes with excessive pressure drop
- Enforce dp/m limit: `dp_per_m_max_pa = 200 Pa/m` in sizing

#### 3. High Velocities (>2.5 m/s)
**Symptoms**: `v_max_ms > 2.5 m/s` (hard fail)

**Solutions**:
- Upsize pipes: Select larger DN from catalog
- Check design flow: Verify `mdot_design` calculation
- Reduce velocity limit: `v_limit_trunk_ms = 1.2 m/s` (eco-mode)

#### 4. Zero Heat Losses
**Symptoms**: `loss_share_percent = 0.0%` (should be 5-20%)

**Solutions**:
- Verify heat loss application: Check `net.pipe['u_w_per_m2k']` and `net.pipe['text_k']`
- Check thermal simulation: Ensure thermal mode enabled in `pipeflow()`
- Verify KPI calculation: Uses temperature drop (not `qext_w` from results)

#### 5. Maps Not Showing Cascading Colors
**Symptoms**: All pipes same color

**Solutions**:
- Check color scale: Ensure min/max computed from actual values
- Verify results: Check `net.res_pipe` has velocity/temperature columns
- Check map_type: Use `"velocity"`, `"temperature"`, or `"pressure"`

---

## Performance Considerations

### Large Networks (>1000 pipes)
- **Caching**: Enable `cfg._enable_heat_loss_cache = True` for heat loss calculation
- **Parallel Processing**: Heat loss calculation can be parallelized (not yet implemented)
- **Memory**: Use `detailed=False` in KPI extraction to skip pipe-level details

### Network Building
- **Street Filtering**: Progressive buffer expansion (1x → 2x → 4x → 8x) for connectivity
- **Graph Operations**: NetworkX operations are O(V + E), typically <100ms for <1000 nodes

### Simulation
- **Convergence**: Typically 10-50 iterations for trunk-spur networks
- **Performance**: ~1-5 seconds for 100-500 pipes, ~10-30 seconds for 500-1000 pipes

---

## Standards Compliance

### EN 13941-1 Compliance

The module implements EN 13941-1 standard limits:

- **Velocity Limit**: `v_max ≤ 1.5 m/s` (target), `≥95%` of segments within limit
- **Pressure Drop**: `dp_per_100m ≤ 0.3 bar/100m` (maximum)
- **Thermal Losses**: Calculated and reported as `loss_share_percent`
- **Temperature**: Supply/return temperature within operating range

**Compliance Checking** (`kpi_extractor._check_en13941_compliance()`):
- `velocity_ok`: `v_share_within_limits >= 0.95`
- `dp_ok`: `dp_max_bar_per_100m <= 0.3`
- `feasible`: `velocity_ok AND dp_ok`

---

## References & Standards

- **EN 13941-1:2023**: District heating pipes - Design and installation
- **EN 10255**: Steel pipes for district heating
- **DIN EN 13941-1:2023**: German standard for DH design
- **VDE-AR-N 4100:2022**: LV grid connection rules (for HP comparison)

---

**Last Updated**: 2026-01-19  
**Module Version**: v1.1  
**Primary Maintainer**: CHA Development Team

## Recent Updates (2026-01-19)

- **Multi-Map Generation**: CHA pipeline now generates 3 interactive maps (velocity, temperature, pressure)
- **Cascading Colors**: All maps use cascading color gradients (supply: red shades, return: blue shades)
- **Fixed Plant Location**: Support for fixed CHP plant location via WGS84 coordinates
- **Heat Loss Integration**: Full heat loss calculation support with diagnostics storage
