# CHA Pipeline Results Summary

## Current Status

An interactive map exists at:
- `results/cha/ST001_TEST_CLUSTER/interactive_map.html` (70KB, created Jan 4 02:22)

However, the KPIs file (`cha_kpis.json`) is missing, suggesting a previous run may have failed partway through.

## To Run the Pipeline

The conda environment exists but needs to be activated. Based on `environment.yml`, the environment name is `branitz_heat`:

```bash
# Activate environment
conda activate branitz_heat

# Run the pipeline
python src/scripts/01_run_cha.py \
  --cluster-id ST001_TEST_CLUSTER \
  --optimize-convergence \
  --verbose
```

## Expected Output Structure

After successful execution, you should see in `results/cha/ST001_TEST_CLUSTER/`:

```
results/cha/ST001_TEST_CLUSTER/
├── cha_kpis.json          # KPIs with convergence status
├── network.pickle         # Saved pandapipes network
└── interactive_map.html   # Interactive visualization (already exists)
```

## Expected Console Output

The pipeline will show:

1. **Loading cluster data**
   - Building count
   - Street segments loaded
   - Plant coordinates

2. **Network building**
   - Street graph construction
   - Building attachment
   - Trunk topology

3. **Simulation**
   - Initial simulation convergence status
   - Optimization steps (if enabled)
   - Final convergence status

4. **Results**
   - Convergence Status summary
   - Output file paths

## Checking Results

After running, check convergence status:

```bash
python -c "
import json
with open('results/cha/ST001_TEST_CLUSTER/cha_kpis.json', 'r') as f:
    kpis = json.load(f)
    if 'convergence' in kpis:
        conv = kpis['convergence']
        print('Convergence Status:')
        print(f'  Initial: {conv.get(\"initial_converged\")}')
        print(f'  Final: {conv.get(\"final_converged\")}')
        print(f'  Optimized: {conv.get(\"optimized\")}')
"
```

## View Interactive Map

```bash
open results/cha/ST001_TEST_CLUSTER/interactive_map.html
```

The interactive map shows:
- District heating network topology
- Buildings with heat demand
- Pipe segments colored by velocity
- Service connections

