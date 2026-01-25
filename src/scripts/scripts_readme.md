# Scripts Module Documentation

Complete documentation for the Scripts module containing pipeline execution scripts for the Branitz Heat Decision system.

**Module Location**: `src/scripts/`  
**Total Lines of Code**: ~2,007 lines  
**Primary Language**: Python 3.9+  
**Dependencies**: argparse, json, pickle, logging, pathlib, pandas, geopandas, numpy, pandapipes, pandapower

---

## Module Overview

The Scripts module provides command-line execution scripts for running the complete Branitz Heat Decision pipeline:

1. **Data Preparation** (`00_prepare_data.py`): Loads raw data, creates clusters, generates profiles
2. **CHA Pipeline** (`01_run_cha.py`): District heating network analysis
3. **CHA Trunk-Spur** (`01_run_cha_trunk_spur.py`): ⚠️ **DEPRECATED** - Alternative trunk-spur CHA pipeline (use `01_run_cha.py --use-trunk-spur` instead)
4. **DHA Pipeline** (`02_run_dha.py`): LV grid hosting analysis for heat pumps
5. **Economics Pipeline** (`03_run_economics.py`): LCOH, CO₂, and Monte Carlo analysis
6. **Decision Pipeline** (`04_make_decision.py`): ⚠️ **DEPRECATED** - Use `cli/decision.py` or `cli/uhdc.py` instead
7. **Report Generation** (`05_generate_report.py`): ⚠️ **DEPRECATED** - Use `cli/uhdc.py` instead
8. **Map Server** (`serve_maps.py`): ⚠️ **NOT IMPLEMENTED** - Placeholder for future Flask/FastAPI server

### Architecture

The Scripts module follows a sequential pipeline architecture:

```
Scripts Module
├─ 00_prepare_data.py → Data Preparation & Clustering
├─ 01_run_cha.py → CHA Pipeline (Main)
├─ 01_run_cha_trunk_spur.py → CHA Trunk-Spur (DEPRECATED)
├─ 02_run_dha.py → DHA Pipeline
├─ 03_run_economics.py → Economics Pipeline
├─ 04_make_decision.py → Decision Pipeline (DEPRECATED)
├─ 05_generate_report.py → Report Generation (DEPRECATED)
└─ serve_maps.py → Map Server (NOT IMPLEMENTED)
```

---

## Module Files & Functions

### `__init__.py` (Empty) ⭐ **MODULE INITIALIZATION**
**Purpose**: Module initialization (empty, scripts are standalone executables)

---

### `00_prepare_data.py` (269 lines) ⭐ **ACTIVE - DATA PREPARATION**
**Purpose**: Data preparation pipeline - loads raw data, creates clusters, generates profiles

**Main Functions**:

#### `create_street_based_clusters()` ⭐ **STREET-BASED CLUSTERING**
```python
def create_street_based_clusters(
    buildings_path: Path,
    streets_path: Path,
    output_cluster_map_path: Path,
    output_street_clusters_path: Path
) -> Tuple[pd.DataFrame, pd.DataFrame]
```

**Purpose**: Create street-based clusters from buildings and streets geodata

**Workflow**:

1. **Load Buildings**:
   - Load from GeoJSON via `load_buildings_geojson()`
   - Transform to projected CRS (`EPSG:25833`) if needed
   - Enrich with Branitzer attributes (`output_branitzer_siedlungV11.json`)
   - Enrich with gebaeudeanalyse (`gebaeudeanalyse.json`)
   - Estimate envelope via `estimate_envelope()`

2. **Filter Buildings**:
   - Filter to residential with heat demand via `filter_residential_buildings_with_heat_demand()`
   - Save filtered buildings to `data/processed/buildings.parquet`

3. **Load Streets**:
   - Load from GeoJSON via `load_streets_geojson()`
   - Ensure CRS matches buildings

4. **Match Buildings to Streets**:
   - Prefer street name from building address/analysis if available
   - Otherwise use `match_buildings_to_streets()` (address + spatial fallback)

5. **Create Clusters**:
   - Call `create_street_clusters()` to create street-based clusters
   - Save `building_cluster_map.parquet` and `street_clusters.parquet`

**Returns**: `(building_cluster_map, street_clusters)` DataFrames

**Outputs**:
- `data/processed/buildings.parquet` - Filtered residential buildings with heat demand
- `data/processed/building_cluster_map.parquet` - Building-to-cluster mapping
- `data/processed/street_clusters.parquet` - Street cluster metadata

---

#### `generate_profiles_and_design_topn()` ⭐ **PROFILE GENERATION**
```python
def generate_profiles_and_design_topn(
    buildings: gpd.GeoDataFrame,
    cluster_map: pd.DataFrame,
    N: int = 10
) -> None
```

**Purpose**: Generate and save hourly heat demand profiles and design/top-N hours

**Workflow**:

1. **Load Weather**:
   - Load weather from `data/processed/weather.parquet` (8760 hourly temperatures)

2. **Generate Profiles**:
   - Call `generate_hourly_profiles(buildings, weather_df)` to create hourly heat demand per building
   - Shape: `(8760, n_buildings)` - hourly heat demand per building (kW)
   - Save to `data/processed/hourly_heat_profiles.parquet`

3. **Aggregate Cluster Profiles**:
   - Call `aggregate_cluster_profiles(profiles_df, cluster_map)` to sum per cluster

4. **Compute Design/Top-N**:
   - Call `compute_design_and_topn(cluster_profiles, N=10)` to compute:
     - `design_hour`: Hour with peak cluster load
     - `design_load_kw`: Peak cluster load (kW)
     - `topn_hours`: Top N hours by cluster load

5. **Save Design/Top-N**:
   - Save to `data/processed/cluster_design_topn.json`

**Outputs**:
- `data/processed/hourly_heat_profiles.parquet` - Hourly heat demand per building (8760 × n_buildings)
- `data/processed/cluster_design_topn.json` - Design hour and top-N hours per cluster

---

#### `main()` ⭐ **CLI ENTRY POINT**
```python
def main() -> None
```

**Purpose**: CLI entry point for data preparation pipeline

**Arguments**:
- `--verbose`, `-v`: Verbose output
- `--buildings`: Path to buildings GeoJSON (default: `data/raw/hausumringe_mit_adressenV3.geojson`)
- `--streets`: Path to streets GeoJSON (default: `data/raw/strassen_mit_adressenV3_fixed.geojson`)
- `--create-clusters`: Create street-based clusters from raw data

**Usage**:
```bash
# Create clusters from raw data
python src/scripts/00_prepare_data.py --create-clusters \
    --buildings data/raw/hausumringe_mit_adressenV3.geojson \
    --streets data/raw/strassen_mit_adressenV3_fixed.geojson
```

**Interactions**:
- **Uses**: `data/loader.py`, `data/typology.py`, `data/profiles.py`, `data/cluster.py`
- **Outputs**: `data/processed/buildings.parquet`, `building_cluster_map.parquet`, `street_clusters.parquet`, `hourly_heat_profiles.parquet`, `cluster_design_topn.json`

---

### `01_run_cha.py` (827 lines) ⭐ **ACTIVE - CHA PIPELINE**
**Purpose**: CHA pipeline - District heating network analysis

**Main Functions**:

#### `load_cluster_data()` ⭐ **CLUSTER DATA LOADER**
```python
def load_cluster_data(
    cluster_id: str,
) -> Tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, Tuple[float, float], int, float, pd.DataFrame, Optional[str]]
```

**Purpose**: Load data for a specific cluster

**Workflow**:

1. **Validate Cluster ID**: Check format `ST{number}_{STREET_NAME}`

2. **Load Street Clusters**: Get cluster metadata (plant coordinates, street name)

3. **Load Cluster Map**: Get building IDs for cluster

4. **Load Buildings**: Load filtered residential buildings with heat demand

5. **Load Streets**: Load all streets (needed for plant siting on nearby non-cluster streets)

6. **Get Plant Coordinates**: Prefer from cluster metadata, else use building centroid

7. **Load Design Hour/Load**: From `cluster_design_topn.json`

8. **Load Hourly Profiles**: Filter to cluster buildings

**Returns**: `(buildings, streets, plant_coords, design_hour, design_load_kw, hourly_profiles, cluster_street_name)`

---

#### `run_cha_pipeline()` ⭐ **PRIMARY CHA FUNCTION**
```python
def run_cha_pipeline(
    cluster_id: str,
    attach_mode: str = 'split_edge_per_building',
    trunk_mode: str = 'paths_to_buildings',
    optimize_convergence: bool = False,
    output_dir: Optional[Path] = None,
    use_trunk_spur: bool = False,
    catalog_path: Optional[Path] = None,
    max_spur_length_m: float = 50.0,
    plant_wgs84_lat: Optional[float] = None,
    plant_wgs84_lon: Optional[float] = None,
    disable_auto_plant_siting: bool = False,
) -> Dict[str, Path]
```

**Purpose**: Run complete CHA pipeline for a cluster

**Workflow**:

1. **Setup Output Directory**: `results/cha/{cluster_id}/`

2. **Load Cluster Data**: Call `load_cluster_data()`

3. **Override Plant Location** (if WGS84 coordinates provided):
   - Convert WGS84 (lat, lon) to projected CRS (e.g., EPSG:25833)

4. **Get CHA Config**: Load default config via `get_default_config()`

5. **Build Network**:
   - **Standard Builder**: Call `network_builder.build_dh_network_for_cluster()`
   - **Trunk-Spur Builder** (if `use_trunk_spur=True`): Call `build_trunk_spur_network()`
     - Load technical catalog from Excel
     - Prepare design loads dictionary from hourly profiles

6. **Run Pipeflow**:
   - Run `pp.pipeflow(net, mode='sequential')`
   - Check convergence

7. **Optimize Convergence** (if requested):
   - Call `optimize_network_for_convergence()` (standard builder only)
   - Re-run pipeflow

8. **Extract KPIs**:
   - Call `extract_kpis()` to compute EN 13941-1 compliance KPIs
   - Save to `cha_kpis.json`

9. **Save Network**:
   - Save pandapipes network to `network.pickle`

10. **Generate Interactive Maps**:
    - Velocity map: `interactive_map.html`
    - Temperature map: `interactive_map_temperature.html`
    - Pressure map: `interactive_map_pressure.html`

11. **Export Pipe CSVs**:
    - `pipe_velocities_supply_return.csv`
    - `pipe_velocities_supply_return_with_temp.csv`
    - `pipe_velocities_plant_to_plant_main_path.csv`

**Returns**: Dictionary with output paths:
- `kpis`: Path to `cha_kpis.json`
- `network`: Path to `network.pickle`
- `interactive_map`: Path to velocity map HTML
- `interactive_map_temperature`: Path to temperature map HTML
- `interactive_map_pressure`: Path to pressure map HTML

---

#### `main()` ⭐ **CLI ENTRY POINT**
```python
def main() -> None
```

**Purpose**: CLI entry point for CHA pipeline

**Arguments**:
- `--cluster-id` (required): Cluster identifier (e.g., `ST001_HEINRICH_ZILLE_STRASSE`)
- `--attach-mode`: Building attachment mode (`split_edge_per_building`, `nearest_node`)
- `--trunk-mode`: Trunk topology mode (`paths_to_buildings`, `steiner_tree`)
- `--optimize-convergence`: Optimize network topology for numerical convergence
- `--use-trunk-spur`: Use trunk-spur network builder (recommended)
- `--catalog`: Path to technical catalog Excel file (trunk-spur builder)
- `--max-spur-length`: Maximum spur length in meters (default: 50.0)
- `--plant-wgs84-lat`: Fixed plant latitude in WGS84 (EPSG:4326)
- `--plant-wgs84-lon`: Fixed plant longitude in WGS84 (EPSG:4326)
- `--disable-auto-plant-siting`: Disable automatic re-siting to nearby different street
- `--output-dir`: Output directory (default: `results/cha/{cluster_id}`)
- `--verbose`: Enable verbose logging

**Usage**:
```bash
# Standard network builder
python src/scripts/01_run_cha.py --cluster-id ST010_HEINRICH_ZILLE_STRASSE

# Trunk-spur network builder (recommended)
python src/scripts/01_run_cha.py --cluster-id ST010_HEINRICH_ZILLE_STRASSE --use-trunk-spur

# With fixed plant location
python src/scripts/01_run_cha.py --cluster-id ST010_HEINRICH_ZILLE_STRASSE \
    --plant-wgs84-lat 51.76274 \
    --plant-wgs84-lon 14.3453979 \
    --disable-auto-plant-siting
```

**Interactions**:
- **Uses**: `cha/network_builder.py`, `cha/network_builder_trunk_spur.py`, `cha/convergence_optimizer_spur.py`, `cha/kpi_extractor.py`, `cha/qgis_export.py`, `cha/config.py`, `cha/sizing.py`, `data/loader.py`
- **Outputs**: `results/cha/{cluster_id}/cha_kpis.json`, `network.pickle`, `interactive_map*.html`, `pipe_velocities*.csv`

---

### `01_run_cha_trunk_spur.py` (207 lines) ⚠️ **DEPRECATED - USE `01_run_cha.py --use-trunk-spur` INSTEAD**
**Purpose**: Alternative trunk-spur CHA pipeline (standalone version)

**Status**: **DEPRECATED** - Functionality integrated into `01_run_cha.py` with `--use-trunk-spur` flag

**Why Deprecated**:
- Redundant with `01_run_cha.py --use-trunk-spur`
- Less feature-complete (no temperature/pressure maps, no WGS84 plant location)
- Not used by CLI or main pipeline

**Main Functions**:

#### `load_cluster_data_trunk_spur()` ⚠️ **DEPRECATED**
```python
def load_cluster_data_trunk_spur(cluster_id: str) -> tuple
```

**Purpose**: Load data for trunk-spur pipeline (simplified version)

**Limitations**:
- Uses hardcoded default loads (50kW per building) instead of hourly profiles
- Less robust than `load_cluster_data()` in `01_run_cha.py`

---

#### `run_trunk_spur_pipeline()` ⚠️ **DEPRECATED**
```python
def run_trunk_spur_pipeline(
    cluster_id: str,
    catalog_path: Optional[Path] = None,
    output_dir: Optional[Path] = None,
    velocity_limit_ms: float = 1.5
) -> Dict[str, Any]
```

**Purpose**: Run trunk-spur pipeline (standalone version)

**Limitations**:
- No temperature/pressure maps
- No WGS84 plant location support
- No CSV exports
- Less comprehensive KPI extraction

**Recommendation**: Use `01_run_cha.py --use-trunk-spur` instead

---

### `02_run_dha.py` (347 lines) ⭐ **ACTIVE - DHA PIPELINE**
**Purpose**: DHA pipeline - LV grid hosting analysis for heat pumps

**Main Function**:

#### `main()` ⭐ **CLI ENTRY POINT**
```python
def main() -> None
```

**Purpose**: CLI entry point for DHA pipeline

**Workflow**:

1. **Load Cluster Buildings**:
   - Load from `data/processed/buildings.parquet`
   - Filter to cluster via `building_cluster_map.parquet`

2. **Load Design Hour + TopN Hours**:
   - Load from `cluster_design_topn.json`

3. **Load Hourly Heat Profiles**:
   - Load from `hourly_heat_profiles.parquet`
   - Filter to cluster buildings
   - IMPORTANT: Only consider buildings with hourly heat profiles (residential with heat demand)

4. **Load Base Electrical Demand**:
   - **Scenario JSON** (`scenario_json`): Load from `gebaeude_lastphasenV2.json`
   - **BDEW Time Series** (`bdew_timeseries`): Generate from BDEW SLP profiles
     - Requires `building_population_resultsV6.json` for deterministic H0 scaling

5. **Build LV Grid**:
   - **Legacy JSON** (`legacy_json`): Load from `Legacy/DHA/HP New /Data/branitzer_siedlung_ns_v3_ohne_UW.json`
   - **GeoData** (`geodata`): Build from `data/processed/power_lines.geojson` and `power_substations.geojson`

6. **Map Buildings to LV Buses**:
   - Call `mapping.map_buildings_to_lv_buses()`

7. **Assign HP Loads**:
   - Convert heat demand to electrical via COP: `P_el_kw = Q_th_kw / cop`
   - Combine with base load: `P_total_kw = P_base_kw + P_hp_kw`

8. **Run Loadflow**:
   - For design hour and TopN hours
   - Call `loadflow.run_loadflow()` for each hour

9. **Extract KPIs**:
   - Call `kpi_extractor.extract_dha_kpis()` to compute VDE-AR-N 4100 compliance KPIs
   - Save to `dha_kpis.json`

10. **Export Outputs**:
    - GeoJSON: `buses_results.geojson`, `lines_results.geojson`
    - Violations CSV: `violations.csv`
    - Interactive map: `hp_lv_map.html`

**Arguments**:
- `--cluster-id` (required): Cluster ID (e.g., `ST010_HEINRICH_ZILLE_STRASSE`)
- `--cop`: Heat pump COP (default: 2.8)
- `--pf`: Power factor (default: 0.95)
- `--hp-three-phase`: Model HP loads as balanced 3-phase (default)
- `--single-phase`: Model HP loads as single-phase imbalance
- `--topn`: Number of top hours to include (default: 10)
- `--max-mapping-dist-m`: Max building→bus mapping distance (m)
- `--grid-buffer-m`: Buffer around cluster buildings to subset LV grid (default: 1500.0 m)
- `--base-load-json`: Path to base electrical load JSON (default: `data/raw/gebaeude_lastphasenV2.json`)
- `--base-load-source`: Base load source (`scenario_json`, `bdew_timeseries`)
- `--bdew-profiles-csv`: Optional path to `bdew_profiles.csv`
- `--bdew-mapping-json`: Optional path to `bdew_slp_gebaeudefunktionen.json`
- `--bdew-population-json`: REQUIRED for `bdew_timeseries` - Path to `building_population_resultsV6.json`
- `--base-scenario`: Scenario key in `gebaeude_lastphasenV2.json` (default: `winter_werktag_abendspitze`)
- `--base-unit`: Unit of `gebaeude_lastphasenV2.json` values (`AUTO`, `MW`, `kW`, `KW`)
- `--disable-base-load`: Ignore base electrical load (HP-only loads)
- `--use-pf-split`: Compute Q_total as Q_base(pf_base)+Q_hp(pf_hp) instead of one pf_total
- `--pf-base`: Power factor for base load (default: 0.95)
- `--pf-hp`: Power factor for HP incremental load (default: 0.95)
- `--grid-source`: Grid source (`legacy_json`, `geodata`)
- `--legacy-nodes-ways-json`: Path to legacy nodes/ways JSON
- `--output-dir`: Output directory (default: `results/dha/{cluster_id}`)

**Usage**:
```bash
# Basic usage (scenario-based base loads)
python src/scripts/02_run_dha.py --cluster-id ST010_HEINRICH_ZILLE_STRASSE

# With BDEW time series base loads
python src/scripts/02_run_dha.py --cluster-id ST010_HEINRICH_ZILLE_STRASSE \
    --base-load-source bdew_timeseries \
    --bdew-population-json data/raw/building_population_resultsV6.json

# Single-phase imbalance (worst-case)
python src/scripts/02_run_dha.py --cluster-id ST010_HEINRICH_ZILLE_STRASSE --single-phase
```

**Interactions**:
- **Uses**: `dha/grid_builder.py`, `dha/mapping.py`, `dha/loadflow.py`, `dha/kpi_extractor.py`, `dha/export.py`, `dha/base_loads.py`, `dha/bdew_base_loads.py`, `dha/config.py`
- **Outputs**: `results/dha/{cluster_id}/dha_kpis.json`, `buses_results.geojson`, `lines_results.geojson`, `violations.csv`, `hp_lv_map.html`

---

### `03_run_economics.py` (299 lines) ⭐ **ACTIVE - ECONOMICS PIPELINE**
**Purpose**: Economics pipeline - LCOH, CO₂, and Monte Carlo analysis

**Main Functions**:

#### `_load_cluster_building_ids()` ⭐ **CLUSTER BUILDING IDS LOADER**
```python
def _load_cluster_building_ids(cluster_id: str) -> List[str]
```

**Purpose**: Load building IDs for a cluster

**Returns**: List of building ID strings

---

#### `_load_cluster_design_hour()` ⭐ **DESIGN HOUR LOADER**
```python
def _load_cluster_design_hour(cluster_id: str) -> int
```

**Purpose**: Load design hour for a cluster

**Returns**: Design hour (0-8759)

---

#### `_load_annual_heat_mwh()` ⭐ **ANNUAL HEAT LOADER**
```python
def _load_annual_heat_mwh(cluster_building_ids: List[str]) -> float
```

**Purpose**: Load annual heat demand (MWh/year)

**Workflow**:
1. Load hourly heat profiles
2. Sum per hour for cluster buildings
3. Sum over all hours
4. Convert kWh → MWh

**Returns**: Annual heat demand (MWh/year)

---

#### `_load_design_capacity_kw()` ⭐ **DESIGN CAPACITY LOADER**
```python
def _load_design_capacity_kw(cluster_building_ids: List[str], design_hour: int) -> float
```

**Purpose**: Load design capacity (kW) at design hour

**Returns**: Design capacity (kW)

---

#### `_load_dh_lengths_m_from_cha()` ⭐ **DH LENGTHS LOADER**
```python
def _load_dh_lengths_m_from_cha(cluster_id: str) -> Dict[str, float]
```

**Purpose**: Extract DH pipe lengths from CHA KPIs

**Returns**: Dictionary with `trunk_m` and `service_m` lengths

---

#### `_load_dh_pipe_capex_eur_from_cha()` ⭐ **DH PIPE CAPEX LOADER**
```python
def _load_dh_pipe_capex_eur_from_cha(cluster_id: str, params) -> float
```

**Purpose**: Compute DH pipe CAPEX from CHA per-pipe CSV

**Workflow**:
1. Load `pipe_velocities_supply_return_with_temp.csv`
2. For each pipe: `DN = int(round(diameter_mm))`, `cost = length_m × pipe_cost_eur_per_m[DN]`
3. Sum all pipe costs

**Returns**: Total pipe CAPEX (EUR)

---

#### `_load_pump_power_kw_from_cha()` ⭐ **PUMP POWER LOADER**
```python
def _load_pump_power_kw_from_cha(cluster_id: str) -> float
```

**Purpose**: Load pump power from CHA KPIs

**Returns**: Pump power (kW)

---

#### `_load_pipe_lengths_by_dn_from_cha()` ⭐ **PIPE LENGTHS BY DN LOADER**
```python
def _load_pipe_lengths_by_dn_from_cha(cluster_id: str) -> Dict[str, float]
```

**Purpose**: Build `{DNxxx: length_m}` dictionary from CHA per-pipe CSV

**Returns**: Dictionary mapping DN to total length (m)

---

#### `_load_max_feeder_loading_pct_from_dha()` ⭐ **MAX FEEDER LOADING LOADER**
```python
def _load_max_feeder_loading_pct_from_dha(cluster_id: str) -> float
```

**Purpose**: Load max feeder loading from DHA KPIs

**Returns**: Max feeder loading (%)

---

#### `main()` ⭐ **CLI ENTRY POINT**
```python
def main() -> None
```

**Purpose**: CLI entry point for economics pipeline

**Workflow**:

1. **Load Cluster Data**:
   - Building IDs, design hour, annual heat (MWh/year), design capacity (kW)

2. **Load CHA KPIs**:
   - Pipe lengths, pipe CAPEX, pump power, pipe lengths by DN

3. **Load DHA KPIs**:
   - Max feeder loading (%)

4. **Get Default Parameters**:
   - Load via `get_default_economics_params()`

5. **Compute Deterministic LCOH/CO₂**:
   - **DH LCOH**: `compute_lcoh_dh()` with pipe lengths, pump power, annual heat
   - **HP LCOH**: `compute_lcoh_hp()` with design capacity, COP, max feeder loading
   - **DH CO₂**: `compute_co2_dh()` with annual heat, generation type
   - **HP CO₂**: `compute_co2_hp()` with annual heat, COP

6. **Save Deterministic Results**:
   - Save to `economics_deterministic.json`

7. **Run Monte Carlo** (N=500 by default):
   - Call `run_monte_carlo()` with bounded ranges on parameters:
     - CAPEX multiplier: 0.8-1.2
     - Electricity price multiplier: 0.7-1.3
     - Fuel price multiplier: 0.7-1.3
     - Grid CO₂ multiplier: 0.7-1.3
     - HP COP: 2.0-3.5
     - Discount rate: 0.02-0.08

8. **Save Monte Carlo Results**:
   - Summary: `monte_carlo_summary.json`
   - Samples: `monte_carlo_samples.parquet`

**Arguments**:
- `--cluster-id` (required): Cluster identifier
- `--n`: Monte Carlo samples (default: 500)
- `--seed`: Random seed (default: 42)

**Usage**:
```bash
# Basic usage
python src/scripts/03_run_economics.py --cluster-id ST010_HEINRICH_ZILLE_STRASSE

# With custom Monte Carlo samples
python src/scripts/03_run_economics.py --cluster-id ST010_HEINRICH_ZILLE_STRASSE --n 1000 --seed 123
```

**Interactions**:
- **Uses**: `economics/params.py`, `economics/lcoh.py`, `economics/co2.py`, `economics/monte_carlo.py`, `economics/utils.py`
- **Inputs**: `results/cha/{cluster_id}/cha_kpis.json`, `results/dha/{cluster_id}/dha_kpis.json`
- **Outputs**: `results/economics/{cluster_id}/economics_deterministic.json`, `monte_carlo_summary.json`, `monte_carlo_samples.parquet`

---

### `04_make_decision.py` (20 lines) ⚠️ **DEPRECATED - USE `cli/decision.py` OR `cli/uhdc.py` INSTEAD**
**Purpose**: Decision pipeline placeholder (not implemented)

**Status**: **DEPRECATED** - Replaced by `cli/decision.py` and `cli/uhdc.py`

**Why Deprecated**:
- Contains only TODO placeholder
- Functionality implemented in `cli/decision.py` (KPI contract building, decision rules)
- Report generation implemented in `cli/uhdc.py` (HTML/Markdown reports)

**Recommendation**: Use `cli/decision.py` or `cli/uhdc.py` instead

**Migration**:
```bash
# Old (deprecated)
python src/scripts/04_make_decision.py  # Not implemented

# New (use CLI)
python -m branitz_heat_decision.cli.decision --cluster-id ST010_HEINRICH_ZILLE_STRASSE
python -m branitz_heat_decision.cli.uhdc --cluster-id ST010_HEINRICH_ZILLE_STRASSE --out-dir results/uhdc/ST010
```

---

### `05_generate_report.py` (18 lines) ⚠️ **DEPRECATED - USE `cli/uhdc.py` INSTEAD**
**Purpose**: Report generation placeholder (not implemented)

**Status**: **DEPRECATED** - Replaced by `cli/uhdc.py`

**Why Deprecated**:
- Contains only TODO placeholder
- Functionality implemented in `cli/uhdc.py` (HTML, Markdown, JSON reports with interactive maps)

**Recommendation**: Use `cli/uhdc.py` instead

**Migration**:
```bash
# Old (deprecated)
python src/scripts/05_generate_report.py  # Not implemented

# New (use CLI)
python -m branitz_heat_decision.cli.uhdc --cluster-id ST010_HEINRICH_ZILLE_STRASSE --out-dir results/uhdc/ST010 --format html
```

---

### `serve_maps.py` (19 lines) ⚠️ **NOT IMPLEMENTED - PLACEHOLDER**
**Purpose**: Interactive map server placeholder (not implemented)

**Status**: **NOT IMPLEMENTED** - Placeholder for future Flask/FastAPI server

**Why Not Implemented**:
- Contains only TODO placeholder
- No current need (interactive maps work as standalone HTML files)
- Future enhancement (web server for dynamic map serving)

**Future Implementation**:
- Flask or FastAPI server
- Serve interactive maps via HTTP
- Dynamic map generation from results database
- Multi-cluster map browsing

---

## Complete Pipeline Workflow

### Standard Pipeline Execution

```
┌─────────────────────────────────────────────────────────────────┐
│ 0. Data Preparation (00_prepare_data.py)                         │
│    - Load raw buildings/streets GeoJSON                          │
│    - Filter to residential with heat demand                       │
│    - Create street-based clusters                                 │
│    - Generate hourly heat profiles (8760 hours)                   │
│    - Compute design hour and top-N hours                          │
│    Output: data/processed/buildings.parquet, cluster_map,        │
│            hourly_heat_profiles.parquet, cluster_design_topn.json│
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 1. CHA Pipeline (01_run_cha.py)                                  │
│    - Load cluster buildings and streets                           │
│    - Build trunk-spur network (pandapipes)                        │
│    - Run pipeflow (hydraulic + thermal)                           │
│    - Extract EN 13941-1 KPIs                                      │
│    - Generate interactive maps (velocity/temp/pressure)           │
│    Output: results/cha/{cluster_id}/cha_kpis.json,              │
│            network.pickle, interactive_map*.html                  │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 2. DHA Pipeline (02_run_dha.py)                                  │
│    - Load cluster buildings with hourly heat profiles             │
│    - Build LV grid (pandapower)                                   │
│    - Map buildings to LV buses                                    │
│    - Assign HP loads (base + HP) for design+TopN hours            │
│    - Run loadflow for each hour                                   │
│    - Extract VDE-AR-N 4100 KPIs                                   │
│    - Generate interactive map and violations CSV                  │
│    Output: results/dha/{cluster_id}/dha_kpis.json,              │
│            buses_results.geojson, lines_results.geojson,         │
│            violations.csv, hp_lv_map.html                         │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 3. Economics Pipeline (03_run_economics.py)                      │
│    - Load CHA KPIs (pipe lengths, pump power)                    │
│    - Load DHA KPIs (max feeder loading)                          │
│    - Load annual heat demand and design capacity                  │
│    - Compute deterministic LCOH/CO₂ (DH and HP)                   │
│    - Run Monte Carlo simulation (N=500)                           │
│    - Extract probabilistic metrics (quantiles, win fractions)     │
│    Output: results/economics/{cluster_id}/                       │
│            economics_deterministic.json,                         │
│            monte_carlo_summary.json,                             │
│            monte_carlo_samples.parquet                           │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 4. Decision Pipeline (cli/decision.py or cli/uhdc.py)            │
│    - Discover artifacts (CHA/DHA/Economics KPIs)                 │
│    - Build KPI contract                                           │
│    - Apply decision rules (DH/HP/UNDECIDED)                       │
│    - Generate explanation (LLM or template)                       │
│    - Render HTML/Markdown/JSON reports                            │
│    Output: results/decision/{cluster_id}/kpi_contract.json,     │
│            results/uhdc/{cluster_id}/uhdc_report*.html/md/json  │
└─────────────────────────────────────────────────────────────────┘
```

---

## File Interactions & Dependencies

### Internal Dependencies (Within Scripts Module)

```
Scripts Module
  ├─ 00_prepare_data.py (DATA PREP)
  │  └─ Standalone (no dependencies on other scripts)
  │
  ├─ 01_run_cha.py (CHA PIPELINE)
  │  └─ Depends on: 00_prepare_data.py (processed data)
  │
  ├─ 01_run_cha_trunk_spur.py (DEPRECATED)
  │  └─ Replaced by: 01_run_cha.py --use-trunk-spur
  │
  ├─ 02_run_dha.py (DHA PIPELINE)
  │  └─ Depends on: 00_prepare_data.py (processed data), 01_run_cha.py (heat profiles)
  │
  ├─ 03_run_economics.py (ECONOMICS PIPELINE)
  │  └─ Depends on: 01_run_cha.py (CHA KPIs), 02_run_dha.py (DHA KPIs)
  │
  ├─ 04_make_decision.py (DEPRECATED)
  │  └─ Replaced by: cli/decision.py, cli/uhdc.py
  │
  ├─ 05_generate_report.py (DEPRECATED)
  │  └─ Replaced by: cli/uhdc.py
  │
  └─ serve_maps.py (NOT IMPLEMENTED)
     └─ Future enhancement
```

### External Dependencies (Outside Scripts Module)

```
Scripts Module
  ├─ Uses:
  │  ├─ data/loader.py → Load buildings/streets, filter residential
  │  ├─ data/typology.py → Estimate envelope
  │  ├─ data/profiles.py → Generate hourly heat profiles
  │  ├─ data/cluster.py → Create clusters, aggregate profiles
  │  ├─ cha/network_builder.py → Build DH network (standard)
  │  ├─ cha/network_builder_trunk_spur.py → Build DH network (trunk-spur)
  │  ├─ cha/convergence_optimizer_spur.py → Optimize convergence
  │  ├─ cha/kpi_extractor.py → Extract CHA KPIs
  │  ├─ cha/qgis_export.py → Generate interactive maps
  │  ├─ cha/config.py → CHA configuration
  │  ├─ cha/sizing.py → Pipe sizing
  │  ├─ dha/grid_builder.py → Build LV grid
  │  ├─ dha/mapping.py → Map buildings to buses
  │  ├─ dha/loadflow.py → Run powerflow
  │  ├─ dha/kpi_extractor.py → Extract DHA KPIs
  │  ├─ dha/export.py → Export DHA outputs
  │  ├─ dha/base_loads.py → Load base electrical loads
  │  ├─ dha/bdew_base_loads.py → Generate BDEW base loads
  │  ├─ economics/params.py → Economic parameters
  │  ├─ economics/lcoh.py → LCOH calculation
  │  ├─ economics/co2.py → CO₂ calculation
  │  ├─ economics/monte_carlo.py → Monte Carlo simulation
  │  └─ config.py → Path configuration
  │
  ├─ Replaced by (for decision/report):
  │  ├─ cli/decision.py → Decision pipeline (KPI contract, rules)
  │  └─ cli/uhdc.py → Report generation (HTML/Markdown/JSON)
  │
  └─ Outputs:
     ├─ data/processed/buildings.parquet
     ├─ data/processed/building_cluster_map.parquet
     ├─ data/processed/hourly_heat_profiles.parquet
     ├─ data/processed/cluster_design_topn.json
     ├─ results/cha/{cluster_id}/cha_kpis.json, network.pickle, interactive_map*.html
     ├─ results/dha/{cluster_id}/dha_kpis.json, buses_results.geojson, violations.csv, hp_lv_map.html
     └─ results/economics/{cluster_id}/economics_deterministic.json, monte_carlo_summary.json
```

---

## Usage Examples

### Complete Pipeline Execution

```bash
# Step 0: Data Preparation
python src/scripts/00_prepare_data.py --create-clusters

# Step 1: CHA Pipeline
python src/scripts/01_run_cha.py --cluster-id ST010_HEINRICH_ZILLE_STRASSE --use-trunk-spur

# Step 2: DHA Pipeline
python src/scripts/02_run_dha.py --cluster-id ST010_HEINRICH_ZILLE_STRASSE

# Step 3: Economics Pipeline
python src/scripts/03_run_economics.py --cluster-id ST010_HEINRICH_ZILLE_STRASSE

# Step 4: Decision & Report (CLI)
python -m branitz_heat_decision.cli.uhdc --cluster-id ST010_HEINRICH_ZILLE_STRASSE --out-dir results/uhdc/ST010 --format all
```

### Single-Step Execution

```bash
# Run CHA with fixed plant location
python src/scripts/01_run_cha.py --cluster-id ST010_HEINRICH_ZILLE_STRASSE \
    --use-trunk-spur \
    --plant-wgs84-lat 51.76274 \
    --plant-wgs84-lon 14.3453979 \
    --disable-auto-plant-siting

# Run DHA with BDEW time series base loads
python src/scripts/02_run_dha.py --cluster-id ST010_HEINRICH_ZILLE_STRASSE \
    --base-load-source bdew_timeseries \
    --bdew-population-json data/raw/building_population_resultsV6.json

# Run Economics with custom Monte Carlo samples
python src/scripts/03_run_economics.py --cluster-id ST010_HEINRICH_ZILLE_STRASSE --n 1000 --seed 123
```

---

## Unused/Deprecated Scripts Summary

### ⚠️ **DEPRECATED SCRIPTS** (Not Used)

| Script | Status | Replacement | Reason |
|--------|--------|-------------|--------|
| `01_run_cha_trunk_spur.py` | **DEPRECATED** | `01_run_cha.py --use-trunk-spur` | Functionality integrated into main CHA script |
| `04_make_decision.py` | **DEPRECATED** | `cli/decision.py` or `cli/uhdc.py` | Contains only TODO placeholder, functionality in CLI |
| `05_generate_report.py` | **DEPRECATED** | `cli/uhdc.py` | Contains only TODO placeholder, functionality in CLI |

### ⚠️ **NOT IMPLEMENTED** (Placeholder)

| Script | Status | Future Plan |
|--------|--------|-------------|
| `serve_maps.py` | **NOT IMPLEMENTED** | Future Flask/FastAPI server for dynamic map serving |

---

## Migration Guide

### Migrating from `01_run_cha_trunk_spur.py` to `01_run_cha.py`

```bash
# Old (deprecated)
python src/scripts/01_run_cha_trunk_spur.py --cluster-id ST010

# New (use main script)
python src/scripts/01_run_cha.py --cluster-id ST010 --use-trunk-spur
```

### Migrating from `04_make_decision.py` to CLI

```bash
# Old (deprecated)
python src/scripts/04_make_decision.py  # Not implemented

# New (use CLI)
python -m branitz_heat_decision.cli.decision --cluster-id ST010_HEINRICH_ZILLE_STRASSE
```

### Migrating from `05_generate_report.py` to CLI

```bash
# Old (deprecated)
python src/scripts/05_generate_report.py  # Not implemented

# New (use CLI)
python -m branitz_heat_decision.cli.uhdc --cluster-id ST010_HEINRICH_ZILLE_STRASSE --out-dir results/uhdc/ST010
```

---

## Error Handling & Validation

### Data Preparation (`00_prepare_data.py`)
- **Missing Files**: Raises `FileNotFoundError` if buildings/streets files not found
- **No Buildings**: Raises `ValueError` if no residential buildings with heat demand found
- **CRS Mismatch**: Automatically transforms CRS to match

### CHA Pipeline (`01_run_cha.py`)
- **Missing Cluster**: Raises `ValueError` if cluster not found
- **Convergence Failure**: Logs warning, continues with unconverged network
- **Missing Maps**: Skips map generation if network not converged

### DHA Pipeline (`02_run_dha.py`)
- **Missing Data**: Raises `FileNotFoundError` if processed data files missing
- **No Buildings**: Raises `ValueError` if cluster has no buildings with hourly profiles
- **Grid Build Failure**: Raises `ValueError` if grid cannot be built

### Economics Pipeline (`03_run_economics.py`)
- **Missing KPIs**: Uses defaults (zeros) if CHA/DHA KPIs missing
- **Monte Carlo Failure**: Logs warning, saves partial results

---

## Performance Considerations

### Data Preparation
- **Cluster Creation**: O(N×M) where N=buildings, M=streets (spatial matching)
- **Profile Generation**: O(N×H) where N=buildings, H=8760 hours

### CHA Pipeline
- **Network Building**: O(N×E) where N=buildings, E=street edges
- **Pipeflow**: O(I×P) where I=iterations, P=pipes (typically 10-50 iterations)

### DHA Pipeline
- **Grid Building**: O(B×L) where B=buses, L=lines
- **Loadflow**: O(I×B) where I=iterations, B=buses (typically 5-10 iterations)

### Economics Pipeline
- **Monte Carlo**: O(N×C) where N=samples (500), C=calculations per sample (4: LCOH_DH, LCOH_HP, CO2_DH, CO2_HP)
- **Parallel Processing**: Not implemented in scripts (use `cli/economics.py` for parallel MC)

---

## Standards Compliance

### Script Standards
- **EN 13941-1**: CHA pipeline compliance (velocity, pressure drop)
- **VDE-AR-N 4100**: DHA pipeline compliance (voltage band, line loading)

### Output Standards
- **KPI Contracts**: JSON schema validation via `decision/schemas.py`
- **Geographic Data**: GeoJSON compliant (EPSG:4326 for lat/lon, EPSG:25833 for projected)

---

## References & Documentation

- **CHA Module**: See `src/branitz_heat_decision/cha/cha_readme.md`
- **DHA Module**: See `src/branitz_heat_decision/dha/dha_readme.md`
- **Economics Module**: See `src/branitz_heat_decision/economics/economics_readme.md`
- **Decision Module**: See `src/branitz_heat_decision/decision/decision_readme.md`
- **UHDC Module**: See `src/branitz_heat_decision/uhdc/uhdc_readme.md`
- **CLI Module**: See `src/branitz_heat_decision/cli/cli_readme.md`
- **Data Module**: See `src/branitz_heat_decision/data/data_readme.md`

---

**Last Updated**: 2026-01-19  
**Module Version**: v1.1  
**Primary Maintainer**: Scripts Module Development Team

## Recent Updates (2026-01-19)

- **CHA Map Generation**: Enhanced to generate 3 maps (velocity, temperature, pressure) with error handling
- **Street ID Support**: Added `street_id` column compatibility in `00_prepare_data.py`
- **Annual Demand Fix**: Fixed annual heat demand aggregation in cluster UI index
