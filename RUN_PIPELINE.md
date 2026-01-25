# Running the CHA Pipeline

## Quick Start

To run the district heating grid pipeline for a street cluster and check convergence:

```bash
# 1. Activate the conda environment
conda activate branitz_env

# 2. Run the pipeline with convergence optimization
python src/scripts/01_run_cha.py \
  --cluster-id ST001_TEST_CLUSTER \
  --optimize-convergence \
  --verbose
```

## Command Options

- `--cluster-id`: Cluster identifier (e.g., `ST001_TEST_CLUSTER` or `ST001_AN_DEN_WEINBERGEN`)
- `--optimize-convergence`: Enable convergence optimization (recommended)
- `--attach-mode`: Building attachment mode (`split_edge_per_building` or `nearest_node`)
- `--trunk-mode`: Trunk topology mode (`paths_to_buildings` or `steiner_tree`)
- `--verbose`: Enable detailed logging

## Output Files

After running, results will be in `results/cha/{cluster_id}/`:

- `cha_kpis.json`: KPIs with convergence status
- `network.pickle`: Saved pandapipes network
- `interactive_map.html`: Interactive visualization

## Check Convergence Status

```bash
# View convergence status from KPIs
python -c "
import json
with open('results/cha/ST001_TEST_CLUSTER/cha_kpis.json', 'r') as f:
    kpis = json.load(f)
    if 'convergence' in kpis:
        conv = kpis['convergence']
        print(f'Initial Converged: {conv.get(\"initial_converged\")}')
        print(f'Final Converged: {conv.get(\"final_converged\")}')
        print(f'Optimized: {conv.get(\"optimized\")}')
"
```

## View Results

```bash
# View interactive map
open results/cha/ST001_TEST_CLUSTER/interactive_map.html

# View KPIs
cat results/cha/ST001_TEST_CLUSTER/cha_kpis.json | python -m json.tool
```

