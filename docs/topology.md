# District Heating Network Topology

**Date:** 2026-01-05  
**Purpose:** Comprehensive documentation of how the district heating network topology is created and structured.

---

## Overview

The district heating network uses a **trunk-spur topology** with a **dual-network structure** (separate supply and return pipes). The network is built in several stages, ensuring that:

1. The trunk only runs on streets where buildings are located
2. The supply trunk goes from plant through all buildings and ends at the last building
3. The return trunk collects all returns and follows the reverse path back to plant
4. Each building has exclusive service connections to the trunk

---

## Network Topology Creation Process

### Step 1: Street Filtering

**Function:** `_filter_streets_to_cluster()`

The system filters streets to only include those where buildings are located:

1. **Street Name Filtering (Primary):** If cluster has a street name (e.g., "Heinrich Zille Strasse"), filter streets by name first
2. **Bounding Box Filtering (Secondary):** If all streets have the same name, use them as-is. Otherwise, filter by building bounding box with buffer
3. **Graph Construction:** Build NetworkX graph from filtered street segments

**Result:** A street subgraph containing only streets with buildings.

```python
# Example: Filter streets to cluster
trunk_edges, street_subgraph = _filter_streets_to_cluster(
    streets, buildings, street_buffer_m=50.0
)
```

---

### Step 2: Building Attach Point Computation

**Function:** `_compute_building_attach_nodes()`

Each building is projected to its nearest street edge to determine where it will connect:

1. **Projection:** For each building, find the nearest street edge
2. **Attach Point:** Calculate the projection point on the edge (not just endpoints)
3. **Edge Association:** Store the edge and projection point for each building

**Result:** List of `(edge, attach_point)` tuples for each building.

```python
# Example: Compute attach points
attach_info = _compute_building_attach_nodes(buildings, street_subgraph)
# Returns: [(edge1, point1), (edge2, point2), ...]
```

**Key Feature:** Each building gets a unique attach point, even if multiple buildings are on the same edge.

---

### Step 3: Trunk Path Building

**Function:** `_build_trunk_through_all_buildings()`

The trunk is built as a path that visits all buildings in order along the street:

#### Case 1: All Buildings on One Edge

When all buildings attach to the same street edge:

1. **Order Buildings:** Sort building attach points by distance along the edge
2. **Connect Plant:** Find path from plant to the start of the edge (where first building is)
3. **Include Full Edge:** Add the entire edge (from start to end, through all buildings)
4. **Result:** Trunk path = `plant → edge_start → edge_end` (where last building is)

#### Case 2: Buildings on Multiple Edges

When buildings are distributed across multiple street edges:

1. **Group by Edge:** Group buildings by their attached edge
2. **Order Within Edge:** Sort attach points along each edge
3. **Greedy Path:** Build path using nearest-neighbor approach:
   - Start from plant
   - Visit nearest unvisited edge
   - Connect to that edge
   - Move to next nearest edge
   - Continue until all edges visited

**Result:** Trunk path that goes through all buildings in order.

```python
# Example: Build trunk through all buildings
trunk_path_edges = _build_trunk_through_all_buildings(
    street_subgraph, plant_node, attach_info
)
```

**Key Feature:** The trunk only uses edges that are on paths to buildings, ensuring no trunk on streets without buildings.

---

### Step 4: Path Sequence Creation

**Function:** `_create_path_from_trunk_edges()`

Extracts the node sequence from trunk edges to create an ordered path:

1. **Start from Plant:** Begin path at plant node
2. **Follow Edges:** Traverse edges in order, building node sequence
3. **Handle Disconnected:** If edges are disconnected, connect them to nearest path node

**Result:** 
- `trunk_path_nodes`: Ordered list of nodes from plant to last building
- `trunk_path_edges`: Ordered list of edges in the path

```python
# Example: Create path sequence
trunk_path_nodes, trunk_path_edges = _create_path_from_trunk_edges(
    street_subgraph, plant_node, trunk_path_edges
)
```

**Path Structure:**
- **Supply Trunk:** `plant → node1 → node2 → ... → last_building_node`
- **Return Trunk:** `last_building_node → ... → node2 → node1 → plant` (reverse)

---

### Step 5: Spur Assignment

**Function:** `_assign_exclusive_spur_points()`

Each building is assigned to an exclusive attachment point on the trunk:

1. **Find Nearest Trunk Edge:** For each building, find the nearest trunk edge
2. **Project to Edge:** Calculate projection point on the trunk edge
3. **Ensure Exclusivity:** Check if projection point is already used by another building
4. **Assign:** Store assignment with edge, attach point, and distance

**Result:** Dictionary mapping `building_id` to spur assignment information.

```python
# Example: Assign exclusive spur points
spur_assignments = _assign_exclusive_spur_points(
    buildings, trunk_path_edges, street_subgraph, max_spur_length_m=50.0
)
# Returns: {
#   'building_1': {
#       'edge': (node1, node2),
#       'attach_point': (x, y),
#       'distance_m': 15.3,
#       'exclusive': True
#   },
#   ...
# }
```

**Key Feature:** No two buildings share the same trunk attachment point.

---

### Step 6: Pandapipes Network Creation

**Function:** `_create_trunk_spur_pandapipes()`

Creates the complete dual-network structure in pandapipes:

#### 6.1 Distance-Based Pressure Initialization

Calculate distances from plant to all trunk nodes for pressure initialization:

```python
distances = _calculate_distances_from_plant(trunk_graph, plant_node)
# Initialize junction pressures based on distance
initial_pressure = base_pressure - (distance * pressure_drop_per_m)
```

#### 6.2 Trunk Junctions (Supply & Return)

For each trunk node, create **two junctions**:
- **Supply Junction:** `S_{node_coords}` (e.g., `S_456298.5_5733661.4`)
- **Return Junction:** `R_{node_coords}` (e.g., `R_456298.5_5733661.4`)

```python
# Create supply and return junctions for each trunk node
for node in trunk_nodes:
    supply_junc = pp.create_junction(net, ..., name=f"S_{node[0]}_{node[1]}")
    return_junc = pp.create_junction(net, ..., name=f"R_{node[0]}_{node[1]}")
```

#### 6.3 Trunk Pipes (Supply & Return)

For each trunk edge, create **two pipes**:
- **Supply Pipe:** `pipe_S_{from}_to_{to}` (e.g., `pipe_S_456298.5_5733661.4_to_456147.7_5733732.5`)
- **Return Pipe:** `pipe_R_{from}_to_{to}` (e.g., `pipe_R_456298.5_5733661.4_to_456147.7_5733732.5`)

```python
# Create supply and return pipes for each trunk edge
for edge in trunk_path_edges:
    from_node, to_node = edge
    # Supply pipe (forward direction)
    pp.create_pipe(net, from_junc=supply_junc_from, to_junc=supply_junc_to, 
                   name=f"pipe_S_{from_node[0]}_{from_node[1]}_to_{to_node[0]}_{to_node[1]}")
    # Return pipe (reverse direction)
    pp.create_pipe(net, from_junc=return_junc_to, to_junc=return_junc_from,
                   name=f"pipe_R_{from_node[0]}_{from_node[1]}_to_{to_node[0]}_{to_node[1]}")
```

**Flow Direction:**
- **Supply:** Plant → Building1 → Building2 → ... → Last Building
- **Return:** Last Building → ... → Building2 → Building1 → Plant

#### 6.4 Trunk Service Junctions

For each building, create **unique trunk service junctions**:
- **Supply Trunk Service Junction:** `S_T_{building_id}` (on supply trunk)
- **Return Trunk Service Junction:** `R_T_{building_id}` (on return trunk)

These are created at the building's attach point on the trunk edge.

```python
# Create trunk service junctions for each building
for building_id, assignment in spur_assignments.items():
    attach_point = assignment['attach_point']
    # Supply trunk service junction
    S_T_junc = pp.create_junction(net, ..., name=f"S_T_{building_id}")
    # Return trunk service junction
    R_T_junc = pp.create_junction(net, ..., name=f"R_T_{building_id}")
```

#### 6.5 Trunk Connection Pipes

Very short pipes (1.0m) connecting trunk service junctions to main trunk:

- **Supply Trunk Connection:** `trunk_conn_S_{building_id}` (connects `S_T_{building_id}` to nearest supply trunk junction)
- **Return Trunk Connection:** `trunk_conn_R_{building_id}` (connects `R_T_{building_id}` to nearest return trunk junction)

```python
# Create trunk connection pipes
trunk_conn_S = pp.create_pipe(net, from_junc=trunk_supply_junc, 
                              to_junc=S_T_junc, length_km=0.001,
                              name=f"trunk_conn_S_{building_id}")
trunk_conn_R = pp.create_pipe(net, from_junc=R_T_junc,
                              to_junc=trunk_return_junc, length_km=0.001,
                              name=f"trunk_conn_R_{building_id}")
```

#### 6.6 Building Junctions

For each building, create **two junctions**:
- **Building Supply Junction:** `S_B_{building_id}` (at building location)
- **Building Return Junction:** `R_B_{building_id}` (at building location)

```python
# Create building junctions
building_point = buildings.loc[building_id, 'geometry'].centroid
S_B_junc = pp.create_junction(net, ..., geodata=(building_point.x, building_point.y),
                               name=f"S_B_{building_id}")
R_B_junc = pp.create_junction(net, ..., geodata=(building_point.x, building_point.y),
                               name=f"R_B_{building_id}")
```

#### 6.7 Service Pipes

Pipes connecting buildings to trunk service junctions:

- **Service Supply Pipe:** `service_S_{building_id}` (connects `S_T_{building_id}` to `S_B_{building_id}`)
- **Service Return Pipe:** `service_R_{building_id}` (connects `R_B_{building_id}` to `R_T_{building_id}`)

```python
# Create service pipes
service_S = pp.create_pipe(net, from_junc=S_T_junc, to_junc=S_B_junc,
                           name=f"service_S_{building_id}")
service_R = pp.create_pipe(net, from_junc=R_B_junc, to_junc=R_T_junc,
                           name=f"service_R_{building_id}")
```

#### 6.8 Heat Exchangers

Heat exchangers connect building supply to return, modeling heat extraction:

- **Heat Exchanger:** `hx_{building_id}` (connects `S_B_{building_id}` to `R_B_{building_id}`)

```python
# Create heat exchanger
hx = pp.create_heat_exchanger(net, from_junc=S_B_junc, to_junc=R_B_junc,
                              name=f"hx_{building_id}", ...)
```

**Physical Model:** The heat exchanger extracts heat from the supply water, cooling it before it returns.

#### 6.9 Sink (Heat Demand)

Heat demand is placed at the **building supply junction**:

```python
# Create sink at building supply junction
pp.create_sink(net, junction=S_B_junc, mdot_kg_per_s=mdot,
               name=f"sink_{building_id}")
```

**Why at Supply Junction?** The sink models heat extraction, which occurs when hot supply water enters the building. The cooled water then flows back through the return.

#### 6.10 Plant Components

**Plant Supply Junction:** `plant_supply` (at plant location)  
**Plant Return Junction:** `plant_return` (at plant location)

**Circulation Pump:** `pump_plant` (connects `plant_return` to `plant_supply`)

```python
# Create plant junctions
plant_supply_junc = pp.create_junction(net, ..., name="plant_supply")
plant_return_junc = pp.create_junction(net, ..., name="plant_return")

# Create circulation pump
pump = pp.create_circ_pump_const_pressure(net, return_junction=plant_return_junc,
                                           flow_junction=plant_supply_junc,
                                           p_bar=pressure_bar, name="pump_plant")
```

**Source:** Heat source at plant supply junction

```python
# Create source
pp.create_source(net, junction=plant_supply_junc, mdot_kg_per_s=total_mdot)
```

#### 6.11 Plant Connection to Trunk

Ensure plant is connected to trunk:

```python
# Connect plant to nearest trunk supply junction
plant_to_trunk_supply = pp.create_pipe(net, from_junc=plant_supply_junc,
                                        to_junc=nearest_trunk_supply_junc,
                                        name="plant_to_trunk_supply")
# Connect nearest trunk return junction to plant
trunk_return_to_plant = pp.create_pipe(net, from_junc=nearest_trunk_return_junc,
                                        to_junc=plant_return_junc,
                                        name="trunk_return_to_plant")
```

---

## Complete Network Structure

### Physical Flow Path

```
Plant (Source)
  ↓ [plant_to_trunk_supply]
Trunk Supply Junction 1
  ↓ [pipe_S_...]
Trunk Supply Junction 2
  ↓ [pipe_S_...]
...
Trunk Supply Junction N (Last Building)
  ↓ [trunk_conn_S_building_1]
Trunk Service Supply Junction (S_T_building_1)
  ↓ [service_S_building_1]
Building Supply Junction (S_B_building_1)
  ↓ [sink_building_1] ← Heat Demand
  ↓ [hx_building_1] ← Heat Extraction
Building Return Junction (R_B_building_1)
  ↓ [service_R_building_1]
Trunk Service Return Junction (R_T_building_1)
  ↓ [trunk_conn_R_building_1]
Trunk Return Junction N
  ↓ [pipe_R_...] (reverse direction)
...
Trunk Return Junction 1
  ↓ [trunk_return_to_plant]
Plant Return Junction
  ↓ [pump_plant]
Plant Supply Junction (loop closed)
```

### Network Components Summary

| Component Type | Naming Convention | Count | Purpose |
|---------------|-------------------|-------|---------|
| **Trunk Supply Junctions** | `S_{coords}` | N (trunk nodes) | Supply distribution points |
| **Trunk Return Junctions** | `R_{coords}` | N (trunk nodes) | Return collection points |
| **Trunk Supply Pipes** | `pipe_S_{from}_to_{to}` | N-1 (trunk edges) | Supply distribution pipes |
| **Trunk Return Pipes** | `pipe_R_{from}_to_{to}` | N-1 (trunk edges) | Return collection pipes |
| **Trunk Service Supply Junctions** | `S_T_{building_id}` | M (buildings) | Service connection points on supply trunk |
| **Trunk Service Return Junctions** | `R_T_{building_id}` | M (buildings) | Service connection points on return trunk |
| **Trunk Connection Pipes** | `trunk_conn_S_{id}`, `trunk_conn_R_{id}` | 2M | Connect service junctions to trunk |
| **Building Supply Junctions** | `S_B_{building_id}` | M (buildings) | Building supply entry |
| **Building Return Junctions** | `R_B_{building_id}` | M (buildings) | Building return exit |
| **Service Supply Pipes** | `service_S_{building_id}` | M (buildings) | Connect trunk to building supply |
| **Service Return Pipes** | `service_R_{building_id}` | M (buildings) | Connect building return to trunk |
| **Heat Exchangers** | `hx_{building_id}` | M (buildings) | Model heat extraction |
| **Sinks** | `sink_{building_id}` | M (buildings) | Heat demand (at supply junction) |
| **Plant Junctions** | `plant_supply`, `plant_return` | 2 | Plant location |
| **Circulation Pump** | `pump_plant` | 1 | Maintains pressure and flow |
| **Source** | (default) | 1 | Heat source at plant |

**Where:**
- N = Number of trunk nodes
- M = Number of buildings

---

## Key Design Principles

### 1. Dual-Network Structure

- **Separate Supply and Return:** Supply and return pipes run parallel but are separate networks
- **Separate Junctions:** Each trunk node has both supply and return junctions
- **Reverse Flow:** Return pipes follow the reverse path of supply pipes

### 2. Exclusive Service Connections

- **No Sharing:** Each building has its own trunk service junction
- **Unique Attach Points:** No two buildings share the same trunk attachment point
- **Direct Connection:** Service pipes connect directly from trunk service junctions to buildings

### 3. Trunk-Only on Building Streets

- **Street Filtering:** Trunk only uses streets where buildings are located
- **Path-Based:** Trunk is built as union of paths from plant to building attach nodes
- **No Unnecessary Streets:** Trunk does not extend to streets without buildings

### 4. Ordered Path Through Buildings

- **Sequential Flow:** Supply trunk goes: plant → building1 → building2 → ... → last building
- **Reverse Return:** Return trunk goes: last building → ... → building2 → building1 → plant
- **End at Last Building:** Supply trunk ends at the last building's location

### 5. Correct Heat Demand Modeling

- **Sink at Supply:** Heat demand (sink) is placed at building supply junction
- **Heat Exchanger:** Models heat extraction from supply to return
- **Physical Accuracy:** Matches real-world district heating system behavior

---

## Visualization

The network is visualized with separate layers for:

1. **Supply Pipes (Trunk):** Thick solid blue lines (6-8px width)
   - Color: Dark blue (#2166ac) with velocity-based intensity
   - Flow direction: Plant → Buildings
   - Popup shows: Pipe ID, name, DN, length, velocity, pressure drop, temperature, flow direction

2. **Return Pipes (Trunk):** Thick solid red lines (6-8px width)
   - Color: Dark red (#d73027) with velocity-based intensity
   - Flow direction: Buildings → Plant
   - Popup shows: Pipe ID, name, DN, length, velocity, pressure drop, temperature, flow direction

3. **Service Supply Pipes:** Thin dashed light blue lines (3px width)
   - Color: Light blue (#74add1)
   - Style: Dashed (8px dash, 4px gap)
   - Flow direction: Trunk Service Junction → Building Supply Junction
   - Popup shows: Pipe ID, name, building ID, DN, length, velocity, connection details

4. **Service Return Pipes:** Thin dashed light orange lines (3px width)
   - Color: Light orange (#fdae61)
   - Style: Dashed (8px dash, 4px gap)
   - Flow direction: Building Return Junction → Trunk Service Junction
   - Popup shows: Pipe ID, name, building ID, DN, length, velocity, connection details

5. **Buildings:** Circle markers with size proportional to heat demand
   - Color: Red fill with black border
   - Size: Proportional to √(heat demand)
   - Popup shows: Building ID, type, peak demand, floor area, construction year

6. **Plant Marker:** Fire icon at plant location
   - Color: Red
   - Icon: Font Awesome fire icon
   - Popup shows: Plant location and cluster ID

**Interactive Map Features:**
- **Layer Control:** Toggle layers on/off via legend
- **Color Coding:** 
  - Blue = Supply (hot water)
  - Red = Return (cold water)
  - Thick lines = Trunk pipes
  - Thin dashed lines = Service pipes
- **Velocity Color Bar:** Shows velocity range (0.0 - 1.5 m/s) if network converged
- **Temperature Color Bar:** Shows temperature range if available
- **Hover Tooltips:** Quick information on mouse hover
- **Detailed Popups:** Click pipes/buildings for full information
- **Responsive Design:** Works on desktop and mobile devices

**Visualization Code Location:**
- `src/branitz_heat_decision/cha/qgis_export.py`
- Function: `create_interactive_map()`

---

## File Locations

- **Network Builder:** `src/branitz_heat_decision/cha/network_builder_trunk_spur.py`
- **Visualization:** `src/branitz_heat_decision/cha/qgis_export.py`
- **Configuration:** `src/branitz_heat_decision/cha/config.py`
- **Sizing:** `src/branitz_heat_decision/cha/sizing_catalog.py`

---

## References

- **Legacy Implementation:** `Legacy/network_builder.py`
- **Network Building Issues Analysis:** `docs/network_building_issues_analysis.md`
- **Trunk Topology Issues:** `docs/trunk_topology_issues_analysis.md`

