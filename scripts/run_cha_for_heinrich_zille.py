#!/usr/bin/env python3
"""
Run CHA Pipeline for Heinrich Zille Street.
This script finds the cluster and runs the pipeline with spur optimizer.
"""
import sys
import subprocess
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import pandas as pd
from branitz_heat_decision.config import BUILDING_CLUSTER_MAP_PATH

def find_heinrich_zille_cluster():
    """Find Heinrich Zille cluster ID."""
    if not BUILDING_CLUSTER_MAP_PATH.exists():
        print(f"❌ Cluster map not found: {BUILDING_CLUSTER_MAP_PATH}")
        print("\n👉 Run data preparation first:")
        print("   python src/scripts/00_prepare_data.py --create-clusters")
        return None
    
    cluster_map = pd.read_parquet(BUILDING_CLUSTER_MAP_PATH)
    
    # Search for Heinrich Zille
    heinrich = cluster_map[
        cluster_map['cluster_id'].str.contains('HEINRICH|ZILLE', case=False, na=False)
    ]
    
    if len(heinrich) > 0:
        cluster_id = heinrich['cluster_id'].iloc[0]
        building_count = len(heinrich)
        print(f"✅ Found cluster: {cluster_id}")
        print(f"   Buildings: {building_count}")
        
        if building_count == 77:
            print(f"   ✅ Correct number: 77 buildings")
        else:
            print(f"   ⚠️  Expected 77, found {building_count}")
        
        return cluster_id
    else:
        print("❌ No Heinrich Zille clusters found")
        print("\nAvailable clusters (first 10):")
        clusters = cluster_map.groupby('cluster_id').size().sort_values(ascending=False)
        for cid, count in clusters.head(10).items():
            print(f"   {cid}: {count} buildings")
        
        # Use cluster with most buildings as fallback
        if len(clusters) > 0:
            fallback_id = clusters.index[0]
            fallback_count = clusters.iloc[0]
            print(f"\n⚠️  Using fallback cluster: {fallback_id} ({fallback_count} buildings)")
            return fallback_id
        
        return None

def main():
    print("=" * 70)
    print("CHA Pipeline Runner: Heinrich Zille Street")
    print("=" * 70)
    print()
    
    # Find cluster
    cluster_id = find_heinrich_zille_cluster()
    
    if cluster_id is None:
        print("\n❌ Cannot proceed without cluster ID")
        sys.exit(1)
    
    print()
    print("=" * 70)
    print(f"Running CHA Pipeline with Spur Optimizer")
    print("=" * 70)
    print()
    
    # Run pipeline
    script_path = Path(__file__).parents[1] / "src" / "scripts" / "01_run_cha.py"
    
    cmd = [
        sys.executable,
        str(script_path),
        "--cluster-id", cluster_id,
        "--use-trunk-spur",
        "--optimize-convergence",
        "--verbose"
    ]
    
    print(f"Command: {' '.join(cmd)}")
    print()
    
    try:
        result = subprocess.run(cmd, check=False)
        
        print()
        print("=" * 70)
        if result.returncode == 0:
            print("✅ Pipeline completed successfully!")
            print()
            print(f"Output files in: results/cha/{cluster_id}/")
            print("  - cha_kpis.json")
            print("  - network.pickle")
            print("  - interactive_map.html")
            print()
            print(f"Open interactive map:")
            print(f"  open results/cha/{cluster_id}/interactive_map.html")
        else:
            print(f"❌ Pipeline failed with exit code {result.returncode}")
            print("Check the error messages above for details.")
        
        print("=" * 70)
        sys.exit(result.returncode)
        
    except Exception as e:
        print(f"❌ Error running pipeline: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()

