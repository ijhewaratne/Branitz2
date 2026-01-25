# Quick Start: Run CHA Pipeline for Heinrich Zille Street

## 1. Check Cluster (Diagnostic)

```bash
python scripts/check_heinrich_zille_cluster.py
```

This shows:
- If cluster exists
- How many buildings in cluster
- Correct cluster ID to use

## 2. Run CHA Pipeline

```bash
# Use the cluster ID from step 1
python src/scripts/01_run_cha.py \
  --cluster-id ST001_HEINRICH_ZILLE_STRASSE \
  --use-trunk-spur \
  --optimize-convergence \
  --verbose
```

## 3. Check Outputs

```bash
# List output files
ls -lh results/cha/ST001_HEINRICH_ZILLE_STRASSE/

# View KPIs
cat results/cha/ST001_HEINRICH_ZILLE_STRASSE/cha_kpis.json | python -m json.tool | head -50
```

## 4. Open Interactive Map

```bash
open results/cha/ST001_HEINRICH_ZILLE_STRASSE/interactive_map.html
```

## Pipeline Flow (Quick Reference)

1. **Load Data** → Buildings, streets, plant coords, design loads
2. **Build Network** → Create topology (trunk + spurs or standard)
3. **Assign Loads** → Set mass flow rates per building
4. **Simulate** → Solve hydraulic equations
5. **Optimize** → Fix convergence if needed
6. **Extract KPIs** → EN 13941-1 compliance metrics
7. **Save Outputs** → JSON, pickle, HTML map

See `docs/cha_pipeline_flow.md` for detailed explanation.

