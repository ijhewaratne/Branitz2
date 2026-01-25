# District Heating Grid Convergence Checking

## Overview

This document explains how to lay a district heating grid for a street-based cluster and check for numerical convergence.

## Running the CHA Pipeline

To lay a district heating grid for a street cluster and check convergence:

```bash
# Activate conda environment
conda activate branitz_env

# Run CHA pipeline with convergence optimization
python src/scripts/01_run_cha.py \
  --cluster-id ST001_AN_DEN_WEINBERGEN \
  --optimize-convergence \
  --verbose
```

### Command Line Arguments

- `--cluster-id`: Street cluster ID (format: `ST{number}_{STREET_NAME}`)
- `--optimize-convergence`: Enable convergence optimization (recommended)
- `--attach-mode`: Building attachment mode (`split_edge_per_building` or `nearest_node`)
- `--trunk-mode`: Trunk topology mode (`paths_to_buildings` or `steiner_tree`)
- `--verbose`: Enable detailed logging

## Convergence Checking Process

The pipeline performs the following convergence checks:

### 1. Initial Simulation

After building the network, an initial pandapipes simulation is run:
- Checks if `net.converged` is `True` after `pp.pipeflow()`
- Logs convergence status

### 2. Convergence Optimization (if enabled)

If `--optimize-convergence` is used or initial simulation fails:
- Runs `ConvergenceOptimizer` to fix topology issues
- Applies fixes for:
  - Parallel paths (adds roughness variations)
  - Missing loops (adds minimal high-resistance loop)
  - Connectivity issues
  - Pressure distribution
  - Short pipes
- Runs simulation again after optimization

### 3. Final Convergence Status

The final convergence status is recorded in:
- Console output
- `cha_kpis.json` file (in `convergence` section)

## Output Files

### `cha_kpis.json`

Contains convergence status in the `convergence` section:

```json
{
  "convergence": {
    "initial_converged": true,
    "final_converged": true,
    "optimized": false
  },
  "feasible": true,
  ...
}
```

Fields:
- `initial_converged`: Whether the initial simulation converged
- `final_converged`: Whether the final simulation converged
- `optimized`: Whether optimization was applied
- `warning`: Optional warning message if KPIs from non-converged network

### `network.pickle`

Saved pandapipes network object (can be loaded to inspect convergence):
```python
import pickle
with open('results/cha/ST001_AN_DEN_WEINBERGEN/network.pickle', 'rb') as f:
    net = pickle.load(f)
    print(f"Converged: {net.converged}")
```

### `interactive_map.html`

Interactive visualization of the network (even if not converged).

## Checking Convergence Status

### From Command Line

```bash
# Check convergence status from KPIs
python -c "
import json
with open('results/cha/ST001_AN_DEN_WEINBERGEN/cha_kpis.json', 'r') as f:
    kpis = json.load(f)
    if 'convergence' in kpis:
        conv = kpis['convergence']
        print(f'Initial: {conv.get(\"initial_converged\")}')
        print(f'Final: {conv.get(\"final_converged\")}')
        print(f'Optimized: {conv.get(\"optimized\")}')
"
```

### From Python

```python
import json
from pathlib import Path

kpis_path = Path('results/cha/ST001_AN_DEN_WEINBERGEN/cha_kpis.json')
with open(kpis_path, 'r') as f:
    kpis = json.load(f)
    
if kpis.get('convergence', {}).get('final_converged'):
    print("✓ Network converged successfully")
else:
    print("✗ Network did not converge")
    if 'warning' in kpis.get('convergence', {}):
        print(f"Warning: {kpis['convergence']['warning']}")
```

## Troubleshooting Non-Convergence

If the network does not converge:

1. **Check network topology**:
   - Tree networks (no loops) often fail
   - Optimization should add minimal loop

2. **Check pipe lengths**:
   - Very short pipes (< 1m) can cause issues
   - Optimization fixes short pipes

3. **Check pressure distribution**:
   - Poor initial pressures can prevent convergence
   - Optimization improves pressure distribution

4. **Review logs**:
   - Enable `--verbose` to see optimization steps
   - Check which fixes were applied

5. **Manual inspection**:
   ```python
   import pickle
   net = pickle.load(open('results/cha/ST001_AN_DEN_WEINBERGEN/network.pickle', 'rb'))
   print(f"Junctions: {len(net.junction)}")
   print(f"Pipes: {len(net.pipe)}")
   print(f"Sinks: {len(net.sink)}")
   print(f"Sources: {len(net.source)}")
   ```

## Example Workflow

```bash
# 1. List available clusters
python -c "
import pandas as pd
clusters = pd.read_parquet('data/processed/street_clusters.parquet')
print(clusters[['street_id', 'building_count']].head())
"

# 2. Run pipeline for a cluster
python src/scripts/01_run_cha.py \
  --cluster-id ST001_AN_DEN_WEINBERGEN \
  --optimize-convergence \
  --verbose

# 3. Check convergence status
python -c "
import json
with open('results/cha/ST001_AN_DEN_WEINBERGEN/cha_kpis.json') as f:
    kpis = json.load(f)
    conv = kpis.get('convergence', {})
    print(f'Converged: {conv.get(\"final_converged\", False)}')
"

# 4. View interactive map
open results/cha/ST001_AN_DEN_WEINBERGEN/interactive_map.html
```

