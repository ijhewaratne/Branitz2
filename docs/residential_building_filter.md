# Residential Building Filter

## Overview

The system now filters buildings to **only include residential buildings with heat demand**. This ensures that:

1. Only residential buildings (e.g., houses, apartments) are considered for district heating network planning
2. Buildings without heat demand are excluded (e.g., unheated garages, storage buildings)
3. Non-residential buildings (offices, schools, retail) are excluded from the analysis

## Implementation

### Filter Function

The `filter_residential_buildings_with_heat_demand()` function in `src/branitz_heat_decision/data/loader.py` filters buildings based on:

1. **Residential Type**:
   - Checks `use_type` column for values containing `'residential'`, `'wohn'` (German for "living/residential")
   - Accepts `'residential_sfh'` (single-family house) and `'residential_mfh'` (multi-family house)
   - If `use_type` not available, checks `building_function` column for similar patterns

2. **Heat Demand**:
   - Filters by `annual_heat_demand_kwh_a` column
   - Only includes buildings with `annual_heat_demand_kwh_a > min_heat_demand_kwh_a` (default: 0.0)

### Usage in Pipeline

#### 1. Data Preparation (`00_prepare_data.py`)

When creating street-based clusters:

```python
from branitz_heat_decision.data.loader import filter_residential_buildings_with_heat_demand

# Load buildings
buildings = gpd.read_file(buildings_path)

# Filter to residential with heat demand
buildings = filter_residential_buildings_with_heat_demand(buildings, min_heat_demand_kwh_a=0.0)

# Then create clusters (only residential buildings will be clustered)
building_street_map = match_buildings_to_streets(buildings, streets)
```

**Result**: Only residential buildings with heat demand are included in:
- `building_cluster_map.parquet`
- `street_clusters.parquet`

#### 2. CHA Pipeline (`01_run_cha.py`)

When loading cluster data:

```python
# Load buildings for cluster
buildings = load_buildings_geojson(BUILDINGS_PATH)
buildings = buildings[buildings['building_id'].isin(cluster_buildings)]

# Filter to residential with heat demand
buildings = filter_residential_buildings_with_heat_demand(buildings, min_heat_demand_kwh_a=0.0)
```

**Result**: Only residential buildings with heat demand are included in the district heating network.

## Filter Logic

### Residential Type Detection

The filter checks for residential buildings using multiple methods:

1. **Primary**: `use_type` column
   - Contains `'residential'` (case-insensitive)
   - Contains `'wohn'` (German, case-insensitive)
   - Equals `'residential_sfh'` or `'residential_mfh'`

2. **Fallback**: `building_function` column
   - Contains `'wohn'` (German)
   - Contains `'residential'`
   - Contains `'mfh'` or `'mehrfam'` (German for multi-family house)

### Heat Demand Filter

- Requires `annual_heat_demand_kwh_a` column
- Filters out buildings with `annual_heat_demand_kwh_a <= min_heat_demand_kwh_a`
- Default threshold: `0.0` (excludes buildings with zero or negative heat demand)

## Example

```python
import geopandas as gpd
from branitz_heat_decision.data.loader import filter_residential_buildings_with_heat_demand

# Load all buildings
buildings = gpd.read_file("data/raw/hausumringe_mit_adressenV3.geojson")

# Before filtering
print(f"Total buildings: {len(buildings)}")
# Output: Total buildings: 1000

# Filter to residential with heat demand
residential_buildings = filter_residential_buildings_with_heat_demand(
    buildings, 
    min_heat_demand_kwh_a=0.0
)

# After filtering
print(f"Residential buildings with heat demand: {len(residential_buildings)}")
# Output: Residential buildings with heat demand: 750

# Check excluded buildings
excluded = ~buildings['building_id'].isin(residential_buildings['building_id'])
print(f"Excluded: {excluded.sum()} buildings")
# Output: Excluded: 250 buildings (non-residential or zero demand)
```

## Logging

The filter logs:
- Starting building count
- Count after residential filter
- Count after heat demand filter
- Final filtered count
- Number of excluded buildings

Example log output:
```
INFO: Filtering buildings: Starting with 1000 buildings
INFO: After residential filter: 850 buildings
INFO: After heat demand filter (>0.0 kWh/a): 750 buildings (removed 100)
INFO: Final filtered count: 750 residential buildings with heat demand
INFO: Removed 250 non-residential or zero-demand buildings
```

## Integration Points

The filter is applied at:

1. **Cluster Creation** (`00_prepare_data.py`):
   - Before matching buildings to streets
   - Ensures only residential buildings are clustered

2. **CHA Pipeline** (`01_run_cha.py`):
   - After loading cluster buildings
   - Ensures only residential buildings are included in network analysis

## Configuration

To change the minimum heat demand threshold:

```python
# In your script
buildings = filter_residential_buildings_with_heat_demand(
    buildings, 
    min_heat_demand_kwh_a=1000.0  # Only buildings with >1000 kWh/a
)
```

## Notes

- The filter is **non-destructive**: Returns a copy of the filtered GeoDataFrame
- Missing columns are handled gracefully with warnings
- If `use_type` or `building_function` columns are missing, the filter may be less effective
- Buildings without `annual_heat_demand_kwh_a` are excluded if the column is required

