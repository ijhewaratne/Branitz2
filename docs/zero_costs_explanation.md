# Why Pipe and Pump Costs Show as 0

## Summary

The pipe and pump costs showing as 0 in the UI can have several causes:

### 1. **Pump Power Always Shows 0** ⚠️

**Root Cause**: Pandapipes `create_circ_pump_const_pressure` does not automatically populate the `p_kw` column in `res_circ_pump_const_pressure` results table.

**Current Code** (`kpi_extractor.py` lines 268-270):
```python
if hasattr(self.net, "res_circ_pump_const_pressure") and self.net.res_circ_pump_const_pressure is not None:
    if "p_kw" in self.net.res_circ_pump_const_pressure.columns:
        pump_power_kw = float(self.net.res_circ_pump_const_pressure["p_kw"].sum())
```

**Why It's 0**:
- The `res_circ_pump_const_pressure` table may exist but the `p_kw` column might not be populated
- Pandapipes calculates pump power but may store it differently (e.g., `p_mw` instead of `p_kw`)
- The pump power might need to be calculated manually from flow and pressure lift

**Solution**: Calculate pump power manually:
```python
# Calculate pump power from flow and pressure lift
if hasattr(net, "circ_pump_const_pressure") and net.circ_pump_const_pressure is not None:
    for idx, pump in net.circ_pump_const_pressure.iterrows():
        plift_bar = pump["plift_bar"]
        # Get flow from results
        if hasattr(net, "res_circ_pump_const_pressure"):
            mdot_kg_per_s = net.res_circ_pump_const_pressure.loc[idx, "mdot_kg_per_s"]
            # P = mdot * g * H / efficiency
            # For water: P = mdot * plift_bar * 100000 / (rho * efficiency)
            rho = 1000  # kg/m³
            efficiency = 0.75
            p_kw = (mdot_kg_per_s * plift_bar * 100000) / (rho * efficiency * 1000)
```

### 2. **Pipe Costs Show 0 for Some Clusters**

**Root Cause**: The economics script (`03_run_economics.py`) loads pipe lengths from:
1. **Primary source**: `results/cha/<cluster_id>/pipe_velocities_supply_return_with_temp.csv`
   - Must have `length_m` and `diameter_mm` columns
2. **Fallback**: `results/cha/<cluster_id>/cha_kpis.json`
   - Looks for `losses.length_supply_m`, `losses.length_return_m`, `losses.length_service_m`

**Why It's 0**:
- **CSV file doesn't exist**: CHA pipeline didn't generate the CSV
- **CSV exists but missing columns**: The CSV was generated but doesn't have `length_m` or `diameter_mm`
- **CHA not run**: The cluster hasn't run CHA yet, so no pipe data exists
- **Wrong cluster**: The UI might be displaying a different cluster than expected

**Verification Steps**:
```bash
# Check if CSV exists
ls results/cha/<cluster_id>/pipe_velocities_supply_return_with_temp.csv

# Check CSV columns
head -1 results/cha/<cluster_id>/pipe_velocities_supply_return_with_temp.csv

# Check economics file
cat results/economics/<cluster_id>/economics_deterministic.json | jq '.pipe_lengths_by_dn_m'
```

**Solution**: 
1. Ensure CHA pipeline runs completely and generates the CSV
2. Verify the CSV has `length_m` and `diameter_mm` columns
3. Re-run economics: `python src/scripts/03_run_economics.py --cluster-id <cluster_id>`

### 3. **Why Your Example Shows 0**

Based on the image you shared, if you're seeing:
- `capex_pipes: 0`
- `capex_pump: 0`
- `capex_plant: 50000`

This suggests:
1. **Pump**: Always 0 (known issue - pump power not extracted correctly)
2. **Pipes**: Either:
   - The cluster you're viewing hasn't run CHA
   - The CSV file wasn't generated
   - The economics was run before CHA completed

**To Fix**:
1. **For Pipes**: Re-run CHA for the cluster, then re-run economics
2. **For Pump**: This is a code issue that needs to be fixed in `kpi_extractor.py`

## Current Status by Cluster

From recent economics files:
- ✅ `ST001_AN_DEN_WEINBERGEN`: pipes=178,671 EUR, pump=0
- ✅ `ST002_ANTON_BRUCKNER_STRASSE`: pipes=74,590 EUR, pump=0
- ✅ `ST003_BLEYERSTRASSE`: pipes=199,154 EUR, pump=0
- ❌ `ST005_CLEMENTINESTRASSE`: pipes=0, pump=0 (needs CHA run)
- ✅ `ST010_HEINRICH_ZILLE_STRASSE`: pipes=2,010,629 EUR, pump=0

## Recommended Fixes

### Fix 1: Pump Power Calculation
Update `src/branitz_heat_decision/cha/kpi_extractor.py` to calculate pump power from flow and pressure:

```python
# Calculate pump power from flow and pressure lift
pump_power_kw = 0.0
if hasattr(net, "circ_pump_const_pressure") and net.circ_pump_const_pressure is not None:
    for idx, pump in net.circ_pump_const_pressure.iterrows():
        plift_bar = float(pump["plift_bar"])
        # Get mass flow from results
        if hasattr(net, "res_circ_pump_const_pressure") and net.res_circ_pump_const_pressure is not None:
            if idx in net.res_circ_pump_const_pressure.index:
                mdot_kg_per_s = float(net.res_circ_pump_const_pressure.loc[idx, "mdot_kg_per_s"])
                # P = (mdot * plift * 100000) / (rho * efficiency * 1000)
                # where plift is in bar, convert to Pa: plift_bar * 100000
                rho = 1000.0  # kg/m³
                efficiency = 0.75
                p_kw = (mdot_kg_per_s * plift_bar * 100000.0) / (rho * efficiency * 1000.0)
                pump_power_kw += p_kw
```

### Fix 2: Ensure CSV Generation
Verify that `01_run_cha.py` always generates the CSV file with required columns.

### Fix 3: Add Validation
Add checks in `03_run_economics.py` to warn if pipe lengths are 0:
```python
if total_pipe_length_m == 0:
    logger.warning(f"No pipe lengths found for {cluster_id}. CHA may not have completed.")
```
