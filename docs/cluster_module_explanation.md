# Cluster Module (`cluster.py`) - Complete Explanation

## Overview

The `cluster.py` module handles **street-based clustering** of buildings and **aggregation of hourly heat profiles** to cluster level. It's a core component of the data preparation pipeline that groups buildings by streets and computes design loads for district heating network sizing.

## Module Structure

The module contains **9 main functions** organized into three categories:

1. **Profile Aggregation Functions** (3 functions)
2. **Street-Based Clustering Functions** (3 functions)  
3. **Writer Functions** (2 functions)

---

## 1. Profile Aggregation Functions

### `aggregate_cluster_profiles()`

**Purpose**: Sums hourly heat demand profiles from individual buildings to cluster level.

**How it works**:
1. **Input Validation**:
   - Checks that `hourly_profiles` has exactly 8760 rows (1 year of hourly data)
   - Validates that `cluster_map` has `building_id` column
   - Auto-detects cluster ID column from: `['cluster_id', 'street_id', 'street_cluster']`

2. **Building-to-Cluster Mapping**:
   - Creates a dictionary mapping each `building_id` to its `cluster_id`
   - Extracts unique cluster IDs from the cluster map

3. **Profile Aggregation**:
   - For each cluster:
     - Finds all buildings belonging to that cluster
     - Filters to buildings that exist in `hourly_profiles.columns`
     - **Sums** the hourly profiles across all buildings in the cluster
     - Creates a Series with 8760 values (one per hour)
   - If a cluster has no buildings in the profiles, creates a zero-filled Series with a warning

4. **Output**:
   - Returns dictionary: `{cluster_id: pd.Series(8760)}`
   - Each Series contains aggregated hourly heat demand in kW

**Example**:
```python
# Input: hourly_profiles (8760 rows × 100 buildings)
#        cluster_map (100 rows: building_id → cluster_id)

# Output: {
#   "ST001_AN_DEN_WEINBERGEN": Series([1250.5, 1240.2, ...], 8760 values),
#   "ST002_AN_DER_BAHN": Series([890.3, 880.1, ...], 8760 values),
#   ...
# }
```

---

### `compute_design_and_topn()`

**Purpose**: Identifies the design hour (peak load) and top-N highest load hours for each cluster.

**How it works**:
1. **For each cluster profile**:
   - Validates profile has 8760 hours (warns and skips if not)
   - **Design hour**: Finds hour with maximum load using `series.idxmax()`
   - **Design load**: Maximum load value using `series.max()`
   - **Top-N hours**: Sorts profile by load (descending), takes first N hours
   - **Top-N loads**: Corresponding load values for those hours

2. **Metadata**:
   - Stores metadata: `N` (number of top hours), `source_profiles`, `version`

3. **Output Structure**:
```json
{
  "clusters": {
    "ST001_AN_DEN_WEINBERGEN": {
      "design_hour": 3421,
      "design_load_kw": 1250.5,
      "topn_hours": [3421, 3422, 3420, ...],
      "topn_loads_kw": [1250.5, 1248.3, 1245.1, ...]
    }
  },
  "meta": {
    "N": 10,
    "source_profiles": "hourly_heat_profiles.parquet",
    "version": "v1"
  }
}
```

**Why this matters**:
- **Design hour**: Used for network sizing (worst-case scenario)
- **Top-N hours**: Used for reliability analysis and peak load assessment

---

### `create_cluster_summary()`

**Purpose**: Creates a summary DataFrame with one row per cluster containing aggregated statistics.

**How it works**:
1. **Auto-detects cluster ID column** (supports aliases: `cluster_id`, `street_id`, `street_cluster`)

2. **For each cluster**:
   - **Building count**: Counts buildings in cluster from `cluster_map`
   - **Annual heat demand**: Sums `annual_heat_demand_kwh_a` from `buildings_df`
     - Fallback: If column missing, sums from hourly profile
   - **Design metrics**: Extracts from `design_topn_dict["clusters"][cluster_id]`
     - Fallback: Computes from profile if not in dict
   - **Top-N statistics**: Computes mean, min, max from `topn_loads_kw`

3. **Output DataFrame**:
```
   cluster_id  n_buildings  annual_heat_kwh_a  design_hour  design_load_kw  topn_mean_kw  topn_min_kw  topn_max_kw
0  ST001_...           25           125000.0         3421         1250.5        1240.2       1200.0       1250.5
1  ST002_...           18            89000.0         2105          890.3         880.1        850.0        890.3
```

**Use cases**:
- Quick overview of cluster characteristics
- Reporting and visualization
- Filtering clusters by size or demand

---

## 2. Street-Based Clustering Functions

### `extract_street_from_address()`

**Purpose**: Extracts street name from various address data formats.

**How it works**:
1. **Handles multiple input formats**:
   - **List of dicts**: `[{"str": "Parkstraße", "hnr": 6}]` → extracts `"str"` field
   - **Dict**: `{"street": "Parkstraße", "number": 6}` → extracts `"street"` or `"strasse"` field
   - **String**: `"Parkstraße 6, 03042 Cottbus"` → parses to extract street name

2. **String parsing logic**:
   - Splits by comma, takes first part
   - Removes house number (last word if numeric)
   - Returns remaining street name

**Example**:
```python
extract_street_from_address([{"str": "AN DEN WEINBERGEN", "hnr": 1}])
# → "AN DEN WEINBERGEN"

extract_street_from_address("Parkstraße 6, 03042 Cottbus")
# → "Parkstraße"
```

---

### `normalize_street_name()`

**Purpose**: Normalizes street names for consistent matching (handles German characters, abbreviations).

**How it works**:
1. **Case normalization**: Converts to uppercase
2. **German character replacement**:
   - `Ä` → `AE`
   - `Ö` → `OE`
   - `Ü` → `UE`
   - `ß` → `SS`
3. **Abbreviation expansion**:
   - `STR.` → `STRASSE`
   - `STR` → `STRASSE`
   - `ST.` → `STRASSE`
4. **Whitespace cleanup**: Removes extra spaces

**Example**:
```python
normalize_street_name("Parkstraße")
# → "PARKSTRASSE"

normalize_street_name("An der Bahn Str.")
# → "AN DER BAHN STRASSE"
```

**Why this matters**: Street names in building addresses may not exactly match street names in the street GeoJSON. Normalization enables fuzzy matching.

---

### `match_buildings_to_streets()`

**Purpose**: Matches buildings to streets using address data with spatial fallback.

**How it works**:
1. **Street name extraction**:
   - Extracts street name from each building's `adressen` column
   - Normalizes the extracted street name

2. **Address-based matching** (primary method):
   - **Exact match**: Tries normalized street name against normalized street names in GeoJSON
   - **Fuzzy match**: If exact fails, checks if normalized names contain each other
   - Match methods: `'address_exact'` or `'address_fuzzy'`

3. **Spatial fallback** (if address matching fails):
   - Finds nearest street to building centroid
   - Only matches if distance ≤ `max_distance_m` (default: 500m)
   - Match method: `'spatial'`

4. **Output DataFrame**:
```
   building_id  street_name        street_normalized    matched_method
0  B0001        AN DEN WEINBERGEN  AN DEN WEINBERGEN   address_exact
1  B0002        AN DEN WEINBERGEN  AN DEN WEINBERGEN   address_fuzzy
2  B0003        AN DER BAHN        AN DER BAHN         spatial
```

**Why this matters**: Not all buildings have perfect address data. Spatial fallback ensures buildings are matched even with incomplete addresses.

---

### `create_street_clusters()`

**Purpose**: Creates street-based clusters from building-to-street mappings.

**How it works**:
1. **Groups buildings by street**:
   - Uses `groupby('street_name')` on `building_street_map`
   - Each street becomes one cluster

2. **Cluster ID generation**:
   - Format: `ST{number:03d}_{STREET_NAME}`
   - Example: `ST001_AN_DEN_WEINBERGEN`
   - Normalizes street name and replaces special chars with underscores

3. **Plant location calculation**:
   - **Primary**: Centroid of all buildings in cluster
   - **Fallback**: Midpoint of street if no buildings

4. **Outputs two DataFrames**:
   - **`building_cluster_map`**: `[building_id, cluster_id]` - maps each building to its cluster
   - **`street_clusters`**: Cluster metadata with plant coordinates, building counts

**Example output**:
```python
# building_cluster_map:
   building_id  cluster_id
0  B0001       ST001_AN_DEN_WEINBERGEN
1  B0002       ST001_AN_DEN_WEINBERGEN
2  B0003       ST002_AN_DER_BAHN

# street_clusters:
   street_id                  cluster_name        plant_x      plant_y  building_count
0  ST001_AN_DEN_WEINBERGEN    AN DEN WEINBERGEN  385000.5     5800000.2  25
1  ST002_AN_DER_BAHN          AN DER BAHN        385100.3     5800100.1  18
```

---

## 3. Writer Functions

### `save_design_topn_json()`

**Purpose**: Saves design hour and top-N hours dictionary to JSON file with validation.

**How it works**:
1. **Validates structure**:
   - Checks `design_topn_dict` is a dictionary
   - Verifies `"clusters"` and `"meta"` keys exist

2. **File operations**:
   - Creates parent directory if needed
   - Writes JSON with indentation (default: 2 spaces)
   - Uses UTF-8 encoding with `ensure_ascii=False` (preserves German characters)

**Example usage**:
```python
design_topn = compute_design_and_topn(cluster_profiles, N=10)
save_design_topn_json(design_topn, "data/processed/cluster_design_topn.json")
```

---

### `save_cluster_summary_parquet()`

**Purpose**: Saves cluster summary DataFrame to Parquet file with validation.

**How it works**:
1. **Validates required columns**:
   - Checks for: `cluster_id`, `n_buildings`, `annual_heat_kwh_a`, `design_hour`, `design_load_kw`

2. **File operations**:
   - Creates parent directory if needed
   - Writes Parquet using PyArrow engine
   - Applies compression (default: `snappy`)
   - Writes statistics for efficient querying

**Example usage**:
```python
summary_df = create_cluster_summary(cluster_profiles, cluster_map, buildings_df, design_topn)
save_cluster_summary_parquet(summary_df, "data/processed/cluster_summary.parquet")
```

---

## Data Flow

### Complete Pipeline Flow

```
1. Raw Buildings + Raw Streets
   ↓
2. match_buildings_to_streets()
   → building_street_map (building_id → street_name)
   ↓
3. create_street_clusters()
   → building_cluster_map (building_id → cluster_id)
   → street_clusters (cluster metadata)
   ↓
4. aggregate_cluster_profiles()
   → cluster_profiles (cluster_id → Series(8760))
   ↓
5. compute_design_and_topn()
   → design_topn_dict (design hours, top-N hours)
   ↓
6. create_cluster_summary()
   → summary_df (one row per cluster)
   ↓
7. save_design_topn_json() + save_cluster_summary_parquet()
   → Files saved to disk
```

---

## Key Design Decisions

### 1. **Auto-detection of Cluster ID Column**
- Supports multiple column names: `cluster_id`, `street_id`, `street_cluster`
- Makes the module flexible for different data sources
- Reduces need for manual column renaming

### 2. **Zero Series for Empty Clusters**
- Instead of skipping clusters with no buildings, creates zero-filled Series
- Ensures all clusters have profiles (important for downstream processing)
- Issues warning for visibility

### 3. **Spatial Fallback Matching**
- Primary: Address-based matching (more accurate)
- Fallback: Spatial proximity (ensures coverage)
- Tracks match method for quality assessment

### 4. **Normalization for Fuzzy Matching**
- Handles German characters and abbreviations
- Enables matching despite spelling variations
- Critical for real-world data with inconsistencies

### 5. **Fallback Logic in create_cluster_summary()**
- If design_topn_dict missing cluster, computes from profile
- If buildings_df missing annual_heat_demand, sums from profile
- Makes function robust to incomplete data

---

## Usage Example

```python
from branitz_heat_decision.data.cluster import (
    aggregate_cluster_profiles,
    compute_design_and_topn,
    create_cluster_summary,
    save_design_topn_json,
    save_cluster_summary_parquet
)

# 1. Aggregate profiles
cluster_profiles = aggregate_cluster_profiles(
    hourly_profiles=hourly_profiles_df,  # 8760 × n_buildings
    cluster_map=building_cluster_map     # building_id → cluster_id
)

# 2. Compute design hours
design_topn = compute_design_and_topn(
    cluster_profiles=cluster_profiles,
    N=10,
    source_profiles="hourly_heat_profiles.parquet",
    version="v1"
)

# 3. Create summary
summary_df = create_cluster_summary(
    cluster_profiles=cluster_profiles,
    cluster_map=building_cluster_map,
    buildings_df=buildings_df,  # Can be GeoDataFrame or DataFrame
    design_topn_dict=design_topn
)

# 4. Save outputs
save_design_topn_json(design_topn, "data/processed/cluster_design_topn.json")
save_cluster_summary_parquet(summary_df, "data/processed/cluster_summary.parquet")
```

---

## Integration with Pipeline

The module is used in `src/scripts/00_prepare_data.py`:

1. **Street-based clustering** (if `--create-clusters` flag):
   ```python
   building_street_map = match_buildings_to_streets(buildings, streets)
   building_cluster_map, street_clusters = create_street_clusters(
       buildings, building_street_map, streets
   )
   ```

2. **Profile aggregation** (when processing hourly profiles):
   ```python
   cluster_profiles = aggregate_cluster_profiles(hourly_profiles, cluster_map)
   design_topn = compute_design_and_topn(cluster_profiles, N=10)
   ```

---

## Error Handling

- **Validation errors**: Raises `ValueError` for missing required columns or invalid data
- **Warnings**: Uses `warnings.warn()` for non-critical issues (e.g., missing buildings, length mismatches)
- **Fallbacks**: Provides fallback logic where possible (e.g., spatial matching, profile-based calculations)

---

## Performance Considerations

- **Vectorized operations**: Uses pandas vectorized operations for profile aggregation (fast)
- **Efficient lookups**: Creates dictionaries for O(1) building-to-cluster lookups
- **Parquet compression**: Uses Snappy compression for fast I/O with good compression ratio

---

## Summary

The `cluster.py` module is the **backbone of street-based clustering** in the Branitz Heat Decision system. It:

1. **Groups buildings by streets** using address matching with spatial fallback
2. **Aggregates hourly profiles** from building level to cluster level
3. **Computes design metrics** (peak loads, top-N hours) for network sizing
4. **Creates summary statistics** for reporting and analysis
5. **Saves outputs** in standardized formats (JSON, Parquet)

All functions are designed to be **robust**, **flexible**, and **well-documented**, making the module easy to use and maintain.

