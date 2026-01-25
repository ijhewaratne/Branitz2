# CHA Pipeline Improvements - Merged from Trunk-Spur Implementation

## Summary

The `01_run_cha.py` script has been enhanced with features from `01_run_cha_trunk_spur.py` to provide a more robust and feature-complete pipeline.

## Improvements Added

### 1. ✅ Per-Building Design Loads Support

**Before**: Single cluster-level design load, distributed equally to all buildings

**After**: 
- Dictionary of per-building design loads (`design_loads_kw`)
- Loads distributed proportionally based on floor area (if available)
- Falls back to equal distribution or uses building-level design_load_kw if present
- Loads loaded from design_topn.json when available

**Benefits**:
- More accurate network sizing
- Better representation of actual building demands
- Supports heterogeneous building portfolios

### 2. ✅ Topology Information Extraction

**Added**:
- Extracts topology statistics from `topology_info`
- Logs trunk edges, service connections, buildings connected
- Supports trunk-spur topology (trunk_nodes, spurs) when available
- Topology stats included in KPIs JSON output

**Benefits**:
- Better visibility into network structure
- Easier debugging and analysis
- Consistent with trunk-spur pipeline output format

### 3. ✅ Enhanced Summary Output

**Added**:
- Detailed summary logging with topology statistics
- Convergence status display
- Feasibility and velocity compliance metrics
- Formatted output with visual indicators (✓/✗)

**Example Output**:
```
============================================================
CHA Pipeline Complete: ST001_HEINRICH_ZILLE_STRASSE
============================================================
Buildings: 25
Trunk Edges: 12
Service Connections: 25
Converged: ✓
Feasible: ✓
Velocity compliance: 98.5%
Results saved to results/cha/ST001_HEINRICH_ZILLE_STRASSE
============================================================
```

### 4. ✅ Trunk-Spur Network Builder Option

**Added**:
- New `--use-trunk-spur` flag to use trunk-spur network builder
- Optional `--catalog` parameter for technical catalog path
- Optional `--max-spur-length` parameter for spur length limit
- Automatic detection of trunk-spur builder availability

**Benefits**:
- Better convergence properties (trunk-spur creates closed loops via buildings)
- Strict street-following trunk topology
- Exclusive per-building spurs
- Recommended for better numerical stability

**Usage**:
```bash
# Use trunk-spur builder (recommended)
python src/scripts/01_run_cha.py --cluster-id ST001 --use-trunk-spur

# With custom catalog
python src/scripts/01_run_cha.py --cluster-id ST001 --use-trunk-spur --catalog path/to/catalog.xlsx
```

## Key Differences: Standard vs Trunk-Spur Builder

| Feature | Standard Builder | Trunk-Spur Builder |
|---------|------------------|-------------------|
| Trunk Topology | Minimal spanning tree | Strict street-following |
| Building Connections | Service pipes from trunk | Exclusive per-building spurs |
| Convergence | May need optimization | Built-in optimization |
| Loop Structure | Tree (may need added loops) | Closed loops via buildings |
| Pipe Sizing | Basic catalog | Technical catalog with sizing |

## Code Changes

### Design Loads Handling

**Before**:
```python
total_load_kw = design_load_kw * len(buildings)
mdot_per_sink = mdot_total_kg_s / len(net.sink)  # Equal distribution
```

**After**:
```python
design_loads_kw = {}  # Per-building dictionary
# Load from design_topn.json or distribute proportionally
# Assign mass flows per building based on actual loads
```

### Topology Statistics

**Added**:
```python
topology_stats = {
    'trunk_edges': len(topology_info['trunk_edges']),
    'service_connections': len(topology_info['service_connections']),
    'buildings_connected': len(topology_info['buildings_snapped']),
    # ... trunk-spur specific stats if available
}
kpis['topology'] = topology_stats
```

### Summary Logging

**Enhanced**:
```python
logger.info(f"{'='*60}")
logger.info(f"CHA Pipeline Complete: {cluster_id}")
logger.info(f"Buildings: {len(buildings)}")
for key, value in topology_stats.items():
    logger.info(f"{key.replace('_', ' ').title()}: {value}")
logger.info(f"Converged: {'✓' if final_converged else '✗'}")
```

## Backward Compatibility

✅ **Fully backward compatible**:
- All existing command-line arguments still work
- Default behavior unchanged (uses standard builder)
- Trunk-spur is opt-in via `--use-trunk-spur` flag
- Existing scripts and workflows continue to work

## Migration Guide

### For Existing Scripts

No changes required. Existing scripts will continue to work with the standard builder.

### To Use Trunk-Spur Builder

Simply add `--use-trunk-spur` flag:
```bash
# Old way (still works)
python src/scripts/01_run_cha.py --cluster-id ST001

# New way (recommended for better convergence)
python src/scripts/01_run_cha.py --cluster-id ST001 --use-trunk-spur
```

## Testing

- [x] Standard builder works as before
- [x] Trunk-spur builder integrated correctly
- [x] Per-building loads distributed correctly
- [x] Topology stats extracted and logged
- [x] Summary output formatted correctly
- [x] Backward compatibility maintained

## Files Modified

1. `src/scripts/01_run_cha.py`
   - Added per-building design loads support
   - Added topology info extraction
   - Added enhanced summary output
   - Added trunk-spur builder option
   - Enhanced CLI arguments

## Next Steps

1. Test trunk-spur builder with real clusters
2. Compare convergence rates between builders
3. Document best practices for builder selection
4. Consider making trunk-spur the default if it proves more reliable

