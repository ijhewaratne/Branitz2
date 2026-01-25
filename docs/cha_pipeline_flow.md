# CHA (Central Heating Agent) Pipeline Flow

## Overview

The CHA pipeline designs and analyzes district heating networks for street-based clusters. It follows a deterministic workflow from data loading to network simulation and KPI extraction.

## Complete Pipeline Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                   1. DATA LOADING                                │
└─────────────────────────────────────────────────────────────────┘
                          ↓
    ┌──────────────────────────────────────────────┐
    │ load_cluster_data(cluster_id)                │
    │                                              │
    │ • Load cluster metadata from                 │
    │   street_clusters.parquet                    │
    │ • Get building IDs from                      │
    │   building_cluster_map.parquet               │
    │ • Load filtered buildings                    │
    │   (residential with heat demand)             │
    │ • Load streets (filtered to cluster)         │
    │ • Get plant coordinates                      │
    │ • Load design hour and design load           │
    │   from cluster_design_topn.json              │
    └──────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────────┐
│                   2. NETWORK BUILDING                            │
└─────────────────────────────────────────────────────────────────┘
                          ↓
    ┌──────────────────────────────────────────────┐
    │ Choose Network Builder:                      │
    │                                              │
    │ A. Standard Builder                          │
    │    (network_builder.build_dh_network_for_cluster)│
    │    • Build street graph                      │
    │    • Snap plant to graph                     │
    │    • Attach buildings to streets             │
    │    • Build trunk topology                    │
    │    • Create pandapipes network               │
    │                                              │
    │ B. Trunk-Spur Builder                        │
    │    (network_builder_trunk_spur.build_trunk_spur_network)│
    │    • Filter streets to cluster               │
    │    • Build main trunk path                   │
    │    • Assign exclusive spur points            │
    │    • Create pandapipes network               │
    │    • Size pipes from catalog                 │
    │    • Optimize for convergence                │
    └──────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────────┐
│                   3. DESIGN LOAD ASSIGNMENT                      │
└─────────────────────────────────────────────────────────────────┘
                          ↓
    ┌──────────────────────────────────────────────┐
    │ Set Design Loads on Sinks                    │
    │                                              │
    │ • Load per-building design loads:            │
    │   - From building.design_load_kw column OR   │
    │   - From design_topn.json (cluster level)    │
    │   - Distribute proportionally by floor area  │
    │   - Fallback: equal distribution             │
    │                                              │
    │ • Calculate mass flow rates:                 │
    │   mdot = (load_kW × 1000) /                  │
    │          (cp_water × delta_T × 1000)         │
    │   where:                                     │
    │   - cp_water = 4.186 kJ/(kg·K)              │
    │   - delta_T = supply_temp - return_temp      │
    │                                              │
    │ • Assign mdot_kg_per_s to each sink          │
    │   (matched by building_id in sink name)      │
    │                                              │
    │ • Set source mdot = sum of all sinks         │
    └──────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────────┐
│                   4. NETWORK SIMULATION                          │
└─────────────────────────────────────────────────────────────────┘
                          ↓
    ┌──────────────────────────────────────────────┐
    │ Initial Simulation                           │
    │                                              │
    │ pp.pipeflow(net, mode='all', verbose=False)  │
    │                                              │
    │ • Solves mass and energy balance equations   │
    │ • Uses Newton-Raphson method                 │
    │ • Calculates:                                │
    │   - Flow rates (v_mean_ms)                   │
    │   - Pressure drops (p_from_bar, p_to_bar)    │
    │   - Temperatures (if thermal mode)           │
    │                                              │
    │ • Checks convergence:                        │
    │   net.converged (True/False)                 │
    └──────────────────────────────────────────────┘
                          ↓
         ┌────────────────────┐
         │ Converged?         │
         └────────────────────┘
              ↓ Yes         ↓ No
              ↓              ↓
    ┌─────────────────┐  ┌──────────────────────────┐
    │ Skip Optimization│  │ Convergence Optimization │
    └─────────────────┘  │                          │
              ↓          │ • Add minimal loops      │
              ↓          │ • Fix parallel paths     │
              ↓          │ • Adjust pipe roughness  │
              ↓          │ • Improve pressures      │
              ↓          │ • Ensure connectivity    │
              ↓          │                          │
              ↓          │ • Re-run pipeflow()      │
              ↓          └──────────────────────────┘
              ↓                      ↓
              └──────────┬───────────┘
                         ↓
┌─────────────────────────────────────────────────────────────────┐
│                   5. KPI EXTRACTION                              │
└─────────────────────────────────────────────────────────────────┘
                          ↓
    ┌──────────────────────────────────────────────┐
    │ extract_kpis(net, cluster_id, ...)           │
    │                                              │
    │ EN 13941-1 Compliance KPIs:                  │
    │                                              │
    │ • Velocity Analysis:                         │
    │   - v_max_ms: Maximum velocity               │
    │   - v_mean_ms: Mean velocity                 │
    │   - v_share_within_limits: % pipes within    │
    │     limits (0.1-1.5 m/s)                     │
    │                                              │
    │ • Pressure Drop Analysis:                    │
    │   - dp_max_bar_per_100m: Maximum pressure    │
    │     drop per 100m                            │
    │   - dp_mean_bar_per_100m: Mean pressure drop │
    │                                              │
    │ • Feasibility:                               │
    │   - feasible: True if                        │
    │     v_share ≥ 95% AND                        │
    │     dp_max ≤ 0.3 bar/100m                    │
    │                                              │
    │ • Detailed Pipe-Level KPIs:                  │
    │   - velocity_ms                              │
    │   - pressure_drop_bar                        │
    │   - diameter_mm                              │
    │   - length_m                                 │
    └──────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────────┐
│                   6. OUTPUT GENERATION                           │
└─────────────────────────────────────────────────────────────────┘
                          ↓
    ┌──────────────────────────────────────────────┐
    │ Save Outputs to results/cha/{cluster_id}/    │
    │                                              │
    │ 1. cha_kpis.json                             │
    │    • Network-level KPIs                      │
    │    • Pipe-level detailed KPIs                │
    │    • Convergence status                      │
    │    • Topology statistics                     │
    │    • EN 13941-1 compliance                   │
    │                                              │
    │ 2. network.pickle                            │
    │    • Complete pandapipes network object      │
    │    • Includes simulation results             │
    │    • Can be reloaded for further analysis    │
    │                                              │
    │ 3. interactive_map.html                      │
    │    • Folium-based interactive map            │
    │    • Pipes colored by velocity               │
    │    • Thickness by diameter                   │
    │    • Building markers with demand            │
    │    • Click popups with metrics               │
    │    • Layer controls                          │
    └──────────────────────────────────────────────┘
                          ↓
                      COMPLETE
```

## Detailed Step Explanations

### Step 1: Data Loading

**Purpose**: Load all required data for a specific cluster

**Inputs**:
- `cluster_id` (e.g., "ST001_HEINRICH_ZILLE_STRASSE")
- Cluster metadata from `street_clusters.parquet`
- Building-cluster mapping from `building_cluster_map.parquet`
- Filtered buildings from `processed/buildings.parquet`

**Process**:
1. Validate cluster ID format
2. Load cluster metadata (plant coordinates, building count)
3. Get building IDs for the cluster
4. Load filtered buildings (residential with heat demand)
5. Load streets (filtered to cluster's street name)
6. Load design hour and design load from `design_topn.json`

**Outputs**:
- `buildings`: GeoDataFrame of cluster buildings
- `streets`: GeoDataFrame of cluster streets
- `plant_coords`: (x, y) tuple
- `design_hour`: Hour of peak load (0-8759)
- `design_load_kw`: Peak load in kW

---

### Step 2: Network Building

**Purpose**: Create the physical network topology

**Standard Builder**:
1. **Build Street Graph**: Convert streets to NetworkX graph
2. **Snap Plant**: Find nearest street node to plant coordinates
3. **Attach Buildings**: Connect buildings to nearest street nodes
4. **Build Trunk**: Create minimal tree from plant to all buildings
5. **Create Pandapipes Network**: Convert to pandapipes format

**Trunk-Spur Builder**:
1. **Filter Streets**: Select streets within cluster buffer
2. **Build Main Trunk**: Create longest continuous street path
3. **Assign Spurs**: Map buildings to exclusive spur attachment points
4. **Create Network**: Build pandapipes network with trunk-spur structure
5. **Size Pipes**: Select pipe diameters from technical catalog
6. **Optimize**: Run convergence optimization

---

### Step 3: Design Load Assignment

**Purpose**: Set mass flow rates based on building heat demands

**Process**:
1. **Load Design Loads**:
   - Try building-level `design_load_kw` column
   - Otherwise, use cluster design load from `design_topn.json`
   - Distribute proportionally by floor area
   - Fallback: equal distribution

2. **Calculate Mass Flow**:
   ```
   mdot = Q / (cp × ΔT)
   
   where:
   - Q = heat demand (kW)
   - cp = specific heat capacity of water (4.186 kJ/(kg·K))
   - ΔT = temperature difference (supply - return, typically 30K)
   - mdot = mass flow rate (kg/s)
   ```

3. **Assign to Sinks**:
   - Match sink name to building_id (format: "sink_{building_id}")
   - Set `mdot_kg_per_s` for each sink
   - Set source `mdot_kg_per_s` = sum of all sinks

---

### Step 4: Network Simulation

**Purpose**: Solve hydraulic equations to get flow rates and pressures

**Pandapipes Simulation**:
- Uses Newton-Raphson iterative solver
- Solves mass balance: Σ(flow_in) = Σ(flow_out)
- Solves energy balance: pressure_drop = f(flow, diameter, roughness)
- Uses Darcy-Weisbach equation for pressure drop

**Convergence Criteria**:
- Residuals below tolerance
- Mass balance satisfied
- Pressure consistency achieved

**If Not Converged**:
- Run convergence optimizer
- Add minimal loops (tree networks can't converge)
- Fix parallel paths
- Adjust pipe roughness
- Improve initial pressures

---

### Step 5: KPI Extraction

**Purpose**: Extract compliance metrics per EN 13941-1 standard

**Key Metrics**:

1. **Velocity Limits**:
   - Minimum: 0.1 m/s (prevents sedimentation)
   - Maximum: 1.5 m/s (prevents erosion)
   - Compliance: ≥95% of pipes within limits

2. **Pressure Drop Limits**:
   - Maximum: 0.3 bar per 100m pipe length
   - Ensures pump energy efficiency

3. **Feasibility**:
   ```
   feasible = (v_share_within_limits ≥ 0.95) AND 
              (dp_max_bar_per_100m ≤ 0.3)
   ```

4. **Pipe-Level Metrics**:
   - Velocity, pressure drop, diameter, length
   - Used for detailed analysis and reporting

---

### Step 6: Output Generation

**Output Files**:

1. **`cha_kpis.json`**:
   ```json
   {
     "cluster_id": "ST001_HEINRICH_ZILLE_STRASSE",
     "feasible": true,
     "aggregate": {
       "v_max_ms": 1.45,
       "v_mean_ms": 0.82,
       "v_share_within_limits": 0.98,
       "dp_max_bar_per_100m": 0.28
     },
     "en13941_compliance": {
       "feasible": true,
       "velocity_compliant": true,
       "pressure_drop_compliant": true
     },
     "convergence": {
       "initial_converged": true,
       "final_converged": true
     },
     "topology": {
       "trunk_edges": 12,
       "service_connections": 77
     },
     "detailed": {
       "pipes": [...]
     }
   }
   ```

2. **`network.pickle`**:
   - Complete pandapipes network object
   - Can be reloaded: `net = pickle.load(open('network.pickle', 'rb'))`
   - Contains all simulation results

3. **`interactive_map.html`**:
   - Open in web browser
   - Interactive visualization with:
     - Pipes colored by velocity (blue → red)
     - Thickness by diameter
     - Building markers with demand
     - Click popups with metrics

## Key Physical Parameters

**Water Properties**:
- Specific heat: cp = 4.186 kJ/(kg·K)
- Density: ρ ≈ 970 kg/m³ (at 80°C)

**Temperature Design**:
- Supply temperature: 80°C (353.15 K)
- Return temperature: 50°C (323.15 K)
- Delta T: 30 K

**Pressure**:
- Supply pressure: 10 bar
- Return pressure: ~10 bar (pressure drop through network)

**Velocity Limits (EN 13941-1)**:
- Minimum: 0.1 m/s
- Maximum: 1.5 m/s

**Pressure Drop Limits**:
- Maximum: 0.3 bar per 100m

## Error Handling

**Common Issues**:

1. **Network Not Converging**:
   - Cause: Tree topology (no loops)
   - Solution: Run with `--optimize-convergence` or use `--use-trunk-spur`

2. **No Buildings Found**:
   - Cause: Cluster ID mismatch or buildings not filtered
   - Solution: Check `building_cluster_map.parquet` and run data preparation

3. **Missing Design Loads**:
   - Cause: `design_topn.json` not generated
   - Solution: Run data preparation with profile generation

## Command Line Usage

```bash
# Standard builder
python src/scripts/01_run_cha.py \
  --cluster-id ST001_HEINRICH_ZILLE_STRASSE \
  --optimize-convergence

# Trunk-spur builder (recommended)
python src/scripts/01_run_cha.py \
  --cluster-id ST001_HEINRICH_ZILLE_STRASSE \
  --use-trunk-spur

# With custom catalog
python src/scripts/01_run_cha.py \
  --cluster-id ST001_HEINRICH_ZILLE_STRASSE \
  --use-trunk-spur \
  --catalog data/raw/Technikkatalog.xlsx
```

## Output Location

All outputs are saved to:
```
results/cha/{cluster_id}/
  ├── cha_kpis.json
  ├── network.pickle
  └── interactive_map.html
```

Example:
```
results/cha/ST001_HEINRICH_ZILLE_STRASSE/
  ├── cha_kpis.json
  ├── network.pickle
  └── interactive_map.html
```

