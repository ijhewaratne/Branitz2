# Network Building (CHA) - Detailed Explanation

## Overview

The **Network Building** step creates the complete district heating network structure. It consists of three main sub-processes:

1. **Build Trunk Network** - Create main distribution pipes
2. **Attach Buildings to Trunk** - Connect buildings to the trunk network
3. **Create Pandapipes Network Structure** - Convert to pandapipes format

---

## 1. Build Trunk Network (Main Distribution Pipes)

### Purpose

The trunk network is the **backbone** of the district heating system - the main distribution pipes that carry hot water from the plant to all buildings.

### Process Flow

```
Street Graph (NetworkX)
    ↓
Filter Streets (spatial + name/ID)
    ↓
Build Street Graph
    ↓
Find Plant Location
    ↓
Build Trunk Topology (Dijkstra's Algorithm)
    ↓
Trunk Edges (List of (u, v) tuples)
```

### Step-by-Step Process

#### Step 1.1: Build Street Graph

**Input:**
- `streets_geom` - GeoDataFrame with street segments
- Filtered to cluster spatial extent (with buffer)
- Optionally filtered by street name/ID

**Process:**
```python
def build_street_graph(streets_geom: gpd.GeoDataFrame) -> nx.Graph:
    G = nx.Graph()
    
    for idx, street in streets_geom.iterrows():
        coords = list(street.geometry.coords)
        
        # Add nodes and edges for each segment
        for i in range(len(coords) - 1):
            start_node = coords[i]  # (x, y) tuple
            end_node = coords[i + 1]
            
            # Calculate length
            length_m = Point(start_node).distance(Point(end_node))
            
            # Add edge with attributes
            G.add_edge(
                start_node,
                end_node,
                length_m=length_m,
                geometry=LineString([start_node, end_node]),
                street_name=street.get('name', ''),
                highway_type=street.get('highway', 'residential')
            )
    
    return G
```

**Output:**
- NetworkX graph with:
  - **Nodes**: Street intersection points `(x, y)`
  - **Edges**: Street segments with `length_m`, `geometry`, `street_name`, `highway_type`

**Example:**
```
Graph nodes: (456300.5, 5734003.2), (456416.7, 5734189.1), ...
Graph edges: 
  - (456300.5, 5734003.2) → (456416.7, 5734189.1): length=150.3m
  - (456416.7, 5734189.1) → (456423.8, 5734204.9): length=18.5m
```

---

#### Step 1.2: Find Plant Location

**Purpose:**
- Determine where the heat plant (source) should be located
- Typically at the centroid of buildings (weighted by heat demand)

**Algorithm:**
```python
def choose_plant_node(graph, buildings, design_loads=None):
    if design_loads:
        # Weighted centroid (by heat demand)
        total_load = sum(design_loads.values())
        weighted_x = sum(b.x * design_loads.get(b.id, 0) for b in buildings) / total_load
        weighted_y = sum(b.y * design_loads.get(b.id, 0) for b in buildings) / total_load
        plant_point = Point(weighted_x, weighted_y)
    else:
        # Simple centroid
        plant_point = buildings.geometry.centroid
    
    # Snap to nearest graph node
    plant_node = snap_to_nearest_node(graph, plant_point)
    return plant_node
```

**Output:**
- `plant_node` - `(x, y)` tuple representing plant location

**Example:**
```
Plant node: (456381.9, 5734092.4)
```

---

#### Step 1.3: Build Trunk Topology

**Purpose:**
- Create the main distribution network connecting plant to all building attachment points
- Uses **Dijkstra's shortest path algorithm** to find optimal routes

**Algorithm:**
```python
def build_trunk_topology(graph, plant_node, attach_nodes, trunk_mode, edge_cost_mode):
    trunk_edges = set()
    
    # Edge cost function
    def get_edge_weight(u, v):
        length = graph[u][v].get('length_m', 100.0)
        
        if edge_cost_mode == "avoid_primary_roads":
            highway_type = graph[u][v].get('highway_type', 'residential')
            if highway_type in ['primary', 'trunk', 'motorway']:
                return length * 1.3  # Penalty for major roads
        return length
    
    # Find shortest paths from plant to each attachment point
    for attach_node in attach_nodes:
        try:
            # Use Dijkstra's algorithm with custom edge weights
            path = nx.shortest_path(
                graph,
                plant_node,
                attach_node,
                weight=get_edge_weight
            )
            
            # Add all edges in path to trunk
            for i in range(len(path) - 1):
                edge = tuple(sorted([path[i], path[i + 1]]))
                trunk_edges.add(edge)
        except nx.NetworkXNoPath:
            logger.warning(f"No path from plant to {attach_node}")
    
    return list(trunk_edges)
```

**Edge Cost Modes:**

1. **`length_only`** (default):
   - Uses pure geometric length
   - Optimizes for minimum pipe length
   - `weight = length_m`

2. **`avoid_primary_roads`**:
   - Applies 1.3× penalty to major roads (primary, trunk, motorway)
   - Reflects increased excavation cost and traffic disruption
   - `weight = length_m * 1.3` (if major road)

**Output:**
- `trunk_edges` - List of `(u, v)` tuples representing trunk network edges

**Example:**
```
Trunk edges: [
    ((456381.9, 5734092.4), (456416.7, 5734189.1)),  # Plant → Node 1
    ((456416.7, 5734189.1), (456423.8, 5734204.9)),  # Node 1 → Node 2
    ((456423.8, 5734204.9), (456502.2, 5734222.1)),  # Node 2 → Node 3
    ...
]
```

**Trunk Modes:**

| Mode | Description | Algorithm |
|------|-------------|-----------|
| `strict_street` | Trunk follows selected streets only | Dijkstra on filtered street graph |
| `street_plus_short_spurs` | Trunk + controlled spur expansion | Base trunk + spur identification |
| `paths_to_buildings` | Shortest paths plant→buildings | Dijkstra to each building directly |

---

## 2. Attach Buildings to Trunk

### Purpose

Connect each building to the trunk network via service pipes. The attachment strategy determines how buildings connect to the trunk.

### Process Flow

```
Buildings (GeoDataFrame)
    ↓
Find Nearest Trunk Edge (for each building)
    ↓
Project Building onto Trunk Edge
    ↓
Create Attachment Point (based on attach_mode)
    ↓
Calculate Service Length
    ↓
Buildings with attach_node and service_length_m
```

### Step-by-Step Process

#### Step 2.1: Find Nearest Trunk Edge

**For each building:**
1. Get building location (centroid or geometry)
2. Find nearest trunk edge using spatial queries
3. Project building point onto edge
4. Calculate distance (service length)

**Algorithm:**
```python
def find_nearest_trunk_edge(building_point, trunk_edges, street_graph):
    min_distance = float('inf')
    nearest_edge = None
    projection_point = None
    
    for edge in trunk_edges:
        u, v = edge
        
        # Get edge geometry
        if street_graph.has_edge(u, v):
            edge_geom = street_graph[u][v].get('geometry')
        else:
            edge_geom = LineString([u, v])
        
        # Project building onto edge
        proj_point = edge_geom.interpolate(edge_geom.project(building_point))
        distance = building_point.distance(proj_point)
        
        if distance < min_distance:
            min_distance = distance
            nearest_edge = edge
            projection_point = proj_point
    
    return nearest_edge, projection_point, min_distance
```

**Output:**
- For each building: `(nearest_edge, projection_point, distance)`

---

#### Step 2.2: Create Attachment Point (Attach Mode)

**Three attachment modes:**

##### Mode 1: `nearest_node`

**Behavior:**
- Buildings attach to **nearest existing trunk node**
- Multiple buildings can share the same node
- **Fewer junctions** (computationally efficient)
- **Less realistic** (buildings share connection points)

**Process:**
```python
def attach_nearest_node(building, nearest_edge, projection_point):
    u, v = nearest_edge
    
    # Check if projection is close to existing node
    dist_to_u = projection_point.distance(Point(u))
    dist_to_v = projection_point.distance(Point(v))
    
    if dist_to_u < snap_tol_m:
        attach_node = u
    elif dist_to_v < snap_tol_m:
        attach_node = v
    else:
        # Use closer endpoint
        attach_node = u if dist_to_u < dist_to_v else v
    
    return attach_node
```

**Result:**
- Multiple buildings may have same `attach_node`
- Creates "star-burst" pattern

---

##### Mode 2: `split_edge_per_building` ⭐ (Recommended)

**Behavior:**
- Each building gets its **own unique attachment point**
- New junction created on trunk edge for each building
- **More junctions** (more realistic topology)
- **More realistic** (each building has separate connection)

**Process:**
```python
def attach_split_edge_per_building(building, nearest_edge, projection_point):
    # Project building onto trunk edge
    # Create new node at projection point
    attach_node = (
        round(projection_point.x, 1),
        round(projection_point.y, 1)
    )
    
    # Later: Split edge at this point
    # Original edge: (u, v)
    # Becomes: (u, attach_node) and (attach_node, v)
    
    return attach_node
```

**Edge Splitting:**
```python
def split_edge_at_point(graph, edge, new_node):
    u, v = edge
    
    # Get original edge data
    edge_data = graph[u][v]
    
    # Remove original edge
    graph.remove_edge(u, v)
    
    # Add new node
    graph.add_node(new_node, **edge_data.get('node_attrs', {}))
    
    # Add two new edges
    length1 = Point(u).distance(Point(new_node))
    length2 = Point(new_node).distance(Point(v))
    
    graph.add_edge(u, new_node, 
                   length_m=length1,
                   geometry=LineString([u, new_node]))
    graph.add_edge(new_node, v,
                   length_m=length2,
                   geometry=LineString([new_node, v]))
```

**Result:**
- Each building has unique `attach_node`
- Trunk edges are split to accommodate new junctions
- Creates realistic topology

---

##### Mode 3: `clustered_projection`

**Behavior:**
- Buildings are **clustered** with minimum spacing
- Multiple buildings can share attachment point if close together
- **Medium complexity** (balance between realism and efficiency)

**Process:**
```python
def attach_clustered_projection(buildings, min_spacing_m=8.0):
    # Group buildings by nearest trunk edge
    edge_groups = {}
    
    for building in buildings:
        edge = find_nearest_edge(building)
        if edge not in edge_groups:
            edge_groups[edge] = []
        edge_groups[edge].append(building)
    
    # For each edge group, cluster projections
    attach_nodes = []
    for edge, group in edge_groups.items():
        # Sort by position along edge
        projections = [project(b, edge) for b in group]
        projections.sort(key=lambda p: edge.project(p))
        
        # Cluster with minimum spacing
        clusters = []
        current_cluster = [projections[0]]
        
        for proj in projections[1:]:
            if proj.distance(current_cluster[-1]) < min_spacing_m:
                current_cluster.append(proj)
            else:
                clusters.append(current_cluster)
                current_cluster = [proj]
        
        # Create attach node for each cluster (centroid)
        for cluster in clusters:
            attach_node = Point([p.x for p in cluster], [p.y for p in cluster]).centroid
            attach_nodes.append(attach_node)
    
    return attach_nodes
```

**Result:**
- Buildings clustered with minimum spacing
- Fewer junctions than `split_edge_per_building`
- More realistic than `nearest_node`

---

#### Step 2.3: Calculate Service Length

**For each building:**
```python
service_length_m = building_point.distance(attach_node)
```

**Output:**
- `buildings_snapped` GeoDataFrame with:
  - `attach_node` - `(x, y)` tuple of attachment point
  - `service_length_m` - Distance from building to trunk

**Example:**
```
Building B1:
  - Location: (456502.2, 5734222.1)
  - Attach node: (456500.0, 5734220.0)
  - Service length: 3.2 m

Building B2:
  - Location: (456748.7, 5734257.3)
  - Attach node: (456745.0, 5734255.0)
  - Service length: 4.8 m
```

---

## 3. Create Pandapipes Network Structure

### Purpose

Convert the NetworkX graph structure into a **pandapipes network** - a format ready for hydraulic and thermal simulation.

### Process Flow

```
Trunk Edges + Buildings
    ↓
Create Pandapipes Network
    ↓
Add Junctions (supply + return)
    ↓
Add Pipes (trunk + service)
    ↓
Add Sinks (buildings)
    ↓
Add Heat Exchangers
    ↓
Add Source (plant)
    ↓
Add Pump
    ↓
Pandapipes Network (ready for simulation)
```

### Step-by-Step Process

#### Step 3.1: Create Empty Network

```python
net = pp.create_empty_network(f"DH_network_{cluster_id}", fluid="water")
net.junction_geodata = pd.DataFrame(columns=["x", "y"])
```

**Network Structure:**
- `net.junction` - DataFrame with junctions (nodes)
- `net.pipe` - DataFrame with pipes (edges)
- `net.sink` - DataFrame with sinks (consumers)
- `net.ext_grid` - DataFrame with sources (plant)
- `net.heat_exchanger` - DataFrame with heat exchangers
- `net.circ_pump_pressure` - DataFrame with circulation pumps

---

#### Step 3.2: Create Trunk Junctions

**For each trunk node, create TWO junctions:**
- **Supply junction** - Hot water flow (plant → buildings)
- **Return junction** - Cold water flow (buildings → plant)

**Process:**
```python
def create_trunk_junctions(net, trunk_nodes, plant_node, config):
    node_to_junction = {}
    
    # Calculate distances from plant for pressure initialization
    distances = calculate_distances(trunk_nodes, plant_node)
    
    for node in trunk_nodes:
        x, y = node
        distance_m = distances[node]
        
        # Calculate initial pressure (distance-based)
        pressure_drop = distance_m * 0.001  # 0.001 bar/m
        supply_pressure = max(1.0, config.system_pressure_bar - pressure_drop)
        return_pressure = max(0.9, supply_pressure - 0.1)
        
        # Supply junction
        supply_junc = pp.create_junction(
            net,
            pn_bar=supply_pressure,
            tfluid_k=config.t_supply_C + 273.15,  # Convert to Kelvin
            name=f"S_{x:.1f}_{y:.1f}",
            geodata=(x, y)
        )
        
        # Return junction (slightly offset for visualization)
        return_junc = pp.create_junction(
            net,
            pn_bar=return_pressure,
            tfluid_k=config.t_return_C + 273.15,
            name=f"R_{x:.1f}_{y:.1f}",
            geodata=(x + 1, y + 1)  # 1m offset
        )
        
        node_to_junction[node] = {
            'supply': supply_junc,
            'return': return_junc
        }
    
    return node_to_junction
```

**Output:**
- `node_to_junction` - Mapping: `(x, y) → {'supply': junc_idx, 'return': junc_idx}`

**Example:**
```
Node (456381.9, 5734092.4):
  - Supply junction: 0 (pressure: 2.0 bar, temp: 353.15 K)
  - Return junction: 1 (pressure: 1.9 bar, temp: 333.15 K)
```

---

#### Step 3.3: Create Trunk Pipes

**For each trunk edge, create TWO pipes:**
- **Supply pipe** - Hot water: `supply_u → supply_v`
- **Return pipe** - Cold water: `return_v → return_u` (reversed direction)

**Process:**
```python
def create_trunk_pipes(net, trunk_edges, node_to_junction, street_graph):
    for edge in trunk_edges:
        u, v = edge
        
        # Get edge length
        if street_graph.has_edge(u, v):
            length_m = street_graph[u][v].get('length_m', 100.0)
        else:
            length_m = Point(u).distance(Point(v))
        
        # Get junctions
        u_supply = node_to_junction[u]['supply']
        u_return = node_to_junction[u]['return']
        v_supply = node_to_junction[v]['supply']
        v_return = node_to_junction[v]['return']
        
        # Supply pipe (u → v)
        pp.create_pipe_from_parameters(
            net,
            from_junction=u_supply,
            to_junction=v_supply,
            length_km=length_m / 1000.0,
            diameter_m=0.15,  # Initial diameter (will be sized later)
            k_mm=0.001,  # Roughness
            name=f"trunk_supply_{u}_{v}",
            sections=5,
            alpha_w_per_m2k=0.0  # Heat loss coefficient
        )
        
        # Return pipe (v → u, reversed)
        pp.create_pipe_from_parameters(
            net,
            from_junction=v_return,
            to_junction=u_return,
            length_km=length_m / 1000.0,
            diameter_m=0.15,
            k_mm=0.001,
            name=f"trunk_return_{v}_{u}",
            sections=5,
            alpha_w_per_m2k=0.0
        )
```

**Output:**
- Trunk pipes added to `net.pipe` DataFrame

**Example:**
```
Trunk pipe: trunk_supply_((456381.9, 5734092.4), (456416.7, 5734189.1))
  - From: Supply junction 0
  - To: Supply junction 2
  - Length: 0.1503 km
  - Diameter: 0.15 m (initial)
```

---

#### Step 3.4: Create Building Junctions

**For each building, create TWO junctions:**
- **Building supply junction** - Entry point for hot water
- **Building return junction** - Exit point for cold water

**Process:**
```python
def create_building_junctions(net, buildings_snapped, node_to_junction, config):
    building_to_junction = {}
    
    for idx, building in buildings_snapped.iterrows():
        building_id = building['building_id']
        building_point = building.geometry.centroid
        attach_node = building['attach_node']
        
        # Get attachment junction pressure (from trunk)
        attach_distance = calculate_distance(attach_node, plant_node)
        attach_pressure = max(0.8, config.system_pressure_bar - attach_distance * 0.001)
        
        # Building supply junction
        building_supply = pp.create_junction(
            net,
            pn_bar=attach_pressure,
            tfluid_k=config.t_supply_C + 273.15,
            name=f"building_supply_{building_id}",
            geodata=(building_point.x, building_point.y)
        )
        
        # Building return junction
        building_return = pp.create_junction(
            net,
            pn_bar=attach_pressure - 0.05,  # Slightly lower
            tfluid_k=config.t_return_C + 273.15,
            name=f"building_return_{building_id}",
            geodata=(building_point.x + 0.5, building_point.y + 0.5)  # Small offset
        )
        
        building_to_junction[building_id] = {
            'supply': building_supply,
            'return': building_return
        }
    
    return building_to_junction
```

**Output:**
- `building_to_junction` - Mapping: `building_id → {'supply': junc_idx, 'return': junc_idx}`

---

#### Step 3.5: Create Service Pipes

**For each building, create TWO service pipes:**
- **Service supply pipe** - Trunk supply → Building supply
- **Service return pipe** - Building return → Trunk return

**Process:**
```python
def create_service_pipes(net, buildings_snapped, node_to_junction, building_to_junction):
    for idx, building in buildings_snapped.iterrows():
        building_id = building['building_id']
        attach_node = building['attach_node']
        service_length_m = building['service_length_m']
        
        # Get junctions
        trunk_supply = node_to_junction[attach_node]['supply']
        trunk_return = node_to_junction[attach_node]['return']
        building_supply = building_to_junction[building_id]['supply']
        building_return = building_to_junction[building_id]['return']
        
        # Service supply pipe
        pp.create_pipe_from_parameters(
            net,
            from_junction=trunk_supply,
            to_junction=building_supply,
            length_km=service_length_m / 1000.0,
            diameter_m=0.020,  # DN20 (default service pipe)
            k_mm=0.001,
            name=f"service_supply_{building_id}",
            sections=3,
            alpha_w_per_m2k=0.0
        )
        
        # Service return pipe
        pp.create_pipe_from_parameters(
            net,
            from_junction=building_return,
            to_junction=trunk_return,
            length_km=service_length_m / 1000.0,
            diameter_m=0.020,  # DN20
            k_mm=0.001,
            name=f"service_return_{building_id}",
            sections=3,
            alpha_w_per_m2k=0.0
        )
```

**Output:**
- Service pipes added to `net.pipe` DataFrame

**Example:**
```
Service pipe: service_supply_B1
  - From: Trunk supply junction 5
  - To: Building supply junction 10
  - Length: 0.0032 km (3.2 m)
  - Diameter: 0.020 m (DN20)
```

---

#### Step 3.6: Create Heat Exchangers

**For each building, create a heat exchanger:**
- Represents the building's heating system
- Transfers heat from supply to return
- Creates pressure drop

**Process:**
```python
def create_heat_exchangers(net, buildings_snapped, building_to_junction):
    for idx, building in buildings_snapped.iterrows():
        building_id = building['building_id']
        
        building_supply = building_to_junction[building_id]['supply']
        building_return = building_to_junction[building_id]['return']
        
        # Create heat exchanger (will be sized later)
        pp.create_heat_exchanger(
            net,
            from_junction=building_supply,
            to_junction=building_return,
            qext_w=0.0,  # Will be set during simulation
            name=f"HX_{building_id}"
        )
```

**Output:**
- Heat exchangers added to `net.heat_exchanger` DataFrame

---

#### Step 3.7: Create Sinks (Consumers)

**For each building, create a sink:**
- Represents heat demand (mass flow rate)
- Will be assigned during simulation

**Process:**
```python
def create_sinks(net, buildings_snapped, building_to_junction):
    for idx, building in buildings_snapped.iterrows():
        building_id = building['building_id']
        
        building_supply = building_to_junction[building_id]['supply']
        
        # Create sink (mass flow will be assigned during simulation)
        pp.create_sink(
            net,
            junction=building_supply,
            mdot_kg_per_s=0.0,  # Will be calculated from heat demand
            name=f"sink_{building_id}"
        )
```

**Output:**
- Sinks added to `net.sink` DataFrame

---

#### Step 3.8: Create Source (Plant)

**Create external grid (source) at plant:**
- Provides hot water at fixed pressure and temperature
- Represents the heat plant

**Process:**
```python
def create_plant_source(net, plant_node, node_to_junction, config):
    # Get plant supply junction
    plant_supply = node_to_junction[plant_node]['supply']
    
    # Create external grid (source)
    pp.create_ext_grid(
        net,
        junction=plant_supply,
        p_bar=config.system_pressure_bar,
        t_k=config.t_supply_C + 273.15,
        name="heat_plant"
    )
```

**Output:**
- Source added to `net.ext_grid` DataFrame

---

#### Step 3.9: Create Circulation Pump

**Create pump to maintain circulation:**
- Maintains pressure in the system
- Ensures flow from supply to return

**Process:**
```python
def create_circulation_pump(net, plant_node, node_to_junction, config):
    plant_supply = node_to_junction[plant_node]['supply']
    plant_return = node_to_junction[plant_node]['return']
    
    # Create circulation pump
    pp.create_circ_pump_pressure(
        net,
        return_junction=plant_return,
        flow_junction=plant_supply,
        p_flow_bar=config.system_pressure_bar,
        plift_bar=1.0,  # Pressure lift
        name="circulation_pump"
    )
```

**Output:**
- Pump added to `net.circ_pump_pressure` DataFrame

---

## Complete Network Structure

### Final Network Components

```
Pandapipes Network:
├── Junctions (374 total)
│   ├── Trunk supply junctions (110)
│   ├── Trunk return junctions (110)
│   ├── Building supply junctions (77)
│   ├── Building return junctions (77)
│   └── Plant junctions (2)
│
├── Pipes (449 total)
│   ├── Trunk supply pipes (109)
│   ├── Trunk return pipes (109)
│   ├── Service supply pipes (77)
│   └── Service return pipes (77)
│
├── Sinks (77)
│   └── One per building (mass flow assigned during simulation)
│
├── Heat Exchangers (77)
│   └── One per building (heat transfer)
│
├── Source (1)
│   └── External grid at plant
│
└── Pump (1)
    └── Circulation pump
```

---

## Network Topology Example

### Visual Representation

```
                    PLANT (Source)
                         |
                    [Supply] [Return]
                         |     |
                    ┌────┘     └────┐
                    │                │
              Trunk Supply    Trunk Return
                    │                │
        ┌───────────┼───────────┐    │
        │           │           │    │
    [Node 1]    [Node 2]    [Node 3] │
        │           │           │    │
        │           │           │    │
    [Attach]   [Attach]   [Attach]  │
        │           │           │    │
    Service    Service    Service    │
        │           │           │    │
    [B1 S]     [B2 S]     [B3 S]    │
        │           │           │    │
      [HX]       [HX]       [HX]     │
        │           │           │    │
    [B1 R]     [B2 R]     [B3 R]    │
        │           │           │    │
    Service    Service    Service    │
        │           │           │    │
    [Attach]   [Attach]   [Attach]  │
        │           │           │    │
        └───────────┼───────────┘    │
                    │                │
              Trunk Return    Trunk Supply
                    │                │
                    └────┐     ┌────┘
                         │     │
                    [Return] [Supply]
                         |     |
                    PLANT (Pump)
```

---

## Key Parameters

### Trunk Network

- **Trunk Mode**: `strict_street`, `street_plus_short_spurs`, `paths_to_buildings`
- **Edge Cost Mode**: `length_only`, `avoid_primary_roads`
- **Plant Location**: Weighted centroid or simple centroid

### Building Attachment

- **Attach Mode**: `nearest_node`, `split_edge_per_building`, `clustered_projection`
- **Snap Tolerance**: 2.0 m (reuse existing node if within tolerance)
- **Min Spacing**: 8.0 m (for clustered_projection)
- **Max Attach Distance**: 500.0 m (maximum service length)

### Network Properties

- **System Pressure**: 2.0 bar (default)
- **Supply Temperature**: 80°C (353.15 K)
- **Return Temperature**: 60°C (333.15 K)
- **Default Service Diameter**: DN20 (0.020 m)
- **Default Trunk Diameter**: DN150 (0.150 m, initial, will be sized)

---

## Summary

The Network Building process creates a complete district heating network structure:

1. ✅ **Trunk Network** - Main distribution pipes using Dijkstra's algorithm
2. ✅ **Building Attachment** - Each building connected to trunk (mode-dependent)
3. ✅ **Pandapipes Structure** - Complete network with junctions, pipes, sinks, heat exchangers, source, and pump

The network is now ready for:
- Pipe sizing (Step 4)
- Pipeflow simulation (Step 5)
- Results extraction (Step 8)

