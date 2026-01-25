# How to Run CHA Pipeline for Heinrich Zille Street

## Quick Start (Automated)

```bash
# Run the automated script (handles conda activation and finds cluster)
./scripts/run_cha_heinrich_zille.sh
```

## Manual Steps

### Step 1: Activate Conda Environment

```bash
conda activate branitz_env
```

### Step 2: Find Heinrich Zille Cluster ID

```bash
python scripts/check_heinrich_zille_cluster.py
```

This will show you the correct cluster ID (e.g., `ST001_HEINRICH_ZILLE_STRASSE`)

### Step 3: Run CHA Pipeline

```bash
python src/scripts/01_run_cha.py \
  --cluster-id ST001_HEINRICH_ZILLE_STRASSE \
  --use-trunk-spur \
  --optimize-convergence \
  --verbose
```

**Note**: The pipeline now uses `convergence_optimizer_spur.py` which is specifically designed for trunk-spur networks with:
- Spur-specific topology validation
- Building junction degree checks
- Spur length variation to break symmetry
- Virtual bypass pipes for overloaded junctions

### Step 4: Check Outputs

```bash
# List output files
ls -lh results/cha/ST001_HEINRICH_ZILLE_STRASSE/

# View KPIs (first 50 lines)
cat results/cha/ST001_HEINRICH_ZILLE_STRASSE/cha_kpis.json | python -m json.tool | head -50
```

### Step 5: Open Interactive Map

```bash
open results/cha/ST001_HEINRICH_ZILLE_STRASSE/interactive_map.html
```

## What the Pipeline Does

1. **Loads Data**: Buildings, streets, design loads for Heinrich Zille cluster
2. **Builds Network**: Creates trunk-spur topology (trunk along streets + exclusive spurs to buildings)
3. **Assigns Loads**: Sets mass flow rates per building based on heat demand
4. **Runs Simulation**: Solves hydraulic equations using pandapipes `pipeflow()`
5. **Optimizes**: Uses spur optimizer to fix convergence issues
6. **Extracts KPIs**: EN 13941-1 compliance metrics
7. **Generates Outputs**: JSON, pickle, HTML map

## Spur Optimizer Features

The `convergence_optimizer_spur.py` includes:

- **Spur Topology Validation**: Checks building junction degrees, spur junction degrees, trunk junction limits
- **Symmetry Breaking**: Adds length variations to spur pipes to avoid numerical issues
- **Load Balancing**: Adds virtual bypass pipes for overloaded junctions
- **Connectivity**: Ensures all network components are connected

## Expected Output

```
Starting CHA pipeline for cluster ST001_HEINRICH_ZILLE_STRASSE
Found cluster metadata: 77 buildings
Loaded 77 residential buildings with heat demand
Building trunk-spur network...
Trunk-spur network built: converged=True
Extracting KPIs...
Saved KPIs to results/cha/ST001_HEINRICH_ZILLE_STRASSE/cha_kpis.json
Saved network to results/cha/ST001_HEINRICH_ZILLE_STRASSE/network.pickle
Generating interactive map...
Saved interactive map to results/cha/ST001_HEINRICH_ZILLE_STRASSE/interactive_map.html
```

## Troubleshooting

**If cluster not found**: Run data preparation first
```bash
python src/scripts/00_prepare_data.py --create-clusters
```

**If pipeline fails**: Check logs with `--verbose` flag

**If network doesn't converge**: The spur optimizer should handle this automatically

