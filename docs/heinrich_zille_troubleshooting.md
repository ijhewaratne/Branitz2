# Heinrich Zille Street - Troubleshooting Guide

## Expected: 77 Residential Buildings

You mentioned there should be **77 residential buildings** in Heinrich Zille Street. Here's how to diagnose and fix issues:

## Step 1: Check Cluster Exists

Run the diagnostic script:
```bash
python scripts/check_heinrich_zille_cluster.py
```

This will:
- Check if cluster map exists
- Search for Heinrich Zille clusters
- Count buildings in each cluster
- Verify processed buildings contain Heinrich Zille buildings
- Show recommended next steps

## Step 2: Verify Data Preparation

If cluster doesn't exist or has wrong number of buildings:

```bash
# Re-run data preparation to create clusters
python src/scripts/00_prepare_data.py --create-clusters --verbose
```

This will:
- Load raw buildings and streets
- Filter to residential with heat demand
- Match buildings to streets (address + spatial)
- Create street-based clusters
- Save `building_cluster_map.parquet` and `street_clusters.parquet`

**Check the logs** for:
- How many buildings were filtered (residential with heat demand)
- How many buildings matched to Heinrich Zille street
- If any buildings were unmatched

## Step 3: Find the Correct Cluster ID

Cluster IDs are normalized (uppercase, spaces→underscores, special chars removed).

**Heinrich Zille Street** might become:
- `ST001_HEINRICH_ZILLE_STRASSE`
- `ST001_HEINRICH_ZILLE`
- `ST042_HEINRICH_ZILLE_STRASSE` (number depends on order)

Check available clusters:
```bash
python -c "
import pandas as pd
df = pd.read_parquet('data/processed/building_cluster_map.parquet')
clusters = df.groupby('cluster_id').size().sort_values(ascending=False)
print('Top clusters by building count:')
print(clusters.head(20))
"
```

## Step 4: Run CHA Pipeline

Once you have the correct cluster ID:

```bash
python src/scripts/01_run_cha.py \
  --cluster-id ST001_HEINRICH_ZILLE_STRASSE \
  --use-trunk-spur \
  --optimize-convergence \
  --verbose
```

**Expected output**:
```
Starting CHA pipeline for cluster ST001_HEINRICH_ZILLE_STRASSE
Found cluster metadata: 77 buildings
Loaded 77 residential buildings with heat demand
...
CHA Pipeline Complete: ST001_HEINRICH_ZILLE_STRASSE
Buildings: 77
...
Results saved to results/cha/ST001_HEINRICH_ZILLE_STRASSE
```

## Step 5: Check Output Files

After pipeline completes, check outputs:

```bash
# List output files
ls -lh results/cha/ST001_HEINRICH_ZILLE_STRASSE/

# Expected files:
# - cha_kpis.json        (KPIs and compliance metrics)
# - network.pickle       (pandapipes network object)
# - interactive_map.html (Interactive visualization)
```

## Step 6: Open Interactive Map

**On macOS**:
```bash
open results/cha/ST001_HEINRICH_ZILLE_STRASSE/interactive_map.html
```

**On Linux**:
```bash
xdg-open results/cha/ST001_HEINRICH_ZILLE_STRASSE/interactive_map.html
```

**Or manually**: Navigate to the file in Finder/File Manager and double-click.

## Common Issues

### Issue 1: Cluster Not Found

**Symptoms**:
```
ValueError: No buildings found for cluster ST001_HEINRICH_ZILLE_STRASSE
```

**Solutions**:
1. Run data preparation: `python src/scripts/00_prepare_data.py --create-clusters`
2. Check cluster ID spelling (must match exactly)
3. Use diagnostic script to find correct cluster ID

### Issue 2: Wrong Number of Buildings

**Symptoms**: Pipeline runs but shows fewer than 77 buildings

**Possible Causes**:
1. **Buildings filtered out**: Not residential or no heat demand
2. **Street matching failed**: Buildings not matched to Heinrich Zille street
3. **Address parsing issue**: Street name not recognized

**Solutions**:
1. Check filtering logs during data preparation
2. Check `data/processed/buildings.parquet` - how many total residential buildings?
3. Check raw building addresses for Heinrich Zille

### Issue 3: No Output Files Generated

**Symptoms**: Pipeline runs but no files in `results/cha/{cluster_id}/`

**Possible Causes**:
1. Pipeline failed before output generation
2. Wrong output directory
3. Permission issues

**Solutions**:
1. Check pipeline logs for errors
2. Verify `results/cha/{cluster_id}/` directory exists
3. Check file permissions

### Issue 4: Interactive Map Not Opening

**Symptoms**: HTML file exists but doesn't open or shows blank page

**Solutions**:
1. Check file size: `ls -lh results/cha/*/interactive_map.html` (should be > 10KB)
2. Try opening in different browser
3. Check browser console for JavaScript errors
4. Verify network converged (non-converged networks may have incomplete maps)

## Debugging Steps

### 1. Check Raw Building Data

```python
import geopandas as gpd

# Load raw buildings
buildings = gpd.read_file("data/raw/hausumringe_mit_adressenV3.geojson")

# Find Heinrich Zille buildings
heinrich = buildings[buildings['adressen'].astype(str).str.contains('HEINRICH|ZILLE', case=False, na=False)]
print(f"Total Heinrich Zille buildings in raw data: {len(heinrich)}")
print(f"Residential: {heinrich['building_function'].str.contains('wohn', case=False, na=False).sum()}")
```

### 2. Check Filtering

```python
from branitz_heat_decision.data.loader import load_processed_buildings

# Load processed buildings
buildings = load_processed_buildings()

# Check filtering stats
print(f"Total processed buildings: {len(buildings)}")
print(f"Residential: {buildings['use_type'].str.contains('residential', case=False).sum()}")
```

### 3. Check Cluster Map

```python
import pandas as pd

# Load cluster map
cluster_map = pd.read_parquet("data/processed/building_cluster_map.parquet")

# Find Heinrich Zille cluster
heinrich = cluster_map[cluster_map['cluster_id'].str.contains('HEINRICH|ZILLE', case=False)]
print(f"Cluster IDs: {heinrich['cluster_id'].unique()}")
print(f"Building counts: {heinrich.groupby('cluster_id').size()}")
```

## Expected Workflow

```
1. Prepare Data
   python src/scripts/00_prepare_data.py --create-clusters
   
2. Check Cluster
   python scripts/check_heinrich_zille_cluster.py
   
3. Run CHA Pipeline
   python src/scripts/01_run_cha.py \
     --cluster-id <CORRECT_CLUSTER_ID> \
     --use-trunk-spur
   
4. Verify Outputs
   ls -lh results/cha/<CLUSTER_ID>/
   
5. Open Map
   open results/cha/<CLUSTER_ID>/interactive_map.html
```

## Getting Help

If issues persist:

1. **Check logs**: Run with `--verbose` flag
2. **Verify data**: Ensure raw data files exist and are valid
3. **Check cluster creation**: Verify street matching logic
4. **Review filtering**: Ensure buildings aren't being incorrectly filtered

## Quick Reference

**Cluster ID format**: `ST{number}_{STREET_NAME}` (uppercase, underscores)

**Expected outputs**:
- `results/cha/{cluster_id}/cha_kpis.json`
- `results/cha/{cluster_id}/network.pickle`
- `results/cha/{cluster_id}/interactive_map.html`

**Open map**: `open results/cha/{cluster_id}/interactive_map.html`

