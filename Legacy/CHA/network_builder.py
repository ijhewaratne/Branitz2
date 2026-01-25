"""
Network builder for CHA.
Constructs district heating network topology from input data using pandapipes.
"""

import logging
from typing import Dict, List, Optional, Tuple, Union

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
import pandapipes as pp
from shapely.geometry import Point, LineString

from branitz_ai.cha.config import (
    CHAConfig,
    get_default_config,
    DEFAULT_TRUNK_MODE,
    TRUNK_MODE_FULL_STREET,
    TRUNK_MODE_PATHS_TO_BUILDINGS,
    TRUNK_MODE_SELECTED_STREETS,
)
from branitz_ai.cha.geometry_utils import (
    build_street_graph,
    snap_buildings_to_street_graph,
    select_dominant_component_by_buildings,
    _round_xy,
    choose_plant_node,
    build_trunk_topology,
    find_nearest_edge_for_points,
    _round_xy
)
from branitz_ai.cha.spur_expansion import (
    estimate_service_lengths_to_trunk,
    identify_long_service_buildings,
    find_candidate_spur_edges,
    expand_trunk_with_spurs,
    re_snap_buildings_to_expanded_trunk,
    validate_expanded_trunk,
    collect_routing_diagnostics
)
from branitz_ai.cha.sizing_utils import (
    estimate_building_mdot_kgs,
    compute_edge_mdot_from_tree,
    size_trunk_pipes,
    select_diameter_from_catalog
)
from branitz_ai.cha.network_validator import NetworkValidator
# Note: stabilize_network function not currently implemented in network_stabilizer.py
# from branitz_ai.cha.network_stabilizer import stabilize_network

logger = logging.getLogger(__name__)


def build_dh_network_for_cluster(
    cluster_id: str,
    buildings_df: gpd.GeoDataFrame,
    cluster_design_info: dict,
    streets_geom: gpd.GeoDataFrame,
    pipe_catalog: pd.DataFrame,
    trunk_mode: str = DEFAULT_TRUNK_MODE,
    attach_mode: Optional[str] = None,
    plant_selection: str = "weighted_centroid",
    *,
    cluster_map_df: Optional[pd.DataFrame] = None,
    hourly_profiles_df: Optional[pd.DataFrame] = None,
    streets_geom_bbox: Optional[gpd.GeoDataFrame] = None,  # Bbox-filtered streets (before name/ID filter)
    config: Optional[CHAConfig] = None
) -> pp.pandapipesNet:
    """
    Build a district heating network for a given cluster using pandapipes.
    
    Steps:
    A. Select buildings for cluster
    B. Build street graph
    C. Snap buildings to street graph
    D. Choose plant node
    E. Build trunk topology
    F. Create pandapipes net (junctions, pipes, sinks, source, pump)
    G. Initial DN sizing (pre-sizing)
    
    Args:
        cluster_id: Cluster identifier
        buildings_df: GeoDataFrame with building data (building_id, geometry, ...)
        cluster_design_info: Dict with 'design_hour' and optionally 'topn_hours'
        streets_geom: GeoDataFrame with street LineString geometries
        pipe_catalog: DataFrame with columns: dn_label, inner_diameter_m, (optional: roughness_m, cost_per_m)
        cluster_map_df: Optional DataFrame with building_id -> cluster_id mapping
        hourly_profiles_df: Optional DataFrame with hourly heat profiles (for pre-sizing)
        config: Optional CHAConfig (uses defaults if None)
        
    Returns:
        pandapipesNet object with complete network topology
    """
    if config is None:
        config = get_default_config()
    # Override trunk/attach/plant selection if provided
    if trunk_mode:
        config.trunk_mode = trunk_mode
    if attach_mode:
        config.attach_mode = attach_mode
    # Store plant selection strategy if the config supports it (future use)
    try:
        config.plant_selection = plant_selection
    except Exception:
        pass
    
    logger.info(f"Building DH network for cluster: {cluster_id}")
    
    # Validate pipe catalog data contract
    if 'dn_label' not in pipe_catalog.columns:
        raise ValueError(
            "pipe_catalog must have 'dn_label' column. "
            "Data contract violation."
        )
    if 'inner_diameter_m' not in pipe_catalog.columns:
        raise ValueError(
            "pipe_catalog must have 'inner_diameter_m' column. "
            "Data contract violation."
        )
    
    # Step A: Select buildings (validates building_id and geometry)
    buildings_in_cluster = _select_buildings_for_cluster(
        buildings_df, cluster_id, cluster_map_df
    )
    logger.info(f"Selected {len(buildings_in_cluster)} buildings for cluster {cluster_id}")
    
    # Step B: Build street graph (validates CRS is projected)
    street_graph = build_street_graph(streets_geom)
    
    # Step C: Snap buildings to street graph
    buildings_snapped, street_graph = snap_buildings_to_street_graph(
        buildings_in_cluster,
        street_graph,
        attach_mode=config.attach_mode,
        attach_snap_tol_m=config.attach_snap_tol_m,
        min_attach_spacing_m=config.min_attach_spacing_m
    )
    
    # Step C.5: Select dominant connected component by building count
    # NOTE: For projection-only modes (split_edge_per_building, clustered_projection),
    # attach_nodes are projection points not yet in the graph, so we can't filter by attach_node.
    # We'll do component selection after insert_building_attach_nodes() instead.
    if config.attach_mode == "nearest_node":
        # For nearest_node, attach_nodes are actual graph nodes, so we can filter now
        street_graph_dom, buildings_snapped_dom, comp_stats = select_dominant_component_by_buildings(
            street_graph, buildings_snapped
        )
        logger.info(
            f"Dominant component selection: "
            f"{comp_stats.get('dominant_buildings', len(buildings_snapped_dom))}/"
            f"{comp_stats.get('total_buildings', len(buildings_snapped))} buildings retained. "
            f"Graph {comp_stats.get('graph_nodes_before')}→{comp_stats.get('graph_nodes_after')} nodes."
        )
        street_graph = street_graph_dom
        buildings_snapped = buildings_snapped_dom
    else:
        # For projection-only modes, keep all buildings for now
        # Component selection will happen after insert_building_attach_nodes()
        logger.info(
            f"Skipping early component selection for {config.attach_mode} mode "
            f"(attach_nodes not yet in graph). Will select after edge splitting."
        )
    
    # Step C.6: Insert building attach nodes (for split_edge_per_building and clustered_projection modes)
    # This creates more granular attachment points by splitting edges at projection points
    if config.attach_mode in ("split_edge_per_building", "clustered_projection"):
        # Convert graph to edges_gdf for insert_building_attach_nodes
        streets_edges_gdf = _graph_to_edges_gdf(street_graph)
        # Set CRS if available from streets_geom
        if streets_geom.crs is not None:
            streets_edges_gdf.set_crs(streets_geom.crs, inplace=True)
        
        logger.info(
            f"Inserting building attach nodes using mode: {config.attach_mode} "
            f"({len(buildings_snapped)} buildings)"
        )
        street_graph, buildings_snapped = insert_building_attach_nodes(
            G=street_graph,
            streets_edges_gdf=streets_edges_gdf,
            buildings_gdf=buildings_snapped,
            config=config
        )
        logger.info(
            f"After attach node insertion: {street_graph.number_of_nodes()} nodes, "
            f"{street_graph.number_of_edges()} edges"
        )
    else:
        # Existing nearest-node snapping logic is already handled by snap_buildings_to_street_graph
        pass
    
    # Guard for tiny graphs
    if street_graph.number_of_edges() < 2 and len(buildings_snapped) > 20:
        error_msg = (
            f"Street graph too small for cluster {cluster_id} "
            f"({street_graph.number_of_nodes()} nodes, {street_graph.number_of_edges()} edges) "
            f"for {len(buildings_snapped)} buildings.\n"
            "\n"
            "ROOT CAUSE: The streets data file is too sparse (only 2 street segments total).\n"
            "This is a DATA QUALITY issue, not a code bug.\n"
            "\n"
            "Diagnostics:\n"
            f"  - Buildings in cluster: {len(buildings_snapped)}\n"
            f"  - Street graph nodes: {street_graph.number_of_nodes()}\n"
            f"  - Street graph edges: {street_graph.number_of_edges()}\n"
            f"  - Expected: Dozens/hundreds of edges for {len(buildings_snapped)} buildings\n"
            "\n"
            "SOLUTIONS:\n"
            "  1. Use a different streets data source:\n"
            "     - Check if 'strassen_mit_adressenV3.geojson' can be fixed/repaired\n"
            "     - Look for OSM data or other street network sources\n"
            "     - Generate street network from building addresses\n"
            "\n"
            "  2. For testing/debugging only, you can temporarily:\n"
            "     - Comment out this guard in network_builder.py (line ~115)\n"
            "     - The network will build but may not converge due to poor topology\n"
            "\n"
            "  3. Verify data:\n"
            "     - Check if streets file covers the cluster area\n"
            "     - Verify CRS alignment (should be auto-fixed, but check logs)\n"
            "     - Consider using a larger spatial buffer (currently 500m)"
        )
        raise ValueError(error_msg)
    
    # Step D: Choose plant node (restricted to dominant component nodes)
    # Optionally compute design loads for weighted centroid
    design_loads = None
    if hourly_profiles_df is not None and 'design_hour' in cluster_design_info:
        design_hour = cluster_design_info['design_hour']
        design_loads = {}
        for _, building in buildings_snapped.iterrows():
            building_id = building['building_id']
            if building_id in hourly_profiles_df.columns:
                # Extract design load in kW_th
                design_loads[building_id] = float(hourly_profiles_df.loc[design_hour, building_id])
            else:
                design_loads[building_id] = 0.0
    
    dominant_nodes = set(street_graph.nodes())
    plant_node = choose_plant_node(
        street_graph,
        buildings_snapped,
        design_loads=design_loads,
        candidate_nodes=dominant_nodes
    )
    
    # Step E: Build trunk topology (within dominant component)
    attach_nodes = buildings_snapped['attach_node'].dropna().tolist()
    
    # Normalize trunk_mode aliases
    if config.trunk_mode == "strict_street":
        trunk_mode_normalized = "selected_streets"
    else:
        trunk_mode_normalized = config.trunk_mode
    
    # Build trunk topology based on mode (with optional spur expansion)
    if trunk_mode_normalized == "street_plus_short_spurs":
        # Step E.1: Build base trunk (strict street)
        base_trunk_edges = build_trunk_topology(
            street_graph,
            plant_node,
            attach_nodes,
            trunk_mode="selected_streets",  # Use strict mode for base
            edge_cost_mode=config.edge_cost_mode
        )
        
        logger.info(f"Base trunk built: {len(base_trunk_edges)} edges")
        
        # PHASED EXPANSION: If enabled, use base trunk only (spurs added later after convergence test)
        if getattr(config, 'spur_phased_expansion', False):
            logger.info("=" * 70)
            logger.info("PHASED SPUR EXPANSION MODE")
            logger.info("  Step 1: Using base trunk only for initial convergence test")
            logger.info("  Step 2: Spurs will be added after base trunk converges")
            logger.info("=" * 70)
            trunk_edges = base_trunk_edges
            routing_diagnostics = None
            # Store base_trunk_edges in a way that can be accessed later
            # We'll store it in the network object after creation
        else:
            # IMMEDIATE EXPANSION: Add spurs now (original behavior)
            # Step E.2: Estimate service lengths with base trunk
            service_lengths = estimate_service_lengths_to_trunk(
                buildings_snapped,
                base_trunk_edges,
                street_graph
            )
            for building_id, svc_len in service_lengths.items():
                mask = buildings_snapped["building_id"] == building_id
                if mask.any():
                    idx = buildings_snapped[mask].index[0]
                    buildings_snapped.at[idx, "service_length_m"] = svc_len
            
            # Step E.3: Identify buildings needing spurs
            long_service_buildings = identify_long_service_buildings(
                buildings_snapped,
                config.service_length_promote_threshold_m
            )
            
            # Step E.4: Find candidate spurs (need bbox-filtered street graph)
            if streets_geom_bbox is None:
                logger.warning("streets_geom_bbox not provided, skipping spur expansion")
                trunk_edges = base_trunk_edges
                routing_diagnostics = None
            else:
                bbox_street_graph = build_street_graph(streets_geom_bbox)

                # Geometry of selected street for spatial buffer
                selected_street_geom = streets_geom

                spur_edges = find_candidate_spur_edges(
                    long_service_buildings,
                    bbox_street_graph,      # Bbox-filtered streets (candidate pool)
                    street_graph,           # Base trunk graph (selected streets)
                    base_trunk_edges,
                    selected_street_geom,   # For spatial buffer check
                    buildings_snapped,     # For service length evaluation
                    config
                )

                # Step E.5: Expand trunk with approved spurs
                trunk_edges = expand_trunk_with_spurs(
                    base_trunk_edges,
                    spur_edges,
                    bbox_street_graph       # Graph containing trunk + spur edges
                )

                logger.info(
                    f"Trunk expansion: base={len(base_trunk_edges)} edges, "
                    f"spurs={len(spur_edges)} edges, total={len(trunk_edges)} edges"
                )

                # Step E.6: Re-snap buildings to expanded trunk
                if len(spur_edges) > 0:
                    buildings_snapped = re_snap_buildings_to_expanded_trunk(
                        buildings_snapped,
                        trunk_edges,
                        bbox_street_graph
                    )

                # Step E.7: Validate expanded trunk
                attach_nodes_updated = buildings_snapped["attach_node"].dropna().tolist()
                validate_expanded_trunk(
                    trunk_edges,
                    plant_node,
                    attach_nodes_updated,
                    bbox_street_graph
                )
                
                # Step E.8: Collect routing diagnostics (store for later export)
                routing_diagnostics = collect_routing_diagnostics(
                    buildings_snapped,
                    base_trunk_edges,
                    trunk_edges,  # Expanded trunk
                    bbox_street_graph,
                    plant_node
                )
    else:
        # Use existing logic for other modes (with cost-based routing if configured)
        trunk_edges = build_trunk_topology(
            street_graph,
            plant_node,
            attach_nodes,
            trunk_mode=trunk_mode_normalized,
            edge_cost_mode=config.edge_cost_mode
        )
    
    # Step E.5: Connectivity sanity check - ensure all attach_nodes are reachable (for non-spur modes only)
    # Note: For spur expansion mode, validation is done in Step E.7 (validate_expanded_trunk)
    if trunk_mode_normalized != "street_plus_short_spurs":
        # Build a set of all nodes in the trunk topology
        trunk_nodes = set()
        for edge in trunk_edges:
            trunk_nodes.add(edge[0])
            trunk_nodes.add(edge[1])
        trunk_nodes.add(plant_node)  # Plant is always in trunk
        
        # Check each building's attach_node
        buildings_reachable = buildings_snapped.copy()
        unreachable_buildings = []
        
        for idx, building in buildings_snapped.iterrows():
            building_id = building['building_id']
            attach_node = building.get('attach_node')
            
            if attach_node is None:
                unreachable_buildings.append((building_id, "attach_node is None"))
                continue
            
            if attach_node not in trunk_nodes:
                # Try to find nearest trunk node or edge
                min_dist = float('inf')
                nearest_trunk_node = None
                nearest_trunk_edge = None
                
                attach_point = Point(attach_node)
                
                # First, try to find nearest trunk edge (for split_edge_per_building mode)
                if config.attach_mode in ("split_edge_per_building", "clustered_projection"):
                    for edge in trunk_edges:
                        u, v = edge
                        if street_graph.has_edge(u, v):
                            edge_data = street_graph.get_edge_data(u, v)
                            edge_geom = edge_data.get('geometry')
                            if edge_geom is None:
                                edge_geom = LineString([Point(u), Point(v)])
                            
                            # Project attach_point onto edge
                            proj_dist = edge_geom.project(attach_point)
                            proj_point = edge_geom.interpolate(proj_dist)
                            dist_to_edge = attach_point.distance(proj_point)
                            
                            max_dist = getattr(config, 'max_attach_distance_m', 500.0)
                            if dist_to_edge < min_dist and dist_to_edge < max_dist:
                                min_dist = dist_to_edge
                                nearest_trunk_edge = (u, v, edge_geom, proj_point, proj_dist)
                                nearest_trunk_node = None  # Will create new node on edge
                
                # Fallback: find nearest trunk node
                if nearest_trunk_edge is None:
                    for trunk_node in trunk_nodes:
                        dist = attach_point.distance(Point(trunk_node))
                        if dist < min_dist:
                            min_dist = dist
                            nearest_trunk_node = trunk_node
                
                if nearest_trunk_edge is not None:
                    # Create new node on trunk edge for split_edge_per_building mode
                    u, v, edge_geom, proj_point, proj_dist = nearest_trunk_edge
                    
                    # For split_edge_per_building, ensure each building gets a unique node
                    # by checking if any other building already uses a node at this location
                    snap_tol = getattr(config, 'attach_snap_tol_m', 2.0)
                    existing_node = None
                    
                    # Check existing trunk nodes
                    for tn in trunk_nodes:
                        if Point(proj_point).distance(Point(tn)) < snap_tol:
                            existing_node = tn
                            break
                    
                    # Also check if any already-processed building uses this node
                    if existing_node is None:
                        for _, other_building in buildings_reachable.iterrows():
                            other_attach = other_building.get('attach_node')
                            if other_attach is not None and Point(proj_point).distance(Point(other_attach)) < snap_tol:
                                existing_node = other_attach
                                break
                    
                    if existing_node:
                        # Node already exists, but for split_edge_per_building we want unique nodes
                        # Add a small offset to make it unique (0.1m increments)
                        offset = 0.0
                        attempts = 0
                        while existing_node is not None and attempts < 10:
                            offset += 0.1  # 0.1m offset per attempt
                            offset_point = edge_geom.interpolate(proj_dist + offset)
                            new_node = _round_xy(offset_point.x, offset_point.y)
                            
                            # Check if this offset node is unique
                            existing_node = None
                            for tn in trunk_nodes:
                                if Point(new_node).distance(Point(tn)) < snap_tol:
                                    existing_node = tn
                                    break
                            if existing_node is None:
                                for _, other_building in buildings_reachable.iterrows():
                                    other_attach = other_building.get('attach_node')
                                    if other_attach is not None and Point(new_node).distance(Point(other_attach)) < snap_tol:
                                        existing_node = other_attach
                                        break
                            attempts += 1
                        
                        if existing_node is None:
                            final_node = new_node
                        else:
                            # Fallback to existing node if we can't find unique position
                            final_node = existing_node
                    else:
                        # No existing node, use projection point
                        new_node = _round_xy(proj_point.x, proj_point.y)
                        final_node = new_node
                    
                    # Add new node to graph and trunk_nodes if it doesn't exist
                    if final_node not in street_graph:
                        street_graph.add_node(final_node)
                    if final_node not in trunk_nodes:
                        trunk_nodes.add(final_node)
                    
                    logger.warning(
                        f"Building {building_id}: attach_node {attach_node} not in trunk topology. "
                        f"Creating new node on trunk edge: {final_node} (distance: {min_dist:.2f}m)"
                    )
                    idx_reach = buildings_reachable[buildings_reachable["building_id"] == building_id].index[0]
                    buildings_reachable.at[idx_reach, "attach_node"] = final_node
                    # Update service length
                    building_geom = building.get('geometry')
                    if building_geom is not None:
                        new_svc_len = float(Point(final_node).distance(building_geom))
                        buildings_reachable.at[idx_reach, "service_length_m"] = new_svc_len
                elif nearest_trunk_node is not None:
                    max_dist = getattr(config, 'max_attach_distance_m', 500.0)
                    if min_dist < max_dist:  # Within threshold, reassign
                        logger.warning(
                            f"Building {building_id}: attach_node {attach_node} not in trunk topology. "
                            f"Reassigning to nearest trunk node {nearest_trunk_node} (distance: {min_dist:.2f}m)"
                        )
                    idx_reach = buildings_reachable[buildings_reachable["building_id"] == building_id].index[0]
                    buildings_reachable.at[idx_reach, "attach_node"] = nearest_trunk_node
                    # Update service length
                    building_geom = building.get('geometry')
                    if building_geom is not None:
                        new_svc_len = float(Point(nearest_trunk_node).distance(building_geom))
                        buildings_reachable.at[idx_reach, "service_length_m"] = new_svc_len
                else:
                    # Too far, exclude building
                    max_dist = getattr(config, 'max_attach_distance_m', 500.0)
                    reason = f"attach_node {attach_node} not in trunk topology and nearest trunk node is {min_dist:.2f}m away (>{max_dist}m threshold)"
                    unreachable_buildings.append((building_id, reason))
                    logger.warning(f"Building {building_id}: {reason}. Excluding from network.")
        
        # Remove unreachable buildings
        if unreachable_buildings:
            reachable_ids = set(buildings_reachable['building_id']) - {bid for bid, _ in unreachable_buildings}
            buildings_reachable = buildings_reachable[buildings_reachable['building_id'].isin(reachable_ids)].copy()
            logger.info(
                f"Connectivity check: {len(unreachable_buildings)} buildings excluded, "
                f"{len(buildings_reachable)} buildings remain"
            )
        
        # Update buildings_snapped to use reachable buildings
        buildings_snapped = buildings_reachable
    
    if len(trunk_edges) == 0:
        raise ValueError(
            f"No trunk topology could be built for cluster {cluster_id}. "
            "This indicates a severe topology problem (disconnected street graph or CRS mismatch)."
        )
    
    # Step F: Create pandapipes net (only for buildings in dominant component)
    net = _create_pandapipes_net(
        cluster_id,
        street_graph,  # Use dominant component subgraph
        plant_node,
        trunk_edges,
        buildings_snapped,  # Use filtered buildings
        config
    )
    
    # Step G: Initial DN sizing (pre-sizing)
    if hourly_profiles_df is not None and 'design_hour' in cluster_design_info:
        design_hour = cluster_design_info['design_hour']
        _apply_initial_sizing(
            net,
            buildings_snapped,
            trunk_edges,
            street_graph,
            plant_node,
            hourly_profiles_df,
            design_hour,
            pipe_catalog,
            config
        )
    else:
        logger.warning("No hourly_profiles_df or design_hour provided. Using default pipe sizes.")
        _apply_default_sizing(net, pipe_catalog, config)
    
    logger.info(f"Network built: {len(net.junction)} junctions, {len(net.pipe)} pipes")
    
    # Step H: Export map-ready GeoDataFrames (for visualization)
    # Store in net for later export
    net.trunk_edges_gdf = _create_trunk_edges_gdf(trunk_edges, street_graph)
    net.service_lines_gdf = _create_service_lines_gdf(buildings_snapped)
    net.buildings_gdf = buildings_snapped.copy()
    net.plant_point = Point(plant_node) if isinstance(plant_node, tuple) else plant_node
    
    # Store routing diagnostics if available (from spur expansion)
    if 'routing_diagnostics' in locals() and routing_diagnostics is not None:
        net.routing_diagnostics = routing_diagnostics
    
    # Store base_trunk_edges for phased spur expansion
    if trunk_mode_normalized == "street_plus_short_spurs" and getattr(config, 'spur_phased_expansion', False):
        if 'base_trunk_edges' in locals():
            net.base_trunk_edges = base_trunk_edges
            net.base_trunk_street_graph = street_graph
            logger.debug("Stored base_trunk_edges for phased spur expansion")
    
    # Optional: Validate network topology for convergence issues
    if getattr(config, 'validate_network_topology', False):
        try:
            validator = NetworkValidator(net)
            validation_results = validator.validate_all()
            
            if not validation_results['is_valid']:
                logger.warning(f"Network validation found {len(validation_results['issues'])} issues:")
                for issue in validation_results['issues']:
                    logger.warning(f"  [{issue['severity']}] {issue['message']}")
            else:
                logger.info("Network topology validation passed - no critical issues detected")
            
            # Store validation results in network for later inspection
            net.validation_results = validation_results
        except Exception as e:
            logger.warning(f"Network validation failed: {e}. Continuing without validation.")
    
    # Optional: Optimize network for convergence (integrated validation + stabilization)
    if getattr(config, 'optimize_convergence', False):
        try:
            from branitz_ai.cha.convergence_optimizer import ConvergenceOptimizer
            
            optimizer = ConvergenceOptimizer(net)
            converged = optimizer.optimize_for_convergence(
                max_iterations=getattr(config, 'optimize_max_iterations', 3),
                fix_parallel=getattr(config, 'optimize_fix_parallel', True),
                fix_loops=getattr(config, 'optimize_fix_loops', True),
                fix_connectivity=getattr(config, 'optimize_fix_connectivity', True),
                fix_pressures=getattr(config, 'optimize_fix_pressures', True),
                fix_short_pipes_flag=getattr(config, 'optimize_fix_short_pipes', True),
                min_length_m=getattr(config, 'stabilize_min_length_m', 1.0),
                parallel_variation_pct=getattr(config, 'stabilize_parallel_variation_pct', 0.01),
                loop_method=getattr(config, 'stabilize_loop_method', 'high_resistance'),
                virtual_pipe_resistance=getattr(config, 'stabilize_virtual_pipe_resistance', 100.0),
                plant_pressure_bar=getattr(config, 'system_pressure_bar', 3.5),
                pressure_drop_per_m=getattr(config, 'stabilize_pressure_drop_per_m', 0.001)
            )
            net = optimizer.get_optimized_network()
            
            # Store optimization summary
            net.optimization_summary = optimizer.get_optimization_summary()
            
            if converged:
                logger.info("✅ Network convergence optimization completed successfully")
            else:
                logger.warning("⚠️  Network convergence optimization completed with remaining issues")
        except Exception as e:
            logger.warning(f"Network convergence optimization failed: {e}. Continuing without optimization.")
    
    # Optional: Stabilize network for convergence (legacy, use optimize_convergence instead)
    elif getattr(config, 'stabilize_network', False):
        try:
            net = stabilize_network(
                net,
                fix_parallel=getattr(config, 'stabilize_fix_parallel', True),
                fix_short_pipes=getattr(config, 'stabilize_fix_short_pipes', True),
                fix_loops=getattr(config, 'stabilize_fix_loops', False),
                ensure_connectivity=getattr(config, 'stabilize_ensure_connectivity', True),
                improve_pressures=getattr(config, 'stabilize_improve_pressures', True),
                min_length_m=getattr(config, 'stabilize_min_length_m', 1.0),
                parallel_variation_pct=getattr(config, 'stabilize_parallel_variation_pct', 0.01),
                loop_method=getattr(config, 'stabilize_loop_method', 'high_resistance'),
                virtual_pipe_resistance=getattr(config, 'stabilize_virtual_pipe_resistance', 100.0),
                plant_pressure_bar=getattr(config, 'system_pressure_bar', 3.5),
                pressure_drop_per_m=getattr(config, 'stabilize_pressure_drop_per_m', 0.001)
            )
            logger.info("Network stabilization applied")
        except Exception as e:
            logger.warning(f"Network stabilization failed: {e}. Continuing without stabilization.")
    
    return net


def _select_buildings_for_cluster(
    buildings_df: gpd.GeoDataFrame,
    cluster_id: str,
    cluster_map_df: Optional[pd.DataFrame] = None
) -> gpd.GeoDataFrame:
    """
    Select buildings for cluster.
    
    Data contract requirements:
    - buildings_df must have 'building_id' column
    - buildings_df must have 'geometry' column (GeoDataFrame)
    - Cluster mapping resolved through either:
      a) 'cluster_id' column on buildings_df, or
      b) 'street_id' column on buildings_df, or
      c) explicit cluster_map_df with 'building_id' -> 'cluster_id' mapping
    
    Args:
        buildings_df: GeoDataFrame with building data (must have building_id, geometry)
        cluster_id: Cluster identifier
        cluster_map_df: Optional DataFrame with building_id -> cluster_id mapping
        
    Returns:
        GeoDataFrame with buildings in cluster
        
    Raises:
        ValueError: If required columns missing or no buildings found
    """
    # Validate required columns
    if 'building_id' not in buildings_df.columns:
        raise ValueError(
            "buildings_df must have 'building_id' column. "
            "Data contract violation."
        )
    
    if not isinstance(buildings_df, gpd.GeoDataFrame):
        raise ValueError(
            "buildings_df must be a GeoDataFrame with 'geometry' column. "
            "Data contract violation."
        )
    
    if buildings_df.geometry.isna().all():
        raise ValueError(
            "buildings_df must have valid geometry column. "
            "Data contract violation."
        )
    
    # Check if buildings already have cluster_id
    if 'cluster_id' in buildings_df.columns:
        buildings_in_cluster = buildings_df[buildings_df['cluster_id'] == cluster_id].copy()
    elif 'street_id' in buildings_df.columns:
        buildings_in_cluster = buildings_df[buildings_df['street_id'] == cluster_id].copy()
    elif cluster_map_df is not None:
        # Validate cluster_map_df
        if 'building_id' not in cluster_map_df.columns:
            raise ValueError(
                "cluster_map_df must have 'building_id' column. "
                "Data contract violation."
            )
        if 'cluster_id' not in cluster_map_df.columns:
            raise ValueError(
                "cluster_map_df must have 'cluster_id' column. "
                "Data contract violation."
            )
        
        # Join with cluster map
        cluster_buildings = cluster_map_df[cluster_map_df['cluster_id'] == cluster_id]
        
        building_ids = cluster_buildings['building_id'].tolist()
        buildings_in_cluster = buildings_df[buildings_df['building_id'].isin(building_ids)].copy()
    else:
        raise ValueError(
            f"Cannot select buildings for cluster {cluster_id}: "
            "no cluster_id/street_id column in buildings_df and no cluster_map_df provided. "
            "Data contract violation."
        )
    
    # Validate
    if len(buildings_in_cluster) == 0:
        raise ValueError(f"No buildings found for cluster {cluster_id}")
    
    if not all(buildings_in_cluster.geometry.notna()):
        raise ValueError(
            f"Some buildings in cluster {cluster_id} have missing geometry. "
            "Data contract violation: all buildings must have valid geometry."
        )
    
    # Ensure building_id is present in result
    if 'building_id' not in buildings_in_cluster.columns:
        raise ValueError(
            "Result missing 'building_id' column. "
            "Data contract violation."
        )
    
    return buildings_in_cluster


def _create_pandapipes_net(
    cluster_id: str,
    street_graph: nx.Graph,
    plant_node: Tuple,
    trunk_edges: List[Tuple],
    buildings_snapped: gpd.GeoDataFrame,
    config: CHAConfig
) -> pp.pandapipesNet:
    """
    Create pandapipes network with junctions, pipes, sinks, source, and pump.
    
    Args:
        cluster_id: Cluster identifier
        street_graph: NetworkX street graph
        plant_node: Plant node identifier
        trunk_edges: List of trunk edge tuples
        buildings_snapped: GeoDataFrame with snapped buildings
        config: CHAConfig
        
    Returns:
        pandapipesNet object
    """
    # Create empty network with water fluid
    net = pp.create_empty_network(f"DH_network_{cluster_id}", fluid="water")
    
    # Initialize junction geodata table for visualization
    # This stores (x, y) coordinates for each junction to enable accurate map rendering
    net.junction_geodata = pd.DataFrame(columns=["x", "y"])
    
    # Initialize is_plant flag column to track plant junctions explicitly
    # This prevents reliance on element names and ensures deterministic plant location
    # Initialize as False for all junctions (will be set to True for plant junctions)
    if len(net.junction) > 0:
        net.junction["is_plant"] = False
    else:
        # If junction DataFrame is empty, the column will be added when first junction is created
        # We'll initialize it after creating the first junction
        pass
    
    # Create node mapping: (x, y) -> junction indices
    node_to_junction = {}
    junction_counter = 0
    
    # Step 1: Create junctions for trunk nodes with distance-based pressure initialization
    # For each unique node in trunk_edges, create supply and return junctions
    trunk_nodes = set()
    for edge in trunk_edges:
        trunk_nodes.add(edge[0])
        trunk_nodes.add(edge[1])
    
    # Calculate shortest path distances from plant to each node for pressure initialization
    # Build a simple graph from trunk edges for distance calculation
    trunk_graph = nx.Graph()
    for edge in trunk_edges:
        u, v = edge
        # Get edge length from street graph if available
        if street_graph.has_edge(u, v):
            length = street_graph[u][v].get('length_m', 100.0)
        elif street_graph.has_edge(v, u):
            length = street_graph[v][u].get('length_m', 100.0)
        else:
            # Fallback: Euclidean distance
            length = np.sqrt((u[0] - v[0])**2 + (u[1] - v[1])**2)
        trunk_graph.add_edge(u, v, weight=length)
    
    # Calculate distances from plant node
    node_distances = {}
    if plant_node in trunk_nodes and nx.has_path(trunk_graph, plant_node, plant_node):
        # Use NetworkX shortest path lengths
        try:
            distances = nx.single_source_dijkstra_path_length(trunk_graph, plant_node, weight='weight')
            node_distances = distances
        except Exception as e:
            logger.warning(f"Could not calculate shortest paths for pressure initialization: {e}")
            # Fallback: use Euclidean distance
            for node in trunk_nodes:
                node_distances[node] = np.sqrt((node[0] - plant_node[0])**2 + (node[1] - plant_node[1])**2)
    else:
        # Fallback: use Euclidean distance from plant
        for node in trunk_nodes:
            node_distances[node] = np.sqrt((node[0] - plant_node[0])**2 + (node[1] - plant_node[1])**2)
    
    # Find maximum distance for normalization
    max_distance = max(node_distances.values()) if node_distances else 1.0
    
    # Create junctions with distance-based pressure initialization
    for node in trunk_nodes:
        node_pos = node  # (x, y) tuple
        
        # Calculate distance from plant (in meters)
        distance_m = node_distances.get(node, 0.0)
        
        # Calculate pressure drop: typical DH systems ~100-200 Pa/m (0.001-0.002 bar/100m)
        # Use a conservative gradient: 0.001 bar/m = 0.1 bar per 100m
        # This ensures we don't go negative even for long networks
        pressure_drop_per_m = 0.001  # bar/m
        pressure_drop = distance_m * pressure_drop_per_m
        
        # Initialize supply pressure: start from system pressure, decrease with distance
        # Ensure minimum pressure of 1.0 bar to avoid negative pressures
        supply_pressure = max(1.0, config.system_pressure_bar - pressure_drop)
        
        # Return side: slightly lower pressure (typically 0.1-0.2 bar lower in DH systems)
        return_pressure_drop = 0.1  # Additional 0.1 bar for return side
        return_pressure = max(0.9, supply_pressure - return_pressure_drop)
        
        # Supply junction
        junc_s = pp.create_junction(
            net,
            pn_bar=supply_pressure,  # Distance-based pressure initialization
            tfluid_k=config.t_supply_C + 273.15,
            name=f"S_{node[0]:.1f}_{node[1]:.1f}"
        )
        # Return junction
        junc_r = pp.create_junction(
            net,
            pn_bar=return_pressure,  # Distance-based pressure initialization (slightly lower)
            tfluid_k=config.t_return_C + 273.15,
            name=f"R_{node[0]:.1f}_{node[1]:.1f}"
        )
        node_to_junction[node] = {'supply': junc_s, 'return': junc_r}
        
        # Log pressure initialization for plant node (for debugging)
        if node == plant_node:
            logger.debug(
                f"Plant node pressure initialization: "
                f"supply={supply_pressure:.3f} bar, return={return_pressure:.3f} bar, "
                f"distance={distance_m:.1f}m"
            )
        
        # Initialize is_plant column if this is the first junction
        if "is_plant" not in net.junction.columns:
            net.junction["is_plant"] = False
        
        # Store junction coordinates for visualization
        net.junction_geodata.loc[junc_s, ["x", "y"]] = [node[0], node[1]]
        net.junction_geodata.loc[junc_r, ["x", "y"]] = [node[0], node[1]]
    
    # Step 2: Create pipes for trunk edges
    # Store edge-to-pipe mapping for sizing
    edge_to_pipe_idx = {}  # (edge, 'supply'|'return') -> pipe_idx
    
    # Build a directed tree from plant to determine correct pipe direction
    # This ensures pipes flow FROM plant TO buildings (not backwards)
    trunk_tree = nx.DiGraph()
    for edge in trunk_edges:
        u, v = edge
        # Add both directions initially (we'll fix direction based on plant distance)
        trunk_tree.add_edge(u, v)
        trunk_tree.add_edge(v, u)
    
    # Calculate shortest distances from plant to all nodes
    if trunk_tree.has_node(plant_node):
        distances = nx.single_source_shortest_path_length(trunk_tree, plant_node)
    else:
        distances = {}
        logger.warning(f"Plant node {plant_node} not in trunk tree, using arbitrary direction")
    
    for edge in trunk_edges:
        edge_normalized = tuple(sorted(edge))
        u, v = edge
        
        # Determine correct direction: from node closer to plant TO node farther from plant
        # If distances not available, use original edge order
        if plant_node in distances:
            dist_u = distances.get(u, float('inf'))
            dist_v = distances.get(v, float('inf'))
            if dist_u <= dist_v:
                from_node, to_node = u, v
            else:
                from_node, to_node = v, u
        else:
            # Fallback: use original edge order (u -> v)
            from_node, to_node = u, v
        
        # Get edge data from graph (check both directions)
        length_m = None
        if street_graph.has_edge(from_node, to_node):
            edge_data = street_graph.get_edge_data(from_node, to_node)
            length_m = edge_data.get('length_m', None)
        elif street_graph.has_edge(to_node, from_node):
            edge_data = street_graph.get_edge_data(to_node, from_node)
            length_m = edge_data.get('length_m', None)
        
        if length_m is None:
            # Fallback: compute distance
            length_m = np.sqrt((from_node[0] - to_node[0])**2 + (from_node[1] - to_node[1])**2)
            logger.warning(f"Edge {edge_normalized} not in graph, using computed distance: {length_m:.2f}m")
        
        # Ensure minimum pipe length to avoid numerical instability
        # Use configurable minimum (default 10m) instead of 0.1m
        min_pipe_length_m = getattr(config, "min_pipe_length_m", 10.0)
        length_m = max(length_m, min_pipe_length_m)
        length_km = length_m / 1000.0
        
        # Supply pipe: FROM plant TO buildings
        junc_s_from = node_to_junction[from_node]['supply']
        junc_s_to = node_to_junction[to_node]['supply']
        # Use create_pipe_from_parameters to specify diameter directly
        pipe_s_idx = pp.create_pipe_from_parameters(
            net,
            from_junction=junc_s_from,
            to_junction=junc_s_to,
            length_km=length_km,
            diameter_m=0.1,  # Temporary, will be sized later
            name=f"pipe_S_{from_node[0]:.1f}_{from_node[1]:.1f}_to_{to_node[0]:.1f}_{to_node[1]:.1f}"
        )
        edge_to_pipe_idx[(edge_normalized, 'supply')] = pipe_s_idx
        
        # Return pipe: FROM buildings TO plant (reverse direction)
        junc_r_from = node_to_junction[to_node]['return']  # Start from building side
        junc_r_to = node_to_junction[from_node]['return']  # End at plant side
        pipe_r_idx = pp.create_pipe_from_parameters(
            net,
            from_junction=junc_r_from,
            to_junction=junc_r_to,
            length_km=length_km,
            diameter_m=0.1,  # Temporary
            name=f"pipe_R_{to_node[0]:.1f}_{to_node[1]:.1f}_to_{from_node[0]:.1f}_{from_node[1]:.1f}"
        )
        edge_to_pipe_idx[(edge_normalized, 'return')] = pipe_r_idx
    
    # Store mapping in net for later use
    net.edge_to_pipe_idx = edge_to_pipe_idx
    
    # Step 3: Create building service connections
    # IMPORTANT: Each building must have its own unique junction on the trunk.
    # Even if multiple buildings attach to the same trunk node, each gets its own junction.
    building_to_junctions = {}
    building_to_service_pipes = {}  # building_id -> {'supply': pipe_idx, 'return': pipe_idx}
    
    # Track unique trunk service junctions per building
    # This ensures no two buildings share the same trunk junction
    building_to_trunk_service_junctions = {}  # building_id -> {'supply': junc_idx, 'return': junc_idx}
    
    for idx, building in buildings_snapped.iterrows():
        building_id = building['building_id']
        attach_node = building.get('attach_node')
        
        # Add minimum-length protection for service pipes
        service_length_m = float(building.get('service_length_m', 10.0))
        service_length_m = max(service_length_m, 1.0)  # avoid zero-length pipes
        service_length_km = service_length_m / 1000.0
        
        if attach_node is None or attach_node not in node_to_junction:
            # This should not happen if we filtered buildings_reachable correctly
            logger.warning(f"Building {building_id}: attach_node not in trunk, skipping service connection")
            continue
        
        # Calculate attachment node pressure from distance (same as trunk nodes)
        attach_distance_m = node_distances.get(attach_node, 0.0)
        pressure_drop_per_m = 0.001  # bar/m (same as trunk)
        attach_pressure_drop = attach_distance_m * pressure_drop_per_m
        attach_supply_pressure = max(1.0, config.system_pressure_bar - attach_pressure_drop)
        attach_return_pressure_drop = 0.1  # Additional 0.1 bar for return side
        attach_return_pressure = max(0.9, attach_supply_pressure - attach_return_pressure_drop)
        
        # Create a unique junction pair on the trunk for this building
        # This ensures each building has its own connection point, even if they share the same attach_node
        trunk_service_supply_junc = pp.create_junction(
            net,
            pn_bar=attach_supply_pressure,  # Same pressure as trunk node
            tfluid_k=config.t_supply_C + 273.15,
            name=f"S_T_{building_id}"  # Unique trunk service junction for this building
        )
        
        trunk_service_return_junc = pp.create_junction(
            net,
            pn_bar=attach_return_pressure,  # Same pressure as trunk node
            tfluid_k=config.t_return_C + 273.15,
            name=f"R_T_{building_id}"  # Unique trunk service junction for this building
        )
        
        # Store trunk service junction coordinates at attach_node location
        net.junction_geodata.loc[trunk_service_supply_junc, ["x", "y"]] = [attach_node[0], attach_node[1]]
        net.junction_geodata.loc[trunk_service_return_junc, ["x", "y"]] = [attach_node[0], attach_node[1]]
        
        # Connect trunk service junctions to main trunk junctions with very short pipes
        # This ensures they're part of the trunk network but are unique per building
        min_pipe_length_m = getattr(config, "min_pipe_length_m", 10.0)
        # Use minimum length to avoid numerical issues
        trunk_connection_length_km = max(min_pipe_length_m, 0.1) / 1000.0
        
        # Connect trunk service supply junction to main trunk supply junction
        pp.create_pipe_from_parameters(
            net,
            from_junction=node_to_junction[attach_node]['supply'],
            to_junction=trunk_service_supply_junc,
            length_km=trunk_connection_length_km,
            diameter_m=0.1,  # Same diameter as trunk (will be sized later)
            name=f"trunk_conn_S_{building_id}"
        )
        
        # Connect trunk service return junction to main trunk return junction (reverse direction)
        pp.create_pipe_from_parameters(
            net,
            from_junction=trunk_service_return_junc,
            to_junction=node_to_junction[attach_node]['return'],
            length_km=trunk_connection_length_km,
            diameter_m=0.1,  # Same diameter as trunk
            name=f"trunk_conn_R_{building_id}"
        )
        
        building_to_trunk_service_junctions[building_id] = {
            'supply': trunk_service_supply_junc,
            'return': trunk_service_return_junc
        }
        
        # Building supply junction (slightly lower than trunk due to service connection)
        service_pressure_drop = 0.05  # 0.05 bar drop across service connection
        building_supply_pressure = max(0.8, attach_supply_pressure - service_pressure_drop)
        
        # Building return junction (slightly higher than trunk return due to service connection)
        building_return_pressure = max(0.8, attach_return_pressure + service_pressure_drop)
        
        # Building supply junction
        junc_b_s = pp.create_junction(
            net,
            pn_bar=building_supply_pressure,  # Pressure accounting for service connection
            tfluid_k=config.t_supply_C + 273.15,
            name=f"S_B_{building_id}"
        )
        
        # Building return junction
        junc_b_r = pp.create_junction(
            net,
            pn_bar=building_return_pressure,  # Pressure accounting for service connection
            tfluid_k=config.t_return_C + 273.15,
            name=f"R_B_{building_id}"
        )
        
        building_to_junctions[building_id] = {
            'supply': junc_b_s,
            'return': junc_b_r,
            'attach_supply': trunk_service_supply_junc,  # Use unique trunk service junction
            'attach_return': trunk_service_return_junc   # Use unique trunk service junction
        }
        
        # Store building junction coordinates for visualization
        # Use building centroid for building junctions
        building_geom = building.get('geometry') if isinstance(building, dict) else building.geometry
        if building_geom is not None and pd.notna(building_geom):
            try:
                pt = building_geom.centroid if hasattr(building_geom, 'centroid') else building_geom
                net.junction_geodata.loc[junc_b_s, ["x", "y"]] = [pt.x, pt.y]
                net.junction_geodata.loc[junc_b_r, ["x", "y"]] = [pt.x, pt.y]
            except Exception:
                # Fallback: use attach node coordinates if building geometry unavailable
                attach_coords = attach_node
                net.junction_geodata.loc[junc_b_s, ["x", "y"]] = [attach_coords[0], attach_coords[1]]
                net.junction_geodata.loc[junc_b_r, ["x", "y"]] = [attach_coords[0], attach_coords[1]]
        
        # Minimal consumer bridge to connect supply to return hydraulically
        # This prevents isolated supply stubs and improves solvability.
        hx_length_m = getattr(config, "building_hx_length_m", 50.0)  # Default 50m to avoid numerical issues
        hx_diam_m = getattr(config, "building_hx_diameter_m", 0.02)
        min_hx_length = getattr(config, "min_pipe_length_m", 10.0)  # Ensure minimum length
        
        pp.create_pipe_from_parameters(
            net,
            from_junction=junc_b_s,
            to_junction=junc_b_r,
            length_km=max(hx_length_m, min_hx_length) / 1000.0,
            diameter_m=hx_diam_m,
            name=f"hx_{building_id}"
        )
        
        # Service supply pipe (trunk service junction -> building)
        # Connects from the unique trunk service junction for this building
        pipe_s_service_idx = pp.create_pipe_from_parameters(
            net,
            from_junction=trunk_service_supply_junc,  # Use unique trunk service junction
            to_junction=junc_b_s,
            length_km=service_length_km,
            diameter_m=0.02,  # Default DN20, will be sized later
            name=f"service_S_{building_id}"
        )
        
        # Service return pipe (building -> trunk service junction)
        # Connects to the unique trunk service junction for this building
        pipe_r_service_idx = pp.create_pipe_from_parameters(
            net,
            from_junction=junc_b_r,
            to_junction=trunk_service_return_junc,  # Use unique trunk service junction
            length_km=service_length_km,
            diameter_m=0.02,  # Default DN20
            name=f"service_R_{building_id}"
        )
        
        building_to_service_pipes[building_id] = {
            'supply': pipe_s_service_idx,
            'return': pipe_r_service_idx
        }
        
        # Add sink (heat demand) at building return junction
        # Sink represents heat extraction (negative flow in return pipe)
        pp.create_sink(
            net,
            junction=junc_b_r,
            mdot_kg_per_s=0.0,  # Will be set from profiles
            name=f"sink_{building_id}"
        )
    
    # Step 4: Add source and pump at plant
    plant_supply_junc = node_to_junction[plant_node]['supply']
    plant_return_junc = node_to_junction[plant_node]['return']
    
    # Mark plant junctions explicitly (prevents name-based confusion)
    net.junction.loc[plant_supply_junc, "is_plant"] = True
    net.junction.loc[plant_return_junc, "is_plant"] = True
    logger.debug(f"Marked plant junctions: supply={plant_supply_junc}, return={plant_return_junc}")
    
    # Source (heat input) at supply junction
    # Note: In district heating, source provides hot water to supply side
    pp.create_source(
        net,
        junction=plant_supply_junc,
        mdot_kg_per_s=0.0,  # Will be computed from total demand
        name="source_plant"
    )
    
    # Circulation pump connecting supply and return
    # In pandapipes, circulation pump connects return to supply
    # return_junction: where flow enters pump (return side)
    # flow_junction: where flow exits pump (supply side)
    p_flow_bar = config.system_pressure_bar  # Use configurable system pressure
    plift_bar = 0.5  # Pressure lift in bar (configurable default)
    
    pp.create_circ_pump_const_pressure(
        net,
        return_junction=plant_return_junc,
        flow_junction=plant_supply_junc,
        p_flow_bar=p_flow_bar,
        plift_bar=plift_bar,
        name="pump_plant"
    )
    
    # Store mappings in net for later use
    net.building_to_service_pipes = building_to_service_pipes
    net.building_to_junctions = building_to_junctions
    
    logger.info(f"Created network: {len(net.junction)} junctions, {len(net.pipe)} pipes, {len(net.sink)} sinks")
    return net


def _apply_initial_sizing(
    net: pp.pandapipesNet,
    buildings_snapped: gpd.GeoDataFrame,
    trunk_edges: List[Tuple],
    street_graph: nx.Graph,
    plant_node: Tuple,
    hourly_profiles_df: pd.DataFrame,
    design_hour: int,
    pipe_catalog: pd.DataFrame,
    config: CHAConfig
):
    """
    Apply initial pipe sizing based on design hour loads.
    
    Args:
        net: pandapipesNet
        buildings_snapped: GeoDataFrame with snapped buildings
        trunk_edges: List of trunk edges
        street_graph: NetworkX graph
        plant_node: Plant node
        hourly_profiles_df: Hourly heat profiles
        design_hour: Design hour index
        pipe_catalog: Pipe catalog DataFrame
        config: CHAConfig
    """
    # Estimate building mass flows
    building_mdot = estimate_building_mdot_kgs(
        hourly_profiles_df,
        "cluster",  # cluster_id not needed here
        buildings_snapped,
        design_hour,
        config
    )
    
    # Build mapping: building_id -> attach_node
    building_to_attach_node = {}
    for idx, building in buildings_snapped.iterrows():
        building_id = building['building_id']
        attach_node = building.get('attach_node')
        building_to_attach_node[building_id] = attach_node
    
    # Compute edge mass flows
    attach_nodes = [n for n in buildings_snapped['attach_node'].dropna().tolist() if n is not None]
    edge_mdot = compute_edge_mdot_from_tree(
        street_graph,
        plant_node,
        attach_nodes,
        building_mdot,
        building_to_attach_node
    )
    
    # Size trunk pipes
    edge_dn = size_trunk_pipes(trunk_edges, edge_mdot, pipe_catalog, config)
    
    # Apply diameters to trunk pipes in network
    if hasattr(net, 'edge_to_pipe_idx'):
        for (edge, pipe_type), pipe_idx in net.edge_to_pipe_idx.items():
            edge_normalized = tuple(sorted(edge)) if isinstance(edge, tuple) else edge
            dn_label = edge_dn.get(edge_normalized, config.service_dn_default)
            diameter_m = pipe_catalog[pipe_catalog['dn_label'] == dn_label]['inner_diameter_m'].values
            if len(diameter_m) > 0:
                net.pipe.at[pipe_idx, 'diameter_m'] = diameter_m[0]
            else:
                logger.warning(f"DN {dn_label} not found in catalog for edge {edge_normalized}")
    
    # Size service pipes
    if hasattr(net, 'building_to_service_pipes'):
        for building_id, m_dot in building_mdot.items():
            if building_id not in net.building_to_service_pipes:
                continue
            
            service_dn = select_diameter_from_catalog(m_dot, pipe_catalog, config)
            diameter_m = pipe_catalog[pipe_catalog['dn_label'] == service_dn]['inner_diameter_m'].values
            if len(diameter_m) > 0:
                diameter = diameter_m[0]
                # Update both supply and return service pipes
                net.pipe.at[net.building_to_service_pipes[building_id]['supply'], 'diameter_m'] = diameter
                net.pipe.at[net.building_to_service_pipes[building_id]['return'], 'diameter_m'] = diameter
            else:
                logger.warning(f"DN {service_dn} not found in catalog for building {building_id}")
    
    logger.info("Applied initial pipe sizing")


def _apply_default_sizing(
    net: pp.pandapipesNet,
    pipe_catalog: pd.DataFrame,
    config: CHAConfig
):
    """
    Apply default pipe sizing when no profiles available.
    
    Args:
        net: pandapipesNet
        pipe_catalog: Pipe catalog DataFrame
        config: CHAConfig
    """
    # Use default service diameter for all service pipes
    default_dn = config.service_dn_default
    default_diameter = pipe_catalog[pipe_catalog['dn_label'] == default_dn]['inner_diameter_m'].values
    if len(default_diameter) > 0:
        default_diameter = default_diameter[0]
    else:
        default_diameter = 0.02  # Fallback
    
    # Apply to all pipes (simplified - in practice, distinguish trunk vs service)
    for pipe_idx in net.pipe.index:
        net.pipe.at[pipe_idx, 'diameter_m'] = default_diameter
    
    logger.info("Applied default pipe sizing")


def _graph_to_edges_gdf(G: nx.Graph) -> gpd.GeoDataFrame:
    """
    Convert NetworkX graph to GeoDataFrame with edge attributes.
    
    Creates a GeoDataFrame with columns: u, v, geometry, length_m, and any other edge attributes.
    
    Args:
        G: NetworkX graph with edges containing 'geometry' and 'length_m' attributes
        
    Returns:
        GeoDataFrame with one row per edge
    """
    records = []
    for u, v, data in G.edges(data=True):
        geom = data.get('geometry')
        if geom is None:
            # Fallback: create LineString from node coordinates
            geom = LineString([Point(u), Point(v)])
        
        record = {
            'u': u,
            'v': v,
            'geometry': geom,
            'length_m': data.get('length_m', geom.length)
        }
        # Copy any other edge attributes
        for key, value in data.items():
            if key not in ['u', 'v', 'geometry', 'length_m']:
                record[key] = value
        
        records.append(record)
    
    return gpd.GeoDataFrame(records, crs=None)  # CRS should be set by caller if needed


def insert_building_attach_nodes(
    G: nx.Graph,
    streets_edges_gdf: gpd.GeoDataFrame,
    buildings_gdf: gpd.GeoDataFrame,
    config: CHAConfig
) -> Tuple[nx.Graph, gpd.GeoDataFrame]:
    """
    Creates new nodes on edges at building projection points (if attach_mode requires it),
    splits edges, and updates buildings_gdf with attach_node and service_length_m.
    
    Args:
        G: NetworkX graph of street network
        streets_edges_gdf: GeoDataFrame with edge geometries, must have 'u', 'v', 'geometry' columns
        buildings_gdf: GeoDataFrame with building geometries, must have 'building_id' column
        config: CHAConfig with attach_mode and related parameters
        
    Returns:
        Tuple of (updated_graph, updated_buildings_gdf)
    """
    mode = getattr(config, "attach_mode", "nearest_node")
    if mode == "nearest_node":
        # No edge splitting needed, just return as-is
        return G, buildings_gdf
    
    # Build an edges_gdf that has u,v,geometry for the graph edges
    # If streets_edges_gdf already has the right structure, use it
    # Otherwise, convert from graph
    if streets_edges_gdf is None or len(streets_edges_gdf) == 0:
        edges_gdf = _graph_to_edges_gdf(G)
    else:
        edges_gdf = streets_edges_gdf.copy()
        # Ensure required columns exist
        if 'u' not in edges_gdf.columns or 'v' not in edges_gdf.columns:
            # Try to extract from graph
            edges_gdf = _graph_to_edges_gdf(G)
    
    # 1) Find projection points
    proj_records = find_nearest_edge_for_points(buildings_gdf, edges_gdf)
    
    # Group by edge for batch splitting
    by_edge = {}
    for r in proj_records:
        edge_idx = r["edge_idx"]
        by_edge.setdefault(edge_idx, []).append(r)
    
    G_new = G.copy()
    buildings_updated = buildings_gdf.copy()
    
    # Initialize columns if they don't exist
    if "attach_node" not in buildings_updated.columns:
        buildings_updated["attach_node"] = None
    if "service_length_m" not in buildings_updated.columns:
        buildings_updated["service_length_m"] = None
    
    # 2) Process each edge with one or more projected buildings
    for edge_idx, recs in by_edge.items():
        if edge_idx not in edges_gdf.index:
            logger.warning(f"Edge index {edge_idx} not found in edges_gdf, skipping")
            continue
        
        edge_row = edges_gdf.loc[edge_idx]
        u = edge_row["u"]
        v = edge_row["v"]
        line: LineString = edge_row.geometry
        
        # Check if edge exists in graph (may be undirected)
        if not G_new.has_edge(u, v):
            if not G_new.has_edge(v, u):
                logger.warning(f"Edge ({u}, {v}) not found in graph, skipping")
                continue
            # Edge is reversed, swap u and v
            u, v = v, u
        
        # Compute projection distances along this line
        recs_sorted = sorted(recs, key=lambda x: x["dist_along_m"])
        
        # Optionally cluster close projections
        proj_points = []
        proj_dists = []
        
        if mode == "clustered_projection":
            min_space = getattr(config, "min_attach_spacing_m", 8.0)
            last_d = None
            for r in recs_sorted:
                d = r["dist_along_m"]
                if last_d is None or abs(d - last_d) >= min_space:
                    proj_dists.append(d)
                    proj_points.append(r["proj_point"])
                    last_d = d
        else:  # split_edge_per_building
            proj_dists = [r["dist_along_m"] for r in recs_sorted]
            proj_points = [r["proj_point"] for r in recs_sorted]
        
        # Create nodes for each unique projection
        # Snap to existing endpoint if close
        snap_tol = getattr(config, "attach_snap_tol_m", 2.0)
        
        new_nodes = []
        for p in proj_points:
            xn, yn = _round_xy(p.x, p.y)
            candidate = (xn, yn)
            
            # Reuse u/v if close
            if Point(candidate).distance(Point(u)) <= snap_tol:
                candidate = u
            elif Point(candidate).distance(Point(v)) <= snap_tol:
                candidate = v
            
            if candidate not in G_new:
                G_new.add_node(candidate, pos=candidate)
            new_nodes.append(candidate)
        
        # Remove original edge and add split edges
        # Build ordered unique nodes along the line by projected distance
        ordered = []
        used = set()
        for nd in new_nodes:
            if nd not in used:
                ordered.append(nd)
                used.add(nd)
        
        # Build full chain: u -> ordered -> v (remove duplicates with endpoints)
        chain = [u] + [n for n in ordered if n not in (u, v)] + [v]
        
        # Remove original edge
        if G_new.has_edge(u, v):
            edge_data = G_new.get_edge_data(u, v)
            G_new.remove_edge(u, v)
        elif G_new.has_edge(v, u):
            edge_data = G_new.get_edge_data(v, u)
            G_new.remove_edge(v, u)
        else:
            edge_data = {}
        
        # Skip trivial chain (no new nodes)
        if len(chain) > 2:
            # Add new edges preserving original street geometry
            # Use cut_linestring to get actual sub-segments of the curved street
            from branitz_ai.cha.geometry_utils import cut_linestring
            
            # Get distances for cutting along the line (for internal nodes only)
            # These should be in order along the line from u to v
            internal_nodes = [n for n in ordered if n not in (u, v)]
            cut_dists = []
            for n in internal_nodes:
                dist = line.project(Point(n))
                if 0 < dist < line.length:
                    cut_dists.append(dist)
            
            # Sort and deduplicate
            cut_dists = sorted(set(cut_dists))
            
            if cut_dists:
                segments = cut_linestring(line, cut_dists)
            else:
                # No internal nodes to split at, use original line
                segments = [line]
            
            # Map segments to chain pairs
            # CRITICAL: Use actual segments from cut_linestring to preserve street geometry
            if len(segments) == len(chain) - 1:
                # Perfect match: segments correspond to chain pairs
                for i, (a, b) in enumerate(zip(chain[:-1], chain[1:])):
                    seg_geom = segments[i]
                    length_m = seg_geom.length
                    
                    # Copy original edge attributes
                    new_edge_data = edge_data.copy()
                    new_edge_data.update({
                        'length_m': float(length_m),
                        'geometry': seg_geom,  # Use actual segment geometry, not straight line!
                        'u': a,
                        'v': b
                    })
                    
                    G_new.add_edge(a, b, **new_edge_data)
            else:
                # Mismatch: fallback with warning
                logger.warning(
                    f"Segment count mismatch: {len(segments)} segments for {len(chain)-1} chain pairs. "
                    f"Using fallback straight-line geometry."
                )
                for a, b in zip(chain[:-1], chain[1:]):
                    length_m = np.sqrt((a[0] - b[0])**2 + (a[1] - b[1])**2)
                    seg_geom = LineString([Point(a), Point(b)])
                    
                    new_edge_data = edge_data.copy()
                    new_edge_data.update({
                        'length_m': float(length_m),
                        'geometry': seg_geom,
                        'u': a,
                        'v': b
                    })
                    
                    G_new.add_edge(a, b, **new_edge_data)
        
        # 3) Assign attach_node per building
        # Map each building to the nearest chain node to its projection
        for r in recs_sorted:
            b_id = r["building_id"]
            proj_p = r["proj_point"]
            
            # Choose nearest node in chain
            best_node = min(chain, key=lambda n: Point(n).distance(proj_p))
            
            # Update buildings_updated
            mask = buildings_updated["building_id"] == b_id
            if mask.any():
                idx = buildings_updated[buildings_updated["building_id"] == b_id].index[0]
                buildings_updated.at[idx, "attach_node"] = best_node
                
                # Service length: straight distance from best_node to building point
                b_geom = buildings_updated.loc[mask, "geometry"].iloc[0]
                svc_len = float(Point(best_node).distance(b_geom))
                buildings_updated.loc[mask, "service_length_m"] = svc_len
    
    return G_new, buildings_updated


def _create_trunk_edges_gdf(trunk_edges: List[Tuple], street_graph: nx.Graph) -> gpd.GeoDataFrame:
    """
    Create GeoDataFrame of trunk edges for visualization.
    
    Properly extracts geometry from graph edges to ensure trunk follows street segments.
    
    Args:
        trunk_edges: List of edge tuples (u, v) from trunk topology
        street_graph: NetworkX graph with edge geometry attributes
        
    Returns:
        GeoDataFrame with LineString geometries for trunk edges
    """
    records = []
    seen_edges = set()  # Track edges to avoid duplicates
    
    for edge in trunk_edges:
        u, v = edge
        
        # Normalize edge direction for deduplication
        edge_key = tuple(sorted([u, v]))
        if edge_key in seen_edges:
            continue
        seen_edges.add(edge_key)
        
        # Try to get geometry from graph edge (check both directions)
        geom = None
        edge_data = None
        
        if street_graph.has_edge(u, v):
            edge_data = street_graph.get_edge_data(u, v)
            geom = edge_data.get('geometry')
        elif street_graph.has_edge(v, u):
            edge_data = street_graph.get_edge_data(v, u)
            geom = edge_data.get('geometry')
        
        # Validate and fix geometry
        if geom is None:
            # Fallback: create LineString from node coordinates
            geom = LineString([Point(u), Point(v)])
        elif not hasattr(geom, 'geom_type'):
            # Geometry might be stored as coordinates or other format
            geom = LineString([Point(u), Point(v)])
        elif geom.geom_type != 'LineString':
            # Convert MultiLineString or other types to LineString
            if geom.geom_type == 'MultiLineString':
                # Merge into single LineString
                coords = []
                for line in geom.geoms:
                    coords.extend(list(line.coords))
                if len(coords) > 1:
                    geom = LineString(coords)
                else:
                    geom = LineString([Point(u), Point(v)])
            else:
                geom = LineString([Point(u), Point(v)])
        
        # Ensure geometry is valid
        try:
            if not geom.is_valid:
                # Try to fix self-intersections
                try:
                    geom = geom.buffer(0)
                except:
                    # If buffer fails, use fallback
                    geom = LineString([Point(u), Point(v)])
            
            # Ensure geometry has valid coordinates
            if geom.is_empty or len(geom.coords) < 2:
                geom = LineString([Point(u), Point(v)])
            
            # Calculate length
            try:
                length_m = geom.length
            except:
                length_m = Point(u).distance(Point(v))
            
            records.append({
                'geometry': geom,
                'u': u,
                'v': v,
                'length_m': length_m
            })
        except Exception as e:
            # Fallback: create simple LineString from node coordinates
            logger.warning(f"Failed to process edge ({u}, {v}): {e}. Using fallback geometry.")
            geom = LineString([Point(u), Point(v)])
            records.append({
                'geometry': geom,
                'u': u,
                'v': v,
                'length_m': Point(u).distance(Point(v))
            })
    
    if not records:
        return gpd.GeoDataFrame(geometry=[], crs=None)
    
    gdf = gpd.GeoDataFrame(records, crs=None)
    
    # Set CRS if available from street graph (assume UTM 33N for German data)
    # This should match the CRS used when building the street graph
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:32633", allow_override=True)
    
    return gdf


def _create_service_lines_gdf(buildings_snapped: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Create GeoDataFrame of service connection lines for visualization.
    
    Creates LineStrings from attach_node to building centroid.
    
    Args:
        buildings_snapped: GeoDataFrame with 'attach_node' and 'geometry' columns
        
    Returns:
        GeoDataFrame with LineString geometries for service connections
    """
    records = []
    for idx, building in buildings_snapped.iterrows():
        attach_node = building.get('attach_node')
        building_geom = building.get('geometry')
        
        if attach_node is None or building_geom is None:
            continue
        
        # Create LineString from attach_node to building centroid
        attach_point = Point(attach_node)
        if hasattr(building_geom, 'centroid'):
            building_point = building_geom.centroid
        else:
            building_point = building_geom
        
        service_line = LineString([attach_point, building_point])
        records.append({
            'building_id': building.get('building_id'),
            'geometry': service_line
        })
    
    if not records:
        return gpd.GeoDataFrame(geometry=[], crs=None)
    
    return gpd.GeoDataFrame(records, crs=None)
