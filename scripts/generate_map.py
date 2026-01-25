#!/usr/bin/env python3
"""
Generate interactive map for a cluster without requiring network convergence.
Creates network and adds dummy results for visualization.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import geopandas as gpd
import pandas as pd
import numpy as np
import pandapipes as pp
import logging
from typing import Tuple

from branitz_heat_decision.config import (
    BUILDINGS_PATH, BUILDING_CLUSTER_MAP_PATH, resolve_cluster_path
)
from branitz_heat_decision.data.loader import load_buildings_geojson, load_streets_geojson
from branitz_heat_decision.cha import network_builder
from branitz_heat_decision.cha.qgis_export import create_interactive_map
from branitz_heat_decision.cha.config import CHAConfig, get_default_config
from branitz_heat_decision.cha.sizing import load_pipe_catalog

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def add_dummy_results(net: pp.pandapipesNet, config: CHAConfig):
    """Add dummy simulation results for visualization."""
    net.converged = True
    
    # Create dummy pipe results
    n_pipes = len(net.pipe)
    net.res_pipe = pd.DataFrame({
        'v_mean_ms': np.random.uniform(0.3, 1.2, n_pipes),
        'p_from_bar': np.random.uniform(1.8, 2.0, n_pipes),
        'p_to_bar': np.random.uniform(1.7, 1.9, n_pipes),
        'mdot_from_kg_s': np.random.uniform(0.05, 0.5, n_pipes),
        'mdot_to_kg_s': np.random.uniform(0.05, 0.5, n_pipes),
        'tfrom_k': np.full(n_pipes, config.supply_temp_k),
        'tto_k': np.full(n_pipes, config.supply_temp_k - 5),
        'lambda': np.full(n_pipes, 0.02),
        'reynolds': np.random.uniform(5000, 50000, n_pipes),
        'qext_w': np.random.uniform(50, 200, n_pipes),
    }, index=net.pipe.index)
    
    # Create dummy junction results
    n_junctions = len(net.junction)
    net.res_junction = pd.DataFrame({
        'p_bar': np.random.uniform(1.7, 2.0, n_junctions),
        't_k': np.full(n_junctions, config.supply_temp_k),
    }, index=net.junction.index)
    
    logger.info(f"Added dummy results for {n_pipes} pipes and {n_junctions} junctions")


def load_cluster_data(cluster_id: str) -> Tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Load buildings and streets for cluster."""
    # Load cluster map
    cluster_map = pd.read_parquet(BUILDING_CLUSTER_MAP_PATH)
    cluster_buildings = cluster_map[cluster_map['cluster_id'] == cluster_id]['building_id'].tolist()
    
    if not cluster_buildings:
        raise ValueError(f"No buildings found for cluster {cluster_id}")
    
    # Load buildings
    if BUILDINGS_PATH.suffix == '.parquet':
        buildings = gpd.read_parquet(BUILDINGS_PATH)
    else:
        buildings = load_buildings_geojson(BUILDINGS_PATH)
    
    buildings = buildings[buildings['building_id'].isin(cluster_buildings)].copy()
    
    # Load streets (create minimal if missing)
    from branitz_heat_decision.config import DATA_PROCESSED
    streets_path = DATA_PROCESSED / "streets.geojson"
    if not streets_path.exists():
        streets_path = DATA_PROCESSED.parent / "raw" / "streets.geojson"
    
    if not streets_path.exists():
        from shapely.geometry import LineString
        bounds = buildings.total_bounds
        street_geoms = [
            LineString([(bounds[0], bounds[1]), (bounds[2], bounds[1])]),
            LineString([(bounds[0], bounds[3]), (bounds[2], bounds[3])]),
            LineString([(bounds[0], bounds[1]), (bounds[0], bounds[3])]),
            LineString([(bounds[2], bounds[1]), (bounds[2], bounds[3])]),
        ]
        streets = gpd.GeoDataFrame(
            {'street_id': [f'street_{i}' for i in range(4)]},
            geometry=street_geoms,
            crs=buildings.crs
        )
    else:
        streets = load_streets_geojson(streets_path)
        if streets.crs != buildings.crs:
            streets = streets.to_crs(buildings.crs)
    
    return buildings, streets


def generate_map_for_cluster(cluster_id: str, output_path: Path = None):
    """Generate interactive map for cluster."""
    logger.info(f"Generating map for cluster {cluster_id}")
    
    if output_path is None:
        output_path = resolve_cluster_path(cluster_id, "cha") / "interactive_map.html"
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Load data
    buildings, streets = load_cluster_data(cluster_id)
    
    # Get plant coordinates (centroid)
    cluster_centroid = buildings.geometry.union_all().centroid
    plant_coords = (cluster_centroid.x, cluster_centroid.y)
    
    # Load pipe catalog and config
    pipe_catalog = load_pipe_catalog()
    config = get_default_config()
    
    # Build network
    logger.info("Building network...")
    net, _ = network_builder.build_dh_network_for_cluster(
        cluster_id=cluster_id,
        buildings=buildings,
        streets=streets,
        plant_coords=plant_coords,
        pipe_catalog=pipe_catalog,
        attach_mode='split_edge_per_building',
        trunk_mode='paths_to_buildings',
        config=config
    )
    
    logger.info(f"Network created: {len(net.junction)} junctions, {len(net.pipe)} pipes")
    
    # Add dummy results for visualization
    logger.info("Adding dummy simulation results...")
    add_dummy_results(net, config)
    
    # Generate map
    logger.info("Generating interactive map...")
    create_interactive_map(
        net=net,
        buildings=buildings,
        cluster_id=cluster_id,
        output_path=output_path,
        config=config
    )
    
    logger.info(f"Map saved to: {output_path}")
    return output_path


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Generate interactive map for cluster")
    parser.add_argument("--cluster-id", type=str, required=True, help="Cluster identifier")
    parser.add_argument("--output", type=str, default=None, help="Output path (default: results/cha/{cluster_id}/interactive_map.html)")
    
    args = parser.parse_args()
    
    output_path = Path(args.output) if args.output else None
    map_path = generate_map_for_cluster(args.cluster_id, output_path)
    
    print(f"\nInteractive map generated: {map_path}")
    print(f"Open in browser: open {map_path}")

