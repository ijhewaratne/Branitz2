#!/bin/bash
# Run CHA Pipeline for Heinrich Zille Street
# Uses spur-specific optimizer

set -e

echo "=========================================="
echo "CHA Pipeline: Heinrich Zille Street"
echo "=========================================="
echo ""

# Activate conda environment
echo "Activating conda environment..."
source $(conda info --base)/etc/profile.d/conda.sh
conda activate branitz_env

echo "Environment activated: $(conda info --envs | grep '*')"
echo ""

# Check if cluster exists first
echo "Checking for Heinrich Zille clusters..."
python3 << 'PYEOF'
import sys
sys.path.insert(0, 'src')
import pandas as pd
from pathlib import Path

cluster_map_path = Path("data/processed/building_cluster_map.parquet")
if cluster_map_path.exists():
    cluster_map = pd.read_parquet(cluster_map_path)
    heinrich = cluster_map[cluster_map['cluster_id'].str.contains('HEINRICH|ZILLE', case=False, na=False)]
    
    if len(heinrich) > 0:
        print("\n✅ Found Heinrich Zille clusters:")
        for cluster_id, group in heinrich.groupby('cluster_id'):
            print(f"   {cluster_id}: {len(group)} buildings")
        print("\n")
    else:
        print("\n⚠️  No Heinrich Zille clusters found.")
        print("   Available clusters:")
        for cid in sorted(cluster_map['cluster_id'].unique())[:5]:
            count = len(cluster_map[cluster_map['cluster_id'] == cid])
            print(f"   {cid}: {count} buildings")
        print("\n⚠️  Will try with first available cluster or fail if none match")
        print("")
else:
    print("\n❌ Cluster map not found. Run data preparation first:")
    print("   python src/scripts/00_prepare_data.py --create-clusters")
    sys.exit(1)
PYEOF

# Find Heinrich Zille cluster ID
CLUSTER_ID=$(python3 << 'PYEOF'
import sys
sys.path.insert(0, 'src')
import pandas as pd
from pathlib import Path

cluster_map_path = Path("data/processed/building_cluster_map.parquet")
if cluster_map_path.exists():
    cluster_map = pd.read_parquet(cluster_map_path)
    heinrich = cluster_map[cluster_map['cluster_id'].str.contains('HEINRICH|ZILLE', case=False, na=False)]
    
    if len(heinrich) > 0:
        cluster_id = heinrich['cluster_id'].iloc[0]
        print(cluster_id)
    else:
        # Try to find any cluster with reasonable number of buildings
        clusters = cluster_map.groupby('cluster_id').size()
        if len(clusters) > 0:
            # Get cluster with most buildings
            cluster_id = clusters.idxmax()
            print(cluster_id)
        else:
            sys.exit(1)
else:
    sys.exit(1)
PYEOF
)

if [ -z "$CLUSTER_ID" ]; then
    echo "❌ Could not find cluster ID. Please run data preparation first:"
    echo "   python src/scripts/00_prepare_data.py --create-clusters"
    exit 1
fi

echo "Using cluster ID: $CLUSTER_ID"
echo ""

# Run CHA pipeline
echo "Running CHA pipeline with spur optimizer..."
echo ""

python src/scripts/01_run_cha.py \
  --cluster-id "$CLUSTER_ID" \
  --use-trunk-spur \
  --optimize-convergence \
  --verbose

EXIT_CODE=$?

echo ""
if [ $EXIT_CODE -eq 0 ]; then
    echo "=========================================="
    echo "✅ Pipeline completed successfully!"
    echo "=========================================="
    echo ""
    echo "Output files:"
    echo "  - results/cha/$CLUSTER_ID/cha_kpis.json"
    echo "  - results/cha/$CLUSTER_ID/network.pickle"
    echo "  - results/cha/$CLUSTER_ID/interactive_map.html"
    echo ""
    echo "Open interactive map:"
    echo "  open results/cha/$CLUSTER_ID/interactive_map.html"
    echo ""
else
    echo "=========================================="
    echo "❌ Pipeline failed with exit code $EXIT_CODE"
    echo "=========================================="
    echo ""
    echo "Check the error messages above for details."
    exit $EXIT_CODE
fi

