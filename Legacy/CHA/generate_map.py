#!/usr/bin/env python3
"""
Simple script to generate interactive map for converged network.
Run this from the project root directory.
"""
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

from branitz_ai.viz.dh_map import create_dh_interactive_map, DHMapOptions
from branitz_ai.data.preparation import load_buildings
from branitz_ai.cli.cha_cli import load_streets
import os

print("=" * 70)
print("GENERATING INTERACTIVE MAP FOR CONVERGED NETWORK")
print("=" * 70)

# Configuration
cluster_id = "ST012_HEINRICH_ZILLE_STRAS"
cha_out_dir = "results/cha/converged_network_final"

# Verify network exists
net_path = os.path.join(cha_out_dir, "cha_net.pkl")
if not os.path.exists(net_path):
    print(f"❌ ERROR: Network file not found: {net_path}")
    sys.exit(1)
print(f"✅ Network file found: {net_path}")

# Create maps directory
maps_dir = os.path.join(cha_out_dir, "maps")
os.makedirs(maps_dir, exist_ok=True)
save_path = os.path.join(maps_dir, f"{cluster_id}_dh_map.html")
print(f"Map will be saved to: {save_path}")

# Load data
print("\nLoading data...")
try:
    buildings = load_buildings()
    print(f"✅ Loaded {len(buildings)} buildings")
except Exception as e:
    print(f"❌ Failed to load buildings: {e}")
    sys.exit(1)

try:
    streets = load_streets()
    print(f"✅ Loaded {len(streets)} street segments")
except Exception as e:
    print(f"⚠️  Could not load streets: {e}. Continuing without street background.")
    streets = None

# Create map options
options = DHMapOptions(
    show_service_pipes=True,
    show_temperature=True,
    show_streets=streets is not None
)

# Generate map
print("\nCreating interactive map...")
try:
    m = create_dh_interactive_map(
        cluster_id=cluster_id,
        cha_out_dir=cha_out_dir,
        buildings_gdf=buildings,
        streets_gdf=streets,
        save_path=save_path,
        options=options
    )
    
    # Verify file was created
    if os.path.exists(save_path):
        file_size = os.path.getsize(save_path)
        print("=" * 70)
        print(f"✅ SUCCESS! Interactive map created and saved")
        print(f"   File: {save_path}")
        print(f"   Size: {file_size:,} bytes ({file_size/1024:.1f} KB)")
        print("=" * 70)
        print("Open the HTML file in a web browser to view the interactive map.")
        print("=" * 70)
    else:
        print(f"❌ ERROR: Map file was not created at: {save_path}")
        sys.exit(1)
        
except Exception as e:
    print(f"❌ ERROR: Failed to create map: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

