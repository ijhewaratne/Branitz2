# How to Fix CHA Design Validation Issues

This guide explains each validation issue and provides step-by-step solutions.

**File**: `results/cha/ST010_HEINRICH_ZILLE_STRASSE/design_validation.json`

---

## 🔴 CRITICAL ISSUES (Must Fix)

### Issue 1: "Network has 2 disconnected components (must be connected)"

**What it means**: Your network has 2 separate, unconnected parts. All pipes must be in one connected network.

**Why it happens**:
- Network builder created separate subnetworks
- Some buildings/areas not reachable from plant
- Missing connections between network segments
- Street graph has disconnected parts

**How to fix**:

#### Option A: Use Trunk-Spur Builder (Recommended)
The trunk-spur builder creates better-connected networks:

```bash
# Re-run CHA with trunk-spur builder
python src/scripts/01_run_cha.py \
  --cluster-id ST010_HEINRICH_ZILLE_STRASSE \
  --use-trunk-spur \
  --optimize-convergence
```

**What this does**:
- Creates a main trunk line from plant
- Connects all buildings via spurs (branches)
- Ensures single connected network
- Better for convergence

#### Option B: Check Street Graph Connectivity
If trunk-spur doesn't work, check if streets are connected:

```python
# Debug script to check street connectivity
import networkx as nx
import geopandas as gpd

streets = gpd.read_file("data/processed/street_clusters.parquet")
# Check if street graph is connected
# If not, this is a data issue
```

#### Option C: Manual Network Fix
If you need to fix manually:
1. Identify the two disconnected components
2. Find the shortest path between them
3. Add connecting pipes
4. Re-run validation

**Expected Result**: `network_components: 1` (single connected network)

---

### Issue 2: "Network only converges successfully in 0.0% of scenarios (threshold: 95.0%)"

**What it means**: Network fails all 50 Monte Carlo robustness tests. Requires ≥95% success rate.

**Why it happens**:
- Base case doesn't converge properly
- Network too sensitive to demand/temperature variations
- Constraint violations (velocity > 2.0 m/s, pressure issues)
- Insufficient design margins

**How to fix**:

#### Step 1: Fix Base Case First
Before robustness, ensure base case converges:

```bash
# Run CHA and check if base case converges
python src/scripts/01_run_cha.py \
  --cluster-id ST010_HEINRICH_ZILLE_STRASSE \
  --use-trunk-spur \
  --optimize-convergence
```

**Check logs for**:
- `✓ Pipeflow converged successfully`
- No "convergence failure" errors

#### Step 2: Fix High Velocity Pipes
Your network has 2 pipes exceeding 2.0 m/s (pipes 164, 165):

```python
# After running CHA, check pipe diameters
import pickle
import pandas as pd

net = pickle.load(open("results/cha/ST010_HEINRICH_ZILLE_STRASSE/network.pickle", "rb"))

# Check high-velocity pipes
high_vel = net.res_pipe[net.res_pipe["v_mean_m_per_s"] > 2.0]
print(high_vel[["diameter_mm", "v_mean_m_per_s"]])

# Solution: Increase diameter for these pipes
# Pipe 164: velocity 2.07 m/s → increase diameter
# Pipe 165: velocity 2.02 m/s → increase diameter
```

**Fix in network builder**:
- Increase pipe diameter for high-flow areas
- Or add parallel pipes
- Re-run validation

#### Step 3: Add Design Margins
For robustness, add 20-30% margin:

```python
# In network builder, increase pipe diameters by 20-30%
# This provides margin for demand variations
```

#### Step 4: Check Constraint Thresholds
Robustness uses relaxed thresholds:
- Velocity: ≤ 2.0 m/s (vs. 1.5 m/s nominal)
- Pressure: 0.5-20 bar

If still failing, check:
- Are pressures within range?
- Are velocities below 2.0 m/s?
- Does base case converge?

**Expected Result**: `robustness_success_rate: ≥ 0.95` (95% or higher)

---

### Issue 3: "2 buildings (283.6 MWh/a, 3.6% of demand) not connected to network"

**What it means**: 2 buildings are not connected to the network (3.6% of total demand).

**Why it happens**:
- Buildings too far from network (>50m default threshold)
- Buildings not in street network coverage
- Network builder missed these buildings
- Buildings outside cluster boundary

**How to fix**:

#### Option A: Check Building Locations
```python
# Check which buildings are unconnected
import geopandas as gpd
import pandas as pd

buildings = gpd.read_file("data/processed/buildings.parquet")
# Filter for cluster
cluster_buildings = buildings[buildings["cluster_id"] == "ST010_HEINRICH_ZILLE_STRASSE"]

# Check distances to network
# If buildings are >50m from streets, they won't connect
```

#### Option B: Increase Connection Distance
If buildings are slightly too far:

```python
# In geospatial_checks.py or config
max_connection_distance_m = 75  # Increase from 50m to 75m
```

**Note**: This may not be realistic if buildings are very far.

#### Option C: Extend Network
If buildings are reachable:
1. Check if streets extend to these buildings
2. If yes, network builder should connect them
3. If no, may need to add streets or accept unconnected

**Expected Result**: `unconnected_buildings_count: 0`

---

## ⚠️ WARNINGS (Should Address)

### Warning 1: "71 isolated junctions found (not connected to any pipe)"

**What it means**: 71 junctions exist but aren't used by any pipes.

**Impact**: Low - doesn't affect functionality, but indicates cleanup needed

**How to fix**:
```python
# After network creation, remove unused junctions
# This is typically done automatically, but may need manual cleanup

# In network builder, after creating network:
used_junctions = set()
for pipe in net.pipe.itertuples():
    used_junctions.add(pipe.from_junction)
    used_junctions.add(pipe.to_junction)

# Remove unused junctions
unused = set(net.junction.index) - used_junctions
net.junction.drop(unused, inplace=True)
```

**Expected Result**: `isolated_junctions: 0`

---

### Warning 2: "Maximum velocity 2.07 m/s exceeds recommended limit 1.5 m/s (EN 13941-1)"

**What it means**: Pipe 164 has velocity 2.07 m/s (exceeds 1.5 m/s standard).

**Impact**: Medium - causes higher pressure losses, noise, wear

**How to fix**:

#### Identify High-Velocity Pipes
From your metrics:
- **Pipe 164**: 2.07 m/s
- **Pipe 165**: 2.02 m/s

#### Increase Pipe Diameter
```python
# In network builder or pipe sizing logic
# For pipes 164, 165, increase diameter

# Current: likely DN50 (50mm)
# Increase to: DN65 or DN80 (65mm or 80mm)

# Or use pipe catalog to select larger diameter
```

**Expected Result**: `max_velocity_m_per_s: ≤ 1.5`

---

### Warning 3: "28 pipes have velocity < 0.2 m/s (risk of sedimentation)"

**What it means**: 28 pipes have very low flow, risking sediment buildup.

**Impact**: Medium - can cause blockages, reduced efficiency

**How to fix**:

#### Option A: Reduce Pipe Diameter
For low-flow pipes, use smaller diameters:

```python
# Identify low-velocity pipes
low_vel_pipes = net.res_pipe[net.res_pipe["v_mean_m_per_s"] < 0.2]

# Reduce diameter (e.g., DN50 → DN32 or DN25)
# This increases velocity for same flow
```

#### Option B: Accept Low Flow
If flow is genuinely low (end-of-line pipes), this may be acceptable:
- Monitor for maintenance
- Flush periodically
- Accept as design trade-off

**Expected Result**: `pipes_below_min_velocity: 0` (or acceptable number)

---

### Warning 4: "Maximum pressure gradient 2.50 bar/km exceeds recommended 1.0 bar/km"

**What it means**: High pressure losses per kilometer, indicating high energy costs.

**Impact**: Medium - increases pump power and operating costs

**How to fix**:

#### Option A: Increase Pipe Diameters
Larger pipes = lower pressure losses:

```python
# Increase diameters for high-pressure-drop pipes
# Check which pipes have high pressure drop
# Increase diameter to reduce friction
```

#### Option B: Add Pumps
If pipes must stay small, add pressure boost pumps:

```python
# Add pumps at strategic locations
# This increases CAPEX but reduces pressure issues
```

**Expected Result**: `max_pressure_drop_per_km: ≤ 1.0`

---

### Warning 5: "High flow distribution imbalance (CV=1.18)"

**What it means**: Flow is unevenly distributed (some pipes overloaded, others underutilized).

**Impact**: Low-Medium - indicates suboptimal topology

**How to fix**:

#### Review Network Topology
```python
# Check network layout
# May need to redistribute connections
# Or optimize routing
```

**Note**: This is often acceptable if demand is naturally uneven.

**Expected Result**: `flow_coefficient_of_variation: < 1.0` (lower is better)

---

### Warning 6: "50/50 scenarios violated constraints"

**What it means**: All Monte Carlo scenarios failed constraints (related to robustness issue).

**Impact**: Critical - same as robustness failure

**How to fix**: Same as Issue 2 (Robustness Failure)

---

## 📋 Step-by-Step Fix Plan

### Priority 1: Fix Disconnected Components (CRITICAL)

```bash
# 1. Re-run with trunk-spur builder
python src/scripts/01_run_cha.py \
  --cluster-id ST010_HEINRICH_ZILLE_STRASSE \
  --use-trunk-spur \
  --optimize-convergence

# 2. Check validation again
# Should see: "network_components": 1
```

### Priority 2: Fix Robustness (CRITICAL)

```bash
# 1. Ensure base case converges
# Check logs for convergence success

# 2. Fix high-velocity pipes (164, 165)
# Increase diameter or add parallel pipes

# 3. Re-run validation
# Should see: "robustness_success_rate": ≥ 0.95
```

### Priority 3: Fix Unconnected Buildings (HIGH)

```bash
# 1. Check building locations
# 2. Extend network if needed
# 3. Or increase connection distance threshold
```

### Priority 4: Fix Warnings (MEDIUM)

```bash
# 1. Fix high-velocity pipes (increase diameter)
# 2. Fix low-velocity pipes (reduce diameter)
# 3. Fix pressure gradient (increase diameters or add pumps)
# 4. Clean up isolated junctions
```

---

## 🔧 Quick Fix Commands

### Re-run CHA with Better Builder
```bash
cd "/Users/ishanthahewaratne/Documents/Reserch New/Branitz2"
conda activate branitz_env

python src/scripts/01_run_cha.py \
  --cluster-id ST010_HEINRICH_ZILLE_STRASSE \
  --use-trunk-spur \
  --optimize-convergence
```

### Check Validation Results
```bash
# View validation report
cat results/cha/ST010_HEINRICH_ZILLE_STRASSE/design_validation.json | python -m json.tool

# Or view summary
cat results/cha/ST010_HEINRICH_ZILLE_STRASSE/design_validation_summary.txt
```

---

## 📊 Validation Metrics to Monitor

After fixes, check these metrics:

**Must Pass**:
- `network_components: 1` (single connected network)
- `robustness_success_rate: ≥ 0.95` (95% or higher)
- `unconnected_buildings_count: 0` (all buildings connected)

**Should Pass**:
- `max_velocity_m_per_s: ≤ 1.5` (EN 13941-1 limit)
- `pipes_exceeding_velocity: 0` (no high-velocity pipes)
- `max_pressure_drop_per_km: ≤ 1.0` (efficient operation)
- `isolated_junctions: 0` (clean network)

---

## 🐛 Debugging Tips

### Check Network Topology
```python
import pickle
import networkx as nx
import pandapipes as pp

# Load network
net = pickle.load(open("results/cha/ST010_HEINRICH_ZILLE_STRASSE/network.pickle", "rb"))

# Build graph
G = nx.Graph()
for idx, pipe in net.pipe.iterrows():
    G.add_edge(pipe["from_junction"], pipe["to_junction"])

# Check components
components = list(nx.connected_components(G))
print(f"Number of components: {len(components)}")
for i, comp in enumerate(components):
    print(f"Component {i+1}: {len(comp)} nodes")
```

### Check High-Velocity Pipes
```python
# Find high-velocity pipes
high_vel = net.res_pipe[net.res_pipe["v_mean_m_per_s"] > 1.5]
print(high_vel[["diameter_mm", "length_km", "v_mean_m_per_s", "qext_w"]])
```

### Check Unconnected Buildings
```python
import geopandas as gpd

buildings = gpd.read_file("data/processed/buildings.parquet")
cluster_buildings = buildings[buildings["cluster_id"] == "ST010_HEINRICH_ZILLE_STRASSE"]

# Check which buildings have demand but aren't connected
# (requires comparing with network heat exchangers/sinks)
```

---

## ✅ Success Criteria

After fixes, your validation should show:

```json
{
  "validation_summary": {
    "passed": true,
    "level": "PASS"  // or "PASS_WITH_WARNINGS"
  },
  "check_results": {
    "geospatial": true,
    "hydraulic": true,
    "thermal": true,
    "robustness": true
  },
  "issues": [],  // Empty or minimal
  "metrics": {
    "network_components": 1,
    "robustness_success_rate": 0.95,  // or higher
    "unconnected_buildings_count": 0,
    "max_velocity_m_per_s": 1.5,  // or lower
    "pipes_exceeding_velocity": 0
  }
}
```

---

## 📝 Summary

**Critical Issues** (Fix First):
1. ✅ Disconnected components → Use `--use-trunk-spur`
2. ✅ Robustness failure → Fix base case, add margins
3. ✅ Unconnected buildings → Check locations, extend network

**Warnings** (Fix After):
1. ⚠️ High velocity → Increase pipe diameter
2. ⚠️ Low velocity → Reduce pipe diameter
3. ⚠️ High pressure gradient → Increase diameters or add pumps
4. ⚠️ Isolated junctions → Clean up unused junctions

**Quick Fix**: Re-run with `--use-trunk-spur --optimize-convergence` flags

---

**Last Updated**: 2026-01-19  
**For More Details**: See `DESIGN_VALIDATION_EXPLAINED.md`
