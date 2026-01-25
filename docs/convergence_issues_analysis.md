# Convergence Issues Analysis

## Overview

The pipeline ran successfully but the network did not converge. This document analyzes the convergence issues and their root causes.

## Error Message

```
All nodes are set out of service. Probably they are not supplied. 
Therefore, the hydraulic pipeflow did not converge. 
Have you forgotten to define a supply component or is it not properly connected?
```

## Common Convergence Issues in District Heating Networks

### 1. **Network Connectivity Problems**

**Issue**: Nodes are not connected to the supply source through pipe paths.

**Causes**:
- Disconnected network components
- Source/sink junctions not properly linked via pipes
- Missing pipes in the topology

**Diagnosis**:
- Check if all junctions are reachable from the source
- Verify pipe graph connectivity (should be one connected component)
- Ensure service connections have pipes

**Solution**:
- Review network building logic
- Verify `build_trunk_topology()` creates connected paths
- Check `attach_buildings_to_street()` creates service pipes

### 2. **Mass Flow Balance Issues**

**Issue**: Source mass flow doesn't match total sink demand.

**Causes**:
- Incorrect mass flow calculations
- Sinks with zero or negative mass flow
- Source mass flow not set properly

**Diagnosis**:
```python
source_mdot = net.source['mdot_kg_per_s'].iloc[0]
total_sink_mdot = net.sink['mdot_kg_per_s'].sum()
# Should be: source_mdot ≈ total_sink_mdot
```

**Solution**:
- Set source mass flow to match total demand
- Ensure all sinks have positive mass flow rates
- Calculate mass flows from design loads correctly

### 3. **Pressure Boundary Conditions**

**Issue**: Initial pressure distribution is invalid or inconsistent.

**Causes**:
- All junctions have the same pressure (no pressure gradient)
- Pressure too low or too high
- Missing pressure boundary conditions

**Diagnosis**:
- Check junction pressures: `net.junction['pn_bar']`
- Verify pressure gradient exists
- Ensure plant has appropriate supply pressure

**Solution**:
- Set proper initial pressures
- Use pressure drop estimates for initial conditions
- Set plant pressure higher than consumer pressures

### 4. **Tree Network Topology**

**Issue**: Pure tree networks (no loops) can cause convergence issues in Newton-Raphson solver.

**Causes**:
- Network topology is a tree (no cycles)
- Single path from source to each sink

**Diagnosis**:
- Check network has at least one loop
- Verify `ConvergenceOptimizer` adds minimal loop if needed

**Solution**:
- Use `--optimize-convergence` flag (adds minimal high-resistance loop)
- Ensure `ConvergenceOptimizer` is applied

### 5. **Very Short Pipes**

**Issue**: Extremely short pipes (< 0.1m) cause numerical instabilities.

**Causes**:
- Service connections with zero or near-zero length
- Buildings very close to street attachment points

**Diagnosis**:
- Check pipe lengths: `net.pipe['length_km']`
- Identify pipes shorter than minimum threshold (e.g., 1m)

**Solution**:
- Set minimum pipe length (e.g., 1.0m)
- Apply `ConvergenceOptimizer` with `fix_short_pipes_flag=True`

### 6. **Temperature Settings**

**Issue**: Inconsistent or invalid fluid temperatures.

**Causes**:
- Supply and return temperatures not properly set
- Temperature difference too small or too large

**Diagnosis**:
- Check source temperature: `net.source['t_k']`
- Check junction temperatures: `net.junction['tfluid_k']`
- Verify temperature difference (typically 30-40K for district heating)

**Solution**:
- Set supply temperature (e.g., 80°C = 353.15K)
- Set return temperature (e.g., 50°C = 323.15K)
- Ensure temperature difference is reasonable (20-50K)

## Diagnostic Checklist

When a network fails to converge, check:

1. **Connectivity**:
   - [ ] All junctions reachable from source?
   - [ ] Network is one connected component?
   - [ ] Service pipes exist for all buildings?

2. **Mass Flow**:
   - [ ] Source mass flow > 0?
   - [ ] All sinks have positive mass flow?
   - [ ] Source mass flow ≈ sum of sink mass flows?

3. **Pressure**:
   - [ ] Plant pressure is set (e.g., 10 bar)?
   - [ ] Pressure gradient exists?
   - [ ] Initial pressures are reasonable?

4. **Topology**:
   - [ ] Network has at least one loop?
   - [ ] No extremely short pipes (< 1m)?
   - [ ] Pipe lengths are reasonable?

5. **Temperature**:
   - [ ] Supply temperature set (80°C)?
   - [ ] Temperature difference adequate (30-40K)?
   - [ ] All junctions have temperature values?

## Debugging Tools

### Check Network Structure

```python
import pickle
import networkx as nx
import pandapipes as pp

# Load network
with open('results/cha/ST001_TEST_CLUSTER/network.pickle', 'rb') as f:
    net = pickle.load(f)

# Connectivity
G = nx.Graph()
for _, pipe in net.pipe.iterrows():
    G.add_edge(pipe['from_junction'], pipe['to_junction'])

print(f'Connected components: {nx.number_connected_components(G)}')
print(f'Source junction: {net.source["junction"].iloc[0]}')
print(f'Source in graph: {net.source["junction"].iloc[0] in G}')
```

### Check Mass Balance

```python
source_mdot = net.source['mdot_kg_per_s'].iloc[0]
total_sink_mdot = net.sink['mdot_kg_per_s'].sum()
print(f'Source: {source_mdot} kg/s')
print(f'Sinks: {total_sink_mdot} kg/s')
print(f'Balance: {source_mdot - total_sink_mdot} kg/s')
```

### Check Pipe Lengths

```python
min_length = net.pipe['length_km'].min() * 1000  # Convert to meters
print(f'Shortest pipe: {min_length:.2f} m')
if min_length < 1.0:
    print('WARNING: Very short pipes detected!')
```

## Solutions for Current Test Case

The test cluster (`ST001_TEST_CLUSTER`) likely has connectivity issues because:

1. **Test data limitations**: Test buildings may not be properly connected to streets
2. **Mass flow not set**: Source/sink mass flows may be zero
3. **Topology issues**: Service connections may not create proper pipe paths

### Recommended Fixes

1. **Ensure mass flows are set before simulation**:
   ```python
   # Calculate from design loads
   cp_water = 4.186  # kJ/(kg·K)
   delta_t = 30.0  # K
   mdot_total = (total_load_kw * 1000) / (cp_water * delta_t * 1000)  # kg/s
   
   net.source.loc[0, 'mdot_kg_per_s'] = mdot_total
   net.sink['mdot_kg_per_s'] = mdot_total / len(net.sink)
   ```

2. **Verify connectivity**:
   - Check all service connections have pipes
   - Ensure trunk topology connects all buildings
   - Verify source is on the trunk network

3. **Use convergence optimization**:
   - Always use `--optimize-convergence` flag
   - This adds minimal loops and fixes topology issues

4. **Set minimum pipe lengths**:
   - Enforce minimum length (e.g., 1.0m) for all pipes
   - Especially important for service connections

## Next Steps

For real street-based clusters with proper data:

1. Verify building-to-street assignments are correct
2. Ensure street network topology is valid
3. Check that design loads are properly assigned
4. Run with `--optimize-convergence` to handle edge cases
5. Monitor convergence status in KPIs output

The convergence tracking system is working correctly - it properly identifies and reports non-convergence, which is essential for quality control.

