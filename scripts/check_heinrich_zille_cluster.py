#!/usr/bin/env python3
"""
Diagnostic script to check Heinrich Zille Street cluster.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import pandas as pd
from branitz_heat_decision.config import (
    BUILDING_CLUSTER_MAP_PATH, DATA_PROCESSED, DATA_RAW,
    BUILDINGS_PATH
)

def main():
    print("=" * 70)
    print("HEINRICH ZILLE STREET CLUSTER DIAGNOSTICS")
    print("=" * 70)
    print()
    
    # Check if cluster map exists
    if not BUILDING_CLUSTER_MAP_PATH.exists():
        print(f"❌ Cluster map not found: {BUILDING_CLUSTER_MAP_PATH}")
        print("\n👉 Solution: Run data preparation first:")
        print("   python src/scripts/00_prepare_data.py --create-clusters")
        return
    
    cluster_map = pd.read_parquet(BUILDING_CLUSTER_MAP_PATH)
    print(f"✅ Cluster map loaded: {len(cluster_map)} total building-cluster mappings")
    print()
    
    # Search for Heinrich Zille clusters
    heinrich_clusters = cluster_map[
        cluster_map['cluster_id'].str.contains('HEINRICH|ZILLE', case=False, na=False)
    ]
    
    if len(heinrich_clusters) == 0:
        print("❌ No clusters found with 'HEINRICH' or 'ZILLE' in cluster ID")
        print("\n📋 Available clusters (first 20):")
        for cid in sorted(cluster_map['cluster_id'].unique())[:20]:
            count = len(cluster_map[cluster_map['cluster_id'] == cid])
            print(f"   {cid}: {count} buildings")
        print("\n💡 Tip: Cluster IDs are normalized (spaces→underscores, uppercase)")
        print("   Try searching for partial matches or check raw street names")
        return
    
    print(f"✅ Found {len(heinrich_clusters)} Heinrich Zille clusters:")
    print()
    
    for cluster_id, group in heinrich_clusters.groupby('cluster_id'):
        print(f"   Cluster ID: {cluster_id}")
        print(f"   Buildings in cluster: {len(group)}")
        
        # Check if it matches expected 77
        if len(group) == 77:
            print(f"   ✅ Correct number: 77 buildings")
        else:
            print(f"   ⚠️  Expected 77, found {len(group)}")
        
        print(f"   Building IDs (first 10): {list(group['building_id'].head(10))}")
        print()
    
    # Check processed buildings
    print("=" * 70)
    print("CHECKING PROCESSED BUILDINGS")
    print("=" * 70)
    print()
    
    if BUILDINGS_PATH.exists():
        import geopandas as gpd
        buildings = gpd.read_parquet(BUILDINGS_PATH)
        print(f"✅ Processed buildings file: {len(buildings)} buildings")
        print(f"   Filtered: {buildings.attrs.get('filtered', False)}")
        print(f"   Filter criteria: {buildings.attrs.get('filter_criteria', 'N/A')}")
        
        # Check if Heinrich Zille buildings are in processed file
        heinrich_building_ids = heinrich_clusters['building_id'].unique()
        in_processed = buildings[buildings['building_id'].isin(heinrich_building_ids)]
        print(f"\n   Heinrich Zille buildings in processed file: {len(in_processed)}/{len(heinrich_building_ids)}")
        
        if len(in_processed) < len(heinrich_building_ids):
            missing = len(heinrich_building_ids) - len(in_processed)
            print(f"   ⚠️  {missing} buildings missing (may have been filtered out)")
            print(f"      These buildings may not be residential or have no heat demand")
    else:
        print(f"❌ Processed buildings file not found: {BUILDINGS_PATH}")
        print("\n👉 Solution: Run data preparation first")
    
    print()
    print("=" * 70)
    print("RECOMMENDED ACTIONS")
    print("=" * 70)
    print()
    
    if len(heinrich_clusters) > 0:
        cluster_id = heinrich_clusters['cluster_id'].iloc[0]
        print(f"1. Run CHA pipeline for cluster: {cluster_id}")
        print()
        print(f"   python src/scripts/01_run_cha.py \\")
        print(f"     --cluster-id {cluster_id} \\")
        print(f"     --use-trunk-spur \\")
        print(f"     --optimize-convergence")
        print()
        print(f"2. Check outputs in: results/cha/{cluster_id}/")
        print(f"   - cha_kpis.json")
        print(f"   - network.pickle")
        print(f"   - interactive_map.html")
        print()
        print(f"3. Open interactive map:")
        print(f"   open results/cha/{cluster_id}/interactive_map.html")
    else:
        print("1. First, ensure data preparation has been run:")
        print("   python src/scripts/00_prepare_data.py --create-clusters")
        print()
        print("2. Check raw building data for Heinrich Zille addresses")
        print("3. Verify street matching logic is working correctly")

if __name__ == "__main__":
    main()

