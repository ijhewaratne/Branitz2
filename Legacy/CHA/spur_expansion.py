"""
Spur expansion module for CHA.

Implements controlled expansion of trunk network to reduce service connection lengths.

The spur expansion algorithm extends the trunk network into short side streets when:
1. Buildings have long service connections (> threshold)
2. Short spurs can significantly reduce service lengths
3. All constraints are met (depth, buildings, length, reduction, spatial buffer)

Algorithm Overview:
1. Build base trunk using strict street mode (selected_streets)
2. Estimate service lengths for all buildings
3. Identify buildings with service_length_m > threshold
4. Find candidate spur edges in bbox-filtered street graph (cluster-local, not global)
5. Filter candidates by spatial buffer (must be within buffer_m of selected street)
6. Evaluate each candidate against constraints:
   - Depth from trunk ≤ max_depth_edges
   - Buildings served ≥ min_buildings
   - Total spur length ≤ max_total_length_m
   - Service reduction ≥ reduction_threshold_pct
7. Expand trunk with approved spurs
8. Re-snap buildings to expanded trunk
9. Validate connectivity and reachability

Key Design Principles:
- Deterministic: Same inputs → same outputs
- Cluster-local: Uses bbox-filtered streets (not global dataset)
- Constraint-driven: All spurs must meet multiple criteria
- Explainable: Each spur justified by service length reduction

See docs/CHA_CONFIGURATION.md for configuration options and examples.
"""

import logging
from typing import Dict, List, Tuple, Optional

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
from shapely.geometry import Point, LineString

from branitz_ai.cha.config import CHAConfig

logger = logging.getLogger(__name__)


def estimate_service_lengths_to_trunk(
    buildings_gdf: gpd.GeoDataFrame,
    trunk_edges: List[Tuple],
    street_graph: nx.Graph
) -> pd.Series:
    """
    Compute service length from each building to nearest trunk node.
    
    For each building, finds the shortest path from its attach_node to the nearest
    trunk node and computes the total distance. This is used to identify buildings
    with long service connections that might benefit from spur expansion.
    
    Args:
        buildings_gdf: GeoDataFrame with buildings (must have 'building_id' and 'attach_node')
        trunk_edges: List of (u, v) tuples representing trunk edges
        street_graph: NetworkX graph of street network (used for path finding)
        
    Returns:
        Series with building_id → service_length_m (distance in meters)
        
    Example:
        >>> service_lengths = estimate_service_lengths_to_trunk(
        ...     buildings, trunk_edges, street_graph
        ... )
        >>> long_buildings = service_lengths[service_lengths > 30.0]
    """
    # Build set of trunk nodes
    trunk_nodes = set()
    for u, v in trunk_edges:
        trunk_nodes.add(u)
        trunk_nodes.add(v)
    
    service_lengths = {}
    
    for _, building in buildings_gdf.iterrows():
        building_id = building.get('building_id')
        attach_node = building.get('attach_node')
        
        if attach_node is None:
            service_lengths[building_id] = 0.0
            continue
        
        # If attach_node is already in trunk, service length is distance from building to attach_node
        if attach_node in trunk_nodes:
            building_point = building.geometry
            if building_point is not None:
                attach_point = Point(attach_node)
                service_lengths[building_id] = float(building_point.distance(attach_point))
            else:
                service_lengths[building_id] = 0.0
        else:
            # Find shortest path from attach_node to nearest trunk node
            min_dist = float('inf')
            for trunk_node in trunk_nodes:
                try:
                    path = nx.shortest_path(street_graph, attach_node, trunk_node, weight='length_m')
                    path_length = sum(
                        street_graph[path[i]][path[i+1]].get('length_m', 0.0)
                        for i in range(len(path) - 1)
                    )
                    min_dist = min(min_dist, path_length)
                except (nx.NetworkXNoPath, KeyError):
                    continue
            
            # Add distance from building to attach_node
            building_point = building.geometry
            if building_point is not None:
                attach_point = Point(attach_node)
                building_to_attach = float(building_point.distance(attach_point))
                service_lengths[building_id] = min_dist + building_to_attach
            else:
                service_lengths[building_id] = min_dist if min_dist != float('inf') else 0.0
    
    return pd.Series(service_lengths)


def identify_long_service_buildings(
    buildings_gdf: gpd.GeoDataFrame,
    threshold_m: float
) -> gpd.GeoDataFrame:
    """
    Filter buildings where service_length_m > threshold_m.
    
    This function identifies buildings that are candidates for spur expansion
    based on their service connection length. Buildings with long service
    connections (> threshold) are more likely to benefit from trunk expansion.
    
    Args:
        buildings_gdf: GeoDataFrame with buildings (must have 'service_length_m' column)
        threshold_m: Service length threshold in meters (e.g., 30.0)
        
    Returns:
        Subset of buildings needing spur consideration (GeoDataFrame with same columns)
        
    Example:
        >>> long_buildings = identify_long_service_buildings(buildings, threshold_m=30.0)
        >>> print(f"Found {len(long_buildings)} buildings with service length > 30m")
    """
    if 'service_length_m' not in buildings_gdf.columns:
        logger.warning("No 'service_length_m' column found. Returning empty GeoDataFrame.")
        return buildings_gdf.iloc[0:0].copy()
    
    mask = buildings_gdf['service_length_m'] > threshold_m
    long_service = buildings_gdf[mask].copy()
    
    logger.info(
        f"Identified {len(long_service)} buildings with service length > {threshold_m}m "
        f"(out of {len(buildings_gdf)} total)"
    )
    
    return long_service


def evaluate_spur_candidate(
    candidate_edge: Tuple,
    affected_buildings: List[str],
    base_trunk_edges: List[Tuple],
    base_trunk_graph: nx.Graph,
    bbox_street_graph: nx.Graph,
    selected_street_geometry: gpd.GeoDataFrame,
    buildings_gdf: gpd.GeoDataFrame,
    config: CHAConfig
) -> Dict:
    """
    Evaluate if candidate edge should be promoted to trunk.
    
    Args:
        candidate_edge: (u, v) tuple representing candidate spur edge
        affected_buildings: List of building_id strings that would benefit
        base_trunk_edges: List of (u, v) tuples for base trunk
        base_trunk_graph: NetworkX graph of selected streets only
        bbox_street_graph: NetworkX graph of bbox-filtered streets (cluster-local)
        selected_street_geometry: GeoDataFrame of selected street for spatial buffer
        buildings_gdf: Full building set with service_length_m
        config: CHAConfig with spur parameters
        
    Returns:
        Dict with evaluation results:
        - should_promote: bool
        - service_length_reduction_m: float
        - service_length_reduction_pct: float
        - buildings_served: int
        - depth_from_trunk: int
        - total_spur_length_m: float
        - within_spatial_buffer: bool
        - rejection_reason: Optional[str] (only present if should_promote=False)
    """
    u, v = candidate_edge
    
    # Check 1: Spatial adjacency constraint
    within_spatial_buffer = True
    if len(selected_street_geometry) > 0:
        # Create buffer around selected street
        selected_union = selected_street_geometry.geometry.unary_union
        buffer_geom = selected_union.buffer(config.spur_search_buffer_m)
        
        # Check if candidate edge intersects buffer
        if candidate_edge in bbox_street_graph.edges():
            edge_geom = bbox_street_graph[u][v].get('geometry')
            if edge_geom is not None:
                within_spatial_buffer = edge_geom.intersects(buffer_geom)
            else:
                # Fallback: check if endpoints are within buffer
                u_point = Point(u)
                v_point = Point(v)
                within_spatial_buffer = u_point.intersects(buffer_geom) or v_point.intersects(buffer_geom)
    
    if not within_spatial_buffer:
        return {
            'should_promote': False,
            'service_length_reduction_m': 0.0,
            'service_length_reduction_pct': 0.0,
            'buildings_served': 0,
            'depth_from_trunk': float('inf'),
            'total_spur_length_m': 0.0,
            'within_spatial_buffer': False,
            'rejection_reason': f'Outside spatial buffer ({config.spur_search_buffer_m}m from selected street)'
        }
    
    # Check 2: Depth from trunk
    base_trunk_nodes = set()
    for tu, tv in base_trunk_edges:
        base_trunk_nodes.add(tu)
        base_trunk_nodes.add(tv)
    
    # BFS from base trunk to find depth
    depth = float('inf')
    for trunk_node in base_trunk_nodes:
        try:
            path = nx.shortest_path(bbox_street_graph, trunk_node, u, weight='length_m')
            depth = min(depth, len(path) - 1)
        except (nx.NetworkXNoPath, KeyError):
            continue
    
    if depth > config.spur_max_depth_edges:
        return {
            'should_promote': False,
            'service_length_reduction_m': 0.0,
            'service_length_reduction_pct': 0.0,
            'buildings_served': len(affected_buildings),
            'depth_from_trunk': depth,
            'total_spur_length_m': 0.0,
            'within_spatial_buffer': True,
            'rejection_reason': f'Depth {depth} exceeds max_depth_edges {config.spur_max_depth_edges}'
        }
    
    # Check 3: Service length reduction
    # Compute current service lengths (to base trunk)
    current_service_lengths = {}
    for building_id in affected_buildings:
        building = buildings_gdf[buildings_gdf['building_id'] == building_id]
        if len(building) > 0:
            current_service_lengths[building_id] = building.iloc[0].get('service_length_m', 0.0)
    
    # Estimate new service lengths if spur is added
    # (Simplified: assume building connects to nearest node on candidate edge)
    edge_length = bbox_street_graph[u][v].get('length_m', 0.0)
    total_reduction = 0.0
    
    for building_id in affected_buildings:
        building = buildings_gdf[buildings_gdf['building_id'] == building_id]
        if len(building) == 0:
            continue
        
        building_geom = building.iloc[0].geometry
        if building_geom is None:
            continue
        
        # Find nearest point on candidate edge
        edge_geom = bbox_street_graph[u][v].get('geometry')
        if edge_geom is not None:
            nearest_point = edge_geom.interpolate(edge_geom.project(building_geom))
            new_service_length = float(building_geom.distance(nearest_point))
        else:
            # Fallback: use midpoint
            u_point = Point(u)
            v_point = Point(v)
            midpoint = Point((u[0] + v[0]) / 2, (u[1] + v[1]) / 2)
            new_service_length = float(building_geom.distance(midpoint))
        
        current_length = current_service_lengths.get(building_id, 0.0)
        reduction = max(0.0, current_length - new_service_length)
        total_reduction += reduction
    
    avg_reduction = total_reduction / len(affected_buildings) if affected_buildings else 0.0
    avg_current = sum(current_service_lengths.values()) / len(current_service_lengths) if current_service_lengths else 0.0
    reduction_pct = (avg_reduction / avg_current * 100.0) if avg_current > 0 else 0.0
    
    # Check 4: Minimum buildings
    if len(affected_buildings) < config.spur_min_buildings:
        return {
            'should_promote': False,
            'service_length_reduction_m': avg_reduction,
            'service_length_reduction_pct': reduction_pct,
            'buildings_served': len(affected_buildings),
            'depth_from_trunk': depth,
            'total_spur_length_m': edge_length,
            'within_spatial_buffer': True,
            'rejection_reason': f'Only {len(affected_buildings)} buildings served, need {config.spur_min_buildings}'
        }
    
    # Check 5: Minimum reduction threshold
    if reduction_pct < config.spur_reduction_threshold_pct:
        return {
            'should_promote': False,
            'service_length_reduction_m': avg_reduction,
            'service_length_reduction_pct': reduction_pct,
            'buildings_served': len(affected_buildings),
            'depth_from_trunk': depth,
            'total_spur_length_m': edge_length,
            'within_spatial_buffer': True,
            'rejection_reason': f'Service reduction {reduction_pct:.1f}% below threshold {config.spur_reduction_threshold_pct}%'
        }
    
    # All checks passed
    return {
        'should_promote': True,
        'service_length_reduction_m': avg_reduction,
        'service_length_reduction_pct': reduction_pct,
        'buildings_served': len(affected_buildings),
        'depth_from_trunk': depth,
        'total_spur_length_m': edge_length,
        'within_spatial_buffer': True,
        'rejection_reason': None  # No rejection
    }


def find_candidate_spur_edges(
    long_service_buildings: gpd.GeoDataFrame,
    bbox_street_graph: nx.Graph,
    base_trunk_graph: nx.Graph,
    base_trunk_edges: List[Tuple],
    selected_street_geometry: gpd.GeoDataFrame,
    buildings_gdf: gpd.GeoDataFrame,
    config: CHAConfig
) -> List[Tuple]:
    """
    Find candidate spur edges that could reduce service lengths.
    
    Args:
        long_service_buildings: Buildings with service_length_m > threshold
        bbox_street_graph: Bbox-filtered streets (candidate pool)
        base_trunk_graph: Selected streets only (base trunk graph)
        base_trunk_edges: List of (u, v) tuples for base trunk
        selected_street_geometry: Selected street GeoDataFrame for spatial buffer
        buildings_gdf: Full building set with service_length_m
        config: CHAConfig with spur parameters
        
    Returns:
        List of (u, v) tuples representing candidate spur edges
    """
    if len(long_service_buildings) == 0:
        return []
    
    # Build set of base trunk edges for exclusion
    base_trunk_set = set(tuple(sorted(e)) for e in base_trunk_edges)
    
    # Group buildings by proximity (simple clustering)
    # For now, find nearest edge for each building
    candidate_edges = {}
    edge_to_buildings = {}
    
    for _, building in long_service_buildings.iterrows():
        building_id = building.get('building_id')
        building_geom = building.geometry
        
        if building_geom is None:
            continue
        
        # Find nearest edge in bbox_street_graph that's not in base trunk
        min_dist = float('inf')
        best_edge = None
        
        for u, v, data in bbox_street_graph.edges(data=True):
            edge_tuple = tuple(sorted((u, v)))
            
            # Skip if edge is in base trunk
            if edge_tuple in base_trunk_set:
                continue
            
            # Get edge geometry
            edge_geom = data.get('geometry')
            if edge_geom is None:
                continue
            
            # Compute distance from building to edge
            dist = float(building_geom.distance(edge_geom))
            
            if dist < min_dist:
                min_dist = dist
                best_edge = edge_tuple
        
        if best_edge is not None:
            if best_edge not in edge_to_buildings:
                edge_to_buildings[best_edge] = []
            edge_to_buildings[best_edge].append(building_id)
    
    # Evaluate each candidate edge
    approved_spurs = []
    total_spur_length = 0.0
    
    for candidate_edge, affected_buildings in edge_to_buildings.items():
        # Check total length constraint
        u, v = candidate_edge
        edge_length = bbox_street_graph[u][v].get('length_m', 0.0)
        
        if total_spur_length + edge_length > config.spur_max_total_length_m:
            continue
        
        # Evaluate candidate
        eval_result = evaluate_spur_candidate(
            candidate_edge,
            affected_buildings,
            base_trunk_edges,
            base_trunk_graph,
            bbox_street_graph,
            selected_street_geometry,
            buildings_gdf,
            config
        )
        
        if eval_result['should_promote']:
            approved_spurs.append(candidate_edge)
            total_spur_length += edge_length
            
            logger.info(
                f"Approved spur edge {candidate_edge}: "
                f"{eval_result['buildings_served']} buildings, "
                f"{eval_result['service_length_reduction_pct']:.1f}% reduction, "
                f"depth={eval_result['depth_from_trunk']}"
            )
    
    logger.info(
        f"Found {len(approved_spurs)} approved spur edges "
        f"(total length: {total_spur_length:.1f}m)"
    )
    
    return approved_spurs


def expand_trunk_with_spurs(
    base_trunk_edges: List[Tuple],
    spur_candidates: List[Tuple],
    bbox_street_graph: nx.Graph
) -> List[Tuple]:
    """
    Merge base trunk edges with approved spurs.
    
    This function combines the base trunk (strict street) with approved spur edges.
    It ensures connectivity by adding shortest paths from spurs to base trunk
    if needed (spurs may be on streets not directly connected to selected streets).
    
    Args:
        base_trunk_edges: List of (u, v) tuples for base trunk (strict street)
        spur_candidates: List of (u, v) tuples for approved spurs
        bbox_street_graph: Graph containing both base trunk and candidate spurs
            (must be cluster-local bbox graph, not global)
        
    Returns:
        List of (u, v) tuples representing expanded trunk (base + spurs + connecting paths)
        
    Example:
        >>> expanded_trunk = expand_trunk_with_spurs(
        ...     base_edges, approved_spurs, bbox_graph
        ... )
        >>> print(f"Expanded trunk: {len(base_edges)} base + {len(approved_spurs)} spurs = {len(expanded_trunk)} total")
    """
    # Start with base trunk
    expanded_trunk = set(tuple(sorted(e)) for e in base_trunk_edges)
    
    # Add spur edges
    for spur_edge in spur_candidates:
        expanded_trunk.add(tuple(sorted(spur_edge)))
    
    # Ensure connectivity: add shortest paths from spurs to base trunk if needed
    base_trunk_nodes = set()
    for u, v in base_trunk_edges:
        base_trunk_nodes.add(u)
        base_trunk_nodes.add(v)
    
    # For each spur edge, ensure it's connected to base trunk
    for spur_edge in spur_candidates:
        u, v = spur_edge
        spur_nodes = {u, v}
        
        # Check if either endpoint is in base trunk
        if u in base_trunk_nodes or v in base_trunk_nodes:
            continue  # Already connected
        
        # Find shortest path from spur to base trunk
        min_path = None
        min_length = float('inf')
        
        for spur_node in spur_nodes:
            for trunk_node in base_trunk_nodes:
                try:
                    path = nx.shortest_path(bbox_street_graph, spur_node, trunk_node, weight='length_m')
                    path_length = sum(
                        bbox_street_graph[path[i]][path[i+1]].get('length_m', 0.0)
                        for i in range(len(path) - 1)
                    )
                    if path_length < min_length:
                        min_length = path_length
                        min_path = path
                except (nx.NetworkXNoPath, KeyError):
                    continue
        
        # Add path edges to expanded trunk
        if min_path is not None:
            for i in range(len(min_path) - 1):
                edge = tuple(sorted((min_path[i], min_path[i+1])))
                expanded_trunk.add(edge)
    
    expanded_list = list(expanded_trunk)
    logger.info(
        f"Expanded trunk: {len(base_trunk_edges)} base edges + "
        f"{len(spur_candidates)} spurs = {len(expanded_list)} total edges"
    )
    
    return expanded_list


def re_snap_buildings_to_expanded_trunk(
    buildings_gdf: gpd.GeoDataFrame,
    trunk_edges: List[Tuple],
    bbox_street_graph: nx.Graph
) -> gpd.GeoDataFrame:
    """
    Re-snap buildings to expanded trunk network.
    
    For each building, finds the nearest point on the expanded trunk network
    (either a trunk node or a point on a trunk edge) and updates attach_node
    and service_length_m accordingly.
    
    Args:
        buildings_gdf: GeoDataFrame with buildings (must have 'building_id' and 'geometry')
        trunk_edges: List of (u, v) tuples for expanded trunk
        bbox_street_graph: Graph containing trunk edges (must contain all trunk + spur edges)
        
    Returns:
        Updated GeoDataFrame with new attach_node and service_length_m
    """
    # Build set of trunk nodes and edges for lookup
    trunk_nodes = set()
    trunk_edges_set = set(tuple(sorted(e)) for e in trunk_edges)
    
    for u, v in trunk_edges:
        trunk_nodes.add(u)
        trunk_nodes.add(v)
    
    buildings_updated = buildings_gdf.copy()
    
    for idx, building in buildings_updated.iterrows():
        building_geom = building.geometry
        if building_geom is None:
            continue
        
        building_id = building.get('building_id', idx)
        
        # Find nearest point on trunk network (node or edge)
        min_dist = float('inf')
        best_node = None
        
        # First, check distance to trunk nodes
        for trunk_node in trunk_nodes:
            node_point = Point(trunk_node)
            dist = float(building_geom.distance(node_point))
            if dist < min_dist:
                min_dist = dist
                best_node = trunk_node
        
        # Then, check distance to trunk edges (for more accurate snapping)
        for edge_tuple in trunk_edges_set:
            u, v = edge_tuple
            
            # Get edge from graph
            if not bbox_street_graph.has_edge(u, v):
                # Try reversed
                if bbox_street_graph.has_edge(v, u):
                    u, v = v, u
                else:
                    continue
            
            edge_data = bbox_street_graph.get_edge_data(u, v)
            edge_geom = edge_data.get('geometry')
            
            if edge_geom is None:
                # Fallback: use straight line between nodes
                edge_geom = LineString([Point(u), Point(v)])
            
            # Project building onto edge
            proj_dist = edge_geom.project(building_geom)
            proj_point = edge_geom.interpolate(proj_dist)
            dist_to_edge = float(building_geom.distance(proj_point))
            
            if dist_to_edge < min_dist:
                min_dist = dist_to_edge
                # Use the nearest endpoint as attach_node (or create new node if very close to edge)
                # For simplicity, use the endpoint that's closer to the projection point
                u_point = Point(u)
                v_point = Point(v)
                dist_to_u = float(proj_point.distance(u_point))
                dist_to_v = float(proj_point.distance(v_point))
                
                if dist_to_u < dist_to_v:
                    best_node = u
                else:
                    best_node = v
        
        if best_node is not None:
            buildings_updated.at[idx, 'attach_node'] = best_node
            buildings_updated.at[idx, 'service_length_m'] = min_dist
        else:
            logger.warning(
                f"Building {building_id}: Could not find nearest trunk node/edge. "
                f"Keeping existing attach_node."
            )
    
    logger.info(
        f"Re-snapped {len(buildings_updated)} buildings to expanded trunk "
        f"({len(trunk_edges)} trunk edges, {len(trunk_nodes)} trunk nodes)"
    )
    
    return buildings_updated


def validate_expanded_trunk(
    trunk_edges: List[Tuple],
    plant_node: Tuple,
    attach_nodes: List[Tuple],
    bbox_street_graph: nx.Graph
) -> bool:
    """
    Validate that expanded trunk is connected and all attach nodes are reachable.
    
    Checks:
    1. Plant node is in trunk
    2. All attach nodes are reachable from plant
    3. Trunk forms a connected subgraph
    
    Args:
        trunk_edges: List of (u, v) tuples for expanded trunk
        plant_node: Plant node (x, y) tuple
        attach_nodes: List of attach node (x, y) tuples
        bbox_street_graph: Graph containing trunk edges
        
    Returns:
        True if valid, raises ValueError if invalid
    """
    # Build trunk subgraph
    trunk_nodes = set()
    for u, v in trunk_edges:
        trunk_nodes.add(u)
        trunk_nodes.add(v)
    
    trunk_subgraph = bbox_street_graph.subgraph(trunk_nodes)
    
    # Check 1: Plant node is in trunk
    if plant_node not in trunk_nodes:
        raise ValueError(f"Plant node {plant_node} not in expanded trunk")
    
    # Check 2: All attach nodes are reachable
    unreachable = []
    for attach_node in attach_nodes:
        if attach_node is None:
            continue
        if attach_node not in trunk_nodes:
            logger.warning(
                f"Attach node {attach_node} not in trunk nodes, skipping validation"
            )
            continue
        try:
            nx.shortest_path(trunk_subgraph, plant_node, attach_node)
        except nx.NetworkXNoPath:
            unreachable.append(attach_node)
    
    if unreachable:
        raise ValueError(
            f"{len(unreachable)} attach node(s) not reachable from plant: {unreachable[:5]}"
        )
    
    # Check 3: Trunk is connected (optional check for cycles)
    if not nx.is_connected(trunk_subgraph):
        logger.warning(
            f"Trunk subgraph is not connected: {nx.number_connected_components(trunk_subgraph)} components"
        )
    
    logger.info(
        f"Expanded trunk validation passed: {len(trunk_edges)} edges, "
        f"{len(trunk_nodes)} nodes, {len(attach_nodes)} attach nodes"
    )
    return True


def collect_routing_diagnostics(
    buildings_gdf: gpd.GeoDataFrame,
    trunk_edges_base: List[Tuple],
    trunk_edges_expanded: Optional[List[Tuple]],
    street_graph: nx.Graph,
    plant_node: Tuple
) -> pd.DataFrame:
    """
    Collect per-building routing diagnostics for analysis and reporting.
    
    For each building, records:
    - path_length_m: length of path from plant to attach node along trunk
    - path_segment_count: number of trunk segments in path
    - service_length_m_before_spurs: service length with base trunk
    - service_length_m_after_spurs: service length with expanded trunk (if applicable)
    - spur_benefit_m: reduction in service length due to spurs
    - spur_benefit_pct: percentage reduction
    
    Args:
        buildings_gdf: GeoDataFrame with buildings (must have 'building_id', 'attach_node', 'service_length_m')
        trunk_edges_base: List of (u, v) tuples for base trunk
        trunk_edges_expanded: Optional list of (u, v) tuples for expanded trunk
        street_graph: NetworkX graph containing trunk edges
        plant_node: Plant node (x, y) tuple
        
    Returns:
        DataFrame with building_id and routing metrics
    """
    diagnostics = []
    
    # Build trunk node sets
    base_trunk_nodes = set()
    for u, v in trunk_edges_base:
        base_trunk_nodes.add(u)
        base_trunk_nodes.add(v)
    
    expanded_trunk_nodes = set()
    if trunk_edges_expanded:
        for u, v in trunk_edges_expanded:
            expanded_trunk_nodes.add(u)
            expanded_trunk_nodes.add(v)
    else:
        expanded_trunk_nodes = base_trunk_nodes
    
    # Build trunk subgraphs
    base_trunk_subgraph = street_graph.subgraph(base_trunk_nodes)
    expanded_trunk_subgraph = street_graph.subgraph(expanded_trunk_nodes) if trunk_edges_expanded else base_trunk_subgraph
    
    for _, building in buildings_gdf.iterrows():
        building_id = building.get('building_id')
        attach_node = building.get('attach_node')
        
        if attach_node is None:
            continue
        
        # Get service lengths
        service_length_before = building.get('service_length_m', 0.0)
        
        # Calculate path length and segment count for base trunk
        path_length_base = 0.0
        path_segments_base = 0
        
        if attach_node in base_trunk_nodes:
            try:
                path_base = nx.shortest_path(base_trunk_subgraph, plant_node, attach_node)
                path_segments_base = len(path_base) - 1
                path_length_base = sum(
                    base_trunk_subgraph[path_base[i]][path_base[i+1]].get('length_m', 0.0)
                    for i in range(len(path_base) - 1)
                )
            except (nx.NetworkXNoPath, KeyError):
                pass
        
        # Calculate path length and segment count for expanded trunk
        path_length_expanded = path_length_base
        path_segments_expanded = path_segments_base
        
        if trunk_edges_expanded and attach_node in expanded_trunk_nodes:
            try:
                path_expanded = nx.shortest_path(expanded_trunk_subgraph, plant_node, attach_node)
                path_segments_expanded = len(path_expanded) - 1
                path_length_expanded = sum(
                    expanded_trunk_subgraph[path_expanded[i]][path_expanded[i+1]].get('length_m', 0.0)
                    for i in range(len(path_expanded) - 1)
                )
            except (nx.NetworkXNoPath, KeyError):
                pass
        
        # Estimate service length after spurs (if expanded trunk exists)
        service_length_after = service_length_before
        if trunk_edges_expanded:
            # Re-estimate service length to expanded trunk
            building_geom = building.geometry
            if building_geom is not None:
                min_dist = float('inf')
                for node in expanded_trunk_nodes:
                    node_point = Point(node)
                    dist = float(building_geom.distance(node_point))
                    if dist < min_dist:
                        min_dist = dist
                service_length_after = min_dist if min_dist != float('inf') else service_length_before
        
        # Calculate spur benefit
        spur_benefit_m = max(0.0, service_length_before - service_length_after)
        spur_benefit_pct = (
            (spur_benefit_m / service_length_before * 100.0)
            if service_length_before > 0
            else 0.0
        )
        
        diagnostics.append({
            'building_id': building_id,
            'path_length_m': path_length_expanded,
            'path_segment_count': path_segments_expanded,
            'service_length_m_before_spurs': service_length_before,
            'service_length_m_after_spurs': service_length_after,
            'spur_benefit_m': spur_benefit_m,
            'spur_benefit_pct': spur_benefit_pct
        })
    
    df = pd.DataFrame(diagnostics)
    logger.info(
        f"Collected routing diagnostics for {len(df)} buildings. "
        f"Median spur benefit: {df['spur_benefit_m'].median():.2f}m "
        f"({df['spur_benefit_pct'].median():.1f}%)"
    )
    
    return df

