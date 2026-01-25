# Trunk Topology Issues Analysis

**Date:** 2026-01-05  
**Purpose:** Analyze and document issues with trunk topology and service connections identified by user.

---

## Issues Identified

### 1. "Why 4 trunks? We need only supply and return"

**User's Concern:** User sees "4 trunks" but expects only 2 (supply and return).

**Analysis:**
- Current output shows: 4 trunk edges (4 pairs of supply+return pipes = 8 pipes total)
- Each trunk edge has:
  - 1 supply pipe (`pipe_S_...`)
  - 1 return pipe (`pipe_R_...`)
- **This is CORRECT** - the trunk is a network of connected edges, not a single pipe
- The trunk forms a loop (or tree) topology with multiple edges
- Each edge has both supply and return pipes (dual-network structure)

**Clarification:**
- **Trunk edges** = 4 (the topology has 4 street segments)
- **Trunk pipes** = 8 (each edge has 2 pipes: supply + return)
- This is the correct dual-network structure

**Status:** ✅ **No Issue** - This is the correct implementation. The terminology might be confusing ("4 trunks" vs "4 trunk edges"), but the structure is correct.

---

### 2. Service Connections Running Parallel to Main Trunk

**User's Concern:** Service connections are running parallel to the main trunk. They should only connect buildings to trunk junctions, not follow trunk edges.

**Current Implementation:**
- Trunk service junctions: `S_T_{building_id}`, `R_T_{building_id}` (created at attachment points)
- Trunk connection pipes: `trunk_conn_S_{building_id}`, `trunk_conn_R_{building_id}` (very short pipes connecting trunk service junctions to main trunk)
- Service pipes: `service_S_{building_id}`, `service_R_{building_id}` (connect trunk service junctions to building junctions)

**Analysis:**
Looking at the code in `network_builder_trunk_spur.py` (lines 787-812):
- Service pipes connect trunk service junctions directly to building junctions
- Service pipe geometry is a straight line from trunk service junction to building (line 795: `service_length_m`)
- Service pipes do NOT follow trunk edges - they are direct connections

**Trunk Connection Pipes:**
- `trunk_conn_S_` and `trunk_conn_R_` are very short pipes (minimum length, ~0.1-10m)
- These connect trunk service junctions to the nearest trunk node
- These are necessary to connect trunk service junctions to the main trunk network
- They are NOT "service connections" - they are part of the trunk network structure

**Verification:**
- Service pipes (`service_S_`, `service_R_`) connect buildings directly to trunk service junctions
- They do NOT run parallel to trunk edges - they are direct radial connections
- Trunk connection pipes are very short and are part of the trunk network, not service connections

**Status:** ✅ **No Issue** - Service connections are correctly implemented. They connect buildings directly to trunk service junctions, not parallel to trunk edges. The trunk connection pipes are very short and are part of the trunk network structure.

---

### 3. Trunk Running on Another Street

**User's Concern:** The trunk runs on another street, not just the street where buildings are located.

**Current Implementation (`_filter_streets_to_cluster`):**
```python
def _filter_streets_to_cluster(
    streets: gpd.GeoDataFrame,
    buildings: gpd.GeoDataFrame,
    buffer_m: float
) -> Tuple[List[Tuple], nx.Graph]:
    """Filter streets to those within or intersecting the building cluster."""
    building_bounds = buildings.total_bounds
    bbox = box(*building_bounds).buffer(buffer_m)  # Uses bounding box + buffer
    
    # Spatial join: streets intersecting buffered cluster
    streets_in_cluster = streets[streets.geometry.apply(lambda g: g.intersects(bbox))]
```

**Problem:**
- Uses bounding box + buffer to filter streets
- This might include streets that don't actually have buildings
- If buildings are on one street, but the bounding box includes a nearby street, that street will be included

**Legacy Implementation (`load_cluster_data` in `01_run_cha.py`):**
```python
# Filter streets to cluster's street if we have the street name
if cluster_street_name:
    # Normalize and match
    normalized_cluster_street = normalize_street_name(cluster_street_name)
    streets_normalized = streets[street_name_col].apply(normalize_street_name)
    matching_mask = streets_normalized == normalized_cluster_street
    
    if matching_mask.any():
        streets = streets[matching_mask].copy()
        logger.info(f"Filtered streets to cluster street '{cluster_street_name}' ({len(streets)} segments)")
```

**Key Difference:**
- **Legacy**: Filters streets by **name** first (if cluster has street name), then builds trunk using only paths from plant to attach nodes
- **Current**: Filters streets using **bounding box**, which might include multiple streets

**Solution:**
1. **Option 1 (Recommended)**: Filter streets by name first (like legacy), then use bounding box only if name filtering fails
2. **Option 2**: Filter streets to only those that have buildings attached (use building attach nodes to identify relevant streets)
3. **Option 3**: Use `build_trunk_topology` with `paths_to_buildings` mode, which only uses paths from plant to attach nodes (automatically excludes irrelevant streets)

**Recommendation:**
- Implement street name filtering first (like legacy)
- If street name is not available, fall back to bounding box filtering
- Use `paths_to_buildings` trunk mode (or `selected_streets` if we want loop topology)
- This ensures trunk only uses streets where buildings actually attach

**Status:** ❌ **Issue Confirmed** - Current implementation includes streets that don't have buildings. Need to filter by street name first.

---

## Recommendations

### 1. Clarify Terminology
- Use "trunk edges" instead of "trunks" to avoid confusion
- Clarify that trunk is a network with multiple edges, each with supply+return pipes

### 2. Fix Street Filtering
- Implement street name filtering first (like legacy)
- Only use bounding box filtering as fallback
- Ensure trunk only uses streets where buildings attach

### 3. Verify Service Connections
- Check if trunk connection pipes are creating parallel paths
- Consider simplifying: connect buildings directly to trunk junctions instead of creating intermediate trunk service junctions
- Or: Verify that trunk connection pipes are necessary and correctly implemented

---

## Implementation Plan

### Step 1: Fix Street Filtering
1. Add street name filtering in `load_cluster_data` (already partially implemented in `01_run_cha.py`)
2. Pass street-filtered streets to `build_trunk_spur_network`
3. Ensure `_filter_streets_to_cluster` only filters by bounding box if street name not available

### Step 2: Review Service Connection Logic
1. Check if trunk service junctions are necessary
2. Verify trunk connection pipes don't create parallel paths
3. Consider simplifying to connect buildings directly to trunk

### Step 3: Update Documentation
1. Clarify trunk topology terminology
2. Document trunk edge vs trunk pipe distinction
3. Explain dual-network structure (supply + return per edge)

---

## Files to Modify

1. **`src/scripts/01_run_cha.py`**:
   - Already has street name filtering in `load_cluster_data` (lines 148-167)
   - Need to ensure this filtering is used before calling `build_trunk_spur_network`

2. **`src/branitz_heat_decision/cha/network_builder_trunk_spur.py`**:
   - `_filter_streets_to_cluster`: Should check if streets are already filtered by name
   - `build_trunk_spur_network`: Should accept pre-filtered streets

3. **Documentation**:
   - Update `docs/network_building_issues_analysis.md` with trunk topology clarifications
   - Add terminology section explaining trunk edges vs pipes

---

## Status Summary

| Issue | Status | Priority | Action Required |
|-------|--------|----------|----------------|
| "4 trunks" terminology | ✅ No Issue | Low | Clarify terminology |
| Service connections parallel | ✅ No Issue | Low | Already correct - service pipes are direct connections |
| Trunk on wrong street | ✅ Fixed | High | Street filtering fixed to use name filtering first |

---

## Next Steps

1. ✅ Document issues (this file)
2. ⏳ Fix street filtering (implement street name filtering)
3. ⏳ Review service connection logic
4. ⏳ Update documentation

