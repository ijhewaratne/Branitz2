#!/usr/bin/env python3
"""
CHA Trunk-Spur Pipeline - Full execution script.
"""

import sys
import argparse
import json
import pickle
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

import geopandas as gpd
import pandas as pd
import pandapipes as pp

from branitz_heat_decision.config import (
    BUILDINGS_PATH, BUILDING_CLUSTER_MAP_PATH, DATA_PROCESSED, 
    TECHNICAL_CATALOG_PATH, resolve_cluster_path
)
from branitz_heat_decision.data.loader import load_buildings_geojson, load_streets_geojson
from branitz_heat_decision.cha.network_builder_trunk_spur import build_trunk_spur_network
from branitz_heat_decision.cha.kpi_extractor import extract_kpis
from branitz_heat_decision.cha.qgis_export import create_interactive_map
from branitz_heat_decision.cha.config import get_default_config
from branitz_heat_decision.cha.sizing_catalog import load_technical_catalog

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def load_cluster_data_trunk_spur(cluster_id: str) -> tuple:
    """Load all data needed for trunk-spur pipeline."""
    
    # Load cluster map
    cluster_map = pd.read_parquet(BUILDING_CLUSTER_MAP_PATH)
    building_ids = cluster_map[cluster_map['cluster_id'] == cluster_id]['building_id'].tolist()
    
    if not building_ids:
        raise ValueError(f"No buildings found for cluster {cluster_id}")
    
    # Load buildings
    buildings = gpd.read_parquet(BUILDINGS_PATH)
    buildings = buildings[buildings['building_id'].isin(building_ids)].copy()
    
    # Load design loads
    design_topn_path = DATA_PROCESSED / "cluster_design_topn.json"
    with open(design_topn_path, 'r') as f:
        design_data = json.load(f)
    
    design_loads_kw = {}
    for building_id in building_ids:
        # For now, use proportional loads (in full system, this comes from profiles)
        load_kw = 50.0  # Default 50kW per building
        design_loads_kw[building_id] = load_kw
    
    # Load streets
    streets_path = DATA_PROCESSED / "streets.geojson"
    if not streets_path.exists():
        streets_path = Path("data/raw/strassen_mit_adressenV3_fixed.geojson")
    
    streets = load_streets_geojson(streets_path)
    
    # Get plant coordinates from cluster metadata
    clusters_path = DATA_PROCESSED / "street_clusters.parquet"
    clusters = pd.read_parquet(clusters_path)
    cluster_info = clusters[clusters['street_id'] == cluster_id].iloc[0]
    plant_coords = (cluster_info['plant_x'], cluster_info['plant_y'])
    
    return buildings, streets, plant_coords, design_loads_kw

def run_trunk_spur_pipeline(
    cluster_id: str,
    catalog_path: Optional[Path] = None,
    output_dir: Optional[Path] = None,
    velocity_limit_ms: float = 1.5
):
    """Run complete trunk-spur pipeline."""
    
    logger.info(f"{'='*60}")
    logger.info(f"Trunk-Spur CHA Pipeline: {cluster_id}")
    logger.info(f"{'='*60}")
    
    # Setup output
    if output_dir is None:
        output_dir = resolve_cluster_path(cluster_id, "cha")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Load data
    buildings, streets, plant_coords, design_loads_kw = load_cluster_data_trunk_spur(cluster_id)
    
    # Load technical catalog
    if catalog_path is None:
        catalog_path = Path("data/raw/Technikkatalog_Wärmeplanung_Version_1.1_August24_CC-BY.xlsx")
    
    catalog = load_technical_catalog(catalog_path)
    
    # Build network
    config = get_default_config()
    net, topology_info = build_trunk_spur_network(
        cluster_id=cluster_id,
        buildings=buildings,
        streets=streets,
        plant_coords=plant_coords,
        selected_street_name=None,
        design_loads_kw=design_loads_kw,
        pipe_catalog=catalog,
        config=config,
        max_spur_length_m=50.0
    )
    
    # Extract KPIs
    logger.info("Extracting EN 13941-1 KPIs...")
    kpis = extract_kpis(net, cluster_id, design_hour=0, config=config, detailed=True)
    kpis['topology'] = {
        'trunk_nodes': len(topology_info['trunk_nodes']),
        'trunk_edges': len(topology_info['trunk_edges']),
        'spurs': len(topology_info['spur_assignments']),
        'converged': topology_info['converged']
    }
    
    # Save KPIs
    kpis_path = output_dir / "cha_kpis.json"
    with open(kpis_path, 'w') as f:
        json.dump(kpis, f, indent=2)
    
    # Save network
    network_path = output_dir / "network.pickle"
    with open(network_path, 'wb') as f:
        pickle.dump(net, f)
    
    # Generate interactive map
    logger.info("Generating interactive map...")
    map_path = output_dir / "interactive_map.html"
    create_interactive_map(
        net=net,
        buildings=buildings,
        cluster_id=cluster_id,
        output_path=map_path,
        config=config,
        velocity_range=(0.0, velocity_limit_ms)
    )
    
    # Print summary
    logger.info(f"{'='*60}")
    logger.info("Pipeline Complete")
    logger.info(f"{'='*60}")
    logger.info(f"Cluster: {cluster_id}")
    logger.info(f"Buildings: {len(buildings)}")
    logger.info(f"Trunk edges: {len(topology_info['trunk_edges'])}")
    logger.info(f"Spurs: {len(topology_info['spur_assignments'])}")
    logger.info(f"Converged: {'✓' if topology_info['converged'] else '✗'}")
    logger.info(f"Feasible: {'✓' if kpis['en13941_compliance']['feasible'] else '✗'}")
    logger.info(f"Velocity compliance: {kpis['aggregate']['v_share_within_limits']:.1%}")
    logger.info(f"Outputs: {output_dir}")
    
    return {
        'network': net,
        'kpis': kpis,
        'topology': topology_info,
        'paths': {
            'kpis': kpis_path,
            'network': network_path,
            'map': map_path
        }
    }

def main():
    parser = argparse.ArgumentParser(
        description='Run trunk-spur CHA pipeline',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument('--cluster-id', type=str, required=True, help='Cluster identifier')
    parser.add_argument('--catalog', type=str, help='Path to technical catalog Excel')
    parser.add_argument('--output-dir', type=str, help='Custom output directory')
    parser.add_argument('--verbose', action='store_true', help='Enable debug logging')
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    try:
        catalog_path = Path(args.catalog) if args.catalog else None
        output_dir = Path(args.output_dir) if args.output_dir else None
        
        results = run_trunk_spur_pipeline(
            cluster_id=args.cluster_id,
            catalog_path=catalog_path,
            output_dir=output_dir
        )
        
        print("\n✅ Pipeline completed successfully!")
        print(f"   Interactive map: {results['paths']['map']}")
        
    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()