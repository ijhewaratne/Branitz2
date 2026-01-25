# Data Module Documentation

Complete documentation for the Data module implementing data loading, filtering, typology estimation, profile generation, and clustering for the Branitz Heat Decision pipeline.

**Module Location**: `src/branitz_heat_decision/data/`  
**Total Lines of Code**: ~1,869 lines  
**Primary Language**: Python 3.9+  
**Dependencies**: geopandas, pandas, numpy, pathlib, json, logging, typing, re

---

## Module Overview

The Data module provides data preparation, loading, and processing functionality for the Branitz Heat Decision pipeline:

1. **Data Loading** (`loader.py`): Load and validate buildings, streets, and power grid data from GeoJSON
2. **Building Typology** (`typology.py`): Estimate building envelope parameters using TABULA typology
3. **Profile Generation** (`profiles.py`): Generate hourly heat demand profiles for buildings
4. **Clustering** (`cluster.py`): Create street-based clusters and aggregate profiles

### Architecture

The Data module follows a modular architecture with clear separation of concerns:

```
Data Module
├─ loader.py → Data Loading & Validation
├─ typology.py → Building Typology Estimation
├─ profiles.py → Hourly Profile Generation
└─ cluster.py → Clustering & Aggregation
```

---

## Module Files & Functions

### `__init__.py` (Empty)
**Purpose**: Module initialization (currently empty)  
**Usage**: Python package marker

---

### `loader.py` (665 lines) ⭐ **DATA LOADER**
**Purpose**: Load and validate spatial data (buildings, streets, power grid) from GeoJSON files

**Main Functions**:

#### `filter_residential_buildings_with_heat_demand()` ⭐ **FILTER FUNCTION**
```python
def filter_residential_buildings_with_heat_demand(
    buildings: gpd.GeoDataFrame,
    min_heat_demand_kwh_a: float = 0.0
) -> gpd.GeoDataFrame
```

**Purpose**: Filter buildings to only include residential buildings with heat demand

**Filtering Logic**:
1. **Residential Filter**:
   - Checks `use_type` column (if present): matches `residential*`, `wohn*`, or values `residential_sfh`, `residential_mfh`
   - Checks `building_function` column (if `use_type` missing): matches `wohn*`, `residential*`, `mfh*`, `mehrfam*`
   - **Safety**: If >95% of buildings are `unknown`, skips residential filter (avoids dropping all buildings)
   - **Safety**: If no matches found, skips filter and logs warning (legacy-aligned behavior)
2. **Heat Demand Filter**:
   - Filters by `annual_heat_demand_kwh_a > min_heat_demand_kwh_a` (default: 0.0)
   - Logs count of buildings removed

**Returns**: Filtered GeoDataFrame (residential buildings with heat demand)

---

#### `load_branitzer_siedlung_attributes()` ⭐ **ATTRIBUTES LOADER**
```python
def load_branitzer_siedlung_attributes(path: Union[str, Path]) -> pd.DataFrame
```

**Purpose**: Load enriched building attributes from `output_branitzer_siedlungV11.json`

**File Structure**:
```json
{
  "<GebaeudeID>": {
    "GebaeudeID": "...",
    "Gebaeudefunktion": "...",
    "Gebaeudecode": ...,
    "Adressen": [{"strasse": "...", ...}],
    "Gesamtnettonutzflaeche": ...,
    "Gesamtvolumen": ...,
    "Gesamtgrundflaeche": ...,
    "Gesamtwandflaeche": ...,
    ...
  }
}
```

**Returns**: DataFrame with columns:
- `building_id` (matches DEBBAL... ids used elsewhere)
- `building_function` (German string like 'Wohnhaus', 'Garage', ...)
- `building_code` (numeric code)
- `street_name` (extracted from `Adressen[].strasse` when present)
- `floor_area_m2` (`Gesamtnettonutzflaeche`)
- `volume_m3` (`Gesamtvolumen`)
- `footprint_m2` (`Gesamtgrundflaeche`)
- `wall_area_m2` (`Gesamtwandflaeche`)

---

#### `load_gebaeudeanalyse()` ⭐ **RENOVATION STATE LOADER**
```python
def load_gebaeudeanalyse(path: Union[str, Path]) -> pd.DataFrame
```

**Purpose**: Load building renovation state and heat density from `gebaeudeanalyse.json`

**File Structure**:
```json
{
  "gebaeude": [
    {
      "gebaeude_id": "...",
      "sanierungszustand": "...",
      "waermedichte": ...
    },
    ...
  ]
}
```

**Returns**: DataFrame with columns:
- `building_id` (from `gebaeude_id`)
- `sanierungszustand` (renovation state: "vollsaniert", "teilsaniert", "unsaniert")
- `waermedichte` (heat density)

---

#### `load_processed_buildings()` ⭐ **PROCESSED BUILDINGS LOADER**
```python
def load_processed_buildings(
    cluster_buildings: Optional[List[str]] = None,
    force_reload: bool = False
) -> gpd.GeoDataFrame
```

**Purpose**: Load processed buildings (residential with heat demand) with caching

**Workflow**:
1. **Check Cache**: If `data/processed/buildings.parquet` exists and is already filtered (has `use_type`, `annual_heat_demand_kwh_a` columns):
   - Load from cache (fast path)
   - Filter to cluster if `cluster_buildings` provided
   - Return cached buildings
2. **Load & Filter** (if cache miss or `force_reload=True`):
   - Load raw buildings from `data/raw/hausumringe_mit_adressenV3.geojson` (or alternatives)
   - Apply `filter_residential_buildings_with_heat_demand()`
   - Save to `data/processed/buildings.parquet` (with metadata sidecar `.meta.json`)
   - Filter to cluster if requested
   - Return filtered buildings

**Benefits**:
- Fast subsequent loads (cached filtered buildings)
- Metadata sidecar for auditability (filter date, criteria, source file)
- Cluster filtering support (load subset for specific cluster)

---

#### `load_buildings_geojson()` ⭐ **BUILDINGS GEOJSON LOADER**
```python
def load_buildings_geojson(path: Union[str, Path]) -> gpd.GeoDataFrame
```

**Purpose**: Load buildings from GeoJSON with comprehensive validation

**Validation Rules**:

1. **Building ID Validation**:
   - Must have `building_id` column (unique, scalar strings)
   - **Special Handling**: If `gebaeude` column exists (legacy list/dict structure), extracts stable scalar ID:
     - Handles JSON string `gebaeude`: `'{"oi": "DEBBAL...", ...}'` → `"DEBBAL..."`
     - Handles list/dict `gebaeude`: Extracts first `gebaeude_id`, `building_id`, `id`, `oi`, or `objectid`
     - Falls back to deterministic JSON stringification if no scalar ID found
   - Generates synthetic IDs (`B000001`, ...) if no ID column found

2. **Geometry Validation**:
   - Must have geometry column (Polygon or MultiPolygon)
   - CRS must be projected (not geographic); converts to EPSG:25833 if needed

3. **Column Standardization**:
   - Maps common column names: `floor_area` → `floor_area_m2`, `year_built` → `year_of_construction`, etc.

4. **Numeric Validation**:
   - Checks for NaN/inf in required numeric columns
   - Checks for negative values in required numeric columns

**Returns**: Validated GeoDataFrame with standardized columns

---

#### `load_streets_geojson()` ⭐ **STREETS GEOJSON LOADER**
```python
def load_streets_geojson(path: Union[str, Path]) -> gpd.GeoDataFrame
```

**Purpose**: Load streets from GeoJSON with validation

**Validation Rules**:

1. **Manual GeoJSON Parsing** (for list `name` fields):
   - Parses GeoJSON manually to handle list `name` values (explodes into multiple features)
   - Prevents loss of street names due to GDAL/pyogrio limitations

2. **Street Name Handling**:
   - Standardizes `name` → `street_name`
   - Coerces list/dict values to scalar strings (should be rare after manual parsing)
   - Generates synthetic `street_id` if no identifier found

3. **Geometry Validation**:
   - Must be LineString or MultiLineString (explodes MultiLineString to LineString)
   - CRS must be projected (infers EPSG:25833 from coordinate magnitudes if missing)
   - Computes `length_m` (must be > 0)

4. **Column Standardization**:
   - Ensures `street_name` or `street_id` exists
   - Maps `id` → `street_id`

**Returns**: Validated GeoDataFrame with LineString geometries and street names

---

#### `load_power_grid()` ⭐ **POWER GRID LOADER**
```python
def load_power_grid(
    lines_path: Union[str, Path],
    substations_path: Union[str, Path]
) -> Dict[str, gpd.GeoDataFrame]
```

**Purpose**: Load LV power grid from GeoJSON files

**Validation**:
- Loads `power_lines.geojson` and `power_substations.geojson`
- Sets default `voltage_kv = 0.4` (LV) if missing
- Sets default `capacity_kva = 630` if missing
- Reprojects substations to match lines CRS if mismatch

**Returns**: Dictionary with keys:
- `'lines'`: GeoDataFrame of power lines
- `'substations'`: GeoDataFrame of power substations

---

**Interactions**:
- **Uses**: Raw data files (`data/raw/*.geojson`, `data/raw/*.json`), processed cache (`data/processed/buildings.parquet`)
- **Used by**: CHA pipeline (buildings/streets), DHA pipeline (power grid), data preparation scripts
- **Outputs**: Validated GeoDataFrames (buildings, streets, power grid)

---

### `typology.py` (327 lines) ⭐ **BUILDING TYPOLOGY**
**Purpose**: Estimate building envelope parameters using TABULA typology (U-values, heat demand)

**Main Functions**:

#### `estimate_envelope()` ⭐ **ENVELOPE ESTIMATION**
```python
def estimate_envelope(buildings: gpd.GeoDataFrame) -> gpd.GeoDataFrame
```

**Purpose**: Estimate building envelope parameters using TABULA typology

**Workflow**:

1. **Classification**:
   - **Use Type**: From `building_code` (numeric) or `building_function` (string)
     - `1000-1199` → `residential_sfh`
     - `2000-2399` → `retail`
     - `3000-3299` → `office`
     - Falls back to string heuristics (`wohn*` → `residential_sfh`, etc.)
   - **Construction Band**: From `year_of_construction`
     - `≤1978` → `pre_1978`
     - `1979-1994` → `1979_1994`
     - `1995-2009` → `1995_2009`
     - `≥2010` → `post_2010`
   - **Renovation State**: From `sanierungszustand` or defaults to `unrenovated`

2. **U-Value Lookup**:
   - **Priority 1**: Legacy `uwerte3.json` (by `building_code`) if available
   - **Priority 2**: TABULA `U_TABLE` (by `(use_type, construction_band, renovation_state)`)
   - **Priority 3**: Fallback defaults (`u_wall=0.5`, `u_roof=0.4`, `u_window=1.5`)

3. **Heat Loss Coefficient Calculation**:
   - **Transmission Loss** (`h_trans_w_per_k`): `U_wall × A_wall + U_roof × A_roof + U_floor × A_floor`
   - **Ventilation Loss** (`h_vent_w_per_k`): `0.33 × air_change_rate × volume` (W/K)
   - **Total Loss** (`h_total_w_per_k`): `h_trans + h_vent`

4. **Annual Heat Demand Estimation**:
   - If missing: `annual_heat_demand_kwh_a = specific_heat_demand_kwh_m2a × floor_area_m2`
   - Falls back to default `25000 kWh/a` if `floor_area_m2` missing

**Returns**: GeoDataFrame with added columns:
- `use_type`, `construction_band`, `renovation_state`
- `u_wall`, `u_roof`, `u_window` (U-values in W/m²K)
- `specific_heat_demand_kwh_m2a` (TABULA-specific demand)
- `h_trans_w_per_k`, `h_vent_w_per_k`, `h_total_w_per_k` (heat loss coefficients)
- `t_indoor_c`, `air_change_1_h`, `window_area_share` (indoor conditions)
- `annual_heat_demand_kwh_a` (if missing, estimated)

**Helper Functions**:

#### `_default_uwerte3_path()` ⭐ **U-VALUES PATH LOCATOR**
```python
def _default_uwerte3_path() -> Optional[Path]
```

**Purpose**: Locate `uwerte3.json` deterministically

**Search Order**:
1. `data/raw/uwerte3.json` (preferred for pipeline reproducibility)
2. `Legacy/fromDifferentThesis/gebaeudedaten/uwerte3.json` (repo-shipped legacy)

**Returns**: Path if found, `None` otherwise

#### `_load_uwerte3_table()` ⭐ **U-VALUES TABLE LOADER**
```python
def _load_uwerte3_table(path: Path) -> Dict[int, Dict[str, float]]
```

**Purpose**: Load legacy U-values table keyed by integer `building_code`

**Returns**: Dictionary `{building_code: {u_ausenwand, u_fenster, u_dach, u_bodenplatte, innentemperatur, luftwechselrate, fensterflaechenanteil}}`

#### `classify_construction_band()` ⭐ **CONSTRUCTION BAND CLASSIFIER**
```python
def classify_construction_band(year: int) -> str
```

**Purpose**: Map construction year to TABULA construction band

**Mapping**:
- `≤1978` → `'pre_1978'`
- `1979-1994` → `'1979_1994'`
- `1995-2009` → `'1995_2009'`
- `≥2010` → `'post_2010'`

#### `classify_use_type()` ⭐ **USE TYPE CLASSIFIER**
```python
def classify_use_type(building_function: str) -> str
```

**Purpose**: Map German building function to standard use type

**Mapping**:
- `wohn*` or `residential*` → `'residential_sfh'`
- `mfh*` or `mehrfam*` → `'residential_mfh'`
- `office*` or `büro*` → `'office'`
- `school*` or `schule*` → `'school'`
- `retail*` or `handel*` → `'retail'`
- Default → `'unknown'`

#### `_classify_use_type_from_code()` ⭐ **USE TYPE FROM CODE**
```python
def _classify_use_type_from_code(building_code: object, building_function: object) -> str
```

**Purpose**: Prefer deterministic mapping from numeric `building_code`, fall back to `building_function` heuristics

**Code Mapping**:
- `1000-1199` → `'residential_sfh'`
- `2000-2399` → `'retail'`
- `3000-3299` → `'office'`

**Interactions**:
- **Uses**: Raw data files (`data/raw/uwerte3.json`), building GeoDataFrame (from `loader.py`)
- **Used by**: Data preparation scripts, CHA pipeline (for building heat demand estimation)
- **Outputs**: Enriched buildings GeoDataFrame with envelope parameters

---

### `profiles.py` (167 lines) ⭐ **PROFILE GENERATION**
**Purpose**: Generate hourly heat demand profiles for buildings

**Main Functions**:

#### `generate_hourly_profiles()` ⭐ **PROFILE GENERATOR**
```python
def generate_hourly_profiles(
    buildings: gpd.GeoDataFrame,
    weather_df: pd.DataFrame,
    t_base: float = 15.0,
    space_share: float = 0.85,
    dhw_share: float = 0.15,
    blend_alpha: float = 0.7,
    seed: int = 42
) -> pd.DataFrame
```

**Purpose**: Generate 8760 hourly heat demand profiles for all buildings

**Inputs**:
- `buildings`: GeoDataFrame with `building_id`, `use_type`, `annual_heat_demand_kwh_a` (optional), `h_total_w_per_k` (optional)
- `weather_df`: DataFrame with 8760 rows and `temperature_c` column
- `t_base`: Base temperature for heating degree days (default: 15.0°C)
- `space_share`: Share of annual heat for space heating (default: 0.85)
- `dhw_share`: Share for domestic hot water (default: 0.15)
- `blend_alpha`: Weight for weather-driven vs use-type shape (default: 0.7)
- `seed`: Random seed for reproducibility (default: 42)

**Workflow** (per building):

1. **Space Heating Shape**:
   - **If `h_total_w_per_k` available** (physics-based):
     - `Q_space(t) = H_total × max(0, T_indoor - T_outdoor)` (W)
     - Normalized to sum to 1
   - **Else** (weather-driven):
     - Heating degree days: `HDD(t) = max(0, t_base - T_outdoor)`
     - Weather shape: `HDD(t) / sum(HDD)`
     - Use-type shape: `get_use_type_profile(use_type)` (currently placeholder)
     - Blended shape: `blend_alpha × weather_shape + (1 - blend_alpha) × type_shape`

2. **Annual Demand Handling**:
   - If `annual_heat_demand_kwh_a` missing or ≤ 0:
     - If physics-based: Estimate from `h_total_w_per_k` and weather
     - Else: Use default `25000 kWh/a`

3. **Profile Components**:
   - **Space Heating**: `annual_space × space_shape` (kWh/h)
   - **DHW**: Flat profile `annual_dhw / 8760` (kWh/h)
   - **Total**: `space_profile + dhw_profile` (kWh/h)

4. **Validation**:
   - Validates sum equals `annual_heat_demand_kwh_a` (within 1% tolerance)
   - Logs warnings for mismatches

**Returns**: DataFrame with:
- Index: `hour` (0-8759)
- Columns: `building_id` (one per building)
- Values: Heat demand in `kW_th` (kWh/h)

**Helper Functions**:

#### `get_use_type_profile()` ⭐ **USE TYPE PROFILE**
```python
def get_use_type_profile(use_type: str) -> np.ndarray
```

**Purpose**: Get standardized daily profile shape for use type (placeholder implementation)

**Current Implementation**: Returns flat profile (`np.ones(8760) / 8760`)

**Future Enhancement**: Load from TABULA/VDI profiles

**Interactions**:
- **Uses**: Buildings GeoDataFrame (from `loader.py` or `typology.py`), weather DataFrame (from `data/processed/hourly_weather.csv`)
- **Used by**: Data preparation scripts, CHA pipeline (for hourly heat demand)
- **Outputs**: Hourly profiles DataFrame (`data/processed/hourly_heat_profiles.parquet`)

---

### `cluster.py` (714 lines) ⭐ **CLUSTERING & AGGREGATION**
**Purpose**: Create street-based clusters and aggregate building-level profiles to cluster-level

**Main Functions**:

#### `aggregate_cluster_profiles()` ⭐ **PROFILE AGGREGATION**
```python
def aggregate_cluster_profiles(
    hourly_profiles: pd.DataFrame,
    cluster_map: pd.DataFrame
) -> Dict[str, pd.Series]
```

**Purpose**: Aggregate building-level hourly profiles to cluster-level

**Workflow**:
1. Validates inputs (8760 rows in `hourly_profiles`, `building_id` column in `cluster_map`)
2. Resolves `cluster_id` column (handles aliases: `cluster_id`, `street_id`, `street_cluster`)
3. For each cluster:
   - Finds buildings in cluster
   - Filters to buildings that exist in `hourly_profiles`
   - Sums hourly profiles across buildings: `cluster_profile = hourly_profiles[buildings].sum(axis=1)`
   - Creates zero series if no buildings found (warns)

**Returns**: Dictionary `{cluster_id: Series(8760)}` with aggregated hourly heat demand (kW_th)

---

#### `compute_design_and_topn()` ⭐ **DESIGN HOUR COMPUTATION**
```python
def compute_design_and_topn(
    cluster_profiles: Dict[str, pd.Series],
    N: int = 10,
    source_profiles: str = "hourly_heat_profiles.parquet",
    version: str = "v1"
) -> Dict
```

**Purpose**: Compute design hour and top-N hours for each cluster

**Workflow**:
1. For each cluster:
   - **Design Hour**: Hour with maximum load (`series.idxmax()`)
   - **Design Load**: Maximum load (`series.max()`)
   - **Top-N Hours**: N hours with highest loads (sorted descending)
   - **Top-N Loads**: Corresponding load values

**Returns**: Dictionary ready for JSON serialization:
```json
{
  "clusters": {
    "cluster_id": {
      "design_hour": int,
      "design_load_kw": float,
      "topn_hours": [int, ...],
      "topn_loads_kw": [float, ...]
    }
  },
  "meta": {
    "N": int,
    "source_profiles": str,
    "version": str
  }
}
```

---

#### `create_cluster_summary()` ⭐ **CLUSTER SUMMARY CREATOR**
```python
def create_cluster_summary(
    cluster_profiles: Dict[str, pd.Series],
    cluster_map: pd.DataFrame,
    buildings_df: pd.DataFrame,
    design_topn_dict: Dict
) -> pd.DataFrame
```

**Purpose**: Create summary table with one row per cluster

**Summary Columns**:
- `cluster_id`: Cluster identifier
- `n_buildings`: Number of buildings in cluster
- `annual_heat_kwh_a`: Sum of building annual heat demand
- `design_hour`: Design hour (from `design_topn_dict`)
- `design_load_kw`: Design load (kW)
- `topn_mean_kw`: Mean of top-N loads
- `topn_min_kw`: Minimum of top-N loads
- `topn_max_kw`: Maximum of top-N loads

**Returns**: DataFrame with one row per cluster

---

#### `extract_street_from_address()` ⭐ **STREET EXTRACTOR**
```python
def extract_street_from_address(address_data) -> Optional[str]
```

**Purpose**: Extract street name from building address data

**Handles**:
- List of addresses: Takes first address
- Dict format: Extracts `'str'`, `'street'`, or `'strasse'` key
- String format: Parses full address (removes house number)

**Returns**: Street name string, or `None` if not found

---

#### `normalize_street_name()` ⭐ **STREET NAME NORMALIZER**
```python
def normalize_street_name(name: str) -> str
```

**Purpose**: Normalize street name for matching

**Normalization**:
- Case normalization (uppercase)
- German character variations (`ß` → `SS`, umlauts)
- Abbreviation handling (`Str.` → `Strasse`, `St.` → `Strasse`)
- Remove special characters, extra whitespace

**Returns**: Normalized street name

---

#### `match_buildings_to_streets()` ⭐ **BUILDING-STREET MATCHER**
```python
def match_buildings_to_streets(
    buildings: gpd.GeoDataFrame,
    streets: gpd.GeoDataFrame,
    max_distance_m: float = 500.0
) -> pd.DataFrame
```

**Purpose**: Match buildings to streets based on address data and spatial proximity

**Matching Strategy**:

1. **Address-Based Matching** (primary):
   - Extracts street name from building `adressen` column
   - Normalizes building street name and street GeoDataFrame street names
   - **Exact Match**: Normalized building street name matches normalized street name
   - **Fuzzy Match**: Normalized building street name contained in (or contains) normalized street name

2. **Spatial Fallback** (if address matching fails):
   - Finds nearest street segment (by centroid distance)
   - Matches if distance ≤ `max_distance_m` (default: 500 m)

**Returns**: DataFrame with columns:
- `building_id`: Building identifier
- `street_name`: Matched street name
- `street_normalized`: Normalized street name
- `matched_method`: `'address_exact'`, `'address_fuzzy'`, or `'spatial'`

---

#### `create_street_clusters()` ⭐ **STREET CLUSTER CREATOR**
```python
def create_street_clusters(
    buildings: gpd.GeoDataFrame,
    building_street_map: pd.DataFrame,
    streets: gpd.GeoDataFrame
) -> Tuple[pd.DataFrame, pd.DataFrame]
```

**Purpose**: Create street-based clusters from building-to-street mappings

**Workflow**:
1. Groups buildings by `street_name` (from `building_street_map`)
2. For each street:
   - Creates cluster ID: `ST{number:03d}_{STREET_NAME_NORMALIZED}` (e.g., `ST001_HEINRICH_ZILLE_STRASSE`)
   - Calculates plant location: Centroid of cluster buildings (or street midpoint fallback)
   - Records cluster metadata

**Returns**: Tuple of:
- `building_cluster_map`: DataFrame with `['building_id', 'cluster_id']`
- `street_clusters`: DataFrame with cluster metadata (`street_id`, `cluster_name`, `plant_x`, `plant_y`, `building_count`)

---

#### `save_design_topn_json()` ⭐ **DESIGN TOPN EXPORTER**
```python
def save_design_topn_json(
    design_topn_dict: Dict,
    path: Union[str, Path],
    indent: int = 2
) -> None
```

**Purpose**: Save design hour and top-N hours dictionary to JSON file

**Validation**:
- Validates structure (`clusters`, `meta` keys)
- Creates directory if needed
- Writes JSON with proper formatting

**Saves**: `data/processed/cluster_design_topn.json`

---

#### `save_cluster_summary_parquet()` ⭐ **CLUSTER SUMMARY EXPORTER**
```python
def save_cluster_summary_parquet(
    summary_df: pd.DataFrame,
    path: Union[str, Path],
    compression: str = 'snappy',
    index: bool = False
) -> None
```

**Purpose**: Save cluster summary DataFrame to parquet file

**Validation**:
- Validates required columns (`cluster_id`, `n_buildings`, `annual_heat_kwh_a`, `design_hour`, `design_load_kw`)
- Creates directory if needed
- Writes parquet with compression (default: snappy)

**Saves**: `data/processed/cluster_load_summary.parquet`

---

**Interactions**:
- **Uses**: Hourly profiles (from `profiles.py`), cluster map (from clustering functions), buildings DataFrame
- **Used by**: Data preparation scripts, CHA pipeline (for cluster-based analysis)
- **Outputs**: Cluster profiles dictionary, design/top-N JSON, cluster summary parquet

---

## Complete Workflow

### Data Preparation Pipeline

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. Load Raw Data (loader.py)                                     │
│    - load_buildings_geojson() → Buildings GeoDataFrame           │
│    - load_streets_geojson() → Streets GeoDataFrame               │
│    - load_branitzer_siedlung_attributes() → Attributes DataFrame │
│    - load_gebaeudeanalyse() → Renovation State DataFrame         │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 2. Filter Buildings (loader.py)                                  │
│    - filter_residential_buildings_with_heat_demand()             │
│    Output: Filtered buildings (residential with heat demand)     │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 3. Estimate Building Envelope (typology.py)                     │
│    - estimate_envelope()                                         │
│    - Classify use_type, construction_band, renovation_state      │
│    - Lookup U-values (uwerte3.json or TABULA)                   │
│    - Calculate h_total_w_per_k                                   │
│    - Estimate annual_heat_demand_kwh_a (if missing)             │
│    Output: Enriched buildings with envelope parameters           │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 4. Generate Hourly Profiles (profiles.py)                       │
│    - generate_hourly_profiles(buildings, weather_df)             │
│    - Space heating shape (physics-based or weather-driven)       │
│    - DHW profile (flat)                                          │
│    - Validate annual sum                                         │
│    Output: hourly_heat_profiles.parquet [8760 × n_buildings]     │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 5. Create Street Clusters (cluster.py)                           │
│    - match_buildings_to_streets(buildings, streets)              │
│    - create_street_clusters(buildings, building_street_map)      │
│    Output: building_cluster_map.parquet, street_clusters.parquet │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 6. Aggregate Cluster Profiles (cluster.py)                       │
│    - aggregate_cluster_profiles(hourly_profiles, cluster_map)    │
│    - compute_design_and_topn(cluster_profiles, N=10)             │
│    - create_cluster_summary(...)                                 │
│    Output: cluster_design_topn.json, cluster_load_summary.parquet│
└─────────────────────────────────────────────────────────────────┘
```

---

## File Interactions & Dependencies

### Internal Dependencies (Within Data Module)

```
Data Module
├─ loader.py (DATA LOADER)
│  ├─ Uses: Raw GeoJSON files, processed cache
│  └─ Used by: typology.py, profiles.py, cluster.py
│
├─ typology.py (BUILDING TYPOLOGY)
│  ├─ Uses: loader.py (load_buildings_geojson), uwerte3.json
│  └─ Used by: profiles.py (for h_total_w_per_k)
│
├─ profiles.py (PROFILE GENERATION)
│  ├─ Uses: loader.py (buildings), typology.py (h_total_w_per_k), weather DataFrame
│  └─ Used by: cluster.py (for hourly_profiles)
│
└─ cluster.py (CLUSTERING)
   ├─ Uses: loader.py (buildings, streets), profiles.py (hourly_profiles)
   └─ Used by: CHA pipeline (cluster-based analysis)
```

### External Dependencies (Outside Data Module)

```
Data Module
  ├─ Uses:
  │  ├─ Raw data files: data/raw/*.geojson, data/raw/*.json
  │  ├─ Processed cache: data/processed/buildings.parquet
  │  ├─ Weather data: data/processed/hourly_weather.csv
  │  └─ Legacy files: Legacy/fromDifferentThesis/gebaeudedaten/uwerte3.json
  │
  ├─ Called by:
  │  ├─ Data preparation scripts: scripts/00_prepare_data.py
  │  ├─ CHA pipeline: scripts/01_run_cha.py
  │  └─ DHA pipeline: scripts/02_run_dha.py
  │
  └─ Outputs:
     ├─ Processed buildings: data/processed/buildings.parquet
     ├─ Hourly profiles: data/processed/hourly_heat_profiles.parquet
     ├─ Cluster map: data/processed/building_cluster_map.parquet
     ├─ Street clusters: data/processed/street_clusters.parquet
     ├─ Design/top-N: data/processed/cluster_design_topn.json
     └─ Cluster summary: data/processed/cluster_load_summary.parquet
```

---

## Key Workflows & Patterns

### 1. Building ID Extraction Pattern (`load_buildings_geojson`)

**Pattern**: Extract stable scalar ID from legacy list/dict `gebaeude` structures

```python
def _extract_building_id_from_gebaeude(val: Any) -> Optional[str]:
    # Handle JSON string: '{"oi": "DEBBAL...", ...}' → "DEBBAL..."
    if isinstance(val, str) and (val.startswith("{") or val.startswith("[")):
        parsed = json.loads(val)
        return _extract_building_id_from_gebaeude(parsed)
    
    # Handle list/dict: Extract first scalar ID
    if isinstance(val, list) and len(val) > 0:
        first = val[0]
        if isinstance(first, dict):
            for key in ("gebaeude_id", "building_id", "id", "oi", "objectid"):
                if key in first and first[key] is not None:
                    return str(first[key])
    
    # Handle dict: Extract scalar ID
    if isinstance(val, dict):
        for key in ("gebaeude_id", "building_id", "id", "oi", "objectid"):
            if key in val and val[key] is not None:
                return str(val[key])
    
    # Scalar fallback
    return str(val) if val is not None else None
```

**Benefits**:
- Stable IDs across runs (deterministic extraction)
- Handles legacy data formats
- Prevents non-scalar IDs (lists/dicts) from breaking profile alignment

---

### 2. Caching Pattern (`load_processed_buildings`)

**Pattern**: Cache filtered buildings with metadata sidecar

```python
# Check cache
if not force_reload and BUILDINGS_PATH.exists():
    buildings = gpd.read_parquet(BUILDINGS_PATH)
    if _looks_like_filtered(buildings):  # Has required columns
        meta_info = json.loads(meta_path.read_text())
        logger.info(f"Loaded {len(buildings)} pre-filtered buildings")
        return buildings

# Load & filter (if cache miss)
buildings = load_buildings_geojson(raw_path)
buildings = filter_residential_buildings_with_heat_demand(buildings)

# Save cache
buildings.to_parquet(BUILDINGS_PATH)
meta_path.write_text(json.dumps({"filtered": True, "filter_date": ...}))
```

**Benefits**:
- Fast subsequent loads (no re-filtering)
- Metadata auditability (filter date, criteria)
- Safe fallback (reloads if cache invalid)

---

### 3. Profile Generation Pattern (`generate_hourly_profiles`)

**Pattern**: Physics-based profile generation with weather-driven fallback

```python
# Physics-based (preferred if h_total available)
if np.isfinite(h_total) and h_total > 0:
    dT = np.maximum(0.0, t_indoor - temp_c)
    raw_space_kw = (h_total * dT) / 1000.0
    space_shape = raw_space_kw / raw_space_kw.sum()
else:
    # Weather-driven fallback
    hdd = np.maximum(0, t_base - temp_c)
    weather_shape = hdd / hdd.sum()
    type_shape = get_use_type_profile(use_type)
    space_shape = blend_alpha * weather_shape + (1 - blend_alpha) * type_shape

# Apply annual demand
space_profile = (annual_demand * space_share) * space_shape
dhw_profile = np.full(8760, (annual_demand * dhw_share) / 8760)
total_profile = space_profile + dhw_profile
```

**Benefits**:
- Physics-based accuracy when `h_total` available (from typology)
- Weather-driven fallback for legacy compatibility
- Validates annual sum (catches errors early)

---

### 4. Street Matching Pattern (`match_buildings_to_streets`)

**Pattern**: Multi-strategy matching (address-first, spatial fallback)

```python
# Strategy 1: Address-based matching
street_name_from_address = extract_street_from_address(building['adressen'])
if street_name_from_address:
    normalized_address = normalize_street_name(street_name_from_address)
    if normalized_address in street_normalized_map:
        matched_street = street_normalized_map[normalized_address]
        match_method = 'address_exact'
    else:
        # Fuzzy match (containment check)
        for norm_street, orig_street in street_normalized_map.items():
            if normalized_address in norm_street or norm_street in normalized_address:
                matched_street = orig_street
                match_method = 'address_fuzzy'
                break

# Strategy 2: Spatial fallback
if matched_street is None:
    building_point = building.geometry.centroid
    nearest_street_idx = find_nearest_street(building_point, streets)
    if distance <= max_distance_m:
        matched_street = streets.loc[nearest_street_idx, 'street_name']
        match_method = 'spatial'
```

**Benefits**:
- Accurate matching (address-first, high precision)
- Robust fallback (spatial matching for missing addresses)
- Transparent matching method (logs strategy used)

---

### 5. Cluster Aggregation Pattern (`aggregate_cluster_profiles`)

**Pattern**: Sum building-level profiles to cluster-level

```python
# For each cluster
for cluster_id in unique_clusters:
    cluster_buildings = cluster_map[cluster_map[cluster_id_col] == cluster_id]['building_id'].tolist()
    available_buildings = [b for b in cluster_buildings if b in hourly_profiles.columns]
    
    if len(available_buildings) == 0:
        cluster_profiles[cluster_id] = pd.Series(0.0, index=hourly_profiles.index)
        continue
    
    # Sum across buildings
    cluster_profile = hourly_profiles[available_buildings].sum(axis=1)
    cluster_profiles[cluster_id] = cluster_profile
```

**Benefits**:
- Simple aggregation (sum preserves annual totals)
- Handles missing buildings gracefully (zero series)
- Validates cluster membership (logs warnings)

---

## Usage Examples

### Complete Data Preparation

```python
from branitz_heat_decision.data.loader import (
    load_processed_buildings,
    load_streets_geojson,
    load_branitzer_siedlung_attributes,
    load_gebaeudeanalyse
)
from branitz_heat_decision.data.typology import estimate_envelope
from branitz_heat_decision.data.profiles import generate_hourly_profiles
from branitz_heat_decision.data.cluster import (
    match_buildings_to_streets,
    create_street_clusters,
    aggregate_cluster_profiles,
    compute_design_and_topn,
    create_cluster_summary,
    save_design_topn_json,
    save_cluster_summary_parquet
)

# 1. Load processed buildings (with caching)
buildings = load_processed_buildings()

# 2. Enrich with attributes
attributes = load_branitzer_siedlung_attributes("data/raw/output_branitzer_siedlungV11.json")
buildings = buildings.merge(attributes, on="building_id", how="left")

renovation = load_gebaeudeanalyse("data/raw/gebaeudeanalyse.json")
buildings = buildings.merge(renovation, on="building_id", how="left")

# 3. Estimate envelope (U-values, h_total)
buildings = estimate_envelope(buildings)

# 4. Generate hourly profiles
weather_df = pd.read_csv("data/processed/hourly_weather.csv")
hourly_profiles = generate_hourly_profiles(buildings, weather_df)

# 5. Create street clusters
streets = load_streets_geojson("data/raw/strassen.geojson")
building_street_map = match_buildings_to_streets(buildings, streets)
building_cluster_map, street_clusters = create_street_clusters(
    buildings, building_street_map, streets
)

# 6. Aggregate cluster profiles
cluster_profiles = aggregate_cluster_profiles(hourly_profiles, building_cluster_map)
design_topn_dict = compute_design_and_topn(cluster_profiles, N=10)
cluster_summary = create_cluster_summary(
    cluster_profiles, building_cluster_map, buildings, design_topn_dict
)

# 7. Save outputs
save_design_topn_json(design_topn_dict, "data/processed/cluster_design_topn.json")
save_cluster_summary_parquet(cluster_summary, "data/processed/cluster_load_summary.parquet")
```

### Filtering Buildings for a Specific Cluster

```python
from branitz_heat_decision.data.cluster import aggregate_cluster_profiles
import pandas as pd

# Load cluster map
cluster_map = pd.read_parquet("data/processed/building_cluster_map.parquet")

# Get building IDs for a specific cluster
cluster_id = "ST010_HEINRICH_ZILLE_STRASSE"
cluster_buildings = cluster_map[cluster_map["cluster_id"] == cluster_id]["building_id"].tolist()

# Load filtered buildings for cluster
buildings = load_processed_buildings(cluster_buildings=cluster_buildings)
```

### Typology Estimation with Legacy U-Values

```python
from branitz_heat_decision.data.typology import estimate_envelope

# Load buildings
buildings = load_processed_buildings()

# Estimate envelope (automatically uses uwerte3.json if available)
buildings = estimate_envelope(buildings)

# Check if h_total was computed
print(f"Buildings with h_total: {buildings['h_total_w_per_k'].notna().sum()}")
```

---

## Error Handling & Validation

### Input Validation

#### Building ID Validation (`load_buildings_geojson`)
- **Unique IDs**: Raises `DataValidationError` if duplicate `building_id` found
- **Scalar IDs**: Extracts scalar IDs from legacy list/dict `gebaeude` structures
- **Missing IDs**: Generates synthetic IDs (`B000001`, ...) if no ID column found

#### Geometry Validation (`load_buildings_geojson`, `load_streets_geojson`)
- **Buildings**: Must be Polygon or MultiPolygon (raises `DataValidationError` on other types)
- **Streets**: Must be LineString or MultiLineString (explodes MultiLineString to LineString)
- **CRS**: Must be projected (converts to EPSG:25833 if geographic)
- **Length**: Streets must have `length_m > 0` (raises `DataValidationError` if zero/negative)

#### Numeric Validation (`load_buildings_geojson`)
- **NaN/Inf**: Raises `DataValidationError` if NaN/inf found in required numeric columns
- **Negative Values**: Raises `DataValidationError` if negative values found in required numeric columns

---

### Error Handling Patterns

#### Graceful Degradation (`filter_residential_buildings_with_heat_demand`)
```python
# If >95% of buildings are unknown, skip residential filter
if unknownish.mean() > 0.95:
    logger.warning("use_type mostly unknown. Skipping residential filter.")
    # Continue without filter (avoid dropping all buildings)
```

#### Fallback Values (`estimate_envelope`)
```python
# Prefer uwerte3, fall back to TABULA, fall back to defaults
if uvals3 is not None:
    u_wall = uvals3.get("u_ausenwand", 0.5)
elif key in U_TABLE:
    u_wall = U_TABLE[key]['wall']
else:
    u_wall = 0.5  # Default fallback
```

#### Missing Building Handling (`aggregate_cluster_profiles`)
```python
# If no buildings found in hourly_profiles, create zero series
if len(available_buildings) == 0:
    warnings.warn(f"Cluster {cluster_id} has no buildings in hourly_profiles")
    cluster_profiles[cluster_id] = pd.Series(0.0, index=hourly_profiles.index)
```

---

## Performance Considerations

### Caching Strategy (`load_processed_buildings`)
- **Cache Hit**: O(1) file read (no filtering needed)
- **Cache Miss**: O(n) filtering operation (n = number of buildings)
- **Metadata Sidecar**: O(1) JSON read (small file)

### Profile Generation (`generate_hourly_profiles`)
- **Time Complexity**: O(n × 8760) where n = number of buildings
- **Memory**: Stores full 8760 × n DataFrame in memory
- **Optimization**: Physics-based profiles (`h_total` available) skip weather interpolation

### Cluster Aggregation (`aggregate_cluster_profiles`)
- **Time Complexity**: O(m × 8760) where m = number of clusters
- **Memory**: Stores m × 8760 dictionary (cluster profiles)
- **Optimization**: Vectorized sum (`sum(axis=1)`) for cluster aggregation

---

## Standards Compliance

### Building Typology Standards

- **TABULA**: European building typology database for U-values and specific heat demand
- **DIN EN ISO 13790**: Heat loss calculation method (transmission + ventilation)
- **DIN 4108**: U-value requirements for building components

### Data Validation Standards

- **GeoPandas**: Standardized geometry validation (Polygon, LineString, CRS)
- **Parquet**: Standardized column types and metadata storage
- **JSON Schema**: Validated structure for design/top-N dictionary

---

## References & Standards

- **TABULA**: European building typology database
- **DIN EN ISO 13790**: Thermal performance of buildings
- **DIN 4108**: Thermal insulation and energy economy in buildings
- **GeoJSON**: RFC 7946 standard for geographic data interchange
- **Parquet**: Apache Parquet columnar storage format

---

**Last Updated**: 2026-01-19  
**Module Version**: v1.1  
**Primary Maintainer**: Data Module Development Team

## Recent Updates (2026-01-19)

- **UI Index Enhancement**: Added `design_hour` field to cluster UI index
- **Street ID Compatibility**: Added `street_id` alias for backward compatibility with older scripts
- **Annual Demand Aggregation**: Fixed annual heat demand calculation in UI index
