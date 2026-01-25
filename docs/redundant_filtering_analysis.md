# Redundant Filtering Analysis & Resolution Plan

## Current Situation

### Problem: Filtering Happens Twice

**Data Preparation (`00_prepare_data.py`):**
```
Raw buildings (GeoJSON) 
  → Filter (residential + heat demand) 
  → Create clusters
  → Save: building_cluster_map.parquet ✅
  → ❌ Does NOT save filtered buildings
```

**CHA Pipeline (`01_run_cha.py`):**
```
Load from BUILDINGS_PATH (processed/buildings.parquet)
  → If not exists, load raw GeoJSON
  → Filter AGAIN (residential + heat demand) 
  → Use for network building
```

### Issues Identified

1. **Redundant filtering**: Same filter applied twice
2. **Missing processed file**: Filtered buildings not saved during data preparation
3. **Inefficiency**: Loading and filtering raw data again in CHA pipeline
4. **Inconsistency risk**: If filter logic changes, results may differ

## Current Data Flow

```
┌─────────────────────────────────────────────────────────────┐
│ 00_prepare_data.py                                          │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ Load raw GeoJSON                                        │ │
│ │ Filter → residential + heat demand                      │ │
│ │ Create clusters                                         │ │
│ │ Save: building_cluster_map.parquet                      │ │
│ │ ❌ Filtered buildings NOT saved                         │ │
│ └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ 01_run_cha.py                                               │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ Load BUILDINGS_PATH                                     │ │
│ │ (May not exist → load raw GeoJSON)                      │ │
│ │ Filter AGAIN → residential + heat demand                │ │ ⚠️ REDUNDANT
│ │ Build network                                            │ │
│ └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

## Resolution Plan

### Solution: Single Source of Truth for Filtered Buildings

**Principle**: Filter once, save the result, reuse everywhere.

### Proposed Changes

#### Phase 1: Save Filtered Buildings During Data Preparation

**File: `src/scripts/00_prepare_data.py`**

1. After filtering, save filtered buildings to `BUILDINGS_PATH`:
   ```python
   # After filtering in create_street_based_clusters()
   filtered_buildings.to_parquet(BUILDINGS_PATH, index=False)
   buildings.attrs['filtered'] = True
   buildings.attrs['filter_criteria'] = 'residential_with_heat_demand'
   ```

2. Ensure metadata tracks filtering status:
   - `filtered: bool` - Whether buildings have been filtered
   - `filter_criteria: str` - What filter was applied
   - `filter_date: str` - When filtering was done

#### Phase 2: Smart Loading in CHA Pipeline

**File: `src/scripts/01_run_cha.py`**

1. Create a smart loader that:
   - Prefers processed filtered buildings file
   - Checks metadata to see if already filtered
   - Only filters if necessary

2. Implementation:
   ```python
   def load_buildings_smart(cluster_buildings: List[str]) -> gpd.GeoDataFrame:
       """Load buildings with automatic filtering if needed."""
       if BUILDINGS_PATH.exists():
           buildings = gpd.read_parquet(BUILDINGS_PATH)
           # Check if already filtered
           if buildings.attrs.get('filtered', False):
               logger.info("Using pre-filtered buildings from processed file")
               return buildings[buildings['building_id'].isin(cluster_buildings)]
           else:
               logger.info("Buildings file exists but not filtered, filtering now...")
               buildings = filter_residential_buildings_with_heat_demand(buildings)
               buildings.attrs['filtered'] = True
               # Optionally save back
               buildings.to_parquet(BUILDINGS_PATH, index=False)
       else:
           # Fallback: load raw and filter
           buildings = load_buildings_geojson(RAW_BUILDINGS_PATH)
           buildings = filter_residential_buildings_with_heat_demand(buildings)
           # Save for future use
           buildings.to_parquet(BUILDINGS_PATH, index=False)
           buildings.attrs['filtered'] = True
       
       return buildings[buildings['building_id'].isin(cluster_buildings)]
   ```

#### Phase 3: Centralize Building Loading Logic

**File: `src/branitz_heat_decision/data/loader.py`**

Add a new function that encapsulates the smart loading:

```python
def load_processed_buildings(
    cluster_buildings: Optional[List[str]] = None,
    force_reload: bool = False
) -> gpd.GeoDataFrame:
    """
    Load processed buildings, filtering if needed.
    
    Args:
        cluster_buildings: Optional list of building IDs to filter to
        force_reload: If True, reload from raw even if processed exists
    
    Returns:
        GeoDataFrame of filtered buildings (residential with heat demand)
    """
    from branitz_heat_decision.config import BUILDINGS_PATH, DATA_RAW
    
    # Check if processed file exists and is up-to-date
    if not force_reload and BUILDINGS_PATH.exists():
        buildings = gpd.read_parquet(BUILDINGS_PATH)
        
        # Check metadata
        if buildings.attrs.get('filtered', False):
            logger.info(f"Loaded {len(buildings)} pre-filtered buildings from {BUILDINGS_PATH}")
            if cluster_buildings:
                buildings = buildings[buildings['building_id'].isin(cluster_buildings)]
            return buildings
        else:
            logger.info("Processed file exists but not filtered, filtering now...")
    
    # Need to filter: load from raw
    raw_path = DATA_RAW / "hausumringe_mit_adressenV3.geojson"
    if not raw_path.exists():
        raise FileNotFoundError(f"Raw buildings file not found: {raw_path}")
    
    logger.info(f"Loading and filtering buildings from {raw_path}")
    buildings = load_buildings_geojson(raw_path)
    buildings = filter_residential_buildings_with_heat_demand(buildings)
    
    # Add metadata
    buildings.attrs['filtered'] = True
    buildings.attrs['filter_criteria'] = 'residential_with_heat_demand_min_0_kwh_a'
    buildings.attrs['filter_date'] = pd.Timestamp.now().isoformat()
    
    # Save processed version
    BUILDINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    buildings.to_parquet(BUILDINGS_PATH, index=False)
    logger.info(f"Saved filtered buildings to {BUILDINGS_PATH}")
    
    # Filter to cluster if requested
    if cluster_buildings:
        buildings = buildings[buildings['building_id'].isin(cluster_buildings)]
    
    return buildings
```

## Implementation Steps

### Step 1: Update Data Preparation (`00_prepare_data.py`)

1. After filtering in `create_street_based_clusters()`:
   - Save filtered buildings to `BUILDINGS_PATH`
   - Add metadata attributes
   - Log the save operation

### Step 2: Update CHA Pipeline (`01_run_cha.py`)

1. Replace direct building loading with `load_processed_buildings()`
2. Remove redundant filtering logic
3. Let the loader handle filtering automatically

### Step 3: Add Smart Loader (`loader.py`)

1. Implement `load_processed_buildings()` function
2. Handle metadata checking
3. Save processed buildings when filtering is done

### Step 4: Update Other Scripts

1. Check other scripts that load buildings (e.g., `01_run_cha_trunk_spur.py`)
2. Update them to use `load_processed_buildings()`

## Benefits

1. ✅ **Single source of truth**: Filtered buildings stored once
2. ✅ **No redundancy**: Filtering happens once during data preparation
3. ✅ **Faster CHA pipeline**: Just loads pre-filtered data
4. ✅ **Consistency**: Same filtered dataset used everywhere
5. ✅ **Metadata tracking**: Know when/how filtering was done
6. ✅ **Fallback support**: Still works if processed file missing

## Data Flow After Changes

```
┌─────────────────────────────────────────────────────────────┐
│ 00_prepare_data.py                                          │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ Load raw GeoJSON                                        │ │
│ │ Filter → residential + heat demand                      │ │
│ │ Save: BUILDINGS_PATH (processed/buildings.parquet) ✅   │ │
│ │ Create clusters                                         │ │
│ │ Save: building_cluster_map.parquet                      │ │
│ └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                           ↓
                    Saved filtered buildings
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ 01_run_cha.py                                               │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ load_processed_buildings()                              │ │
│ │   → Check BUILDINGS_PATH                                │ │
│ │   → Check metadata (already filtered?)                  │ │
│ │   → Load pre-filtered buildings ✅                      │ │
│ │   → Filter to cluster                                   │ │
│ │ Build network                                            │ │
│ └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

## Migration Path

1. **Phase 1** (Backward compatible):
   - Add `load_processed_buildings()` function
   - Keep old logic as fallback
   - Update `00_prepare_data.py` to save filtered buildings

2. **Phase 2** (Update consumers):
   - Update `01_run_cha.py` to use new loader
   - Remove redundant filtering
   - Test thoroughly

3. **Phase 3** (Cleanup):
   - Remove old direct loading code if no longer needed
   - Update documentation

## Testing Strategy

1. **Test data preparation**:
   - Run `00_prepare_data.py --create-clusters`
   - Verify `BUILDINGS_PATH` exists
   - Verify metadata attributes present
   - Verify only residential buildings with heat demand

2. **Test CHA pipeline**:
   - Run `01_run_cha.py` with cluster ID
   - Verify uses pre-filtered buildings
   - Verify no redundant filtering logs
   - Verify network built correctly

3. **Test edge cases**:
   - Missing processed file (should filter and save)
   - Processed file without metadata (should filter and update)
   - Force reload flag (should reload from raw)

## Files to Modify

1. ✅ `src/scripts/00_prepare_data.py` - Save filtered buildings
2. ✅ `src/branitz_heat_decision/data/loader.py` - Add smart loader
3. ✅ `src/scripts/01_run_cha.py` - Use smart loader
4. ✅ `src/branitz_heat_decision/config.py` - No changes needed
5. ⚠️ Other scripts using buildings (if any) - Update to use smart loader

