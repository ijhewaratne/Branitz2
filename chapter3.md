# Chapter 3: System Architecture and Data Foundation

## 3.2 Data Foundation (HDA)

The **Heat Demand Agent (HDA)** serves as the foundational data preparation layer of the Branitz Heat Decision AI System. It transforms raw geospatial and building data into standardized, validated inputs for downstream agents (CHA, DHA, Economics). The HDA ensures data quality, consistency, and traceability through rigorous validation procedures.

### 3.2.1 Input Data

The HDA processes three primary data sources:

#### 3.2.1.1 Wärmekataster (Building Heat Cadastre)

**Source**: `hausumringe_mit_adressenV3.geojson` (GeoJSON format)

**Fields**:
- **Geometry**: Building footprints as polygons (EPSG:25833 or WGS84)
- **Building ID**: Unique identifier (normalized to `building_id` format)
- **Address Information**: Street name, building number
- **Building Function**: `Gebaeudefunktion` (e.g., "Wohnhaus", "Garage", "Gewerbe")
- **Building Code**: Numeric classification code (1000-1200: residential, 2000-2400: retail, 3000-3300: office)
- **Geometric Attributes** (from enrichment):
  - `Gesamtnettonutzflaeche` (Total net floor area, m²)
  - `Gesamtvolumen` (Total volume, m³)
  - `Gesamtgrundflaeche` (Footprint area, m²)
  - `Gesamtwandflaeche` (Total wall area, m²) - critical for U-value heat loss calculation

**Enrichment Sources**:
- `output_branitzer_siedlungV11.json`: Building attributes, addresses, geometric properties
- `gebaeudeanalyse.json`: Renovation state (`sanierungszustand`), heat density (`waermedichte`, kWh/m²a)

**Data Flow**:
```
hausumringe_mit_adressenV3.geojson
    ↓ (merge with enrichment files)
    ↓ (normalize building_id, extract addresses)
    ↓ (filter residential buildings)
buildings.parquet (processed)
```

#### 3.2.1.2 OSM Streets

**Source**: `strassen_mit_adressenV3_fixed.geojson` (GeoJSON format)

**Fields**:
- **Geometry**: Street centerlines as LineStrings (EPSG:25833)
- **Street Name**: Normalized street identifier
- **Street ID**: Unique identifier (synthetic if missing)

**Usage**:
- Network topology construction (CHA: district heating network routing)
- Building-to-street attachment (service connection points)
- Cluster definition (street-based building aggregation)

**Data Flow**:
```
strassen_mit_adressenV3_fixed.geojson
    ↓ (validate geometry, normalize names)
    ↓ (create street graph for network building)
street_graph (NetworkX) → CHA network builder
```

#### 3.2.1.3 Synthetic LV Grid

**Source**: `branitzer_siedlung_ns_v3_ohne_UW.json` (Legacy OSM-based format)

**Components**:
- **Buses**: Electrical nodes (substations, connection points)
  - Coordinates (lat/lon or projected)
  - Voltage level (0.4 kV for LV)
  - Capacity (kVA for transformers)
- **Lines**: Electrical conductors
  - Start/end bus connections
  - Length (m)
  - Type (cable/overhead)
  - Resistance, reactance parameters

**Usage**:
- DHA (District Heat Pump Agent): Powerflow simulation
- Hosting capacity analysis for heat pump integration
- Voltage drop and line loading calculations

**Data Flow**:
```
branitzer_siedlung_ns_v3_ohne_UW.json
    ↓ (parse OSM nodes/ways)
    ↓ (convert to pandapower network)
pandapower network → DHA powerflow simulation
```

---

### 3.2.2 Data Cleaning

The HDA implements comprehensive data validation and cleaning procedures to ensure downstream agents receive consistent, error-free inputs.

#### 3.2.2.1 CRS Validation

**Requirement**: All geospatial data must use a projected coordinate reference system (not geographic WGS84).

**Procedure**:
1. **CRS Detection**: Check if CRS is defined in GeoJSON metadata or GeoDataFrame
2. **Geographic CRS Handling**: If WGS84 (EPSG:4326) detected, automatically transform to EPSG:25833 (UTM Zone 33N)
3. **Missing CRS Handling**: 
   - Buildings: Infer from coordinate magnitudes (UTM: >100,000; WGS84: <100)
   - Default to EPSG:25833 if ambiguous
4. **CRS Consistency**: Ensure all datasets share the same CRS before spatial operations

**Code Example**:
```python
# From src/branitz_heat_decision/data/loader.py
if gdf.crs is None:
    logger.warning("No CRS defined. Assuming EPSG:25833")
    gdf.set_crs("EPSG:25833", inplace=True)
elif gdf.crs.is_geographic:
    logger.info(f"Geographic CRS detected ({gdf.crs}). Converting to EPSG:25833")
    gdf = gdf.to_crs("EPSG:25833")
```

**Validation Checks**:
- ✅ CRS must be defined (not `None`)
- ✅ CRS must be projected (not geographic)
- ✅ All datasets must share the same CRS before merging/spatial operations

#### 3.2.2.2 Missing Data Handling

**Building Data**:
- **Missing `annual_heat_demand_kwh_a`**: 
  - If `waermedichte` (kWh/m²a) and `floor_area_m2` available: `annual_demand = waermedichte × floor_area`
  - If `specific_heat_demand_kwh_m2a` (from TABULA) and `floor_area_m2` available: `annual_demand = specific_demand × floor_area`
  - Default: 25,000 kWh/a (conservative estimate)
- **Missing `use_type`**: 
  - Infer from `building_function` (German strings: "Wohnhaus" → `residential_sfh`)
  - Infer from `building_code` (1000-1200 → `residential_sfh`)
  - Default: `unknown` (excluded from residential filter)
- **Missing `year_of_construction`**: 
  - Default `construction_band`: `unknown` (uses fallback U-values)
- **Missing `renovation_state`**: 
  - Default: `unrenovated` (conservative, higher U-values)

**Street Data**:
- **Missing `street_name`**: Generate synthetic `street_id` from geometry hash
- **Missing `street_id`**: Auto-generate sequential IDs

**Weather Data**:
- **Missing `temperature_c`**: Raise `ValueError` (required for profile generation)
- **Missing hours**: Must have exactly 8760 rows (one per hour of year)

**Handling Strategy**:
- **Conservative Defaults**: Use worst-case assumptions (unrenovated, high U-values) when data missing
- **Logging**: All missing data cases are logged with warnings
- **Validation**: Critical fields (building_id, geometry, temperature) must be present

#### 3.2.2.3 Geometry Checks

**Building Geometry**:
- **Type Validation**: Must be Polygon or MultiPolygon
- **Validity Check**: `geometry.is_valid` (no self-intersections, closed rings)
- **Empty Geometry**: Filter out empty or null geometries
- **Area Validation**: Minimum footprint area > 0 m²
- **Coordinate Validation**: Check for NaN or infinite coordinates

**Street Geometry**:
- **Type Validation**: Must be LineString or MultiLineString
- **Length Validation**: Minimum length > 0 m
- **Endpoint Snapping**: Snap endpoints within 1.0 m to improve graph connectivity
- **Connectivity Check**: Ensure street graph is connected (single component)

**Code Example**:
```python
# From src/branitz_heat_decision/data/loader.py
if gdf.geometry.is_empty.any():
    logger.warning(f"Found {gdf.geometry.is_empty.sum()} empty geometries, removing")
    gdf = gdf[~gdf.geometry.is_empty]

if not gdf.geometry.is_valid.all():
    logger.warning(f"Found {(~gdf.geometry.is_valid).sum()} invalid geometries")
    # Attempt to fix with buffer(0) trick
    invalid = ~gdf.geometry.is_valid
    gdf.loc[invalid, 'geometry'] = gdf.loc[invalid, 'geometry'].buffer(0)
```

**Validation Checks**:
- ✅ All geometries must be valid (no self-intersections)
- ✅ All geometries must be non-empty
- ✅ Building footprints must have area > 0
- ✅ Street segments must have length > 0

---

### 3.2.3 Building Typology

The HDA uses **TABULA-based U-value estimation** to characterize building thermal performance. TABULA (Typology Approach for Building Stock Energy Assessment) provides standardized U-values based on construction period, building type, and renovation state.

#### 3.2.3.1 Construction Band Classification

Buildings are classified into construction bands based on `year_of_construction`:

| Construction Band | Year Range | Description |
|-------------------|------------|-------------|
| `pre_1978` | ≤ 1978 | Pre-thermal insulation regulations |
| `1979_1994` | 1979-1994 | Early thermal insulation standards |
| `1995_2009` | 1995-2009 | Improved insulation (EnEV 2002) |
| `post_2010` | ≥ 2010 | Modern standards (EnEV 2009+) |

**Code**:
```python
def classify_construction_band(year: int) -> str:
    if year <= 1978:
        return 'pre_1978'
    elif 1979 <= year <= 1994:
        return '1979_1994'
    elif 1995 <= year <= 2009:
        return '1995_2009'
    else:
        return 'post_2010'
```

#### 3.2.3.2 Renovation State Classification

Renovation states are normalized from German terms:

| Normalized State | German Terms | Description |
|------------------|--------------|-------------|
| `unrenovated` | "unsaniert", "unrenovated" | No thermal renovation |
| `partial` | "teilsaniert", "teil saniert", "partial" | Partial renovation (windows/roof) |
| `full` | "vollsaniert", "voll saniert", "fully_renovated" | Full thermal renovation |

#### 3.2.3.3 U-Value Lookup Tables

**TABULA U-Value Table** (W/(m²·K)):

**Single-Family Houses (SFH)**:

| Construction Band | Renovation | U_wall | U_roof | U_window |
|-------------------|------------|--------|--------|----------|
| pre_1978 | unrenovated | 1.2 | 1.0 | 2.7 |
| pre_1978 | partial | 0.6 | 0.5 | 1.8 |
| pre_1978 | full | 0.2 | 0.18 | 1.1 |
| 1979_1994 | unrenovated | 0.8 | 0.7 | 2.5 |
| 1979_1994 | partial | 0.4 | 0.35 | 1.6 |
| 1979_1994 | full | 0.15 | 0.13 | 0.9 |
| 1995_2009 | unrenovated | 0.5 | 0.4 | 1.8 |
| 1995_2009 | partial | 0.3 | 0.25 | 1.3 |
| 1995_2009 | full | 0.13 | 0.10 | 0.7 |
| post_2010 | unrenovated | 0.3 | 0.25 | 1.4 |
| post_2010 | full | 0.13 | 0.10 | 0.7 |

**Multi-Family Houses (MFH)**:

| Construction Band | Renovation | U_wall | U_roof | U_window |
|-------------------|------------|--------|--------|----------|
| pre_1978 | unrenovated | 1.4 | 1.2 | 2.8 |
| ... | ... | ... | ... | ... |

**Fallback Values** (when lookup fails):
- `U_wall = 0.5 W/(m²·K)`
- `U_roof = 0.4 W/(m²·K)`
- `U_window = 1.5 W/(m²·K)`

#### 3.2.3.4 Specific Heat Demand Lookup

**TABULA Specific Heat Demand** (kWh/(m²·a)):

| Use Type | Construction Band | Renovation | Specific Demand |
|----------|-------------------|------------|-----------------|
| residential_sfh | pre_1978 | unrenovated | 250 |
| residential_sfh | pre_1978 | full | 60 |
| residential_sfh | post_2010 | full | 40 |
| ... | ... | ... | ... |

**Fallback**: 100 kWh/(m²·a)

#### 3.2.3.5 Heat Loss Coefficient Calculation

For buildings with geometric data (`wall_area_m2`, `footprint_m2`, `volume_m3`), the total heat loss coefficient `H_total` (W/K) is calculated:

**Transmission Loss**:
```
H_trans = U_wall × A_wall + U_roof × A_roof + U_floor × A_floor
```

**Ventilation Loss**:
```
H_vent = 0.33 × air_change_rate × V
```

**Total Heat Loss Coefficient**:
```
H_total = H_trans + H_vent
```

Where:
- `A_wall`, `A_roof`, `A_floor`: Wall, roof, and floor areas (m²)
- `air_change_rate`: Air changes per hour (default: 0.5 h⁻¹)
- `V`: Building volume (m³)

**Usage**: `H_total` is used for physics-based hourly profile generation (see Section 3.2.4).

---

### 3.2.4 Hourly Profile Generation

The HDA generates 8760-hour (one year) heat demand profiles for each building, combining weather-driven space heating patterns with use-type-specific daily patterns.

#### 3.2.4.1 Profile Generation Formula

The hourly heat demand `Q_hour(t)` (kW) is calculated as:

```
Q_hour(t) = Q_space(t) + Q_dhw(t)
```

Where:

**Space Heating Profile**:
```
Q_space(t) = Q_annual_space × shape_space(t)
```

**Space Heating Shape** (normalized to sum to 1):
```
shape_space(t) = α × weather_shape(t) + (1 - α) × use_type_shape(t)
```

**Parameters**:
- `Q_annual_space = Q_annual × space_share` (annual space heating demand, kWh/a)
- `Q_annual_dhw = Q_annual × dhw_share` (annual DHW demand, kWh/a)
- `space_share = 0.85` (85% of annual demand for space heating)
- `dhw_share = 0.15` (15% for domestic hot water, residential only)
- `α = 0.7` (blend factor: 70% weather-driven, 30% use-type pattern)

#### 3.2.4.2 Weather-Driven Shape

**Heating Degree Days (HDD) Method**:
```
HDD(t) = max(0, T_base - T_out(t))
weather_shape(t) = HDD(t) / Σ(HDD)
```

Where:
- `T_base = 15.0°C` (base temperature for heating)
- `T_out(t)`: Outdoor temperature at hour `t` (°C)

**Physics-Based Method** (when `H_total` available):
```
Q_space_raw(t) = H_total × max(0, T_indoor - T_out(t)) / 1000  [kW]
shape_space(t) = Q_space_raw(t) / Σ(Q_space_raw)
```

Where:
- `T_indoor = 20.0°C` (indoor setpoint)
- `H_total`: Total heat loss coefficient (W/K)

#### 3.2.4.3 Use-Type Shape Patterns

**Residential Single-Family House (SFH)** - Standardized Daily Pattern:

The use-type shape captures daily occupancy patterns with morning and evening peaks:

```
Hour of Day Pattern (normalized):
- 00:00-06:00: Low (sleeping) - 0.8× baseline
- 06:00-08:00: Morning peak (wake-up, shower) - 1.5× baseline
- 08:00-17:00: Low (away from home) - 0.7× baseline
- 17:00-22:00: Evening peak (return home, cooking) - 1.4× baseline
- 22:00-24:00: Moderate (evening activity) - 1.0× baseline
```

**Seasonal Variation**:
- Winter months (Dec-Feb): +20% multiplier
- Summer months (Jun-Aug): -50% multiplier (space heating only, DHW constant)

**Multi-Family House (MFH)**: Similar pattern but with lower peak-to-baseline ratio (1.3× vs 1.5×) due to diversity.

**Non-Residential**: Flat profile (constant demand throughout day/year).

**Current Implementation Note**: The system currently uses a simplified flat use-type profile (`get_use_type_profile()` returns uniform distribution). Future enhancements will load standardized TABULA/VDI profiles.

#### 3.2.4.4 Domestic Hot Water (DHW) Profile

For residential buildings, DHW demand is modeled as a flat profile:

```
Q_dhw(t) = Q_annual_dhw / 8760  [kW]
```

**Future Enhancement**: DHW profiles can be upgraded to show morning/evening peaks (shower times).

#### 3.2.4.5 Complete Profile Example

**Input**:
- Building: Residential SFH, `Q_annual = 30,000 kWh/a`
- Weather: `T_out(t)` (8760 hours)
- `space_share = 0.85`, `dhw_share = 0.15`
- `α = 0.7`

**Calculation**:
1. `Q_annual_space = 30,000 × 0.85 = 25,500 kWh/a`
2. `Q_annual_dhw = 30,000 × 0.15 = 4,500 kWh/a`
3. For each hour `t`:
   - `HDD(t) = max(0, 15.0 - T_out(t))`
   - `weather_shape(t) = HDD(t) / Σ(HDD)`
   - `use_type_shape(t)` = SFH daily pattern (normalized)
   - `shape_space(t) = 0.7 × weather_shape(t) + 0.3 × use_type_shape(t)`
   - `Q_space(t) = 25,500 × shape_space(t)` [kWh]
   - `Q_dhw(t) = 4,500 / 8760` [kWh]
   - `Q_hour(t) = Q_space(t) + Q_dhw(t)` [kW]

#### 3.2.4.6 Validation

**Annual Sum Validation**:

The system validates that the sum of hourly profiles equals the annual demand within tolerance:

```
|Σ(Q_hour) - Q_annual| / Q_annual ≤ 0.01  (1% tolerance)
```

**Code Example**:
```python
# From src/branitz_heat_decision/data/profiles.py
for building_id in buildings['building_id']:
    annual_sum = float(profiles_df[building_id].sum())
    expected = buildings.loc[buildings['building_id'] == building_id, 
                            'annual_heat_demand_kwh_a'].iloc[0]
    if expected > 0 and abs(annual_sum - expected) > expected * 0.01:
        logger.warning(
            f"Building {building_id}: sum={annual_sum:.0f}, "
            f"expected={expected:.0f}, diff={abs(annual_sum - expected):.0f}"
        )
```

**Validation Checks**:
- ✅ Sum of 8760 hourly values = annual demand (±1% tolerance)
- ✅ All hourly values ≥ 0 (no negative demand)
- ✅ Profile has 8760 rows (one per hour)
- ✅ Peak demand occurs during winter months (weather-driven validation)

**Output Format**:
- **DataFrame**: `index = hour (0-8759)`, `columns = building_id`, `values = kW_th`
- **File**: `data/processed/hourly_heat_profiles.parquet`
- **Shape**: `(8760, n_buildings)`

---

### 3.2.5 Design Hour and Top-N Hours

After generating hourly profiles, the HDA computes:

1. **Design Hour**: Hour with maximum aggregated cluster load (used for CHA network sizing)
2. **Top-N Hours**: N hours with highest loads (default: N=10, used for robustness analysis)

**Code**:
```python
# From src/branitz_heat_decision/data/cluster.py
design_hour = int(series.idxmax())
design_load_kw = float(series.max())

top_n = series.sort_values(ascending=False).head(N)
topn_hours = [int(i) for i in top_n.index]
topn_loads_kw = [float(v) for v in top_n.values]
```

**Output**: `data/processed/cluster_design_topn.json`

---

## Summary

The HDA (Heat Demand Agent) provides the foundational data layer for the Branitz Heat Decision AI System:

- **Input**: Raw Wärmekataster, OSM streets, synthetic LV grid
- **Processing**: CRS validation, missing data handling, geometry checks, TABULA typology classification
- **Output**: Validated buildings, 8760-hour profiles, design hour, Top-N hours
- **Quality Assurance**: Comprehensive validation (CRS, geometry, annual sum tolerance ±1%)

All outputs are deterministic, traceable, and ready for downstream agents (CHA, DHA, Economics).

---

## 3.3 Centralized Heating Agent (CHA)

The **Centralized Heating Agent (CHA)** simulates district heating (DH) networks using **pandapipes**, a hydraulic-thermal simulation library. The CHA builds network topology from GIS data, sizes pipes according to EN 13941-1 standards, optimizes for numerical convergence, and extracts compliance KPIs.

### 3.3.1 Network Topology Construction

The CHA transforms street centerlines and building footprints into a dual-pipe (supply/return) district heating network topology.

#### 3.3.1.1 Street Graph Conversion (OSM → NetworkX)

**Input**: Street centerlines GeoDataFrame (LineString geometries)

**Process**:
1. **Extract Endpoints**: Each LineString's start and end coordinates become graph nodes
2. **Create Edges**: Each LineString becomes an edge between its endpoints
3. **Store Attributes**: Edge attributes include:
   - `length_m`: Geometric length of street segment
   - `street_id`: Street identifier
   - `geometry`: Original LineString for spatial queries

**Code Example**:
```python
# From src/branitz_heat_decision/cha/network_builder.py
def build_street_graph(streets: gpd.GeoDataFrame) -> nx.Graph:
    G = nx.Graph()
    for idx, row in streets.iterrows():
        geom = row.geometry
        start = tuple(geom.coords[0])  # (x, y)
        end = tuple(geom.coords[-1])
        G.add_edge(start, end, 
                  length_m=geom.length,
                  street_id=row.get('street_id', f'street_{idx}'),
                  geometry=LineString([start, end]))
    return G
```

**Endpoint Snapping**: Endpoints within 1.0 m are automatically snapped to improve graph connectivity (prevents disconnected components from floating-point coordinate differences).

#### 3.3.1.2 Building Snapping Strategies

Buildings must be attached to the street graph to define service connection points. Two strategies are implemented:

**Strategy 1: `nearest_node`**
- **Method**: Attach building to nearest existing graph node (street intersection)
- **Advantage**: Minimal graph modification
- **Disadvantage**: May create unrealistic service connections if buildings are far from intersections
- **Use Case**: Dense urban areas with many intersections

**Strategy 2: `split_edge_per_building` (Recommended)**
- **Method**: 
  1. Find nearest street edge to building centroid
  2. Project building centroid onto edge (perpendicular projection)
  3. Split edge at projection point, creating new node
  4. Attach building to new node
- **Advantage**: Realistic service connection points (buildings connect at nearest point on street)
- **Disadvantage**: Increases graph complexity (more nodes)
- **Use Case**: Standard case, recommended for most scenarios

**Code Example**:
```python
# From src/branitz_heat_decision/cha/network_builder.py
def attach_buildings_to_street(buildings, G, attach_mode='split_edge_per_building'):
    for building in buildings:
        building_point = building.geometry.centroid
        nearest_edge = find_nearest_edge(G, building_point)
        
        if attach_mode == 'split_edge_per_building':
            # Project onto edge
            nearest_point = line.interpolate(line.project(building_point))
            new_node = (round(nearest_point.x, 3), round(nearest_point.y, 3))
            
            # Split edge
            u, v = nearest_edge
            G.remove_edge(u, v)
            G.add_edge(u, new_node, ...)
            G.add_edge(new_node, v, ...)
            attach_node = new_node
        elif attach_mode == 'nearest_node':
            # Use closest endpoint
            attach_node = min([u, v], key=lambda n: Point(n).distance(building_point))
```

**Distance Threshold**: Buildings >500 m from nearest street edge trigger warnings (may indicate data quality issues).

#### 3.3.1.3 Trunk Routing

The trunk network connects the plant (source) to all building attachment points. Two routing modes are available:

**Mode 1: `paths_to_buildings` (Minimal Tree)**
- **Method**: 
  1. Compute shortest path from plant to each building attachment node (Dijkstra's algorithm, weighted by `length_m`)
  2. Union all paths to form trunk edges
  3. Result: Minimal spanning tree (acyclic, minimum total length)
- **Advantage**: 
  - Minimal pipe length (cost-optimal)
  - Deterministic (unique solution)
- **Disadvantage**: No redundancy (single path to each building)
- **Use Case**: Standard case, recommended for most scenarios

**Mode 2: `selected_streets` (Full Street Network)**
- **Method**: Use pre-selected street segments (e.g., all streets in cluster)
- **Advantage**: Potential for looped networks (redundancy)
- **Disadvantage**: Higher pipe length (cost)
- **Use Case**: Future enhancement (not fully implemented)

**Code Example**:
```python
# From src/branitz_heat_decision/cha/network_builder.py
def build_trunk_topology(G, plant_node, buildings, mode='paths_to_buildings'):
    if mode == 'paths_to_buildings':
        paths = {}
        for attach_node in attach_nodes:
            path = nx.shortest_path(G, plant_node, attach_node, weight='length_m')
            paths[attach_node] = path
        
        # Union all paths
        trunk_edges = []
        for path in paths.values():
            edges = list(zip(path[:-1], path[1:]))
            trunk_edges.extend(edges)
        trunk_edges = list(set(trunk_edges))  # Remove duplicates
```

**Trunk-Spur Architecture** (Advanced):
- **Trunk**: Street-following main pipes (supply/return pairs)
- **Spurs**: Exclusive per-building service connections (one spur per building, no sharing)
- **Tee-on-Main**: Spurs connect to trunk via tee junctions (splits trunk edge)
- **Implementation**: `network_builder_trunk_spur.py` (used with `--use-trunk-spur` flag)

#### 3.3.1.4 QGIS Export

The CHA exports network topology to **GeoPackage** format for manual validation in QGIS.

**Layers Exported**:
1. **`pipes_supply`**: Supply pipe centerlines (LineString)
   - Attributes: `pipe_id`, `diameter_mm`, `velocity_ms`, `pressure_drop_bar`, `length_m`
2. **`pipes_return`**: Return pipe centerlines (LineString)
   - Same attributes as supply
3. **`junctions`**: Network nodes (Point)
   - Attributes: `junction_id`, `pressure_bar`, `temperature_c`
4. **`buildings`**: Building footprints (Polygon)
   - Attributes: `building_id`, `heat_demand_kw`, `attach_node`
5. **`plant`**: CHP plant location (Point)
   - Attributes: `plant_id`, `coordinates`

**Code Example**:
```python
# From src/branitz_heat_decision/cha/qgis_export.py
def export_to_qgis(net, buildings, output_path):
    # Export pipes
    supply_pipes_gdf = create_pipe_gdf(net, role='supply')
    return_pipes_gdf = create_pipe_gdf(net, role='return')
    
    # Export to GeoPackage
    with fiona.open(output_path, 'w', driver='GPKG', ...) as f:
        f.write(supply_pipes_gdf)
        f.write(return_pipes_gdf)
        # ... other layers
```

**Usage**: Load GeoPackage in QGIS to visually validate:
- Network connectivity (no gaps)
- Pipe sizing (DN progression from plant to buildings)
- Building attachment points (realistic locations)

---

### 3.3.2 Pipe Sizing Algorithm

The CHA sizes pipes to meet EN 13941-1 velocity limits (≤1.5 m/s) and pressure drop constraints (≤0.3 bar/100m) while minimizing cost.

#### 3.3.2.1 Mass Flow Calculation

Mass flow rate `ṁ` (kg/s) is calculated from heat demand:

```
ṁ = Q / (c_p × ΔT)
```

Where:
- `Q`: Heat demand (kW)
- `c_p = 4.18 kJ/(kg·K)`: Specific heat capacity of water
- `ΔT = 30 K`: Temperature difference (supply 90°C - return 60°C)

**For Trunk Pipes**: Mass flow is the sum of all downstream building flows (tree accumulation from leaves to root).

**For Service Pipes**: Mass flow equals the individual building's design load.

**Code Example**:
```python
# From src/branitz_heat_decision/cha/sizing_catalog.py
cp_j_per_kgk = 4180.0  # J/(kg·K)
delta_t = 30.0  # K

# Per building
for building_id, load_kw in design_loads_kw.items():
    mdot_kg_s = (load_kw * 1000.0) / (cp_j_per_kgk * delta_t)

# Trunk: accumulate downstream loads
node_subtree_load_kw = {n: 0.0 for n in trunk_nodes}
for building_id, load in design_loads_kw.items():
    attach_node = building_to_node[building_id]
    node_subtree_load_kw[attach_node] += load

# Postorder traversal: sum children loads
for node in reversed(bfs_order):
    for child in children[node]:
        node_subtree_load_kw[node] += node_subtree_load_kw[child]
```

#### 3.3.2.2 Diameter Calculation

Required diameter `D_req` (m) is calculated from target velocity:

```
D_req = √(4ṁ / (π × ρ × v_target))
```

Where:
- `ṁ`: Mass flow rate (kg/s)
- `ρ = 970 kg/m³`: Water density at operating temperature (90°C)
- `v_target = 1.5 m/s`: Target velocity (EN 13941-1 limit)

**Code Example**:
```python
# From src/branitz_heat_decision/cha/sizing_catalog.py
def _velocity_ms(mdot_kg_s: float, d_m: float, rho: float) -> float:
    area = np.pi * (d_m ** 2) / 4.0
    return (mdot_kg_s / rho) / area

# Invert to get required diameter
def _diameter_for_velocity(mdot_kg_s: float, v_target_ms: float, rho: float) -> float:
    area_req = mdot_kg_s / (rho * v_target_ms)
    return np.sqrt(4.0 * area_req / np.pi)
```

#### 3.3.2.3 Catalog Lookup

The system selects the **smallest DN (nominal diameter) with `inner_diameter ≥ D_req`** from the pipe catalog.

**Catalog Format** (DataFrame):
| DN | inner_diameter_mm | inner_diameter_m | cost_eur_per_m | material |
|----|-------------------|------------------|----------------|----------|
| 20 | 21.3 | 0.0213 | 45 | steel |
| 25 | 26.9 | 0.0269 | 58 | steel |
| 32 | 33.7 | 0.0337 | 75 | steel |
| ... | ... | ... | ... | ... |

**Catalog Sources**:
1. **Technikkatalog Wärmeplanung** (Tab 45): Baden-Württemberg technical catalog (Excel)
2. **EN 10255 Default**: Standard steel pipe catalog (fallback)

**Code Example**:
```python
# From src/branitz_heat_decision/cha/sizing_catalog.py
d_req_m = _diameter_for_velocity(mdot, v_target=1.5, rho=970.0)

# Select smallest DN >= d_req
suitable = catalog[catalog['inner_diameter_m'] >= d_req_m]
if not suitable.empty:
    dn_choice = suitable.loc[suitable['inner_diameter_m'].idxmin(), 'DN']
else:
    # Use largest available
    dn_choice = catalog.loc[catalog['inner_diameter_m'].idxmax(), 'DN']
```

#### 3.3.2.4 Iteration: Velocity and Pressure Drop Validation

After catalog selection, the system validates that the chosen DN meets both velocity and pressure drop constraints:

**Velocity Check**:
```
v_actual = 4ṁ / (π × D² × ρ)
v_actual ≤ v_limit (1.5 m/s for trunk, 1.5 m/s for service)
```

**Pressure Drop Check** (Swamee-Jain friction factor):
```
Re = (ρ × v × D) / μ
f = 0.25 / (log₁₀(ε/(3.7D) + 5.74/Re^0.9))²  [turbulent]
Δp/L = f × (ρ × v²) / (2 × D)
Δp_per_100m = (Δp/L) × 100
Δp_per_100m ≤ 0.3 bar/100m
```

**Iteration Logic**:
1. Start with smallest DN ≥ `D_req`
2. Calculate `v_actual` and `Δp_per_100m`
3. If `v_actual > v_limit` OR `Δp_per_100m > 0.3 bar/100m`:
   - Select next larger DN from catalog
   - Recalculate
   - Repeat until constraints satisfied
4. If no DN satisfies constraints:
   - Use largest available DN
   - Flag as `v_abs_max_exceeded` or `dp_per_m_exceeded`

**Code Example**:
```python
# From src/branitz_heat_decision/cha/sizing_catalog.py
for dn in sorted(dn_steps):
    d_m = _diameter_m_for_dn(dn)
    v = _velocity_ms(mdot, d_m, rho)
    dp_pm = _dp_per_m_pa(mdot, d_m, rho, mu, eps)
    
    ok_v = (v <= v_limit_trunk_ms)
    ok_dp = (dp_pm <= dp_per_m_max_pa)
    
    if ok_v and ok_dp:
        chosen_dn = dn
        break
else:
    # No DN satisfied constraints
    chosen_dn = max(dn_steps)
    status = "v_abs_max_exceeded" if not ok_v else "dp_per_m_exceeded"
```

**Design Margin**: A 25% design margin is applied to design loads before sizing (ensures robustness under load variations):
```python
design_loads_kw_sized = {bid: load * 1.25 for bid, load in design_loads_kw.items()}
```

---

### 3.3.3 Convergence Optimization

Pandapipes uses a **Newton-Raphson solver** for hydraulic simulation, which requires the network to have at least one loop to avoid singular matrices. Tree networks (acyclic) cause convergence failures.

#### 3.3.3.1 Problem: Tree Networks and Singular Matrices

**Mathematical Issue**: 
- Newton-Raphson solves: `J × Δx = -F(x)`
- For tree networks, the Jacobian matrix `J` is singular (determinant = 0)
- Result: Solver fails with `SingularMatrixError` or non-convergence

**Network Topology**: 
- Minimal spanning trees (from `paths_to_buildings` mode) are acyclic
- No loops exist → singular matrix

#### 3.3.3.2 Solution: Minimal High-Resistance Loop

The **ConvergenceOptimizer** adds a minimal loop that satisfies the mathematical requirement without affecting flow distribution:

**Strategy**:
1. **Find Farthest Sinks**: Identify two sinks (buildings) farthest from plant
2. **Create Loop Junction**: Add two new junctions near the farthest sinks
3. **Connect with High-Resistance Pipe**: 
   - Length: 10 m
   - Diameter: DN50 (standard)
   - **Roughness: 100 mm** (very high → negligible flow)
4. **Connect Sinks**: Link sinks to loop junctions with 1 m pipes (also high resistance)

**Code Example**:
```python
# From src/branitz_heat_decision/cha/convergence_optimizer.py
def _add_minimal_loop(self):
    # Find two farthest sinks
    distances = nx.single_source_shortest_path_length(
        self.supply_graph, self.plant_junction
    )
    farthest_sinks = sorted(distances.items(), key=lambda x: x[1], reverse=True)[:2]
    
    sink1, sink2 = farthest_sinks[0][0], farthest_sinks[1][0]
    
    # Add loop pipe (10m, roughness=100mm)
    loop_pipe = pp.create_pipe(
        self.net,
        from_junction=loop_junction_1,
        to_junction=loop_junction_2,
        length_km=0.01,   # 10m
        diameter_m=0.05,  # DN50
        k_mm=100.0,       # Very high roughness → negligible flow
        name="minimal_loop"
    )
```

**Why This Works**:
- High roughness (100 mm vs. normal 0.1 mm) creates enormous resistance
- Flow through loop: `Q_loop ≈ 0` (negligible compared to main flow)
- Network topology: Now has a loop (satisfies Newton-Raphson requirement)
- Flow distribution: Unchanged (loop carries <0.1% of total flow)

#### 3.3.3.3 Roughness Variations

To further improve convergence, the optimizer applies small roughness variations (±0.01%) to parallel pipes:

**Problem**: Identical parallel pipes can cause numerical instabilities

**Solution**: 
```python
# From src/branitz_heat_decision/cha/convergence_optimizer.py
if parallel_variation_pct > 0:
    for pipe_idx, pipe in self.net.pipe.iterrows():
        base_roughness = pipe['k_mm']
        variation = base_roughness * (parallel_variation_pct / 100.0)
        new_roughness = base_roughness + np.random.uniform(-variation, variation)
        self.net.pipe.loc[pipe_idx, 'k_mm'] = new_roughness
```

**Effect**: Breaks numerical symmetry, improves solver stability

#### 3.3.3.4 Validation

After optimization, the network must pass pandapipes validation:

**Convergence Check**:
```python
pp.pipeflow(net, tol_p=1e-4)  # Pressure tolerance: 0.0001 bar
assert net.converged == True
```

**Validation Criteria**:
- ✅ `net.converged == True`
- ✅ `net.res_pipe` contains valid results (no NaN)
- ✅ `net.res_junction` contains valid pressures (all > 0 bar absolute)
- ✅ Mass balance: `Σ(mdot_in) = Σ(mdot_out)` (within tolerance)

**Optimization Log**: The optimizer tracks all fixes applied:
```python
optimization_summary = {
    'iterations': 2,
    'fixes_applied': 3,
    'fixes_by_type': {
        'minimal_loop': 1,
        'roughness_variation': 1,
        'pressure_adjustment': 1
    },
    'final_validation': {
        'converged': True,
        'mass_balance_ok': True
    }
}
```

---

### 3.3.4 KPI Extraction (EN 13941-1)

The CHA extracts **EN 13941-1 compliant KPIs** from converged networks. These KPIs form the **KPI contract** used by downstream agents (Economics, Decision).

#### 3.3.4.1 KPI Contract Structure

The KPI contract is a JSON structure with the following hierarchy:

```json
{
  "cluster_id": "ST010_HEINRICH_ZILLE_STRASSE",
  "design_hour": 6667,
  "aggregate": {
    "v_share_within_limits": 0.98,
    "v_max_ms": 1.45,
    "v_mean_ms": 0.85,
    "dp_max_bar_per_100m": 0.28,
    "loss_share_percent": 3.2,
    "length_total_m": 5420.5,
    "length_supply_m": 2710.25,
    "length_return_m": 2710.25
  },
  "hydraulics": {
    "velocity_ok": true,
    "dp_ok": true,
    "max_velocity_ms": 1.45,
    "velocity_share_within_limits": 0.98
  },
  "thermal": {
    "supply_temp_c": 90.0,
    "return_temp_c": 60.0,
    "temp_diff_k": 30.0,
    "max_temp_drop_c": 2.5
  },
  "losses": {
    "total_thermal_loss_kw": 85.2,
    "loss_share_percent": 3.2,
    "loss_per_100m_kw": 1.57
  },
  "en13941_compliance": {
    "velocity_ok": true,
    "dp_ok": true,
    "feasible": true,
    "reason_codes": ["DH_OK"]
  }
}
```

#### 3.3.4.2 Key KPIs

**Velocity Share Within Limits** (`v_share_within_limits`):
```
v_share_within_limits = (count of pipes with v ≤ 1.5 m/s) / (total pipe count)
```

**Requirement**: `v_share_within_limits ≥ 0.95` (95% of pipes must meet velocity limit)

**Maximum Pressure Drop per 100m** (`dp_per_100m_max`):
```
dp_per_100m_max = max(Δp_per_100m for all pipes)
```

**Requirement**: `dp_per_100m_max ≤ 0.3 bar/100m` (EN 13941-1 limit)

**Heat Loss Share** (`loss_share_pct`):
```
loss_share_pct = (total_thermal_loss_kw / total_heat_demand_kw) × 100
```

**Requirement**: `loss_share_pct ≤ 5%` (planning guideline, non-fatal warning if exceeded)

**Code Example**:
```python
# From src/branitz_heat_decision/cha/kpi_extractor.py
# Velocity share
v_share = float((pipe_kpis['velocity_ms'] <= 1.5).mean())

# Pressure drop max
dp_max = float(pipe_kpis['pressure_drop_per_100m_bar'].max())

# Heat loss share
total_loss_kw = sum(pipe_kpis['heat_loss_kw'])
total_demand_kw = sum(heat_consumers['qext_w']) / 1000.0
loss_share_pct = (total_loss_kw / total_demand_kw) * 100.0
```

#### 3.3.4.3 Feasibility Gate

The CHA determines network **feasibility** based on EN 13941-1 compliance:

**Feasibility Logic**:
```python
velocity_ok = (v_share_within_limits >= 0.95)
dp_ok = (dp_max_bar_per_100m <= 0.3)
feasible = velocity_ok AND dp_ok
```

**Reason Codes**:
- `DH_OK`: Network is feasible (both velocity and pressure drop compliant)
- `DH_VELOCITY_VIOLATION`: >5% of pipes exceed 1.5 m/s
- `DH_DP_VIOLATION`: Maximum pressure drop >0.3 bar/100m

**Code Example**:
```python
# From src/branitz_heat_decision/cha/kpi_extractor.py
def _check_en13941_compliance(self, aggregate, network):
    velocity_ok = aggregate['v_share_within_limits'] >= 0.95
    dp_ok = aggregate['dp_max_bar_per_100m'] <= 0.3
    
    feasible = velocity_ok and dp_ok
    
    reasons = []
    if feasible:
        reasons.append('DH_OK')
    else:
        if not velocity_ok:
            reasons.append('DH_VELOCITY_VIOLATION')
        if not dp_ok:
            reasons.append('DH_DP_VIOLATION')
    
    return {
        'velocity_ok': velocity_ok,
        'dp_ok': dp_ok,
        'feasible': feasible,
        'reason_codes': reasons
    }
```

**Output**: `results/cha/{cluster_id}/cha_kpis.json`

**Usage**: The Decision Agent uses `feasible` flag to determine if district heating is a viable option. If `feasible == False`, the decision may favor heat pumps (DHA) or mark the cluster as `UNDECIDED`.

---

## Summary

The CHA (Centralized Heating Agent) provides:

- **Network Topology**: Street-following trunk networks with building service connections
- **Pipe Sizing**: Catalog-based sizing with velocity and pressure drop constraints
- **Convergence Optimization**: Automatic loop addition for tree networks
- **EN 13941-1 Compliance**: Standardized KPI extraction with feasibility gates

All outputs are deterministic, validated, and ready for Economics Agent (cost calculation) and Decision Agent (feasibility assessment).

---

## 3.4 Decentralized Heating Agent (DHA)

The **Decentralized Heating Agent (DHA)** simulates low-voltage (LV) electrical grid hosting capacity for heat pump integration using **pandapower**. The DHA builds LV grid topology from geodata, maps buildings to electrical buses, assigns heat pump loads, runs powerflow simulations, and extracts VDE-AR-N 4100 compliance KPIs.

### 3.4.1 LV Grid Construction

The DHA constructs a pandapower network from geodata (lines and substations), implementing **Option 2 boundary** (MV bus + MV/LV transformers).

#### 3.4.1.1 From Geodata: Create Buses, Lines, ext_grid

**Input Data**:
- **Lines GeoDataFrame**: LV line centerlines (LineString geometries)
- **Substations GeoDataFrame**: LV substation/transformer locations (Point geometries)

**Process**:

1. **Create MV Bus and External Grid**:
   ```python
   # From src/branitz_heat_decision/dha/grid_builder.py
   mv_bus = pp.create_bus(net, vn_kv=20.0, name="MV_bus", type="b")
   pp.create_ext_grid(net, bus=mv_bus, vm_pu=1.02, name="MV_ext_grid")
   ```

2. **Create LV Buses from Line Endpoints**:
   - Extract start/end coordinates from each LineString
   - Deduplicate endpoints within `endpoint_snap_tol_m` (default: 1.0 m)
   - Create one LV bus per unique endpoint
   - Store coordinates in `net.bus_geodata`

3. **Create LV Lines**:
   ```python
   for line_geom in lines_gdf.geometry:
       coords = list(line_geom.coords)
       for (x1, y1), (x2, y2) in zip(coords[:-1], coords[1:]):
           b1 = get_or_create_lv_bus(x1, y1)
           b2 = get_or_create_lv_bus(x2, y2)
           length_km = Point(x1, y1).distance(Point(x2, y2)) / 1000.0
           
           pp.create_line_from_parameters(
               net,
               from_bus=b1,
               to_bus=b2,
               length_km=length_km,
               r_ohm_per_km=0.206,  # Default LV cable
               x_ohm_per_km=0.080,
               c_nf_per_km=210.0,
               max_i_ka=0.27,
               name=f"lv_line_{idx}"
           )
   ```

4. **Create Transformers** (MV/LV):
   - For each substation point, find/create nearest LV bus
   - Create transformer connecting MV bus to LV bus
   ```python
   pp.create_transformer_from_parameters(
       net,
       hv_bus=mv_bus,      # 20 kV
       lv_bus=lv_bus,      # 0.4 kV
       sn_mva=0.63,        # 630 kVA
       vn_hv_kv=20.0,
       vn_lv_kv=0.4,
       vk_percent=6.0,     # Short-circuit voltage
       vkr_percent=0.5,    # Copper losses
       name=f"trafo_{sidx}"
   )
   ```

**Code Example**:
```python
# From src/branitz_heat_decision/dha/grid_builder.py
def build_lv_grid_option2(lines_gdf, substations_gdf, cfg):
    net = pp.create_empty_network(name="DHA_LV_grid", f_hz=50)
    
    # MV boundary
    mv_bus = pp.create_bus(net, vn_kv=20.0, name="MV_bus")
    pp.create_ext_grid(net, bus=mv_bus, vm_pu=1.02)
    
    # LV buses (deduplicated endpoints)
    key_to_bus = {}
    for line in lines_gdf.geometry:
        for (x1, y1), (x2, y2) in zip(coords[:-1], coords[1:]):
            b1 = get_or_create_lv_bus(x1, y1)
            b2 = get_or_create_lv_bus(x2, y2)
            # Create line...
    
    # Transformers
    for substation in substations_gdf:
        lv_bus = get_or_create_lv_bus(substation.x, substation.y)
        pp.create_transformer_from_parameters(net, hv_bus=mv_bus, lv_bus=lv_bus, ...)
```

#### 3.4.1.2 CRS Validation

**Requirement**: All geodata must use a **projected CRS** (not geographic WGS84) for accurate distance calculations.

**Procedure**:
1. **Check CRS**: Validate that `lines_gdf.crs` and `substations_gdf.crs` are defined
2. **Geographic CRS Handling**: If WGS84 detected, raise `DataValidationError` (LV grids require meter-based distances)
3. **CRS Consistency**: Ensure lines and substations share the same CRS (auto-transform if mismatch)

**Code Example**:
```python
# From src/branitz_heat_decision/dha/grid_builder.py
if lines_gdf.crs is None:
    raise ValueError("lines_gdf must have a CRS (projected meters preferred)")
if substations_gdf.crs is None:
    raise ValueError("substations_gdf must have a CRS (projected meters preferred)")

if str(lines_gdf.crs) != str(substations_gdf.crs):
    substations_gdf = substations_gdf.to_crs(lines_gdf.crs)
```

**Validation Checks**:
- ✅ CRS must be defined (not `None`)
- ✅ CRS must be projected (not geographic)
- ✅ Lines and substations must share the same CRS

#### 3.4.1.3 Default Electrical Parameters

**LV Cable Parameters** (fallback when no DSO standard types available):

| Parameter | Value | Unit | Description |
|-----------|-------|------|-------------|
| `r_ohm_per_km` | 0.206 | Ω/km | Resistance per kilometer |
| `x_ohm_per_km` | 0.080 | Ω/km | Reactance per kilometer |
| `c_nf_per_km` | 210.0 | nF/km | Capacitance per kilometer |
| `max_i_ka` | 0.27 | kA | Maximum current (270 A) |

**Note**: These are generic LV cable parameters (typical for 4×150 mm² Cu cable). For real studies, use DSO standard types from `pandapower.std_types`.

**Code Example**:
```python
# From src/branitz_heat_decision/dha/config.py
@dataclass
class DHAConfig:
    line_r_ohm_per_km: float = 0.206
    line_x_ohm_per_km: float = 0.080
    line_c_nf_per_km: float = 210.0
    line_max_i_ka: float = 0.27
```

**Customization**: Users can override these defaults by:
- Loading DSO standard types: `pp.load_std_type(net, "cable", "NAYY 4x150 SE", element="line")`
- Setting custom parameters per line via `pp.create_line_from_parameters()`

---

### 3.4.2 Building-to-Bus Mapping

Buildings must be mapped to LV buses to assign heat pump loads. The DHA uses **nearest-neighbor search** with a maximum distance threshold.

#### 3.4.2.1 Nearest-Neighbor Search Algorithm

**Input**:
- Buildings GeoDataFrame (with `building_id` and geometry)
- Pandapower network (with `net.bus_geodata` containing LV bus coordinates)

**Algorithm**:
1. **Extract Building Centroids**: Use `building.geometry.centroid` for mapping
2. **Filter LV Buses**: Select buses with `vn_kv ≤ 0.4 kV`
3. **CRS Transformation**: Convert both to projected CRS (EPSG:25833) for meter-based distances
4. **Brute-Force Nearest Neighbor** (chunked for performance):
   ```python
   # From src/branitz_heat_decision/dha/mapping.py
   for i0 in range(0, len(buildings), chunk_size=256):
       i1 = min(i0 + chunk_size, len(buildings))
       # Vectorized distance calculation
       dx = building_x[i0:i1, None] - bus_x[None, :]
       dy = building_y[i0:i1, None] - bus_y[None, :]
       d2 = dx * dx + dy * dy
       j = np.argmin(d2, axis=1)  # Nearest bus index
       dist = np.sqrt(d2[np.arange(i1-i0), j])
   ```
5. **Distance Threshold**: Mark as `mapped=True` if `distance_m ≤ max_distance_m` (default: 1000 m)

**Code Example**:
```python
# From src/branitz_heat_decision/dha/mapping.py
def map_buildings_to_lv_buses(
    buildings_gdf: gpd.GeoDataFrame,
    net,
    max_dist_m: float = 1000.0
) -> pd.DataFrame:
    # Filter LV buses
    lv_bus_idx = net.bus.index[net.bus["vn_kv"] <= 0.4].tolist()
    bus_geo = net.bus_geodata.loc[lv_bus_idx][["x", "y"]]
    
    # Convert to projected CRS
    buildings_proj = buildings_gdf.to_crs("EPSG:25833")
    bus_gdf = gpd.GeoDataFrame(
        bus_geo,
        geometry=gpd.points_from_xy(bus_geo["x"], bus_geo["y"]),
        crs="EPSG:25833"
    )
    
    # Nearest neighbor search (chunked)
    out_rows = []
    for i in range(0, len(buildings_proj), chunk=256):
        # Vectorized distance calculation
        distances = compute_distances(buildings_proj[i:i+256], bus_gdf)
        nearest_bus_idx = np.argmin(distances, axis=1)
        for k, j in enumerate(nearest_bus_idx):
            dist = distances[k, j]
            out_rows.append({
                "building_id": buildings_proj.iloc[i+k]["building_id"],
                "bus_id": int(bus_gdf.iloc[j]["bus_id"]),
                "distance_m": float(dist),
                "mapped": dist <= max_dist_m
            })
    
    return pd.DataFrame(out_rows)
```

#### 3.4.2.2 Validation

**All Buildings Mapped**:
```python
mapped_count = building_bus_map["mapped"].sum()
total_buildings = len(building_bus_map)
if mapped_count < total_buildings:
    logger.warning(
        f"Only {mapped_count}/{total_buildings} buildings mapped "
        f"(unmapped: {total_buildings - mapped_count})"
    )
```

**No Duplicate Assignments**:
- Each building maps to exactly one bus (nearest neighbor is unique)
- Multiple buildings can map to the same bus (aggregation handled in load assignment)

**Validation Checks**:
- ✅ All buildings have a mapping result (even if `mapped=False`)
- ✅ No building maps to multiple buses
- ✅ Unmapped buildings (`distance_m > max_distance_m`) have `bus_id = NaN`

**Output**: DataFrame with columns:
- `building_id`: Building identifier
- `bus_id`: LV bus index (NaN if unmapped)
- `distance_m`: Distance from building centroid to bus (m)
- `mapped`: Boolean flag (`True` if `distance_m ≤ max_distance_m`)

---

### 3.4.3 Load Assignment & Loadflow

The DHA converts heat demand to heat pump electrical load, aggregates loads per bus, and runs powerflow simulations.

#### 3.4.3.1 COP Mapping

**Heat Pump Electrical Power**:
```
P_el = Q_th / COP
```

Where:
- `P_el`: Electrical power consumption (kW)
- `Q_th`: Thermal heat demand (kW)
- `COP`: Coefficient of Performance (dimensionless)

**COP Options**:

1. **Constant COP** (default):
   ```python
   design_cop = 3.0  # Typical air-source HP
   P_el_kw = Q_th_kw / design_cop
   ```

2. **Variable COP by Temperature** (future enhancement):
   ```python
   # COP decreases with outdoor temperature
   cop = f(T_outdoor)  # e.g., COP = 3.5 at 10°C, 2.5 at -10°C
   P_el_kw = Q_th_kw / cop(T_outdoor)
   ```

**Code Example**:
```python
# From src/branitz_heat_decision/dha/loadflow.py
def assign_hp_loads(
    hourly_heat_profiles_df: pd.DataFrame,
    building_bus_map: pd.DataFrame,
    cop: float = 3.0
):
    for hour in hours:
        for building_id in building_bus_map["building_id"]:
            Q_th_kw = hourly_heat_profiles_df.loc[hour, building_id]
            P_el_kw = Q_th_kw / cop
            # Assign to bus...
```

#### 3.4.3.2 Load Aggregation per Bus

For each bus, aggregate loads from all buildings mapped to that bus:

```
P_total_bus = Σ(P_el_building for all buildings on bus)
```

**Code Example**:
```python
# From src/branitz_heat_decision/dha/loadflow.py
df = building_bus_map[["building_id", "bus_id"]].copy()
df["p_hp_kw"] = df["building_id"].map(q_th_kw) / cop

# Aggregate per bus
agg = df.groupby("bus_id", as_index=False)["p_hp_kw"].sum()
# Result: DataFrame with [bus_id, p_hp_kw, p_total_kw, ...]
```

**Base Loads** (optional):
- **BDEW Profiles**: Standard residential electrical load profiles (without HP)
- **Aggregation**: `P_total = P_base + P_hp` (base load + HP load)

#### 3.4.3.3 Solve: Newton-Raphson Powerflow

The DHA runs pandapower loadflow for each hour (design hour + Top-N hours).

**Solver Options**:

1. **Single-Phase (Balanced)** (default):
   ```python
   # From src/branitz_heat_decision/dha/loadflow.py
   pp.create_load(net, bus=bus_id, p_mw=P_total_mw, q_mvar=Q_total_mvar)
   pp.runpp(net, algorithm="nr", init="auto", calculate_voltage_angles=False)
   ```
   - **Algorithm**: Newton-Raphson (`algorithm="nr"`)
   - **Assumption**: Balanced three-phase (all phases identical)
   - **Performance**: Fast (<1 second per hour for <500 buses)

2. **Three-Phase (Unbalanced)** (if available):
   ```python
   if hasattr(pp, "runpp_3ph"):
       pp.create_asymmetric_load(
           net, bus=bus_id,
           p_a_mw=P_a, p_b_mw=P_b, p_c_mw=P_c,
           q_a_mvar=Q_a, q_b_mvar=Q_b, q_c_mvar=Q_c
       )
       pp.runpp_3ph(net, init="auto")
   ```
   - **Algorithm**: Three-phase Newton-Raphson
   - **Assumption**: Unbalanced loads (phase-specific)
   - **Performance**: Slower (~5-10 seconds per hour for 500-1000 buses)

**Code Example**:
```python
# From src/branitz_heat_decision/dha/loadflow.py
def run_loadflow(net, loads_by_hour, hp_three_phase=True):
    results_by_hour = {}
    
    for hour, load_df in loads_by_hour.items():
        # Update loads
        for _, row in load_df.iterrows():
            bus_id = int(row["bus_id"])
            p_mw = row["p_total_kw"] / 1000.0
            q_mvar = row["q_total_kvar"] / 1000.0
            
            load_idx = bus_to_load_idx[bus_id]
            net.load.loc[load_idx, "p_mw"] = p_mw
            net.load.loc[load_idx, "q_mvar"] = q_mvar
        
        # Run powerflow
        try:
            pp.runpp(net, algorithm="nr", init="auto")
            converged = net.converged
        except Exception as e:
            converged = False
            error = str(e)
        
        # Extract results
        results_by_hour[hour] = {
            "converged": converged,
            "bus_results": net.res_bus.copy(),
            "line_results": net.res_line.copy(),
            "trafo_results": net.res_trafo.copy() if hasattr(net, "res_trafo") else None
        }
    
    return results_by_hour
```

**Convergence Validation**:
- ✅ `net.converged == True` (solver converged)
- ✅ `net.res_bus` contains valid voltages (no NaN)
- ✅ All bus voltages within reasonable range (0.5-1.2 pu)

**Per-Hour Results Saved**: All loadflow results are saved for debugging:
- `results/dha/{cluster_id}/loadflow_results_hour_{hour}.json` (optional, if debug mode enabled)

---

### 3.4.4 KPI Extraction (VDE-AR-N 4100)

The DHA extracts **VDE-AR-N 4100 compliant KPIs** from loadflow results. VDE-AR-N 4100 is the German standard for LV grid connection of distributed generation.

#### 3.4.4.1 Voltage Violations

**VDE-AR-N 4100 Limits**:
- **Minimum Voltage**: `v_min_pu = 0.90` (90% of nominal = 360 V for 400 V system)
- **Maximum Voltage**: `v_max_pu = 1.10` (110% of nominal = 440 V for 400 V system)

**Violation Detection**:
```python
# From src/branitz_heat_decision/dha/kpi_extractor.py
for hour, res in results_by_hour.items():
    bus_df = res["bus_results"]
    for bus_idx, row in bus_df.iterrows():
        v_pu = float(row["vm_pu"])
        if v_pu < 0.90 or v_pu > 1.10:
            violations.append({
                "hour": hour,
                "type": "voltage",
                "element": f"bus_{bus_idx}",
                "value": f"{v_pu:.4f} pu",
                "limit": "[0.90, 1.10] pu",
                "severity": "critical" if v_pu < 0.90 else "warning"
            })
```

**KPI Metrics**:
- `voltage_violations_total`: Total number of voltage violation events (across all hours/buses)
- `voltage_violated_hours`: Number of unique hours with voltage violations
- `worst_vmin_pu`: Minimum voltage across all hours/buses
- `worst_vmin_bus`: Bus ID with worst voltage
- `worst_vmin_hour`: Hour when worst voltage occurred

#### 3.4.4.2 Line Overloads

**VDE-AR-N 4100 Limits**:
- **Operational Limit**: `line_loading_limit_pct = 100.0%` (line current ≤ rated current)
- **Planning Warning**: `planning_warning_pct = 80.0%` (planning alert if >80%)

**Violation Detection**:
```python
# From src/branitz_heat_decision/dha/kpi_extractor.py
for hour, res in results_by_hour.items():
    line_df = res["line_results"]
    for line_idx, row in line_df.iterrows():
        loading_pct = float(row["loading_percent"])
        if loading_pct > 100.0:
            violations.append({
                "hour": hour,
                "type": "line_overload",
                "element": f"line_{line_idx}",
                "value": f"{loading_pct:.1f}%",
                "limit": "100.0%",
                "severity": "critical" if loading_pct > 120.0 else "warning"
            })
        elif loading_pct > 80.0:
            violations.append({
                "hour": hour,
                "type": "line_planning_warning",
                "element": f"line_{line_idx}",
                "value": f"{loading_pct:.1f}%",
                "limit": "80.0%",
                "severity": "warning"
            })
```

**KPI Metrics**:
- `line_violations_total`: Total number of line overload events
- `line_overload_hours`: Number of unique hours with line overloads
- `max_feeder_loading_pct`: Maximum line loading across all hours/lines
- `max_loading_line`: Line ID with maximum loading
- `max_feeder_loading_hour`: Hour when maximum loading occurred

#### 3.4.4.3 Transformer Overloads

**Transformer Loading**:
- **Operational Limit**: `trafo_loading_limit_pct = 100.0%` (transformer apparent power ≤ rated power)
- **Severe Threshold**: `loading_severe_threshold = 120.0%` (critical if >120%)

**KPI Metrics**:
- `trafo_violations_total`: Total number of transformer overload events
- `trafo_overload_hours`: Number of unique hours with transformer overloads
- `max_trafo_loading_pct`: Maximum transformer loading
- `max_loading_trafo`: Transformer ID with maximum loading

#### 3.4.4.4 Feasibility Gate

**Feasibility Logic**:
```python
# From src/branitz_heat_decision/dha/kpi_extractor.py
critical_violations = violations_df[
    violations_df["type"].isin([
        "voltage", "line_overload", "trafo_overload", "non_convergence"
    ])
]

feasible = (len(critical_violations) == 0)
```

**Feasibility Criteria**:
- ✅ `voltage_violations == 0` (no voltage violations)
- ✅ `line_overloads == 0` (no line overloads)
- ✅ `trafo_overloads == 0` (no transformer overloads)
- ✅ `non_convergence == 0` (all hours converged)

**Planning Warning**:
```python
planning_warning = (max_feeder_loading_pct > 80.0)
```

**KPI Contract Structure**:
```json
{
  "feasible": true,
  "hours_total": 11,
  "hours_converged": 11,
  "voltage_violations_total": 0,
  "line_violations_total": 0,
  "trafo_violations_total": 0,
  "critical_hours_count": 0,
  "worst_vmin_pu": 0.92,
  "worst_vmin_bus": "42",
  "worst_vmin_hour": 6667,
  "max_feeder_loading_pct": 75.3,
  "max_loading_line": "15",
  "max_feeder_loading_hour": 6667,
  "max_trafo_loading_pct": 68.2,
  "feeder_metrics": {
    "distance_km": 0.45,
    "long_feeder": false,
    "threshold_km": 0.8
  }
}
```

#### 3.4.4.5 Per-Hour Results for Debugging

The DHA saves detailed per-hour results for debugging:

**Output Files**:
- `results/dha/{cluster_id}/dha_kpis.json`: Aggregated KPIs
- `results/dha/{cluster_id}/violations.csv`: Detailed violations table (hour, type, element, value, limit, severity)
- `results/dha/{cluster_id}/buses_results.geojson`: Bus voltage results (GeoJSON)
- `results/dha/{cluster_id}/lines_results.geojson`: Line loading results (GeoJSON)

**Violations CSV Format**:
```csv
hour,type,element,name,value,limit,severity
6667,voltage,bus_42,,0.8850 pu,[0.90, 1.10] pu,critical
6667,line_overload,line_15,,105.3%,100.0%,critical
```

**Code Example**:
```python
# From src/branitz_heat_decision/dha/kpi_extractor.py
violations_df = pd.DataFrame(violations)
violations_df.to_csv("violations.csv", index=False)

# Export bus/line results as GeoJSON
export_bus_results_geojson(net, results_by_hour, "buses_results.geojson")
export_line_results_geojson(net, results_by_hour, "lines_results.geojson")
```

---

## Summary

The DHA (Decentralized Heating Agent) provides:

- **LV Grid Construction**: Option 2 boundary (MV bus + MV/LV transformers) from geodata
- **Building-to-Bus Mapping**: Nearest-neighbor search with 1000 m threshold
- **Load Assignment**: COP-based conversion (`P_el = Q_th / COP`) and bus aggregation
- **Powerflow Simulation**: Newton-Raphson solver (single-phase or three-phase)
- **VDE-AR-N 4100 Compliance**: Voltage, line loading, and transformer loading KPIs with feasibility gates

All outputs are deterministic, validated, and ready for Economics Agent (LV upgrade cost calculation) and Decision Agent (feasibility assessment).

---

## 3.5 Techno-Economic Analysis

The **Techno-Economic Analysis** module computes **Levelized Cost of Heat (LCOH)** and **CO₂ emissions** for both District Heating (DH) and Heat Pump (HP) systems, and propagates uncertainty via **Monte Carlo simulation** to assess decision robustness.

### 3.5.1 LCOH Calculation

The LCOH (Levelized Cost of Heat) represents the average cost per unit of heat delivered over the system lifetime, accounting for both capital and operational expenditures. The system uses the **Capital Recovery Factor (CRF) method**, which annualizes CAPEX and combines it with annual OPEX.

#### 3.5.1.1 CRF Method

**Capital Recovery Factor (CRF)**:
```
CRF = (r × (1 + r)^n) / ((1 + r)^n - 1)
```

Where:
- `r` = discount rate (default: 0.04 = 4%)
- `n` = lifetime in years (default: 20 years)

**Special Case**: If `r = 0`, `CRF = 1/n`

**LCOH Formula**:
```
LCOH = (CAPEX × CRF + OPEX_annual) / Annual_Heat
```

Where:
- `CAPEX`: Total capital expenditure (EUR)
- `CRF`: Capital Recovery Factor (annualization factor)
- `OPEX_annual`: Annual operational expenditure (EUR/year)
- `Annual_Heat`: Annual heat demand (MWh/year)

**Code Example**:
```python
# From src/branitz_heat_decision/economics/utils.py
def crf(discount_rate: float, lifetime_years: int) -> float:
    r = float(discount_rate)
    n = int(lifetime_years)
    if abs(r) < 1e-12:
        return 1.0 / float(n)
    a = (1.0 + r) ** n
    return float(r * a / (a - 1.0))

# From src/branitz_heat_decision/economics/lcoh.py
crf_val = crf(discount_rate=0.04, lifetime_years=20)
lcoh = (total_capex * crf_val + total_opex_annual) / annual_heat_mwh
```

**Cash Flow Diagram (NPV Concept)**:

The CRF method is equivalent to computing the Net Present Value (NPV) of all cash flows and annualizing:

```
NPV = -CAPEX + Σ(OPEX_t / (1+r)^t) for t=1..n

Annualized Cost = NPV × CRF
LCOH = Annualized Cost / Annual_Heat
```

**Visual Representation**:
```
Year 0:  -CAPEX (one-time investment)
Year 1:  -OPEX_annual
Year 2:  -OPEX_annual
...
Year n:  -OPEX_annual

NPV = -CAPEX - OPEX_annual × PV_factor
     where PV_factor = (1 - (1+r)^(-n)) / r

Annualized = NPV × CRF
```

#### 3.5.1.2 DH CAPEX

**District Heating Capital Expenditure** consists of three components:

1. **Pipes (by DN)**:
   ```python
   # From src/branitz_heat_decision/economics/lcoh.py
   capex_pipes = 0.0
   for dn, length_m in pipe_lengths_by_dn.items():
       cost_per_m = params.pipe_cost_eur_per_m.get(dn, default_cost)
       capex_pipes += length_m * cost_per_m
   ```

   **Pipe Costs by DN** (default):
   | DN | Cost (EUR/m) |
   |----|--------------|
   | DN20 | 50 |
   | DN25 | 60 |
   | DN32 | 75 |
   | DN40 | 90 |
   | DN50 | 110 |
   | DN65 | 140 |
   | DN80 | 170 |
   | DN100 | 220 |
   | DN125 | 280 |
   | DN150 | 350 |
   | DN200 | 500 |

   **Fallback**: If pipe lengths by DN are not available, uses average cost × total length:
   ```python
   avg_cost = np.mean(list(params.pipe_cost_eur_per_m.values()))
   capex_pipes = total_pipe_length_m * avg_cost
   ```

2. **Plant**:
   ```python
   capex_plant = plant_cost_override OR plant_cost_base_eur
   # Default: plant_cost_base_eur = 1,500,000 EUR
   ```

3. **Pump**:
   ```python
   capex_pump = pump_power_kw × pump_cost_per_kw
   # Default: pump_cost_per_kw = 500 EUR/kW
   ```

**Total DH CAPEX**:
```python
total_capex = capex_pipes + capex_pump + capex_plant
```

#### 3.5.1.3 HP CAPEX

**Heat Pump Capital Expenditure** consists of:

1. **Equipment**:
   ```python
   # From src/branitz_heat_decision/economics/lcoh.py
   capex_hp = hp_total_capacity_kw_th × hp_cost_eur_per_kw_th
   # Default: hp_cost_eur_per_kw_th = 900 EUR/kW_th
   ```

2. **LV Upgrade** (conditional, if loading > 80%):
   ```python
   loading_threshold = params.feeder_loading_planning_limit * 100.0  # 80%
   if max_feeder_loading_pct > loading_threshold:
       overload_factor = (max_feeder_loading_pct - loading_threshold) / 100.0
       hp_el_capacity_kw = hp_total_capacity_kw_th / cop_annual_average
       upgrade_kw_el = overload_factor * hp_el_capacity_kw * 1.5  # 1.5x safety margin
       capex_lv_upgrade = upgrade_kw_el × lv_upgrade_cost_eur_per_kw_el
       # Default: lv_upgrade_cost_eur_per_kw_el = 200 EUR/kW_el
   else:
       capex_lv_upgrade = 0.0
   ```

**Total HP CAPEX**:
```python
total_capex = capex_hp + capex_lv_upgrade
```

#### 3.5.1.4 OPEX

**Operational Expenditure** consists of:

1. **Fixed OPEX (O&M)**:
   ```python
   opex_om = capex_total × om_frac_per_year
   # Default: dh_om_frac_per_year = 0.02 (2% of CAPEX per year)
   # Default: hp_om_frac_per_year = 0.02 (2% of CAPEX per year)
   ```

2. **Variable OPEX (Energy Costs)**:

   **For DH** (depends on generation type):
   ```python
   if generation_type == "gas":
       efficiency = 0.90
       opex_energy = (annual_heat_mwh / efficiency) × gas_price_eur_per_mwh
   elif generation_type == "biomass":
       efficiency = 0.85
       opex_energy = (annual_heat_mwh / efficiency) × biomass_price_eur_per_mwh
   elif generation_type == "electric":
       cop = 3.0
       opex_energy = (annual_heat_mwh / cop) × electricity_price_eur_per_mwh
   ```

   **For HP**:
   ```python
   annual_el_mwh = annual_heat_mwh / cop_annual_average
   opex_energy = annual_el_mwh × electricity_price_eur_per_mwh
   ```

**Total Annual OPEX**:
```python
total_opex_annual = opex_om + opex_energy
```

**Code Example**:
```python
# From src/branitz_heat_decision/economics/lcoh.py
# DH OPEX
opex_om = total_capex * params.dh_om_frac_per_year
opex_energy = (annual_heat_mwh / efficiency) * params.gas_price_eur_per_mwh
total_opex_annual = opex_om + opex_energy

# HP OPEX
opex_om = capex_hp * params.hp_om_frac_per_year
annual_el_mwh = annual_heat_mwh / cop_annual_average
opex_energy = annual_el_mwh * params.electricity_price_eur_per_mwh
total_opex_annual = opex_om + opex_energy
```

---

### 3.5.2 CO₂ Emissions

The system calculates **specific CO₂ emissions** (kg CO₂ per MWh of heat delivered) and **annual CO₂ emissions** (t/a) for both DH and HP systems.

#### 3.5.2.1 DH CO₂ Emissions

**Formula**:
```
CO₂ = (Annual_Heat / η_boiler) × EF_gas
```

Where:
- `Annual_Heat`: Annual heat demand (MWh/year)
- `η_boiler`: Boiler efficiency (0.90 for gas, 0.85 for biomass)
- `EF_gas`: Emission factor for fuel (kg CO₂/MWh)

**Specific CO₂** (per MWh of heat):
```
CO₂_per_MWh = EF_fuel / η_boiler
```

**Code Example**:
```python
# From src/branitz_heat_decision/economics/co2.py
if generation_type == "gas":
    efficiency = 0.90
    emission_factor = params.ef_gas_kg_per_mwh  # Default: 200 kg/MWh
    co2_per_mwh = emission_factor / efficiency
    annual_co2 = (annual_heat_mwh / efficiency) * emission_factor
elif generation_type == "biomass":
    efficiency = 0.85
    emission_factor = params.ef_biomass_kg_per_mwh  # Default: 25 kg/MWh
    co2_per_mwh = emission_factor / efficiency
    annual_co2 = (annual_heat_mwh / efficiency) * emission_factor
elif generation_type == "electric":
    cop_central = 3.0
    emission_factor = params.ef_electricity_kg_per_mwh  # Default: 350 kg/MWh
    co2_per_mwh = emission_factor / cop_central
    annual_co2 = annual_heat_mwh * co2_per_mwh
```

#### 3.5.2.2 HP CO₂ Emissions

**Formula**:
```
CO₂ = (Annual_Heat / COP) × EF_electricity
```

Where:
- `Annual_Heat`: Annual heat demand (MWh/year)
- `COP`: Coefficient of Performance (dimensionless)
- `EF_electricity`: Emission factor for electricity (kg CO₂/MWh_el)

**Specific CO₂** (per MWh of heat):
```
CO₂_per_MWh = EF_electricity / COP
```

**Code Example**:
```python
# From src/branitz_heat_decision/economics/co2.py
annual_el_mwh = annual_heat_mwh / cop_annual_average
annual_co2 = annual_el_mwh * params.ef_electricity_kg_per_mwh
co2_per_mwh = annual_co2 / annual_heat_mwh
```

#### 3.5.2.3 Emission Factors from UBA 2025

**Default Emission Factors** (can be updated from UBA 2025 data):

| Fuel/Energy Source | Emission Factor (kg CO₂/MWh) | Source |
|-------------------|------------------------------|--------|
| Electricity (German grid mix) | 350.0 | Reference (updateable from UBA 2025) |
| Natural Gas | 200.0 | Reference (updateable from UBA 2025) |
| Biomass | 25.0 | Reference (updateable from UBA 2025) |

**Note**: Emission factors should be updated from **UBA (Umweltbundesamt) 2025** data for current German grid mix and fuel-specific factors. The system allows parameter customization via YAML configuration.

**Code Example**:
```python
# From src/branitz_heat_decision/economics/params.py
@dataclass(frozen=True)
class EconomicParameters:
    ef_electricity_kg_per_mwh: float = 350.0  # German grid mix (reference)
    ef_gas_kg_per_mwh: float = 200.0
    ef_biomass_kg_per_mwh: float = 25.0
```

---

### 3.5.3 Monte Carlo Uncertainty

The system propagates uncertainty in key parameters via **Monte Carlo simulation** to assess decision robustness. Each sample recomputes LCOH and CO₂ emissions, and the results are aggregated into win fractions and quantiles.

#### 3.5.3.1 Distributions

**Supported Probability Distributions**:

1. **Normal Distribution**:
   ```python
   # For: discount_rate, COP, electricity_price
   {"dist": "normal", "mean": 0.04, "std": 0.01, "clip": [0.01, 0.08]}
   ```
   - **Use Cases**: Discount rate, COP (when well-characterized), electricity price
   - **Parameters**: `mean`, `std`, optional `clip` (min, max)

2. **Triangular Distribution**:
   ```python
   # For: prices (gas, biomass), pipe_cost_multiplier
   {"dist": "triangular", "low": 40, "mode": 80, "high": 140}
   ```
   - **Use Cases**: Prices (when min/mode/max are known), cost multipliers
   - **Parameters**: `low`, `mode`, `high`

3. **Log-Normal Distribution**:
   ```python
   # For: demand (annual_heat_mwh)
   {"dist": "lognormal", "mean": 1000.0, "std": 200.0, "clip": [500, 2000]}
   ```
   - **Use Cases**: Demand (positive, right-skewed), capacity factors
   - **Parameters**: `mean`, `std` (of X, not log(X)), optional `clip`

4. **Uniform Distribution**:
   ```python
   # For: bounded ranges (MVP)
   {"dist": "uniform", "low": 0.8, "high": 1.2}
   ```
   - **Use Cases**: Simple bounded uncertainty (MVP approach)
   - **Parameters**: `low`, `high`

**Default Randomness Configuration**:
```python
# From src/branitz_heat_decision/economics/monte_carlo.py
randomness_config = {
    "discount_rate": {
        "dist": "normal",
        "mean": 0.04,
        "std": 0.01,
        "clip": [0.01, 0.08]
    },
    "electricity_price": {
        "dist": "normal",
        "mean": 250.0,
        "std": 50.0,
        "clip": [150, 400]
    },
    "gas_price": {
        "dist": "triangular",
        "low": 40,
        "mode": 80,
        "high": 140
    },
    "pipe_cost_multiplier": {
        "dist": "triangular",
        "low": 0.8,
        "mode": 1.0,
        "high": 1.2
    },
    "cop": {
        "dist": "normal",
        "mean": 2.8,
        "std": 0.3,
        "clip": [2.0, 4.0]
    },
    "ef_electricity": {
        "dist": "normal",
        "mean": 350.0,
        "std": 80.0,
        "clip": [200, 500]
    }
}
```

#### 3.5.3.2 N=500 Samples

**Monte Carlo Process**:

1. **Sample Parameters**: For each sample `i` (1..N):
   ```python
   # From src/branitz_heat_decision/economics/monte_carlo.py
   rng = np.random.default_rng(seed=42)
   for sample_id in range(1, n_samples + 1):
       # Sample each parameter from its distribution
       discount_rate = sample_param(
           {"dist": "normal", "mean": 0.04, "std": 0.01, "clip": [0.01, 0.08]},
           rng
       )
       cop = sample_param(
           {"dist": "normal", "mean": 2.8, "std": 0.3, "clip": [2.0, 4.0]},
           rng
       )
       # ... sample other parameters
   ```

2. **Recompute LCOH/CO₂ per Sample**:
   ```python
   # Create modified parameters
   sample_params = apply_multipliers(
       base_params,
       discount_rate=discount_rate,
       cop=hp_cop,
       # ... other sampled values
   )
   
   # Recompute LCOH
   lcoh_dh = lcoh_dh_crf(dh_inputs, sample_params)
   lcoh_hp = lcoh_hp_crf(hp_inputs, sample_params)
   
   # Recompute CO₂
   co2_dh_kg_per_mwh, co2_dh_br = compute_co2_dh(annual_heat_mwh, params=sample_params)
   co2_hp_kg_per_mwh, co2_hp_br = compute_co2_hp(annual_heat_mwh, cop=sample_params.cop_default, params=sample_params)
   ```

3. **Store Sample Results**:
   ```python
   samples.append({
       "sample_id": sample_id,
       "lcoh_dh_eur_per_mwh": lcoh_dh,
       "lcoh_hp_eur_per_mwh": lcoh_hp,
       "co2_dh_t_per_a": co2_dh_br["annual_co2_kg"] / 1000.0,
       "co2_hp_t_per_a": co2_hp_br["annual_co2_kg"] / 1000.0,
       "param_discount_rate": discount_rate,
       "param_cop": cop,
       # ... other sampled parameters
   })
   ```

**Default**: `N = 500` samples (configurable via `MonteCarloParams.n`)

#### 3.5.3.3 Outputs: Win Fractions and Quantiles

**Win Fractions**:

1. **Probability DH Cheaper**:
   ```python
   prob_dh_cheaper = sum(1 for s in samples if s["lcoh_dh"] < s["lcoh_hp"]) / len(samples)
   ```

2. **Probability DH Lower CO₂**:
   ```python
   prob_dh_lower_co2 = sum(1 for s in samples if s["co2_dh"] < s["co2_hp"]) / len(samples)
   ```

**Quantiles** (P05, P50, P95):

For each metric (LCOH_DH, LCOH_HP, CO₂_DH, CO₂_HP):
```python
# From src/branitz_heat_decision/economics/utils.py
def percentile(values: list[float], q: float) -> float:
    xs = sorted(values)
    i = q * (len(xs) - 1)
    lo = int(math.floor(i))
    hi = int(math.ceil(i))
    if lo == hi:
        return xs[lo]
    w = i - lo
    return xs[lo] * (1.0 - w) + xs[hi] * w

# Extract quantiles
lcoh_dh_vals = [s["lcoh_dh_eur_per_mwh"] for s in samples]
lcoh_dh_p10 = percentile(lcoh_dh_vals, 0.10)  # P10
lcoh_dh_p50 = percentile(lcoh_dh_vals, 0.50)  # Median (P50)
lcoh_dh_p90 = percentile(lcoh_dh_vals, 0.90)  # P90
```

**Summary Output**:
```python
summary = {
    "n": len(samples),
    "prob_dh_cheaper": prob_dh_cheaper,
    "prob_dh_lower_co2": prob_dh_lower_co2,
    "lcoh_dh_p10": percentile(lcoh_dh_vals, 0.10),
    "lcoh_dh_p50": percentile(lcoh_dh_vals, 0.50),
    "lcoh_dh_p90": percentile(lcoh_dh_vals, 0.90),
    "lcoh_hp_p10": percentile(lcoh_hp_vals, 0.10),
    "lcoh_hp_p50": percentile(lcoh_hp_vals, 0.50),
    "lcoh_hp_p90": percentile(lcoh_hp_vals, 0.90),
    "co2_dh_p10": percentile(co2_dh_vals, 0.10),
    "co2_dh_p50": percentile(co2_dh_vals, 0.50),
    "co2_dh_p90": percentile(co2_dh_vals, 0.90),
    "co2_hp_p10": percentile(co2_hp_vals, 0.10),
    "co2_hp_p50": percentile(co2_hp_vals, 0.50),
    "co2_hp_p90": percentile(co2_hp_vals, 0.90),
}
```

#### 3.5.3.4 Decision Robustness

**Robustness Classification**:

A decision is considered **robust** if:
```
robust = (win_fraction ≥ 0.70)
```

Where `win_fraction` is:
- `prob_dh_cheaper` (if DH is chosen based on LCOH)
- `prob_dh_lower_co2` (if DH is chosen based on CO₂)
- Or a combined metric (e.g., `min(prob_dh_cheaper, prob_dh_lower_co2)`)

**Interpretation**:
- **Robust** (`win_fraction ≥ 0.70`): Decision is stable across 70%+ of uncertainty scenarios
- **Marginal** (`0.50 ≤ win_fraction < 0.70`): Decision is sensitive to parameter uncertainty
- **Uncertain** (`win_fraction < 0.50`): Decision may flip under uncertainty

**Code Example**:
```python
# From Decision Agent (conceptual)
win_fraction = prob_dh_cheaper if decision == "DH" else (1.0 - prob_dh_cheaper)
robust = (win_fraction >= 0.70)

if robust:
    robustness_class = "robust"
elif win_fraction >= 0.50:
    robustness_class = "marginal"
else:
    robustness_class = "uncertain"
```

**Output Files**:
- `results/economics/{cluster_id}/economics_deterministic.json`: Deterministic LCOH/CO₂
- `results/economics/{cluster_id}/economics_monte_carlo.json`: Summary (quantiles, win fractions)
- `results/economics/{cluster_id}/economics_monte_carlo_samples.csv`: All N samples (for detailed analysis)

---

## Summary

The Techno-Economic Analysis module provides:

- **LCOH Calculation**: CRF method with detailed CAPEX/OPEX breakdown (pipes, plant, pump, HP equipment, LV upgrade)
- **CO₂ Emissions**: Fuel-specific and COP-dependent calculations with UBA 2025-compatible emission factors
- **Monte Carlo Uncertainty**: N=500 samples with Normal/Triangular/Log-normal distributions, producing win fractions and quantiles (P10, P50, P90)
- **Decision Robustness**: Classification based on win fraction threshold (≥0.70 = robust)

All outputs are deterministic (seeded random number generator), validated, and ready for Decision Agent (LCOH comparison, CO₂ tie-breaker, robustness classification).

---

## 3.6 Decision Coordination (UHDC)

The **Urban Heat Decision Coordinator (UHDC)** orchestrates the final decision-making process by building a **KPI contract** from all agent outputs, applying **rule-based decision logic**, and generating **constrained LLM explanations** for stakeholders.

### 3.6.1 KPI Contract Schema

The **KPI Contract** is the canonical, schema-validated data structure that serves as the single source of truth for decision-making. It aggregates KPIs from CHA, DHA, and Economics agents into a standardized format.

#### 3.6.1.1 JSON Schema Structure

**Required Top-Level Fields**:
```json
{
  "version": "1.0",
  "cluster_id": "ST010_HEINRICH_ZILLE_STRASSE",
  "metadata": {
    "created_utc": "2025-01-25T10:30:00Z",
    "inputs": {...},
    "notes": "..."
  },
  "district_heating": {
    "feasible": true,
    "reasons": ["DH_OK", "ROBUST_DECISION"],
    "lcoh": {
      "median": 145.2,
      "p05": 130.5,
      "p95": 162.8
    },
    "co2": {
      "median": 220.0,
      "p05": 200.0,
      "p95": 240.0
    },
    "hydraulics": {
      "velocity_ok": true,
      "dp_ok": true,
      "v_max_ms": 1.35,
      "v_share_within_limits": 0.98
    },
    "losses": {
      "total_length_m": 1250.0,
      "loss_share_pct": 3.2,
      "pump_power_kw": 15.5
    }
  },
  "heat_pumps": {
    "feasible": true,
    "reasons": ["HP_OK"],
    "lcoh": {
      "median": 152.8,
      "p05": 138.0,
      "p95": 170.5
    },
    "co2": {
      "median": 125.0,
      "p05": 110.0,
      "p95": 140.0
    },
    "lv_grid": {
      "planning_warning": false,
      "max_feeder_loading_pct": 72.5,
      "voltage_violations_total": 0,
      "line_violations_total": 0
    },
    "hp_system": {
      "hp_total_kw_design": 450.0
    }
  },
  "monte_carlo": {
    "dh_wins_fraction": 0.68,
    "hp_wins_fraction": 0.32,
    "n_samples": 500,
    "seed": 42
  }
}
```

**Required Fields Summary**:

| Field | Type | Description |
|-------|------|-------------|
| `version` | string | Contract schema version (must be "1.0") |
| `cluster_id` | string | Cluster identifier |
| `metadata` | object | Timestamp, inputs, notes |
| `district_heating` | object | DH feasibility, LCOH, CO₂, hydraulics, losses |
| `heat_pumps` | object | HP feasibility, LCOH, CO₂, LV grid, HP system |
| `monte_carlo` | object (optional) | Win fractions, sample count, seed |

**District Heating Block**:
- `feasible`: boolean (required)
- `reasons`: list of strings (required, non-empty, must be valid REASON_CODES)
- `lcoh`: object with `median`, `p05`, `p95` (required)
- `co2`: object with `median`, `p05`, `p95` (required)
- `hydraulics`: object with `velocity_ok`, `dp_ok`, `v_max_ms`, `v_share_within_limits` (required)
- `losses`: object with `total_length_m`, `loss_share_pct`, `pump_power_kw` (required)

**Heat Pumps Block**:
- `feasible`: boolean (required)
- `reasons`: list of strings (required, non-empty, must be valid REASON_CODES)
- `lcoh`: object with `median`, `p05`, `p95` (required)
- `co2`: object with `median`, `p05`, `p95` (required)
- `lv_grid`: object with `planning_warning`, `max_feeder_loading_pct`, `voltage_violations_total`, `line_violations_total` (required)
- `hp_system`: object with HP capacity metrics (required)

#### 3.6.1.2 Validation

**Schema Validation**:

The system uses a custom `ContractValidator` class (equivalent to `jsonschema.validate()` in concept) to ensure contract integrity:

```python
# From src/branitz_heat_decision/decision/schemas.py
class ContractValidator:
    @staticmethod
    def validate(contract: Dict[str, Any]) -> None:
        """Validate entire contract. Raises ValueError with detailed message."""
        
        # Top-level keys
        required_keys = ['version', 'cluster_id', 'metadata', 'district_heating', 'heat_pumps']
        missing = [k for k in required_keys if k not in contract]
        if missing:
            raise ValueError(f"Contract missing top-level keys: {missing}")
        
        # Version check
        if contract['version'] != "1.0":
            raise ValueError(f"Unsupported contract version: {contract['version']}")
        
        # Validate metadata
        metadata = contract['metadata']
        if 'created_utc' not in metadata:
            raise ValueError("metadata must contain 'created_utc' timestamp")
        
        # Validate DH block
        ContractValidator._validate_dh_block(contract['district_heating'])
        
        # Validate HP block
        ContractValidator._validate_hp_block(contract['heat_pumps'])
        
        # Validate MC block (optional but if present must be complete)
        if 'monte_carlo' in contract and contract['monte_carlo'] is not None:
            ContractValidator._validate_mc_block(contract['monte_carlo'])
```

**Validation Checks**:

1. **Type Validation**: All fields must match expected types (boolean, number, string, list, object)
2. **Required Fields**: All required fields must be present
3. **Reason Codes**: All reason codes must exist in `REASON_CODES` dictionary
4. **Range Validation**: Numeric fields must be within valid ranges (e.g., `v_share_within_limits` ∈ [0, 1])
5. **Version Check**: Contract version must be "1.0"

**Code Example**:
```python
# From src/branitz_heat_decision/decision/kpi_contract.py
from branitz_heat_decision.decision.schemas import ContractValidator

# Build contract
contract = build_kpi_contract(
    cluster_id="ST010",
    cha_kpis=cha_kpis,
    dha_kpis=dha_kpis,
    economics_summary=econ_summary
)

# Validate
try:
    ContractValidator.validate(contract)
    logger.info("Contract validation passed")
except ValueError as e:
    logger.error(f"Contract validation failed: {e}")
    raise
```

**Reason Codes**:

All reason codes must be valid entries from the `REASON_CODES` dictionary:

```python
# From src/branitz_heat_decision/decision/schemas.py
REASON_CODES = {
    "DH_OK": "District heating meets all EN 13941-1 constraints",
    "DH_VELOCITY_VIOLATION": "DH velocity exceeds 1.5 m/s limit",
    "ONLY_DH_FEASIBLE": "Only district heating is technically feasible",
    "COST_DOMINANT_DH": "DH LCOH is >5% lower than HP",
    "CO2_TIEBREAKER_DH": "DH chosen due to lower CO₂ emissions",
    "ROBUST_DECISION": "Monte Carlo win fraction ≥70%",
    # ... (30+ reason codes total)
}
```

---

### 3.6.2 Rule-Based Decision Logic

The decision logic is **purely deterministic** and **rule-based** (no LLM involvement). It follows a hierarchical decision tree based on feasibility, cost comparison, and CO₂ emissions.

#### 3.6.2.1 Decision Pseudocode

```python
# From src/branitz_heat_decision/decision/rules.py
def decide_from_contract(contract, config):
    dh = contract['district_heating']
    hp = contract['heat_pumps']
    mc = contract.get('monte_carlo', {})
    
    lcoh_dh = dh['lcoh']['median']
    lcoh_hp = hp['lcoh']['median']
    co2_dh = dh['co2']['median']
    co2_hp = hp['co2']['median']
    
    # STEP 1: FEASIBILITY GATE
    if only DH feasible:
        choice = "DH"
        reasons.append("ONLY_DH_FEASIBLE")
    elif only HP feasible:
        choice = "HP"
        reasons.append("ONLY_HP_FEASIBLE")
    elif neither feasible:
        choice = "UNDECIDED"
        reasons.append("NONE_FEASIBLE")
    else:
        # STEP 2: COST COMPARISON
        rel_diff = |LCOH_DH - LCOH_HP| / min(LCOH_DH, LCOH_HP)
        
        if rel_diff > 5%:  # Clear cost winner
            if LCOH_DH < LCOH_HP:
                choice = "DH"
                reasons.append("COST_DOMINANT_DH")
            else:
                choice = "HP"
                reasons.append("COST_DOMINANT_HP")
        else:  # Costs close (≤5%)
            # STEP 3: CO₂ TIE-BREAKER
            reasons.append("COST_CLOSE_USE_CO2")
            if CO2_DH <= CO2_HP:
                choice = "DH"
                reasons.append("CO2_TIEBREAKER_DH")
            else:
                choice = "HP"
                reasons.append("CO2_TIEBREAKER_HP")
    
    # STEP 4: ROBUSTNESS CHECK
    if choice == "DH" and mc.get('dh_wins_fraction'):
        win_fraction = mc['dh_wins_fraction']
        if win_fraction >= 0.70:
            robust = True
            reasons.append("ROBUST_DECISION")
        else:
            robust = False
            reasons.append("SENSITIVE_DECISION")
    elif choice == "HP" and mc.get('hp_wins_fraction'):
        win_fraction = mc['hp_wins_fraction']
        if win_fraction >= 0.70:
            robust = True
            reasons.append("ROBUST_DECISION")
        else:
            robust = False
            reasons.append("SENSITIVE_DECISION")
    
    return DecisionResult(choice, robust, reasons, metrics_used)
```

**Decision Logic Flow**:

1. **Feasibility Gate**: If only one option is feasible → choose it immediately
2. **Cost Comparison**: If costs differ >5% → choose cheaper option
3. **CO₂ Tie-Breaker**: If costs are close (≤5%) → choose lower CO₂ option
4. **Robustness Check**: Evaluate Monte Carlo win fraction (≥70% = robust)

**Code Example**:
```python
# From src/branitz_heat_decision/decision/rules.py
def decide_from_contract(contract, config=None):
    dh = contract['district_heating']
    hp = contract['heat_pumps']
    mc = contract.get('monte_carlo', {})
    
    lcoh_dh = dh['lcoh']['median']
    lcoh_hp = hp['lcoh']['median']
    co2_dh = dh['co2']['median']
    co2_hp = hp['co2']['median']
    
    # Feasibility gate
    if dh['feasible'] and not hp['feasible']:
        choice = "DH"
        reasons.append("ONLY_DH_FEASIBLE")
    elif not dh['feasible'] and hp['feasible']:
        choice = "HP"
        reasons.append("ONLY_HP_FEASIBLE")
    elif not dh['feasible'] and not hp['feasible']:
        choice = "UNDECIDED"
        reasons.append("NONE_FEASIBLE")
    else:
        # Cost comparison
        min_lcoh = min(lcoh_dh, lcoh_hp)
        rel_diff = abs(lcoh_dh - lcoh_hp) / min_lcoh
        
        if rel_diff > config['close_cost_rel_threshold']:  # Default: 0.05 (5%)
            if lcoh_dh < lcoh_hp:
                choice = "DH"
                reasons.append("COST_DOMINANT_DH")
            else:
                choice = "HP"
                reasons.append("COST_DOMINANT_HP")
        else:
            # CO₂ tie-breaker
            reasons.append("COST_CLOSE_USE_CO2")
            if co2_dh <= co2_hp:
                choice = "DH"
                reasons.append("CO2_TIEBREAKER_DH")
            else:
                choice = "HP"
                reasons.append("CO2_TIEBREAKER_HP")
    
    # Robustness check
    robust = False
    if choice == "DH" and mc.get('dh_wins_fraction'):
        win_fraction = mc['dh_wins_fraction']
        if win_fraction >= config['robust_win_fraction']:  # Default: 0.70
            robust = True
            reasons.append("ROBUST_DECISION")
    
    return DecisionResult(choice, robust, reasons, metrics_used)
```

#### 3.6.2.2 Robustness Flag

**Robustness Classification**:

The robustness flag is based on **Monte Carlo win fraction**:

```python
robust = (win_fraction >= 0.70)
```

Where:
- `win_fraction = dh_wins_fraction` (if choice == "DH")
- `win_fraction = hp_wins_fraction` (if choice == "HP")

**Interpretation**:
- **Robust** (`win_fraction ≥ 0.70`): Decision is stable across 70%+ of uncertainty scenarios
- **Sensitive** (`0.55 ≤ win_fraction < 0.70`): Decision is sensitive to parameter uncertainty
- **Uncertain** (`win_fraction < 0.55` or MC missing): Decision may flip under uncertainty

**Code Example**:
```python
# From src/branitz_heat_decision/decision/rules.py
if choice == "DH" and mc.get('dh_wins_fraction'):
    win_fraction = mc['dh_wins_fraction']
    if win_fraction >= config['robust_win_fraction']:  # 0.70
        robust = True
        reasons.append("ROBUST_DECISION")
    elif win_fraction >= config['sensitive_win_fraction']:  # 0.55
        reasons.append("SENSITIVE_DECISION")
```

---

### 3.6.3 Constrained LLM Explainer

The UHDC generates **natural language explanations** using a **constrained LLM** (Gemini) that is **read-only** (never runs simulations) and **fact-checked** against the KPI contract.

#### 3.6.3.1 Prompt Engineering

**Template Structure**:

The prompt is built from **only contract fields** (no external retrieval):

```python
# From src/branitz_heat_decision/uhdc/explainer.py
def _build_constrained_prompt(contract, decision, style):
    template = STYLE_TEMPLATES[style]
    
    # Extract metrics
    dh = contract['district_heating']
    hp = contract['heat_pumps']
    mc = contract.get('monte_carlo', {})
    
    # Build metrics section (all numbers explicit)
    metrics_section = f"""
## District Heating Metrics
- Feasible: {dh['feasible']} (Reasons: {', '.join(dh['reasons'])})
- LCOH: {dh['lcoh']['median']:.1f} €/MWh (95% CI: {dh['lcoh']['p05']:.1f} - {dh['lcoh']['p95']:.1f})
- CO₂: {dh['co2']['median']:.0f} kg/MWh
- Max Velocity: {dh['hydraulics'].get('v_max_ms', 'N/A')} m/s
- Velocity Within Limits: {dh['hydraulics'].get('v_share_within_limits', 'N/A'):.1%}
- Pressure Drop OK: {dh['hydraulics'].get('dp_ok', 'N/A')}
- Thermal Losses: {dh['losses'].get('loss_share_pct', 'N/A')}%

## Heat Pump Metrics
- Feasible: {hp['feasible']} (Reasons: {', '.join(hp['reasons'])})
- LCOH: {hp['lcoh']['median']:.1f} €/MWh (95% CI: {hp['lcoh']['p05']:.1f} - {hp['lcoh']['p95']:.1f})
- CO₂: {hp['co2']['median']:.0f} kg/MWh
- Max Feeder Loading: {hp['lv_grid'].get('max_feeder_loading_pct', 'N/A')}%
- Voltage Violations: {hp['lv_grid'].get('voltage_violations_total', 'N/A')}
- Planning Warning: {hp['lv_grid'].get('planning_warning', 'N/A')}

## Monte Carlo Robustness
- DH Wins: {mc.get('dh_wins_fraction', 0):.1%}
- HP Wins: {mc.get('hp_wins_fraction', 0):.1%}
- Samples: {mc.get('n_samples', 'N/A')}
"""
    
    # Decision section
    decision_section = f"""
## Decision Logic Applied
- Choice: {decision['choice']}
- Robust: {decision['robust']}
- Reason Codes: {', '.join(decision['reason_codes'])}
"""
    
    # Build prompt
    prompt = f"""You are an energy planning assistant specialized in municipal heating decisions.

## STRICT RULES (Violate = Invalid Output)
1. CITE ONLY the metrics provided above - do not invent numbers
2. REFERENCE ONLY standards: EN 13941-1 (DH), VDE-AR-N 4100 (LV grid)
3. STATE ASSUMPTIONS explicitly if needed
4. KEEP length: {template['instruction']}
5. NO HALLUCINATION: Every numeric value must be traceable to the metrics above

## Contract Data
{metrics_section}

{decision_section}

## Style Requirements
- {template['instruction']}
- Tone: {template['tone']}
- Must explicitly cite: {', '.join(template['must_include'])}

## Output
Provide your explanation below:
"""
    
    return prompt.strip()
```

**Key Constraints**:
- **Only Contract Data**: Prompt contains ONLY fields from the KPI contract
- **No External Retrieval**: LLM cannot access external databases or APIs
- **Explicit Numbers**: All metrics are explicitly formatted with units
- **Style Templates**: Different styles (executive, technical, detailed) with specific instructions

#### 3.6.3.2 Temperature=0: Deterministic Output

**LLM Configuration**:

The LLM is called with **temperature=0.0** for deterministic output:

```python
# From src/branitz_heat_decision/uhdc/explainer.py
def _call_llm(prompt: str, model: str) -> str:
    import google.generativeai as genai
    
    client = genai.Client(api_key=GOOGLE_API_KEY)
    
    cfg = types.GenerationConfig(
        temperature=0.0,  # Deterministic
        top_p=0.95,
        top_k=40,
        max_output_tokens=1024,
    )
    
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=cfg,
        request_options=types.RequestOptions(timeout=LLM_TIMEOUT)
    )
    
    return response.text
```

**Determinism Guarantees**:
- **Temperature=0.0**: No randomness in token selection
- **Same Prompt → Same Output**: Identical contract data produces identical explanation
- **Reproducible**: Explanations can be regenerated deterministically

#### 3.6.3.3 Post-Generation Sanity Check

**Safety Validation**:

After LLM generation, the output is validated against the contract to detect hallucination:

```python
# From src/branitz_heat_decision/uhdc/explainer.py
def _validate_explanation_safety(explanation, contract, decision):
    """
    Validate LLM output against contract data to detect hallucination.
    
    Checks:
    1. All numbers in explanation exist in contract
    2. No numbers deviate >1% from contract values
    3. Standard references are correct
    4. Choice matches decision choice
    """
    
    # Extract all numbers from explanation
    numbers_found = re.findall(r'\d+\.?\d*', explanation)
    
    # Build set of allowed numbers from contract
    allowed_numbers = set()
    
    # Add LCOH values (with rounding tolerance)
    _add_number(contract['district_heating']['lcoh']['median'])
    _add_number(contract['heat_pumps']['lcoh']['median'])
    
    # Add CO₂ values
    _add_number(contract['district_heating']['co2']['median'])
    _add_number(contract['heat_pumps']['co2']['median'])
    
    # Add quantiles (P05, P95)
    for side in ("district_heating", "heat_pumps"):
        _add_number(contract[side]["lcoh"].get("p05"))
        _add_number(contract[side]["lcoh"].get("p95"))
    
    # Validate each number found
    for num_str in numbers_found:
        num_float = float(num_str)
        
        # Skip obvious non-metrics (year, cluster ID, etc.)
        if num_float < 0.1 or num_float > 10000:
            continue
        
        # Check if number matches contract (with ±1% tolerance)
        matches = False
        for allowed in allowed_numbers:
            if abs(float(allowed) - num_float) / max(abs(float(allowed)), 0.01) <= 0.01:
                matches = True
                break
        
        if not matches:
            raise ValueError(
                f"Hallucination detected: number {num_str} not found in contract "
                f"(allowed: {sorted(allowed_numbers)})"
            )
    
    # Validate choice matches
    if decision['choice'] not in explanation.upper():
        raise ValueError(f"Decision choice '{decision['choice']}' not mentioned in explanation")
```

**Validation Checks**:
1. **Number Verification**: All numeric values in explanation must exist in contract (with ±1% tolerance)
2. **Choice Verification**: Decision choice must be mentioned in explanation
3. **Standard References**: Only EN 13941-1 and VDE-AR-N 4100 are allowed
4. **No Invention**: Any number not in contract triggers validation error

**Code Example**:
```python
# From src/branitz_heat_decision/uhdc/explainer.py
def explain_with_llm(contract, decision, style="executive"):
    # Build constrained prompt
    prompt = _build_constrained_prompt(contract, decision, style)
    
    # Call LLM
    try:
        explanation = _call_llm(prompt, model="gemini-2.0-flash")
    except Exception as e:
        logger.error(f"LLM API call failed: {e}")
        return _fallback_template_explanation(contract, decision, style)
    
    # Validate safety
    try:
        _validate_explanation_safety(explanation, contract, decision)
    except ValueError as e:
        logger.error(f"LLM safety check failed: {e}")
        return _fallback_template_explanation(contract, decision, style)
    
    return explanation
```

#### 3.6.3.4 Safety: LLM Never Runs Simulations

**Read-Only Constraint**:

The LLM is **strictly read-only** and **never runs simulations**:

1. **No Simulation Access**: LLM cannot call pandapipes, pandapower, or any simulation functions
2. **No Data Retrieval**: LLM cannot access external databases or APIs
3. **Contract-Only Input**: Prompt contains ONLY contract data (no raw simulation outputs)
4. **Template Fallback**: If LLM fails or hallucinates, system falls back to deterministic template

**Safety Guarantees**:
- ✅ **No Side Effects**: LLM cannot modify network models or run calculations
- ✅ **No Hallucination**: Post-generation validation ensures all numbers are traceable
- ✅ **Deterministic Fallback**: Template explanations are always available
- ✅ **Auditable**: All explanations can be traced back to contract data

**Code Example**:
```python
# From src/branitz_heat_decision/uhdc/explainer.py
def explain_with_llm(contract, decision, style="executive"):
    """
    Generate natural language explanation using LLM (Gemini).
    
    Safety:
    - Prompt contains ONLY contract data (no external retrieval)
    - Temperature=0.0 for determinism
    - Post-generation validation ensures no hallucination
    - Falls back to template if LLM fails
    """
    
    # Guard: Missing critical fields → use template
    if not _has_critical_fields(contract):
        return _fallback_template_explanation(contract, decision, style)
    
    # Build constrained prompt (contract data only)
    prompt = _build_constrained_prompt(contract, decision, style)
    
    # Call LLM (read-only, no simulation access)
    explanation = _call_llm(prompt, model="gemini-2.0-flash")
    
    # Validate safety (detect hallucination)
    _validate_explanation_safety(explanation, contract, decision)
    
    return explanation
```

---

## Summary

The Decision Coordination (UHDC) module provides:

- **KPI Contract Schema**: Canonical, schema-validated data structure with required fields (feasible, lcoh, co2, reasons) and strict validation
- **Rule-Based Decision Logic**: Deterministic decision tree (feasibility → cost → CO₂ → robustness) with pseudocode implementation
- **Constrained LLM Explainer**: Read-only LLM with temperature=0, prompt engineering (contract-only input), post-generation sanity checks, and template fallback

All outputs are deterministic, auditable, and ready for stakeholder reports (HTML, Markdown, JSON).

---

## 3.7 Interactive Map Generation

The system generates **interactive HTML maps** using **Folium** to visualize network topology, hydraulic/thermal/electrical performance, and pipe sizing. Maps use **cascading colors** for performance metrics and **dynamic line thickness** for pipe diameter visualization.

### 3.7.1 Cascading Colors

**Cascading colors** provide intuitive visual feedback for performance metrics across the network. Different colormaps are used for hydraulic, thermal, and electrical visualizations.

#### 3.7.1.1 Hydraulic: Colormap coolwarm for Velocity

**Velocity Colormap** (0 → 1.5 m/s):

- **Colormap**: `coolwarm` (matplotlib)
- **Range**: 0.0 m/s (blue) → 1.5 m/s (red)
- **Supply Pipes**: Red gradient (`#fee5d9` → `#fcae91` → `#fb6a4a` → `#cb181d`)
- **Return Pipes**: Blue gradient (`#deebf7` → `#9ecae1` → `#3182bd` → `#08519c`)

**Code Example**:
```python
# From src/branitz_heat_decision/cha/qgis_export.py
import branca.colormap as cm

# Velocity colormap (coolwarm-inspired)
supply_cmap = cm.LinearColormap(
    colors=['#fee5d9', '#fcae91', '#fb6a4a', '#cb181d'],  # Red gradient
    vmin=0.0,
    vmax=1.5,
    caption='Supply velocity (m/s)'
)

return_cmap = cm.LinearColormap(
    colors=['#deebf7', '#9ecae1', '#3182bd', '#08519c'],  # Blue gradient
    vmin=0.0,
    vmax=1.5,
    caption='Return velocity (m/s)'
)

# Apply to pipes
for pipe in pipes:
    velocity = pipe['velocity_ms']
    color = supply_cmap(velocity) if pipe['is_supply'] else return_cmap(velocity)
    folium.PolyLine(..., color=color, ...)
```

**Visual Interpretation**:
- **Blue** (low velocity): Underutilized pipes, potential for downsizing
- **Red** (high velocity): High flow, approaching EN 13941-1 limit (1.5 m/s)
- **Yellow/Orange** (medium): Normal operating range

#### 3.7.1.2 Thermal: Colormap viridis for Temperature Drop

**Temperature Colormap** (30°C → 90°C):

- **Colormap**: `viridis` (or `RdYlBu_r` for supply/return distinction)
- **Range**: 30°C (dark blue) → 90°C (yellow)
- **Supply Pipes**: Red gradient (hot = red)
- **Return Pipes**: Blue gradient (cool = blue)

**Code Example**:
```python
# From src/branitz_heat_decision/cha/qgis_export.py
# Temperature colormap
supply_cmap = cm.LinearColormap(
    colors=['#fee5d9', '#fcae91', '#fb6a4a', '#cb181d'],  # Red gradient
    vmin=30.0,
    vmax=90.0,
    caption='Supply temperature (°C)'
)

return_cmap = cm.LinearColormap(
    colors=['#deebf7', '#9ecae1', '#3182bd', '#08519c'],  # Blue gradient
    vmin=30.0,
    vmax=90.0,
    caption='Return temperature (°C)'
)

# Apply to pipes
for pipe in pipes:
    temp_avg = 0.5 * (pipe['t_from_c'] + pipe['t_to_c'])
    color = supply_cmap(temp_avg) if pipe['is_supply'] else return_cmap(temp_avg)
    folium.PolyLine(..., color=color, ...)
```

**Visual Interpretation**:
- **Dark Blue** (low temp): High thermal losses, poor insulation
- **Yellow/Red** (high temp): Good heat delivery, minimal losses
- **Gradient**: Temperature drop along pipe length (thermal losses)

#### 3.7.1.3 Electrical: Colormap RdYlGn for Voltage

**Voltage Colormap** (0.95 → 1.05 pu):

- **Colormap**: `RdYlGn` (Red-Yellow-Green)
- **Range**: 0.95 pu (red) → 1.05 pu (green)
- **Discrete Thresholds**:
  - **Green** (≥1.00 pu): Good voltage
  - **Yellow** (0.95-1.00 pu): Caution
  - **Orange** (0.90-0.95 pu): Warning
  - **Red** (<0.90 pu): Critical (VDE-AR-N 4100 violation)

**Code Example**:
```python
# From src/branitz_heat_decision/dha/export.py
from branca.colormap import LinearColormap

# Voltage colormap (RdYlGn-inspired)
def bus_color(v_pu):
    if v_pu < 0.90:
        return "#E74C3C"  # Red (critical)
    if v_pu < 0.95:
        return "#E67E22"  # Orange (warning)
    if v_pu < 1.00:
        return "#F1C40F"  # Yellow (caution)
    return "#2ECC71"  # Green (good)

# Apply to buses
for bus in buses:
    v_pu = bus['vm_pu']
    color = bus_color(v_pu)
    folium.CircleMarker(
        location=[bus['lat'], bus['lon']],
        fill_color=color,
        ...
    )
```

**Visual Interpretation**:
- **Green** (≥1.00 pu): Voltage within normal range
- **Yellow** (0.95-1.00 pu): Marginal, monitor closely
- **Orange/Red** (<0.95 pu): VDE-AR-N 4100 violation, requires mitigation

**Note**: For continuous colormap (RdYlGn), the system can use:
```python
voltage_cmap = LinearColormap(
    colors=['#d73027', '#fee08b', '#1a9850'],  # Red → Yellow → Green
    vmin=0.95,
    vmax=1.05,
    caption='Voltage (pu)'
)
```

---

### 3.7.2 Pipe Sizing Visualization

**Line thickness** is used to visualize pipe diameter (DN), providing immediate visual feedback on network sizing.

#### 3.7.2.1 Line Thickness: Linear Scale

**Formula**:
```
thickness = DN / 20 (px)
```

Where:
- `DN`: Nominal diameter (e.g., DN50 = 50 mm)
- `thickness`: Folium line weight in pixels

**Scaling by Role**:

1. **Trunk Pipes** (DN 50-200):
   ```python
   # From src/branitz_heat_decision/cha/qgis_export.py
   def pipe_weight(diameter_mm: float, role: str) -> float:
       if role == "trunk":
           d_min, d_max = 50.0, 200.0
           w_min, w_max = 4.0, 12.0
           # Linear interpolation
           w = w_min + (d - d_min) * (w_max - w_min) / (d_max - d_min)
           return max(w_min, min(w_max, w))
   ```

2. **Service Pipes** (DN 20-80):
   ```python
   if role == "service":
       d_min, d_max = 20.0, 80.0
       w_min, w_max = 2.0, 7.0
       w = w_min + (d - d_min) * (w_max - w_min) / (d_max - d_min)
       return max(w_min, min(w_max, w))
   ```

**DN-to-Thickness Mapping** (lookup table):
```python
# From src/branitz_heat_decision/cha/qgis_export.py
DN_TO_WIDTH = {
    20: 2, 25: 2.5, 32: 3, 40: 3.5, 50: 4,
    65: 5, 80: 6, 100: 7, 125: 8, 150: 9,
    200: 10, 250: 12, 300: 14, 400: 16
}
```

**Code Example**:
```python
# From src/branitz_heat_decision/cha/qgis_export.py
for pipe in pipes:
    dn = pipe.get('dn', None) or _parse_dn_from_std_type(pipe.get('std_type', ''))
    diameter_mm = pipe.get('diameter_mm', np.nan)
    
    # Get line weight
    role = "trunk" if not pipe['is_service'] else "service"
    weight = pipe_weight(diameter_mm, role)
    
    # Alternative: use lookup table
    # weight = DN_TO_WIDTH.get(dn, 6)
    
    folium.PolyLine(
        locations=pipe['coordinates'],
        weight=weight,  # Line thickness
        color=color,
        ...
    )
```

#### 3.7.2.2 Dynamic: Update Thickness When DN Changes

**Dynamic Updates**:

When pipes are resized (e.g., after iterative sizing), the map automatically updates line thickness:

```python
# From src/branitz_heat_decision/cha/qgis_export.py
def update_pipe_thickness(map_obj, pipe_id, new_dn, role="trunk"):
    """
    Update pipe line thickness after resizing.
    
    Args:
        map_obj: Folium map object
        pipe_id: Pipe identifier
        new_dn: New DN value
        role: "trunk" or "service"
    """
    # Calculate new weight
    new_weight = pipe_weight(new_dn * 10, role)  # Convert DN to mm (approximate)
    
    # Find pipe layer and update
    for layer in map_obj._children.values():
        if hasattr(layer, 'data') and pipe_id in layer.data:
            # Update PolyLine weight
            layer.data[pipe_id]['weight'] = new_weight
            # Trigger map refresh (requires re-rendering)
```

**Visual Legend**:

The map includes a thickness legend showing DN-to-thickness mapping:

```python
# From src/branitz_heat_decision/cha/qgis_export.py
thickness_legend = f"""
<div style="position: fixed; bottom: 20px; right: 20px; ...">
  <div>Line thickness indicates pipe diameter (DN)</div>
  <svg width="230" height="70">
    <line x1="10" y1="12" x2="220" y2="12" 
          stroke="#333" stroke-width="{pipe_weight(25, 'service')}" />
    <text>DN25 (thin)</text>
    
    <line x1="10" y1="28" x2="220" y2="28" 
          stroke="#333" stroke-width="{pipe_weight(50, 'trunk')}" />
    <text>DN50 (medium)</text>
    
    <line x1="10" y1="44" x2="220" y2="44" 
          stroke="#333" stroke-width="{pipe_weight(100, 'trunk')}" />
    <text>DN100 (thick)</text>
    
    <line x1="10" y1="60" x2="220" y2="60" 
          stroke="#333" stroke-width="{pipe_weight(150, 'trunk')}" />
    <text>DN150 (extra thick)</text>
  </svg>
</div>
"""
```

---

### 3.7.3 Folium Integration

The system uses **Folium** (Python wrapper for Leaflet.js) to create interactive maps with multiple layers, popups, and standalone HTML export.

#### 3.7.3.1 Layers

**Layer Structure**:

1. **Trunk Supply Pipes**:
   ```python
   # From src/branitz_heat_decision/cha/qgis_export.py
   trunk_supply_layer = folium.FeatureGroup(name="Supply Pipes (Trunk)", show=True)
   
   for pipe in trunk_supply_pipes:
       folium.PolyLine(
           locations=pipe['coordinates'],
           color=supply_cmap(pipe['velocity_ms']),
           weight=pipe_weight(pipe['diameter_mm'], 'trunk'),
           popup=folium.Popup(popup_html, max_width=350),
           tooltip=f"Trunk Supply: {pipe['velocity_ms']:.2f} m/s, DN: {pipe['dn']}"
       ).add_to(trunk_supply_layer)
   
   trunk_supply_layer.add_to(m)
   ```

2. **Trunk Return Pipes**:
   ```python
   trunk_return_layer = folium.FeatureGroup(name="Return Pipes (Trunk)", show=True)
   # Similar structure with return_cmap
   ```

3. **Service Connections**:
   ```python
   service_supply_layer = folium.FeatureGroup(name="Service Supply Pipes", show=False)
   service_return_layer = folium.FeatureGroup(name="Service Return Pipes", show=False)
   
   for pipe in service_pipes:
       folium.PolyLine(
           locations=pipe['coordinates'],
           color=service_color,
           weight=pipe_weight(pipe['diameter_mm'], 'service'),
           dash_array='6, 6',  # Dashed line for service
           popup=folium.Popup(service_popup_html, max_width=300),
           ...
       ).add_to(service_supply_layer)
   ```

4. **Buildings**:
   ```python
   building_layer = folium.FeatureGroup(name="Buildings", show=True)
   
   for building in buildings:
       demand_kw = building.get('peak_heat_kw', ...)
       radius = max(3, min(20, np.sqrt(demand_kw) / 2))  # Size ∝ sqrt(demand)
       
       folium.CircleMarker(
           location=[building['lat'], building['lon']],
           radius=radius,
           color='black',
           fill_color='red',
           fill_opacity=0.6,
           popup=folium.Popup(building_popup_html, max_width=250),
           tooltip=f"Building: {demand_kw:.1f} kW"
       ).add_to(building_layer)
   ```

5. **Plant**:
   ```python
   folium.Marker(
       location=[plant_lat, plant_lon],
       popup="<b>Heat Plant</b><br>Cluster: {cluster_id}",
       icon=folium.Icon(color='red', icon='fire', prefix='fa'),
   ).add_to(m)
   ```

**Layer Control**:
```python
# From src/branitz_heat_decision/cha/qgis_export.py
if add_layer_control:
    folium.LayerControl(position='topright', collapsed=False).add_to(m)
```

#### 3.7.3.2 Popups: Show Exact KPIs on Click

**Popup Content**:

Each pipe/building/plant element shows detailed KPIs on click:

**Pipe Popup**:
```python
# From src/branitz_heat_decision/cha/qgis_export.py
popup_html = f"""
<div style="font-family: Arial, sans-serif;">
    <h4>Trunk Supply Pipe</h4>
    <b>ID:</b> {pipe['pipe_id']}<br>
    <b>Name:</b> {pipe_name}<br>
    <b>DN:</b> {dn}<br>
    <b>Diameter:</b> {diam_mm:.0f} mm<br>
    <b>Length:</b> {pipe['length_m']:.1f} m<br>
    <b>Velocity:</b> {velocity:.2f} m/s<br>
    <b>Pressure Drop:</b> {pipe['pressure_drop_bar']:.3f} bar<br>
    <b>T_from:</b> {pipe['t_from_c']:.1f} °C<br>
    <b>T_to:</b> {pipe['t_to_c']:.1f} °C<br>
    <b>ΔT (pipe):</b> {pipe['temp_drop_c']:.2f} °C<br>
    <b>Flow Direction:</b> Plant → Buildings
</div>
"""

folium.PolyLine(
    ...,
    popup=folium.Popup(popup_html, max_width=350),
    tooltip=f"Trunk Supply: {velocity:.2f} m/s, DN: {dn}"
)
```

**Building Popup**:
```python
popup_html = f"""
<b>Building {building['building_id']}</b><br>
Type: {building.get('use_type', 'unknown')}<br>
Peak demand: {demand_kw:.2f} kW<br>
Floor area: {building.get('floor_area_m2', 'N/A')} m²<br>
Year: {building.get('year_of_construction', 'N/A')}
"""
```

**Plant Popup**:
```python
popup_html = f"""
<b>Heat Plant</b><br>
Cluster: {cluster_id}<br>
Location: ({plant_lat:.6f}, {plant_lon:.6f})<br>
Capacity: {plant_capacity_kw:.1f} kW
"""
```

#### 3.7.3.3 Export: Save as Standalone HTML

**Standalone HTML Export**:

Maps are exported as **standalone HTML files** that require **no server**:

```python
# From src/branitz_heat_decision/cha/qgis_export.py
def create_interactive_map(
    net: pp.pandapipesNet,
    buildings: gpd.GeoDataFrame,
    cluster_id: str,
    output_path: Optional[Path] = None,
    ...
) -> str:
    # Create Folium map
    m = folium.Map(location=map_center, zoom_start=15, tiles="OpenStreetMap")
    
    # Add layers (pipes, buildings, plant)
    # ...
    
    # Save to HTML
    if output_path is None:
        output_path = Path(f"results/interactive_maps/{cluster_id}.html")
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    m.save(str(output_path))
    
    logger.info(f"Interactive map saved to {output_path}")
    return str(output_path)
```

**Standalone Features**:
- ✅ **No Server Required**: HTML file contains all JavaScript/CSS (Folium bundles Leaflet.js)
- ✅ **Portable**: Can be shared via email, cloud storage, or local file system
- ✅ **Interactive**: Full zoom, pan, layer toggle, popup functionality
- ✅ **Self-Contained**: All data embedded in HTML (GeoJSON inline)

**Output Files**:
- `results/cha/{cluster_id}/interactive_map.html`: Main map (velocity/temperature)
- `results/cha/{cluster_id}/interactive_map_temperature.html`: Temperature-focused map
- `results/cha/{cluster_id}/interactive_map_pressure.html`: Pressure-focused map
- `results/dha/{cluster_id}/hp_lv_map.html`: LV grid map (voltage/loading)

**Code Example**:
```python
# From src/branitz_heat_decision/cha/qgis_export.py
# Create map
map_path = create_interactive_map(
    net=net,
    buildings=buildings,
    cluster_id="ST010_HEINRICH_ZILLE_STRASSE",
    output_path=Path("results/cha/ST010/interactive_map.html"),
    color_by="velocity",  # or "temperature", "pressure"
    velocity_range=(0.0, 1.5),
    temp_range=(30.0, 90.0)
)

# Map is now available as standalone HTML
# Open in browser: file:///path/to/results/cha/ST010/interactive_map.html
```

---

## Summary

The Interactive Map Generation module provides:

- **Cascading Colors**: coolwarm for velocity (0→1.5 m/s), viridis/RdYlBu for temperature (30→90°C), RdYlGn for voltage (0.95→1.05 pu)
- **Pipe Sizing Visualization**: Linear scale thickness = DN/20 (px), dynamic updates when DN changes after resizing
- **Folium Integration**: Multiple layers (trunk supply/return, service connections, buildings, plant), popups with exact KPIs, standalone HTML export (no server required)

All maps are interactive, portable, and ready for stakeholder review and validation.
