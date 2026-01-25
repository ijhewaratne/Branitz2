# Run CHA Pipeline for Heinrich Zille Street - READY TO EXECUTE

## ✅ Setup Complete

The pipeline is configured to use:
- **Spur optimizer**: `convergence_optimizer_spur.py` (optimized for trunk-spur networks)
- **Trunk-spur builder**: Creates strict street-following topology
- **Per-building loads**: Proportional distribution based on floor area

## 🚀 Quick Run

**Option 1: Automated Script** (Recommended)

```bash
conda activate branitz_env
python scripts/run_cha_for_heinrich_zille.py
```

**Option 2: Manual Command**

```bash
conda activate branitz_env

# First, find the cluster ID
python scripts/check_heinrich_zille_cluster.py

# Then run (use the cluster ID from above)
python src/scripts/01_run_cha.py \
  --cluster-id <CLUSTER_ID> \
  --use-trunk-spur \
  --optimize-convergence \
  --verbose
```

## 📋 What Happens

1. **Finds Heinrich Zille cluster** (or uses fallback if not found)
2. **Loads 77 residential buildings** (or count found)
3. **Builds trunk-spur network**:
   - Trunk along streets
   - Exclusive spurs to each building
4. **Assigns design loads** per building
5. **Runs pipeflow simulation** (pandapipes)
6. **Optimizes with spur optimizer** (fixes convergence)
7. **Extracts KPIs** (EN 13941-1 compliance)
8. **Generates outputs**:
   - `results/cha/{cluster_id}/cha_kpis.json`
   - `results/cha/{cluster_id}/network.pickle`
   - `results/cha/{cluster_id}/interactive_map.html`

## 📊 View Results

After pipeline completes:

```bash
# Check outputs
ls -lh results/cha/*/interactive_map.html

# View KPIs
cat results/cha/*/cha_kpis.json | python -m json.tool | head -50

# Open map
open results/cha/*/interactive_map.html
```

## 🔍 Spur Optimizer Features

The `convergence_optimizer_spur.py` provides:

1. **Spur Topology Validation**:
   - Building junctions must have degree = 2
   - Spur junctions must have degree = 3
   - Trunk junctions degree ≤ 4

2. **Symmetry Breaking**:
   - Adds random length variations (±10%) to spur pipes
   - Prevents numerical issues from identical pipe lengths

3. **Load Balancing**:
   - Adds virtual bypass pipes for overloaded junctions
   - Creates alternative paths without major topology changes

4. **Connectivity**:
   - Ensures all network components are connected
   - Adds virtual bridges if needed

## ⚙️ Configuration

The pipeline uses:
- **Network Builder**: Trunk-spur (strict street-following)
- **Optimizer**: Spur-specific (`convergence_optimizer_spur.py`)
- **Convergence**: Automatic optimization if needed
- **Output**: JSON, pickle, HTML map

## 📍 Pipeline Flow Summary

```
Data Loading
    ↓
Network Building (Trunk-Spur)
    ↓
Design Load Assignment (Per-Building)
    ↓
Pipeflow Simulation
    ↓
Spur Optimizer (if needed)
    ↓
KPI Extraction
    ↓
Output Generation
```

See `docs/cha_pipeline_flow.md` for detailed explanation.

