"""
Generate an interactive DH map from CHA outputs.

This script reads CHA network results and creates a Folium-based interactive map
showing the district heating network topology, buildings, and optional temperature gradients.
"""

import argparse
import os
import sys
import logging
from pathlib import Path

# Add project root to path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from branitz_ai.viz.dh_map import create_dh_interactive_map, DHMapOptions
from branitz_ai.data.preparation import load_buildings
from branitz_ai.cli.cha_cli import load_streets

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description="Generate an interactive DH map from CHA outputs."
    )
    parser.add_argument("--cluster-id", required=True, type=str,
                       help="Cluster identifier (e.g., ST012_HEINRICH_ZILLE_STRAS)")
    parser.add_argument("--cha-out", required=True, type=str,
                       help="CHA output dir containing cha_net.pkl")
    parser.add_argument("--save", default=None, type=str,
                       help="Optional HTML output path (default: <cha-out>/maps/<cluster_id>_dh_map.html)")
    parser.add_argument("--no-service", action="store_true",
                       help="Hide service pipes")
    parser.add_argument("--no-temp", action="store_true",
                       help="Disable temperature gradients (use solid colors)")
    parser.add_argument("--no-streets", action="store_true",
                       help="Hide street network background")

    args = parser.parse_args()

    # Default save path if not given
    save_path = args.save
    if save_path is None:
        maps_dir = os.path.join(args.cha_out, "maps")
        os.makedirs(maps_dir, exist_ok=True)
        save_path = os.path.join(maps_dir, f"{args.cluster_id}_dh_map.html")

    options = DHMapOptions(
        show_service_pipes=not args.no_service,
        show_temperature=not args.no_temp,
        show_streets=not args.no_streets
    )

    # Load buildings
    buildings = load_buildings()
    
    # Optionally load streets
    streets = None
    if options.show_streets:
        try:
            streets = load_streets()
            logger.info(f"Loaded {len(streets)} street segments for background")
        except Exception as e:
            logger.warning(f"Could not load streets: {e}. Continuing without street background.")

    create_dh_interactive_map(
        cluster_id=args.cluster_id,
        cha_out_dir=args.cha_out,
        buildings_gdf=buildings,
        streets_gdf=streets,
        save_path=save_path,
        options=options
    )

    logger.info(f"✅ DH interactive map saved to {save_path}")
    logger.info("Open the HTML file in a web browser to view the map.")


if __name__ == "__main__":
    main()

