#!/usr/bin/env python3
"""
CHA pipeline: District heating network analysis.

Generates:
- cha_kpis.json: EN 13941-1 compliance KPIs
- network.pickle: Converged pandapipes network
- interactive_map.html: Interactive visualization
"""
import sys
import argparse
import json
import pickle
import logging
from pathlib import Path
from typing import Tuple, Optional

sys.path.insert(0, str(Path(__file__).parents[1]))

import geopandas as gpd
import pandas as pd
import numpy as np
import pandapipes as pp
from shapely.geometry import Point

from branitz_heat_decision.config import (
    BUILDINGS_PATH, BUILDING_CLUSTER_MAP_PATH, DESIGN_TOPN_PATH,
    DATA_PROCESSED, DATA_RAW, HOURLY_PROFILES_PATH, resolve_cluster_path
)
from branitz_heat_decision.data.loader import (
    load_buildings_geojson, load_streets_geojson,
    filter_residential_buildings_with_heat_demand,
    load_processed_buildings
)
from branitz_heat_decision.cha import network_builder
# Use spur-specific optimizer for trunk-spur networks
from branitz_heat_decision.cha.convergence_optimizer_spur import optimize_network_for_convergence
from branitz_heat_decision.cha.kpi_extractor import extract_kpis
from branitz_heat_decision.cha.qgis_export import create_interactive_map, export_pipe_velocity_csvs
from branitz_heat_decision.cha.config import CHAConfig, get_default_config
from branitz_heat_decision.cha.sizing import load_pipe_catalog

# Optional trunk-spur imports
try:
    from branitz_heat_decision.cha.network_builder_trunk_spur import build_trunk_spur_network
    from branitz_heat_decision.cha.sizing_catalog import load_technical_catalog
    TRUNK_SPUR_AVAILABLE = True
except ImportError as e:
    TRUNK_SPUR_AVAILABLE = False
    # logger not defined yet at import time, will log later if needed
    pass

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def load_cluster_data(
    cluster_id: str,
) -> Tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, Tuple[float, float], int, float, pd.DataFrame, Optional[str]]:
    """
    Load data for a specific cluster.
    
    Returns:
        Tuple of (buildings, streets, plant_coords, design_hour, design_load_kw, hourly_profiles, cluster_street_name)
        hourly_profiles: DataFrame with shape (8760, n_buildings) - hourly heat demand per building
    """
    # Validate cluster ID format (should be ST{number}_{STREET_NAME})
    import re
    if not re.match(r'^ST\d{3}_', cluster_id):
        logger.warning(f"Cluster ID {cluster_id} does not match expected format ST{{number}}_{{STREET_NAME}}")
    
    # Load street clusters to get cluster metadata and validate cluster exists
    street_clusters_path = DATA_PROCESSED / "street_clusters.parquet"
    if street_clusters_path.exists():
        street_clusters = pd.read_parquet(street_clusters_path)
        cluster_info = street_clusters[street_clusters['street_id'] == cluster_id]
        
        if len(cluster_info) == 0:
            logger.warning(f"Cluster {cluster_id} not found in street_clusters.parquet")
            # Continue anyway (might be test data)
            plant_coords_from_cluster = None
            cluster_street_name = None
        else:
            cluster_info = cluster_info.iloc[0]
            plant_coords_from_cluster = (cluster_info['plant_x'], cluster_info['plant_y'])
            cluster_street_name = cluster_info.get('cluster_name', None)
            logger.info(f"Found cluster metadata: {cluster_info.get('building_count', 'N/A')} buildings")
    else:
        logger.warning("street_clusters.parquet not found, using defaults")
        plant_coords_from_cluster = None
        cluster_street_name = None
    
    # Load cluster map
    if not BUILDING_CLUSTER_MAP_PATH.exists():
        raise FileNotFoundError(f"Cluster map not found: {BUILDING_CLUSTER_MAP_PATH}")
    
    cluster_map = pd.read_parquet(BUILDING_CLUSTER_MAP_PATH)
    cluster_buildings = cluster_map[cluster_map['cluster_id'] == cluster_id]['building_id'].tolist()
    
    if not cluster_buildings:
        raise ValueError(f"No buildings found for cluster {cluster_id}")
    
    logger.info(f"Found {len(cluster_buildings)} buildings in cluster {cluster_id}")
    
    # Load processed buildings (already filtered to residential with heat demand)
    # This uses the smart loader which checks if buildings are already filtered
    # and loads from processed file if available, eliminating redundant filtering
    logger.info("Loading processed buildings (residential with heat demand)...")
    buildings = load_processed_buildings(cluster_buildings=cluster_buildings)
    
    if len(buildings) == 0:
        raise ValueError(
            f"No residential buildings with heat demand found for cluster {cluster_id}. "
            f"Ensure data preparation has been run with --create-clusters flag."
        )
    
    logger.info(f"Loaded {len(buildings)} residential buildings with heat demand for cluster {cluster_id}")
    
    # Load streets.
    #
    # IMPORTANT: Keep ALL streets available here.
    # The trunk-spur builder needs nearby streets to place the plant on a *different* street
    # than the selected cluster street (and to connect it accordingly).
    streets_path = DATA_PROCESSED / "streets.geojson"
    if not streets_path.exists():
        # Try raw streets file
        streets_path = DATA_RAW / "strassen_mit_adressenV3_fixed.geojson"
        if not streets_path.exists():
            streets_path = DATA_RAW / "strassen_mit_adressenV3.geojson"
    
    if not streets_path.exists():
        # Create a minimal streets GeoDataFrame from building bounds
        logger.warning("No streets file found, creating minimal street network from building bounds")
        bounds = buildings.total_bounds
        from shapely.geometry import LineString
        street_geoms = [
            LineString([(bounds[0], bounds[1]), (bounds[2], bounds[1])]),  # Bottom
            LineString([(bounds[0], bounds[3]), (bounds[2], bounds[3])]),  # Top
            LineString([(bounds[0], bounds[1]), (bounds[0], bounds[3])]),  # Left
            LineString([(bounds[2], bounds[1]), (bounds[2], bounds[3])]),  # Right
        ]
        streets = gpd.GeoDataFrame(
            {'street_id': [f'street_{i}' for i in range(4)]},
            geometry=street_geoms,
            crs=buildings.crs
        )
    else:
        streets = load_streets_geojson(streets_path)
        
        if cluster_street_name:
            logger.info(
                f"Cluster street name is '{cluster_street_name}'. "
                "Keeping all streets loaded (plant siting needs nearby non-cluster streets)."
            )
        
        # Ensure CRS matches
        if streets.crs != buildings.crs:
            streets = streets.to_crs(buildings.crs)
    
    # Get plant coordinates (prefer from cluster metadata, otherwise use centroid)
    if plant_coords_from_cluster and plant_coords_from_cluster[0] != 0.0:
        plant_coords = plant_coords_from_cluster
        logger.info(f"Plant coordinates from cluster metadata: {plant_coords}")
    else:
        cluster_centroid = buildings.geometry.union_all().centroid
        plant_coords = (cluster_centroid.x, cluster_centroid.y)
        logger.info(f"Plant coordinates from building centroid: {plant_coords}")
    
    # Load design hour and load from design_topn
    design_hour = 0
    design_load_kw = 100.0  # Default
    
    if DESIGN_TOPN_PATH.exists():
        with open(DESIGN_TOPN_PATH, 'r') as f:
            design_topn = json.load(f)
        
        if cluster_id in design_topn.get('clusters', {}):
            cluster_info = design_topn['clusters'][cluster_id]
            design_hour = cluster_info.get('design_hour', 0)
            design_load_kw = cluster_info.get('design_load_kw', 100.0)
            logger.info(f"Design hour: {design_hour}, Design load: {design_load_kw:.1f} kW")
    
    # Load hourly heat demand profiles
    hourly_profiles = None
    if HOURLY_PROFILES_PATH.exists():
        hourly_profiles = pd.read_parquet(HOURLY_PROFILES_PATH)
        logger.info(f"Loaded hourly profiles: {hourly_profiles.shape} (8760 hours × {len(hourly_profiles.columns)} buildings)")
        
        # Filter to only buildings in this cluster
        cluster_building_ids = buildings['building_id'].tolist()
        available_buildings = [bid for bid in cluster_building_ids if bid in hourly_profiles.columns]
        
        if available_buildings:
            hourly_profiles = hourly_profiles[available_buildings]
            logger.info(f"Filtered hourly profiles to {len(available_buildings)} cluster buildings")
        else:
            logger.warning(f"No matching buildings found in hourly profiles for cluster {cluster_id}")
            hourly_profiles = None
    else:
        logger.warning(f"Hourly profiles file not found: {HOURLY_PROFILES_PATH}")
    
    return buildings, streets, plant_coords, design_hour, design_load_kw, hourly_profiles, cluster_street_name


def run_cha_pipeline(
    cluster_id: str,
    attach_mode: str = 'split_edge_per_building',
    trunk_mode: str = 'paths_to_buildings',
    optimize_convergence: bool = False,
    output_dir: Optional[Path] = None,
    use_trunk_spur: bool = False,
    catalog_path: Optional[Path] = None,
    max_spur_length_m: float = 50.0,
    plant_wgs84_lat: Optional[float] = None,
    plant_wgs84_lon: Optional[float] = None,
    disable_auto_plant_siting: bool = False,
):
    """
    Run complete CHA pipeline for a cluster.
    
    Args:
        cluster_id: Cluster identifier
        attach_mode: Building attachment mode
        trunk_mode: Trunk topology mode
        optimize_convergence: Whether to optimize for convergence
        output_dir: Output directory (default: results/cha/{cluster_id})
    """
    logger.info(f"Starting CHA pipeline for cluster {cluster_id}")
    
    # Set output directory
    if output_dir is None:
        output_dir = resolve_cluster_path(cluster_id, "cha")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Load cluster data
    buildings, streets, plant_coords, design_hour, design_load_kw, hourly_profiles, cluster_street_name = load_cluster_data(cluster_id)

    # Override plant location if WGS84 coordinates are provided (EPSG:4326 lat/lon)
    # Automatically disable auto-plant-siting when fixed coordinates are provided
    if plant_wgs84_lat is not None and plant_wgs84_lon is not None:
        pt = gpd.GeoDataFrame(
            {"_": [1]},
            geometry=[Point(float(plant_wgs84_lon), float(plant_wgs84_lat))],  # (lon, lat)
            crs="EPSG:4326",
        )
        target_crs = buildings.crs if buildings.crs else "EPSG:25833"
        pt_proj = pt.to_crs(target_crs)
        plant_coords = (float(pt_proj.geometry.iloc[0].x), float(pt_proj.geometry.iloc[0].y))
        logger.info(
            f"Using fixed plant (WGS84): lat={plant_wgs84_lat}, lon={plant_wgs84_lon} "
            f"-> projected {target_crs}: {plant_coords}"
        )
        # Automatically disable auto-plant-siting when fixed coordinates are provided
        if not disable_auto_plant_siting:
            disable_auto_plant_siting = True
            logger.info("Auto-plant-siting automatically disabled (using fixed WGS84 coordinates)")
    
    # Get CHA config
    config = get_default_config()
    
    # Build network (either standard or trunk-spur)
    if use_trunk_spur:
        if not TRUNK_SPUR_AVAILABLE:
            raise ValueError("Trunk-spur network builder not available. Install required dependencies.")
        
        logger.info("Building trunk-spur network (strict street-following trunks + exclusive spurs)...")
        
        # Load technical catalog for trunk-spur
        if catalog_path is None:
            # Try common filenames (the repo sometimes contains "(1)" suffix)
            candidates = [
                DATA_RAW / "Technikkatalog_Wärmeplanung_Version_1.1_August24_CC-BY.xlsx",
                DATA_RAW / "Technikkatalog_Wärmeplanung_Version_1.1_August24_CC-BY (1).xlsx",
                Path("data/raw/Technikkatalog_Wärmeplanung_Version_1.1_August24_CC-BY.xlsx"),
                Path("data/raw/Technikkatalog_Wärmeplanung_Version_1.1_August24_CC-BY (1).xlsx"),
            ]
            catalog_path = next((p for p in candidates if p.exists()), candidates[0])
        
        if not catalog_path.exists():
            logger.warning(f"Technical catalog not found at {catalog_path}, using default pipe catalog")
            pipe_catalog = load_pipe_catalog()
        else:
            pipe_catalog = load_technical_catalog(catalog_path)
        
        # Prepare design loads dictionary from hourly profiles
        # Each building gets its heat demand from the hourly profiles at the design hour
        design_loads_kw = {}
        if hourly_profiles is not None and not hourly_profiles.empty:
            # Extract per-building heat demand at design hour
            for _, building in buildings.iterrows():
                bid = building['building_id']
                if bid in hourly_profiles.columns:
                    # Get this building's heat demand at the design hour
                    building_demand_kw = float(hourly_profiles.loc[design_hour, bid])
                    design_loads_kw[bid] = building_demand_kw
                    logger.debug(f"Building {bid}: {building_demand_kw:.2f} kW (from hourly profile, hour {design_hour})")
                else:
                    # Fallback: distribute cluster design load
                    logger.warning(f"Building {bid} not in hourly profiles, using distributed cluster load")
                    if 'floor_area_m2' in buildings.columns:
                        total_area = buildings['floor_area_m2'].sum()
                        area_share = building['floor_area_m2'] / total_area if total_area > 0 else 1.0 / len(buildings)
                        design_loads_kw[bid] = float(design_load_kw * area_share)
                    else:
                        design_loads_kw[bid] = float(design_load_kw / len(buildings)) if len(buildings) > 0 else design_load_kw
        else:
            # Fallback: distribute cluster design load if profiles not available
            logger.warning("Hourly profiles not available, distributing cluster design load per building")
            for _, building in buildings.iterrows():
                bid = building['building_id']
                if 'floor_area_m2' in buildings.columns:
                    total_area = buildings['floor_area_m2'].sum()
                    area_share = building['floor_area_m2'] / total_area if total_area > 0 else 1.0 / len(buildings)
                    design_loads_kw[bid] = float(design_load_kw * area_share)
                else:
                    design_loads_kw[bid] = float(design_load_kw / len(buildings)) if len(buildings) > 0 else design_load_kw
        
        total_cluster_load = sum(design_loads_kw.values())
        logger.info(f"Building heat demands from hourly profiles (design hour {design_hour}): "
                   f"total={total_cluster_load:.1f} kW across {len(design_loads_kw)} buildings")
        
        net, topology_info = build_trunk_spur_network(
            cluster_id=cluster_id,
            buildings=buildings,
            streets=streets,
            plant_coords=plant_coords,
            selected_street_name=cluster_street_name,
            design_loads_kw=design_loads_kw,
            pipe_catalog=pipe_catalog,
            config=config,
            max_spur_length_m=max_spur_length_m,
            attach_mode=attach_mode,
            disable_auto_plant_siting=disable_auto_plant_siting,
        )
        
        # Trunk-spur builder already runs simulation and optimization
        # Check if it converged
        initial_converged = topology_info.get('converged', False)
        final_converged = initial_converged
        optimize_convergence = False  # Already optimized by trunk-spur builder
        
        logger.info(f"Trunk-spur network built: converged={initial_converged}")
        
    else:
        # Standard network builder
        logger.info("Building district heating network (standard topology)...")
        
        # Load pipe catalog
        pipe_catalog = load_pipe_catalog()
        
        net, topology_info = network_builder.build_dh_network_for_cluster(
            cluster_id=cluster_id,
            buildings=buildings,
            streets=streets,
            plant_coords=plant_coords,
            pipe_catalog=pipe_catalog,
            attach_mode=attach_mode,
            trunk_mode=trunk_mode,
            config=config
        )
        
        # Set initial_converged to False, will be checked after simulation
        initial_converged = False
        final_converged = False
        
        # Set design loads on sinks (only for standard builder; trunk-spur uses hourly-profile per-building loads)
        # Try to load per-building design loads from design_topn, otherwise use cluster design load
        design_loads_kw = {}
    
    # For trunk-spur, keep the per-building loads derived from hourly profiles earlier.
    # Only overwrite for the standard builder path.
    if not use_trunk_spur:
        # First, try to get per-building loads from building data
        if 'design_load_kw' in buildings.columns:
            for _, building in buildings.iterrows():
                design_loads_kw[building['building_id']] = float(building['design_load_kw'])
        else:
            # Use cluster-level design load and distribute proportionally
            if DESIGN_TOPN_PATH.exists():
                try:
                    with open(DESIGN_TOPN_PATH, 'r') as f:
                        design_topn = json.load(f)
                    if cluster_id in design_topn.get('clusters', {}):
                        cluster_design_load = design_topn['clusters'][cluster_id].get('design_load_kw', design_load_kw)
                        # Distribute cluster load to buildings (proportional to floor area if available)
                        if 'floor_area_m2' in buildings.columns:
                            total_area = buildings['floor_area_m2'].sum()
                            for _, building in buildings.iterrows():
                                area_share = building['floor_area_m2'] / total_area if total_area > 0 else 1.0 / len(buildings)
                                design_loads_kw[building['building_id']] = float(cluster_design_load * area_share)
                        else:
                            per_building_load = cluster_design_load / len(buildings) if len(buildings) > 0 else design_load_kw
                            for _, building in buildings.iterrows():
                                design_loads_kw[building['building_id']] = float(per_building_load)
                except Exception as e:
                    logger.warning(f"Could not load design loads from design_topn: {e}, using defaults")
                    per_building_load = design_load_kw / len(buildings) if len(buildings) > 0 else design_load_kw
                    for _, building in buildings.iterrows():
                        design_loads_kw[building['building_id']] = float(per_building_load)
            else:
                per_building_load = design_load_kw / len(buildings) if len(buildings) > 0 else design_load_kw
                for _, building in buildings.iterrows():
                    design_loads_kw[building['building_id']] = float(per_building_load)
    
    # Calculate mass flow rates per building
    cp_water = 4.186  # kJ/(kg·K)
    delta_t = config.delta_t_k  # K
    total_load_kw = sum(design_loads_kw.values())
    
    # For trunk-spur networks: update heat consumers (pandapipes DH element)
    if use_trunk_spur and hasattr(net, 'heat_consumer') and (net.heat_consumer is not None) and (not net.heat_consumer.empty):
        for _, building in buildings.iterrows():
            bid = building['building_id']
            load_kw = float(design_loads_kw.get(bid, 0.0))
            qext_w = load_kw * 1000.0
            hc_mask = net.heat_consumer['name'] == f"hc_{bid}"
            if hc_mask.any():
                net.heat_consumer.loc[hc_mask, 'qext_w'] = qext_w
                # Option B (requested): qext_w + controlled_mdot_kg_per_s
                # Fix mdot using design ΔT so return temperature becomes a result of the network + losses.
                if 'controlled_mdot_kg_per_s' in net.heat_consumer.columns:
                    cp_j_per_kgk = 4180.0
                    deltat_k = max(1.0, float(config.delta_t_k))
                    controlled_mdot = max(1e-5, qext_w / (cp_j_per_kgk * deltat_k))
                    net.heat_consumer.loc[hc_mask, 'controlled_mdot_kg_per_s'] = controlled_mdot

        logger.info(
            f"Set design loads: total={total_load_kw:.1f} kW across {len(design_loads_kw)} buildings "
            f"(heat_consumer)"
        )

        # Re-run pipeflow in thermal mode so temperatures reflect the updated qext_w.
        try:
            pp.pipeflow(net, mode='sequential', verbose=False, max_iter_hyd=80, max_iter_therm=80)
        except Exception as e:
            logger.warning(f"Thermal pipeflow (sequential) failed after updating heat_consumer loads: {e}")
    
    # For standard networks: assign mass flows to sinks based on building loads
    elif hasattr(net, 'sink') and net.sink is not None and not net.sink.empty:
        # Match sinks to buildings by name (sink names should be like "sink_B0001")
        for sink_idx in net.sink.index:
            sink_name = net.sink.loc[sink_idx, 'name']
            # Extract building_id from sink name (format: "sink_{building_id}")
            if sink_name.startswith('sink_'):
                building_id = sink_name[5:]  # Remove "sink_" prefix
                if building_id in design_loads_kw:
                    load_kw = design_loads_kw[building_id]
                    mdot_kg_s = (load_kw * 1000) / (cp_water * delta_t * 1000)  # kg/s
                    net.sink.loc[sink_idx, 'mdot_kg_per_s'] = mdot_kg_s
                else:
                    logger.warning(f"Building {building_id} not found in design_loads_kw, using average")
                    avg_load = total_load_kw / len(net.sink)
                    mdot_kg_s = (avg_load * 1000) / (cp_water * delta_t * 1000)
                    net.sink.loc[sink_idx, 'mdot_kg_per_s'] = mdot_kg_s
            else:
                logger.warning(f"Sink {sink_name} does not match expected format, using average load")
                avg_load = total_load_kw / len(net.sink)
                mdot_kg_s = (avg_load * 1000) / (cp_water * delta_t * 1000)
                net.sink.loc[sink_idx, 'mdot_kg_per_s'] = mdot_kg_s
        
        # Update source/circ pump to match total demand
        total_mdot = net.sink['mdot_kg_per_s'].sum()
        if hasattr(net, 'source') and not net.source.empty:
            net.source.loc[net.source.index[0], 'mdot_kg_per_s'] = total_mdot
        # Note: Trunk-spur networks use circulation pump, not source - mass flow is handled internally
        
        logger.info(f"Set design loads: total={total_load_kw:.1f} kW across {len(design_loads_kw)} buildings (sinks)")
    
    # Run initial simulation (skip if trunk-spur already did this)
    if use_trunk_spur:
        logger.info("Skipping simulation (already done by trunk-spur builder)")
        # initial_converged and final_converged already set from trunk-spur builder
    else:
        # Run initial simulation
        logger.info("Running initial pandapipes simulation...")
        initial_converged = False
        try:
            pp.pipeflow(net, mode='all', verbose=False)
            initial_converged = getattr(net, 'converged', True)  # pandapipes sets converged attribute
            if initial_converged:
                logger.info("Initial simulation converged successfully")
            else:
                logger.warning("Initial simulation did not converge")
        except Exception as e:
            logger.warning(f"Initial simulation failed: {e}")
            if not optimize_convergence:
                raise
        final_converged = initial_converged
    
    # Optimize for convergence if requested or if initial simulation didn't converge
    if not use_trunk_spur:  # Trunk-spur builder already optimized
        final_converged = initial_converged
    if optimize_convergence or (not use_trunk_spur and not initial_converged):
        logger.info("Optimizing network for convergence...")
        converged, net, opt_summary = optimize_network_for_convergence(net, config)
        final_converged = converged
        if converged:
            logger.info(f"Network optimized and converged after {opt_summary.get('iterations', 'N/A')} iterations")
        else:
            logger.warning("Network optimization did not achieve full convergence")
        
        # Run simulation after optimization
        logger.info("Running simulation after optimization...")
        try:
            pp.pipeflow(net, mode='all', verbose=False)
            final_converged = getattr(net, 'converged', True)
            if final_converged:
                logger.info("Simulation converged after optimization")
            else:
                logger.warning("Simulation still did not converge after optimization")
        except Exception as e:
            logger.warning(f"Simulation failed after optimization: {e}")
            final_converged = False
    
    # Extract topology information for logging
    topology_stats = {}
    if 'trunk_edges' in topology_info:
        topology_stats['trunk_edges'] = len(topology_info['trunk_edges'])
    if 'service_connections' in topology_info:
        topology_stats['service_connections'] = len(topology_info['service_connections'])
    if 'buildings_snapped' in topology_info:
        topology_stats['buildings_connected'] = len(topology_info['buildings_snapped'])
    if 'trunk_nodes' in topology_info:
        topology_stats['trunk_nodes'] = len(topology_info['trunk_nodes'])
    if 'spurs' in topology_info or 'spur_assignments' in topology_info:
        spurs = topology_info.get('spur_assignments', topology_info.get('spurs', {}))
        if isinstance(spurs, dict):
            topology_stats['spurs'] = len(spurs)
        else:
            topology_stats['spurs'] = len(spurs) if hasattr(spurs, '__len__') else 0
    
    # Extract KPIs (only if network converged)
    if final_converged:
        logger.info("Extracting KPIs...")
        kpis = extract_kpis(net, cluster_id, design_hour, config, detailed=True)
        kpis['convergence'] = {
            'initial_converged': initial_converged,
            'final_converged': final_converged,
            'optimized': optimize_convergence or not initial_converged
        }
        # Add topology info to KPIs
        kpis['topology'] = topology_stats
    else:
        logger.warning("Network did not converge. KPIs may be unreliable.")
        # Still extract KPIs but mark as non-converged
        try:
            kpis = extract_kpis(net, cluster_id, design_hour, config, detailed=True)
            kpis['convergence'] = {
                'initial_converged': initial_converged,
                'final_converged': False,
                'optimized': optimize_convergence or not initial_converged,
                'warning': 'KPIs extracted from non-converged network'
            }
            # Add topology info to KPIs
            kpis['topology'] = topology_stats
        except Exception as e:
            logger.error(f"Could not extract KPIs: {e}")
            kpis = {
                'cluster_id': cluster_id,
                'convergence': {
                    'initial_converged': initial_converged,
                    'final_converged': False,
                    'optimized': optimize_convergence or not initial_converged,
                    'error': str(e)
                },
                'feasible': False,
                'error': 'Network did not converge',
                'topology': topology_stats
            }
    
    # Save KPIs to JSON
    kpis_path = output_dir / "cha_kpis.json"
    with open(kpis_path, 'w') as f:
        json.dump(kpis, f, indent=2, default=str)
    logger.info(f"Saved KPIs to {kpis_path}")
    
    # Save network as pickle
    network_path = output_dir / "network.pickle"
    with open(network_path, 'wb') as f:
        pickle.dump(net, f)
    logger.info(f"Saved network to {network_path}")
    
    # Generate interactive maps (with error handling so one failure doesn't stop others)
    map_path = None
    temp_map_path = None
    pressure_map_path = None
    
    # Generate velocity map
    logger.info("Generating interactive map (velocity)...")
    map_path = output_dir / "interactive_map.html"
    try:
        create_interactive_map(
            net=net,
            buildings=buildings,
            cluster_id=cluster_id,
            output_path=map_path,
            config=config,
            color_by="velocity",
            title_suffix="(Velocity)"
        )
        logger.info(f"Saved interactive map to {map_path}")
    except Exception as e:
        logger.error(f"Failed to generate velocity map: {e}", exc_info=True)
        map_path = None

    # Generate temperature map (cascading colors by temperature)
    logger.info("Generating temperature interactive map...")
    temp_map_path = output_dir / "interactive_map_temperature.html"
    try:
        create_interactive_map(
            net=net,
            buildings=buildings,
            cluster_id=cluster_id,
            output_path=temp_map_path,
            config=config,
            color_by="temperature",
            title_suffix="(Temperature)"
        )
        logger.info(f"Saved temperature interactive map to {temp_map_path}")
    except Exception as e:
        logger.error(f"Failed to generate temperature map: {e}", exc_info=True)
        temp_map_path = None

    # Generate pressure map (cascading colors by mean pipe pressure)
    logger.info("Generating pressure interactive map...")
    pressure_map_path = output_dir / "interactive_map_pressure.html"
    try:
        create_interactive_map(
            net=net,
            buildings=buildings,
            cluster_id=cluster_id,
            output_path=pressure_map_path,
            config=config,
            color_by="pressure",
            title_suffix="(Pressure)"
        )
        logger.info(f"Saved pressure interactive map to {pressure_map_path}")
    except Exception as e:
        logger.error(f"Failed to generate pressure map: {e}", exc_info=True)
        pressure_map_path = None

    # Export updated pipe CSVs (velocities + temperatures + map scaling/colors)
    try:
        export_pipe_velocity_csvs(
            net=net,
            output_dir=output_dir,
            cluster_id=cluster_id,
            scale_to_data_range=True,
        )
    except Exception as e:
        logger.warning(f"Failed to export pipe velocity CSVs: {e}")
    
    # Print summary statistics
    logger.info(f"{'='*60}")
    logger.info(f"CHA Pipeline Complete: {cluster_id}")
    logger.info(f"{'='*60}")
    logger.info(f"Buildings: {len(buildings)}")
    if topology_stats:
        for key, value in topology_stats.items():
            logger.info(f"{key.replace('_', ' ').title()}: {value}")
    logger.info(f"Converged: {'✓' if final_converged else '✗'}")
    if final_converged and 'feasible' in kpis:
        logger.info(f"Feasible: {'✓' if kpis.get('feasible') else '✗'}")
    if final_converged and 'aggregate' in kpis and 'v_share_within_limits' in kpis.get('aggregate', {}):
        v_share = kpis['aggregate'].get('v_share_within_limits', 0.0)
        logger.info(f"Velocity compliance: {v_share:.1%}")
    logger.info(f"Results saved to {output_dir}")
    logger.info(f"{'='*60}")
    
    return {
        'kpis': kpis_path,
        'network': network_path,
        'interactive_map': map_path,
        'interactive_map_temperature': temp_map_path,
        'interactive_map_pressure': pressure_map_path,
    }


def main():
    parser = argparse.ArgumentParser(
        description='Run CHA pipeline for district heating network analysis',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Standard network builder
  python scripts/01_run_cha.py --cluster-id ST001_HEINRICH_ZILLE_STRASSE
  python scripts/01_run_cha.py --cluster-id ST001 --optimize-convergence
  python scripts/01_run_cha.py --cluster-id ST001 --attach-mode split_edge_per_building --trunk-mode paths_to_buildings
  
  # Trunk-spur network builder (recommended for better convergence)
  python scripts/01_run_cha.py --cluster-id ST001 --use-trunk-spur
  python scripts/01_run_cha.py --cluster-id ST001 --use-trunk-spur --catalog path/to/catalog.xlsx
        """
    )
    
    parser.add_argument(
        '--cluster-id',
        type=str,
        required=True,
        help='Cluster identifier (e.g., ST001_HEINRICH_ZILLE_STRASSE)'
    )
    
    parser.add_argument(
        '--attach-mode',
        type=str,
        default='split_edge_per_building',
        choices=['split_edge_per_building', 'nearest_node'],
        help='Building attachment mode'
    )
    
    parser.add_argument(
        '--trunk-mode',
        type=str,
        default='paths_to_buildings',
        choices=['paths_to_buildings', 'steiner_tree'],
        help='Trunk topology mode'
    )
    
    parser.add_argument(
        '--optimize-convergence',
        action='store_true',
        help='Optimize network topology for numerical convergence (standard builder only)'
    )
    
    parser.add_argument(
        '--use-trunk-spur',
        action='store_true',
        help='Use trunk-spur network builder (strict street-following trunks + exclusive spurs)'
    )
    
    parser.add_argument(
        '--catalog',
        type=str,
        default=None,
        help='Path to technical catalog Excel file (for trunk-spur builder)'
    )
    
    parser.add_argument(
        '--max-spur-length',
        type=float,
        default=50.0,
        help='Maximum spur length in meters (trunk-spur builder, default: 50.0)'
    )

    parser.add_argument(
        '--plant-wgs84-lat',
        type=float,
        default=None,
        help='Fixed plant latitude in WGS84 (EPSG:4326). Example: 51.76274'
    )
    parser.add_argument(
        '--plant-wgs84-lon',
        type=float,
        default=None,
        help='Fixed plant longitude in WGS84 (EPSG:4326). Example: 14.3453979'
    )
    parser.add_argument(
        '--disable-auto-plant-siting',
        action='store_true',
        help='Disable automatic re-siting of plant to a nearby different street (use provided plant coords as-is).'
    )
    
    parser.add_argument(
        '--output-dir',
        type=str,
        default=None,
        help='Output directory (default: results/cha/{cluster_id})'
    )
    
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    try:
        output_dir = Path(args.output_dir) if args.output_dir else None
        catalog_path = Path(args.catalog) if args.catalog else None
        
        results = run_cha_pipeline(
            cluster_id=args.cluster_id,
            attach_mode=args.attach_mode,
            trunk_mode=args.trunk_mode,
            optimize_convergence=args.optimize_convergence,
            output_dir=output_dir,
            use_trunk_spur=args.use_trunk_spur,
            catalog_path=catalog_path,
            max_spur_length_m=args.max_spur_length,
            plant_wgs84_lat=args.plant_wgs84_lat,
            plant_wgs84_lon=args.plant_wgs84_lon,
            disable_auto_plant_siting=args.disable_auto_plant_siting,
        )
        
        print("\n" + "="*60)
        print("CHA Pipeline Complete")
        print("="*60)
        print(f"Cluster ID: {args.cluster_id}")
        
        # Print convergence status and topology if available
        import json
        if results['kpis'].exists():
            with open(results['kpis'], 'r') as f:
                kpis = json.load(f)
                
                if 'convergence' in kpis:
                    conv = kpis['convergence']
                    print(f"\nConvergence Status:")
                    print(f"  Initial: {'✓ Converged' if conv.get('initial_converged') else '✗ Failed'}")
                    print(f"  Final: {'✓ Converged' if conv.get('final_converged') else '✗ Failed'}")
                    if conv.get('optimized'):
                        print(f"  Optimization: Applied")
                    if 'warning' in conv:
                        print(f"  Warning: {conv['warning']}")
                
                if 'topology' in kpis:
                    topo = kpis['topology']
                    print(f"\nTopology Statistics:")
                    for key, value in topo.items():
                        print(f"  {key.replace('_', ' ').title()}: {value}")
                
                if 'feasible' in kpis:
                    print(f"\nFeasibility: {'✓ Feasible' if kpis.get('feasible') else '✗ Not Feasible'}")
                    if 'aggregate' in kpis and 'v_share_within_limits' in kpis.get('aggregate', {}):
                        v_share = kpis['aggregate'].get('v_share_within_limits', 0.0)
                        print(f"Velocity Compliance: {v_share:.1%}")
        
        print(f"\nOutputs:")
        print(f"  KPIs: {results['kpis']}")
        print(f"  Network: {results['network']}")
        print(f"  Interactive Map: {results['interactive_map']}")
        print("="*60)
        
    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
