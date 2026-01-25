# Legacy Implementation Analysis

**Date:** 2026-01-05  
**Purpose:** Analyze legacy files to identify correct implementation patterns and differences from current implementation.

---

## Files Analyzed

1. **network_builder.py** - Main network builder with dual-network structure
2. **spur_expansion.py** - Spur expansion algorithm for reducing service lengths
3. **dh_network_workflow.py** - Complete workflow automation
4. **config.py** - Configuration with extensive options
5. **sizing_utils.py** - Pipe sizing utilities
6. **geometry_utils.py** - Geometry and street graph utilities
7. **dh_map.py** - Interactive map generation
8. **interactive_pipeline.py** - Interactive CLI workflow
9. **run_cha_map.py** / **generate_map.py** - Map generation scripts

---

## Key Implementation Patterns

### 1. Dual-Network Structure (network_builder.py)

**Correct Implementation:**
- **Separate Supply/Return Junctions**: Each trunk node has both supply (`S_{x}_{y}`) and return (`R_{x}_{y}`) junctions
- **Distance-Based Pressure Initialization**: Pressures initialized based on distance from plant
- **Trunk Service Junctions**: Unique junctions per building (`S_T_{building_id}`, `R_T_{building_id}`)
- **Building Junctions**: Separate supply (`S_B_{building_id}`) and return (`R_B_{building_id}`) junctions
- **Heat Exchangers**: Connect building supply to return (`hx_{building_id}`)
- **Service Pipes**: Separate supply (`service_S_{building_id}`) and return (`service_R_{building_id}`) pipes
- **Trunk Connection Pipes**: Short pipes connecting trunk service junctions to main trunk (`trunk_conn_S_{building_id}`, `trunk_conn_R_{building_id}`)

**Key Code Sections:**
- Lines 802-896: Trunk junction creation with distance-based pressure
- Lines 897-979: Trunk pipe creation (supply and return)
- Lines 984-1160: Building service connections with unique trunk service junctions
- Lines 1162-1194: Plant source and circulation pump

### 2. Sink Placement - ⚠️ IMPORTANT DISCREPANCY

**Legacy Code (network_builder.py, line 1153-1160):**
```python
# Add sink (heat demand) at building return junction
# Sink represents heat extraction (negative flow in return pipe)
pp.create_sink(
    net,
    junction=junc_b_r,  # Building RETURN junction
    mdot_kg_per_s=0.0,
    name=f"sink_{building_id}"
)
```

**Note:** The legacy code places the sink at the **building return junction**, but:
- The legacy documentation (NETWORK_BUILDING_DETAILED_EXPLANATION.md) says sink should be at **building supply junction**
- Our current fix placed it at **building supply junction** (per user request and legacy docs)
- This discrepancy suggests the legacy code may have an error, or there's a different modeling approach

**Recommendation:** Verify with user/physics expert - the documentation appears more correct than the code implementation.

### 3. Pressure Initialization

**Distance-Based Calculation (lines 849-863):**
```python
distance_m = node_distances.get(node, 0.0)
pressure_drop_per_m = 0.001  # bar/m
pressure_drop = distance_m * pressure_drop_per_m
supply_pressure = max(1.0, config.system_pressure_bar - pressure_drop)
return_pressure = max(0.9, supply_pressure - 0.1)  # 0.1 bar lower for return
```

**Key Points:**
- Supply pressure decreases with distance from plant
- Return pressure is 0.1 bar lower than supply at same location
- Minimum pressure of 1.0 bar for supply, 0.9 bar for return
- Used for both trunk nodes and trunk service junctions

### 4. Trunk Service Junctions

**Implementation (lines 1016-1065):**
- Each building gets unique trunk service junctions: `S_T_{building_id}`, `R_T_{building_id}`
- Located at the `attach_node` coordinates
- Connected to main trunk with short pipes (`trunk_conn_S_`, `trunk_conn_R_`)
- Same pressure as the trunk node they attach to

**Why This Matters:**
- Prevents multiple buildings from sharing the same junction
- Ensures proper hydraulic modeling
- Allows individual sizing and pressure tracking

### 5. Service Connection Flow

**Correct Flow Path:**
1. **Supply**: Main Trunk Supply → Trunk Service Junction (S_T) → Service Supply Pipe → Building Supply Junction (S_B) → Heat Exchanger → Building Return Junction (R_B)
2. **Return**: Building Return Junction (R_B) → Service Return Pipe → Trunk Service Junction (R_T) → Main Trunk Return

**Pipes Created:**
- `trunk_conn_S_{building_id}`: Main trunk supply → Trunk service supply
- `service_S_{building_id}`: Trunk service supply → Building supply
- `hx_{building_id}`: Building supply → Building return (heat exchanger)
- `service_R_{building_id}`: Building return → Trunk service return
- `trunk_conn_R_{building_id}`: Trunk service return → Main trunk return

### 6. Plant Connection

**Implementation (lines 1162-1194):**
- Source (`source_plant`) at plant supply junction
- Circulation pump (`pump_plant`) connecting plant return → plant supply
- Uses `pp.create_circ_pump_const_pressure` (correct API)
- Pump parameters: `p_flow_bar`, `plift_bar`

### 7. Spur Expansion (spur_expansion.py)

**Algorithm Overview:**
1. Build base trunk (strict street mode)
2. Estimate service lengths
3. Identify buildings with long service connections (> threshold)
4. Find candidate spur edges
5. Evaluate candidates against constraints:
   - Spatial buffer (within X m of selected street)
   - Depth from trunk (≤ max_depth_edges)
   - Buildings served (≥ min_buildings)
   - Total spur length (≤ max_total_length_m)
   - Service reduction (≥ reduction_threshold_pct)
6. Expand trunk with approved spurs
7. Re-snap buildings to expanded trunk

**Configuration (config.py):**
- `service_length_promote_threshold_m`: 30.0 m (default)
- `spur_max_depth_edges`: 2 (default)
- `spur_min_buildings`: 2 (default)
- `spur_max_total_length_m`: 100.0 m (default)
- `spur_reduction_threshold_pct`: 30.0% (default)
- `spur_search_buffer_m`: 120.0 m (default)

### 8. Interactive Map Generation (dh_map.py)

**Features:**
- Separate layers for supply and return pipes
- Color coding: supply (red `#d62728`), return (blue `#1f77b4`)
- Service pipes in green (`#2ca02c`)
- Optional temperature gradients
- Optional street background

**Key Implementation:**
- Reads pipe names to identify supply/return: `pipe_S_`, `pipe_R_`, `service_S_`, `service_R_`
- Uses `junction_geodata` for coordinates
- Handles missing results gracefully

---

## Comparison with Current Implementation

### ✅ Correctly Implemented in Current Code

1. Dual-network structure (supply + return junctions/pipes)
2. Distance-based pressure initialization
3. Unique trunk service junctions per building
4. Heat exchangers between building supply/return
5. Proper pump placement (plant return → plant supply)
6. Plant connectivity
7. Separate supply/return visualization in maps

### ⚠️ Potential Issues

1. **Sink Placement**: 
   - Legacy code: Building return junction
   - Legacy docs: Building supply junction
   - Current fix: Building supply junction (matches docs, not legacy code)
   - **Status**: Need verification from user/physics expert

2. **Service Pipe Naming**: 
   - Legacy: `service_S_{building_id}`, `service_R_{building_id}`
   - Current: Same ✅

3. **Trunk Pipe Naming**: 
   - Legacy: `pipe_S_{from}_{to}`, `pipe_R_{to}_{from}`
   - Current: Same ✅

4. **Heat Exchanger Naming**: 
   - Legacy: `hx_{building_id}`
   - Current: Same ✅

---

## Recommendations

### 1. Verify Sink Placement

The discrepancy between legacy code (return junction) and legacy docs (supply junction) needs resolution. Our current implementation matches the documentation, which is likely correct based on district heating physics.

### 2. Review Spur Expansion

The legacy implementation includes sophisticated spur expansion logic that might be valuable for improving service connection lengths. Consider integrating if not already present.

### 3. Workflow Integration

The legacy `dh_network_workflow.py` provides a complete workflow automation that could be valuable for production use:
- Automated health checking
- Network stabilization
- Iterative optimization

### 4. Configuration Options

The legacy `config.py` has extensive configuration options that might be useful:
- Spur expansion parameters
- Stabilization options
- Solver configuration
- Validation options

---

## Files Structure

```
Legacy/
├── network_builder.py          # Main network builder (dual-network)
├── spur_expansion.py           # Spur expansion algorithm
├── dh_network_workflow.py      # Complete workflow automation
├── config.py                   # Configuration with extensive options
├── sizing_utils.py             # Pipe sizing utilities
├── geometry_utils.py           # Geometry and street graph utilities
├── dh_map.py                   # Interactive map generation
├── interactive_pipeline.py     # Interactive CLI workflow
├── run_cha_map.py             # Map generation script
├── generate_map.py            # Map generation script
└── NETWORK_BUILDING_DETAILED_EXPLANATION.md  # Detailed documentation
```

---

## Summary

The legacy implementation provides a robust, well-documented dual-network structure that matches our current fixes. The main discrepancy is sink placement (code vs. documentation), which we've resolved by following the documentation and user guidance.

Key takeaways:
- ✅ Dual-network structure is correctly implemented in both legacy and current code
- ✅ Unique trunk service junctions are critical for proper modeling
- ✅ Distance-based pressure initialization improves convergence
- ⚠️ Sink placement discrepancy resolved in favor of documentation/user guidance
- 💡 Spur expansion and workflow automation could be valuable additions

