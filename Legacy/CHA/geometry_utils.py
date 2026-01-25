"""
Geometry utilities for CHA network building.
Handles street graph construction and building-to-street snapping.
"""

import logging
from typing import Dict, List, Tuple, Optional

import geopandas as gpd
import networkx as nx
import numpy as np
from shapely.geometry import Point, LineString, MultiLineString
from shapely.geometry import MultiPoint
from shapely.ops import linemerge

logger = logging.getLogger(__name__)


def build_street_graph(streets_geom: gpd.GeoDataFrame) -> nx.Graph:
    """
    Convert LineString/MultiLineString GeoDataFrame to NetworkX graph.
    
    Rules:
    - Split MultiLineString into LineStrings
    - Use endpoints as nodes
    - Edge attributes: length_m, original geometry
    
    Args:
        streets_geom: GeoDataFrame with LineString/MultiLineString geometries
        
    Returns:
        NetworkX Graph with:
        - nodes: (x, y) tuples as node identifiers
        - edges: with attributes 'length_m' and 'geometry'
        
    Raises:
        ValueError: If CRS is geographic (not projected)
    """
    # Check CRS
    if streets_geom.crs is None:
        logger.warning("No CRS defined for streets_geom. Assuming projected coordinates.")
    elif streets_geom.crs.is_geographic:
        raise ValueError(
            f"Streets geometry has geographic CRS ({streets_geom.crs}). "
            "Projected CRS (meters) required for distance calculations."
        )
    
    graph = nx.Graph()
    
    for idx, row in streets_geom.iterrows():
        geom = row.geometry
        
        # Handle MultiLineString: split into LineStrings
        if isinstance(geom, MultiLineString):
            lines = list(geom.geoms)
        elif isinstance(geom, LineString):
            lines = [geom]
        else:
            logger.warning(f"Row {idx}: Unsupported geometry type {type(geom)}, skipping.")
            continue
        
        for line in lines:
            if len(line.coords) < 2:
                logger.warning(f"Row {idx}: LineString with < 2 coordinates, skipping.")
                continue
            
            # Get endpoints
            start = line.coords[0]
            end = line.coords[-1]
            
            # Add nodes (if not already present)
            graph.add_node(start, pos=start)
            graph.add_node(end, pos=end)
            
            # Add edge with attributes
            length_m = line.length
            # Preserve OSM attributes from GeoDataFrame
            street_name = row.get("name") if "name" in row else None
            highway_type = row.get("highway") if "highway" in row else None
            
            graph.add_edge(
                start,
                end,
                length_m=length_m,
                geometry=line,
                u=start,  # Start node (u)
                v=end,    # End node (v)
                original_idx=idx,
                street_name=street_name,
                highway_type=highway_type
            )
    
    logger.info(f"Built street graph: {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges")
    return graph


def snap_buildings_to_street_graph(
    buildings_gdf: gpd.GeoDataFrame,
    street_graph: nx.Graph,
    *,
    attach_mode: str = "nearest_node",
    attach_snap_tol_m: float = 2.0,
    min_attach_spacing_m: float = 8.0
) -> Tuple[gpd.GeoDataFrame, nx.Graph]:
    """
    Snap building points to nearest street graph edge.
    
    For each building point:
    - Find nearest edge (by geometric distance)
    - Compute nearest point on edge
    - Compute service length = distance from building to nearest point
    
    Attachment modes:
    - "nearest_node": Use nearest existing graph node (current behavior, causes star-bursts)
    - "split_edge_per_building": Compute projection points only (graph modification happens in insert_building_attach_nodes)
    - "clustered_projection": Compute clustered projection points only (graph modification happens in insert_building_attach_nodes)
    
    Args:
        buildings_gdf: GeoDataFrame with Point geometries (building locations)
        street_graph: NetworkX graph from build_street_graph()
        attach_mode: Attachment strategy ("nearest_node", "split_edge_per_building", "clustered_projection")
        attach_snap_tol_m: If projection is within this distance of existing node, reuse node
        min_attach_spacing_m: For clustered_projection, minimum spacing between attach points
        
    Returns:
        Tuple of:
        - GeoDataFrame with added columns:
          - attach_point: Point geometry on nearest edge
          - attach_node: graph node (x, y tuple) for attachment
          - service_length_m: distance from building to attach_point
        - Updated street_graph (may have new nodes/edges if split_edge_per_building mode)
    """
    result_gdf = buildings_gdf.copy()
    graph = street_graph.copy()  # Work on a copy to avoid mutating original
    
    # Ensure we have Point geometries
    if not all(isinstance(g, Point) for g in buildings_gdf.geometry):
        logger.warning("Some geometries are not Points. Converting to centroids.")
        result_gdf.geometry = result_gdf.geometry.centroid
    
    # Find nearest edge and projection point for each building
    building_projections = []  # List of (building_idx, edge, projection_point, distance)
    
    for idx, building in result_gdf.iterrows():
        building_point = building.geometry
        
        # Find nearest edge
        min_dist = float('inf')
        nearest_edge = None
        nearest_point_on_edge = None
        
        for edge_start, edge_end, edge_data in graph.edges(data=True):
            edge_geom = edge_data.get('geometry')
            if edge_geom is None:
                # Fallback: create LineString from nodes
                edge_geom = LineString([edge_start, edge_end])
            
            # Find nearest point on edge
            point_on_edge = edge_geom.interpolate(edge_geom.project(building_point))
            dist = building_point.distance(point_on_edge)
            
            if dist < min_dist:
                min_dist = dist
                nearest_edge = (edge_start, edge_end)
                nearest_point_on_edge = point_on_edge
        
        if nearest_point_on_edge is not None:
            building_projections.append((idx, nearest_edge, nearest_point_on_edge, min_dist))
        else:
            logger.warning(f"Building {idx}: Could not find nearest edge. Using building location.")
            building_projections.append((idx, None, building_point, 0.0))
    
    # Apply attachment strategy
    # NOTE: For split_edge_per_building and clustered_projection modes, we do NOT modify the graph here.
    # Graph modification happens later in insert_building_attach_nodes() to avoid double-processing.
    # This function only computes projection points and attach_node coordinates.
    if attach_mode == "nearest_node":
        attach_points, attach_nodes, service_lengths = _attach_nearest_node(
            building_projections, graph, attach_snap_tol_m
        )
    elif attach_mode in ("split_edge_per_building", "clustered_projection"):
        # Projection-only mode: compute attach points and nodes without modifying graph
        attach_points, attach_nodes, service_lengths = _attach_projection_only(
            building_projections, graph, attach_snap_tol_m, min_attach_spacing_m, attach_mode
        )
    else:
        raise ValueError(f"Unknown attach_mode: {attach_mode}")
    
    result_gdf['attach_point'] = gpd.GeoSeries(attach_points, crs=result_gdf.crs)
    result_gdf['attach_node'] = attach_nodes
    result_gdf['service_length_m'] = service_lengths
    
    logger.info(
        f"Snapped {len(result_gdf)} buildings to street graph "
        f"(mode: {attach_mode}, {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges)"
    )
    return result_gdf, graph


# ---------------------------
# Helper functions for attachment strategies
# ---------------------------


def _attach_nearest_node(
    building_projections: List[Tuple],
    graph: nx.Graph,
    snap_tol_m: float
) -> Tuple[List[Point], List[Tuple], List[float]]:
    """
    Attachment strategy: Use nearest existing graph node.
    
    This is the original behavior - causes star-burst patterns when multiple
    buildings share the same node.
    """
    attach_points = []
    attach_nodes = []
    service_lengths = []
    
    for building_idx, edge, projection_point, dist in building_projections:
        if edge is None:
            attach_points.append(projection_point)
            attach_nodes.append(None)
            service_lengths.append(0.0)
            continue
        
        edge_start, edge_end = edge
        
        # Check if projection is very close to an existing node
        start_point = Point(edge_start)
        end_point = Point(edge_end)
        
        dist_to_start = projection_point.distance(start_point)
        dist_to_end = projection_point.distance(end_point)
        
        if dist_to_start <= snap_tol_m:
            attach_node = edge_start
        elif dist_to_end <= snap_tol_m:
            attach_node = edge_end
        else:
            # Use closer endpoint
            if dist_to_start < dist_to_end:
                attach_node = edge_start
            else:
                attach_node = edge_end
        
        attach_points.append(projection_point)
        attach_nodes.append(attach_node)
        service_lengths.append(dist)
    
    return attach_points, attach_nodes, service_lengths


def _attach_projection_only(
    building_projections: List[Tuple],
    graph: nx.Graph,
    snap_tol_m: float,
    min_spacing_m: float,
    attach_mode: str
) -> Tuple[List[Point], List[Tuple], List[float]]:
    """
    Projection-only attachment strategy for split_edge_per_building and clustered_projection modes.
    
    This function computes projection points and attach_node coordinates WITHOUT modifying the graph.
    Graph modification (edge splitting) happens later in insert_building_attach_nodes() to ensure
    geometry preservation and avoid double-processing.
    
    Args:
        building_projections: List of (building_idx, edge, projection_point, dist)
        graph: NetworkX graph (not modified)
        snap_tol_m: Snap tolerance for reusing existing nodes
        min_spacing_m: Minimum spacing for clustered_projection mode
        attach_mode: Either "split_edge_per_building" or "clustered_projection"
        
    Returns:
        Tuple of (attach_points, attach_nodes, service_lengths)
        attach_nodes are projection point coordinates (rounded), not graph nodes yet
    """
    attach_points = []
    attach_nodes = []
    service_lengths = []
    
    # Group projections by edge
    edge_groups: Dict[Tuple, List[Tuple[Point, int, float]]] = {}
    
    for building_idx, edge, projection_point, dist in building_projections:
        if edge is None:
            attach_points.append(projection_point)
            attach_nodes.append(None)
            service_lengths.append(0.0)
            continue
        
        edge_normalized = tuple(sorted(edge))
        if edge_normalized not in edge_groups:
            edge_groups[edge_normalized] = []
        
        edge_groups[edge_normalized].append((projection_point, building_idx, dist))
    
    # Process each edge group
    for edge_normalized, projections in edge_groups.items():
        edge_start, edge_end = edge_normalized
        edge_data = graph.get_edge_data(edge_start, edge_end)
        
        if edge_data is None:
            # Edge might not exist, skip
            for proj_point, b_idx, dist in projections:
                attach_points.append(proj_point)
                attach_nodes.append(None)
                service_lengths.append(dist)
            continue
        
        edge_geom = edge_data.get('geometry')
        if edge_geom is None:
            edge_geom = LineString([edge_start, edge_end])
        
        # Get positions along edge for all projections
        projections_with_pos = []
        for proj_point, b_idx, dist in projections:
            # Check if very close to existing node
            dist_to_start = proj_point.distance(Point(edge_start))
            dist_to_end = proj_point.distance(Point(edge_end))
            
            if dist_to_start <= snap_tol_m:
                attach_points.append(proj_point)
                attach_nodes.append(edge_start)
                service_lengths.append(dist)
                continue
            elif dist_to_end <= snap_tol_m:
                attach_points.append(proj_point)
                attach_nodes.append(edge_end)
                service_lengths.append(dist)
                continue
            
            # Project onto edge to get position
            pos = edge_geom.project(proj_point)
            projections_with_pos.append((pos, proj_point, b_idx, dist))
        
        if len(projections_with_pos) == 0:
            continue
        
        # Sort by position along edge
        projections_with_pos.sort(key=lambda x: x[0])
        
        # For clustered_projection, group nearby projections
        if attach_mode == "clustered_projection":
            clusters = []
            current_cluster = [projections_with_pos[0]]
            
            for i in range(1, len(projections_with_pos)):
                pos, proj_point, b_idx, dist = projections_with_pos[i]
                prev_pos = projections_with_pos[i-1][0]
                
                if abs(pos - prev_pos) < min_spacing_m:
                    current_cluster.append((pos, proj_point, b_idx, dist))
                else:
                    clusters.append(current_cluster)
                    current_cluster = [(pos, proj_point, b_idx, dist)]
            
            if current_cluster:
                clusters.append(current_cluster)
            
            # For each cluster, use centroid as attach node
            for cluster in clusters:
                cluster_points = [p[1] for p in cluster]
                cluster_centroid = MultiPoint(cluster_points).centroid
                cluster_node = _round_xy(cluster_centroid.x, cluster_centroid.y)
                
                for pos, proj_point, b_idx, dist in cluster:
                    attach_points.append(proj_point)
                    attach_nodes.append(cluster_node)
                    service_lengths.append(dist)
        else:  # split_edge_per_building
            # Each projection gets its own attach node (rounded projection point)
            for pos, proj_point, b_idx, dist in projections_with_pos:
                attach_node = _round_xy(proj_point.x, proj_point.y)
                attach_points.append(proj_point)
                attach_nodes.append(attach_node)
                service_lengths.append(dist)
    
    return attach_points, attach_nodes, service_lengths


def _attach_split_edge_per_building(
    building_projections: List[Tuple],
    graph: nx.Graph,
    snap_tol_m: float
) -> Tuple[List[Point], List[Tuple], List[float], nx.Graph]:
    """
    Attachment strategy: Split edge at projection point, create new node per building.
    
    This ensures main pipes follow streets and each building has a distinct connection point.
    """
    attach_points = []
    attach_nodes = []
    service_lengths = []
    
    # Track which edges have been split and where
    # edge -> list of (projection_point, building_idx, dist) sorted by position along edge
    edge_splits: Dict[Tuple, List[Tuple[Point, int, float]]] = {}
    
    # First pass: collect all projections per edge
    for building_idx, edge, projection_point, dist in building_projections:
        if edge is None:
            attach_points.append(projection_point)
            attach_nodes.append(None)
            service_lengths.append(0.0)
            continue
        
        edge_normalized = tuple(sorted(edge))
        if edge_normalized not in edge_splits:
            edge_splits[edge_normalized] = []
        
        edge_splits[edge_normalized].append((projection_point, building_idx, dist))
    
    # Second pass: split edges and create new nodes
    for edge_normalized, projections in edge_splits.items():
        edge_start, edge_end = edge_normalized
        edge_data = graph.get_edge_data(edge_start, edge_end)
        
        if edge_data is None:
            # Edge might have been removed, skip
            continue
        
        edge_geom = edge_data.get('geometry')
        if edge_geom is None:
            edge_geom = LineString([edge_start, edge_end])
        
        # Sort projections by position along edge (from start to end)
        projections_with_position = []
        for proj_point, b_idx, dist in projections:
            # Check if very close to existing node
            dist_to_start = proj_point.distance(Point(edge_start))
            dist_to_end = proj_point.distance(Point(edge_end))
            
            if dist_to_start <= snap_tol_m:
                # Reuse start node
                attach_points.append(proj_point)
                attach_nodes.append(edge_start)
                service_lengths.append(dist)
                continue
            elif dist_to_end <= snap_tol_m:
                # Reuse end node
                attach_points.append(proj_point)
                attach_nodes.append(edge_end)
                service_lengths.append(dist)
                continue
            
            # Project onto edge to get position
            position = edge_geom.project(proj_point)
            projections_with_position.append((position, proj_point, b_idx, dist))
        
        if len(projections_with_position) == 0:
            continue
        
        # Sort by position along edge
        projections_with_position.sort(key=lambda x: x[0])
        
        # Split edge: create new nodes and update graph
        current_start = edge_start
        current_start_pos = 0.0
        
        # Remove original edge
        graph.remove_edge(edge_start, edge_end)
        original_length = edge_data.get('length_m', edge_geom.length)
        
        for pos, proj_point, b_idx, dist in projections_with_position:
            # Create new node at projection point
            new_node = (proj_point.x, proj_point.y)
            
            # Add node to graph
            graph.add_node(new_node, pos=new_node)
            
            # Create edge segment from current_start to new_node
            segment_length = original_length * (pos - current_start_pos) / edge_geom.length
            segment_geom = LineString([
                Point(current_start),
                proj_point
            ])
            
            graph.add_edge(
                current_start,
                new_node,
                length_m=segment_length,
                geometry=segment_geom,
                original_idx=edge_data.get('original_idx')
            )
            
            # Record attachment
            attach_points.append(proj_point)
            attach_nodes.append(new_node)
            service_lengths.append(dist)
            
            # Update for next segment
            current_start = new_node
            current_start_pos = pos
        
        # Add final segment from last new node to edge_end
        final_pos = edge_geom.length
        final_segment_length = original_length * (final_pos - current_start_pos) / edge_geom.length
        final_segment_geom = LineString([
            Point(current_start),
            Point(edge_end)
        ])
        
        graph.add_edge(
            current_start,
            edge_end,
            length_m=final_segment_length,
            geometry=final_segment_geom,
            original_idx=edge_data.get('original_idx')
        )
    
    return attach_points, attach_nodes, service_lengths, graph


def _attach_clustered_projection(
    building_projections: List[Tuple],
    graph: nx.Graph,
    snap_tol_m: float,
    min_spacing_m: float
) -> Tuple[List[Point], List[Tuple], List[float], nx.Graph]:
    """
    Attachment strategy: Group nearby projections, share one node per group.
    
    This is a middle ground between nearest_node and split_edge_per_building.
    """
    attach_points = []
    attach_nodes = []
    service_lengths = []
    
    # Group projections by edge and position
    edge_groups: Dict[Tuple, List[Tuple[Point, int, float]]] = {}
    
    for building_idx, edge, projection_point, dist in building_projections:
        if edge is None:
            attach_points.append(projection_point)
            attach_nodes.append(None)
            service_lengths.append(0.0)
            continue
        
        edge_normalized = tuple(sorted(edge))
        if edge_normalized not in edge_groups:
            edge_groups[edge_normalized] = []
        
        edge_groups[edge_normalized].append((projection_point, building_idx, dist))
    
    # Process each edge: cluster nearby projections
    for edge_normalized, projections in edge_groups.items():
        edge_start, edge_end = edge_normalized
        edge_data = graph.get_edge_data(edge_start, edge_end)
        
        if edge_data is None:
            continue
        
        edge_geom = edge_data.get('geometry')
        if edge_geom is None:
            edge_geom = LineString([edge_start, edge_end])
        
        # Sort by position along edge
        projections_with_pos = []
        for proj_point, b_idx, dist in projections:
            dist_to_start = proj_point.distance(Point(edge_start))
            dist_to_end = proj_point.distance(Point(edge_end))
            
            if dist_to_start <= snap_tol_m:
                attach_points.append(proj_point)
                attach_nodes.append(edge_start)
                service_lengths.append(dist)
                continue
            elif dist_to_end <= snap_tol_m:
                attach_points.append(proj_point)
                attach_nodes.append(edge_end)
                service_lengths.append(dist)
                continue
            
            pos = edge_geom.project(proj_point)
            projections_with_pos.append((pos, proj_point, b_idx, dist))
        
        if len(projections_with_pos) == 0:
            continue
        
        projections_with_pos.sort(key=lambda x: x[0])
        
        # Cluster: group projections within min_spacing_m
        clusters = []
        current_cluster = [projections_with_pos[0]]
        
        for i in range(1, len(projections_with_pos)):
            pos, proj_point, b_idx, dist = projections_with_pos[i]
            prev_proj = projections_with_pos[i-1][1]
            actual_dist = proj_point.distance(prev_proj)
            
            if actual_dist < min_spacing_m:
                current_cluster.append((pos, proj_point, b_idx, dist))
            else:
                clusters.append(current_cluster)
                current_cluster = [(pos, proj_point, b_idx, dist)]
        
        if current_cluster:
            clusters.append(current_cluster)
        
        # For each cluster, create one node at the cluster centroid
        graph.remove_edge(edge_start, edge_end)
        original_length = edge_data.get('length_m', edge_geom.length)
        
        current_start = edge_start
        current_start_pos = 0.0
        
        for cluster in clusters:
            # Compute cluster centroid
            cluster_points = [p[1] for p in cluster]
            cluster_centroid = MultiPoint(cluster_points).centroid
            cluster_node = (cluster_centroid.x, cluster_centroid.y)
            
            # Add node
            graph.add_node(cluster_node, pos=cluster_node)
            
            # Compute position along edge for centroid
            centroid_pos = edge_geom.project(cluster_centroid)
            
            # Create edge segment
            segment_length = original_length * (centroid_pos - current_start_pos) / edge_geom.length
            segment_geom = LineString([Point(current_start), cluster_centroid])
            
            graph.add_edge(
                current_start,
                cluster_node,
                length_m=segment_length,
                geometry=segment_geom,
                original_idx=edge_data.get('original_idx')
            )
            
            # Assign all buildings in cluster to this node
            for pos, proj_point, b_idx, dist in cluster:
                attach_points.append(proj_point)
                attach_nodes.append(cluster_node)
                service_lengths.append(dist)
            
            current_start = cluster_node
            current_start_pos = centroid_pos
        
        # Final segment
        final_pos = edge_geom.length
        final_segment_length = original_length * (final_pos - current_start_pos) / edge_geom.length
        final_segment_geom = LineString([Point(current_start), Point(edge_end)])
        
        graph.add_edge(
            current_start,
            edge_end,
            length_m=final_segment_length,
            geometry=final_segment_geom,
            original_idx=edge_data.get('original_idx')
        )
    
    return attach_points, attach_nodes, service_lengths, graph


def select_dominant_component_by_buildings(
    graph: nx.Graph,
    buildings_snapped: gpd.GeoDataFrame
) -> Tuple[nx.Graph, gpd.GeoDataFrame, Dict]:
    """
    Select the connected component that contains the highest number of building attach_nodes.
    
    This ensures we build the network only within the dominant connected component,
    preventing disconnected subgraphs that cause singular Jacobian matrices.
    
    Args:
        graph: NetworkX street graph
        buildings_snapped: GeoDataFrame with 'attach_node' column
        
    Returns:
        Tuple of:
        - subgraph of dominant component
        - buildings filtered to those attaching to that component
        - stats dict with component information
    """
    attach_nodes = buildings_snapped["attach_node"].dropna().tolist()
    if len(attach_nodes) == 0:
        logger.warning("No attach nodes found in buildings_snapped")
        return graph, buildings_snapped, {"reason": "no_attach_nodes"}
    
    components = list(nx.connected_components(graph))
    if len(components) <= 1:
        logger.info(f"Graph has {len(components)} component(s), using entire graph")
        return graph, buildings_snapped, {
            "n_components": len(components),
            "dominant_buildings": len(attach_nodes)
        }
    
    # Count buildings per component
    comp_counts = []
    for comp in components:
        count = sum(1 for n in attach_nodes if n in comp)
        comp_counts.append(count)
    
    # Select component with most buildings
    best_idx = int(np.argmax(comp_counts))
    best_comp = components[best_idx]
    
    dominant_nodes = set(best_comp)
    buildings_dom = buildings_snapped[
        buildings_snapped["attach_node"].isin(dominant_nodes)
    ].copy()
    
    G_dom = graph.subgraph(dominant_nodes).copy()
    
    stats = {
        "n_components": len(components),
        "dominant_component_index": best_idx,
        "dominant_buildings": len(buildings_dom),
        "total_buildings": len(buildings_snapped),
        "graph_nodes_before": graph.number_of_nodes(),
        "graph_edges_before": graph.number_of_edges(),
        "graph_nodes_after": G_dom.number_of_nodes(),
        "graph_edges_after": G_dom.number_of_edges(),
    }
    
    logger.info(
        f"Selected dominant component: {stats['dominant_buildings']}/{stats['total_buildings']} buildings, "
        f"{stats['graph_nodes_after']} nodes, {stats['graph_edges_after']} edges"
    )
    
    return G_dom, buildings_dom, stats


def choose_plant_node(
    graph: nx.Graph,
    buildings_gdf: gpd.GeoDataFrame,
    *,
    design_loads: Optional[Dict[str, float]] = None,
    candidate_nodes: Optional[set] = None
) -> Tuple:
    """
    Choose plant/source node deterministically.
    
    Heuristic: Choose the street graph node closest to the weighted centroid
    of all building points in the cluster. If design_loads are provided,
    the centroid is weighted by building heat demand (kW).
    
    IMPORTANT: Only uses nodes from the graph G, ensuring the plant is placed
    on a street that was included in the filtered corridor (e.g., via --street-name).
    
    Args:
        graph: NetworkX street graph (already filtered to allowed streets)
        buildings_gdf: GeoDataFrame with building locations (must have 'building_id')
        design_loads: Optional dict mapping building_id -> design_load_kw
                      If provided, centroid is weighted by heat demand
        candidate_nodes: Optional set of candidate nodes to restrict search to
                         (e.g., nodes in dominant connected component)
                         If None, uses all nodes in graph
        
    Returns:
        Node identifier (x, y tuple) for plant location
    """
    if len(buildings_gdf) == 0:
        raise ValueError("Cannot choose plant node: no buildings provided")
    
    if len(graph.nodes()) == 0:
        raise ValueError("Cannot choose plant node: graph has no nodes")
    
    # 1) Create a weighted centroid
    if design_loads is not None:
        # design_loads: dict building_id -> kw
        weights = buildings_gdf["building_id"].map(design_loads).fillna(1.0).to_numpy()
    else:
        weights = np.ones(len(buildings_gdf))
    
    xs = buildings_gdf.geometry.x.to_numpy()
    ys = buildings_gdf.geometry.y.to_numpy()
    
    cx = np.average(xs, weights=weights)
    cy = np.average(ys, weights=weights)
    target = Point(cx, cy)
    
    # 2) Choose nearest graph node to that centroid
    # Restrict to candidate_nodes if provided, otherwise use all nodes in graph
    nodes_iter = list(graph.nodes())
    if candidate_nodes is not None:
        nodes_iter = [n for n in nodes_iter if n in candidate_nodes]
        if len(nodes_iter) == 0:
            logger.warning("No candidate nodes found in graph, using all nodes")
            nodes_iter = list(graph.nodes())
    
    # Ensure we only use nodes that exist in the graph
    # (This is already guaranteed since nodes_iter comes from graph.nodes())
    best = min(nodes_iter, key=lambda n: target.distance(Point(n[0], n[1])))
    
    min_dist = target.distance(Point(best[0], best[1]))
    logger.info(f"Chose plant node: {best} (distance from {'weighted' if design_loads else 'unweighted'} centroid: {min_dist:.2f}m)")
    return best


def build_trunk_topology(
    graph: nx.Graph,
    plant_node: Tuple,
    attach_nodes: List[Tuple],
    trunk_mode: str,
    edge_cost_mode: str = "length_only"
) -> List[Tuple]:
    """
    Build trunk topology based on selected trunk_mode.
    
    trunk_mode options:
    - full_street: return all edges in the (pre-filtered) street graph
    - paths_to_buildings / selected_streets / strict_street: minimal backbone = union of shortest paths
    - strict_street: alias for selected_streets (explicit)
    
    edge_cost_mode options:
    - length_only: use pure geometric length (length_m) as Dijkstra weight
    - avoid_primary_roads: apply penalty factor to major OSM road types
    
    Args:
        graph: NetworkX graph of street network
        plant_node: Plant node (x, y) tuple
        attach_nodes: List of attach node (x, y) tuples
        trunk_mode: Trunk topology policy
        edge_cost_mode: Edge cost mode for Dijkstra weights
        
    Returns:
        List of (u, v) tuples representing trunk edges
    """
    # Normalize trunk_mode aliases
    if trunk_mode == "strict_street":
        trunk_mode = "selected_streets"
    
    if trunk_mode == "full_street":
        trunk = list(graph.edges())
        logger.info(f"Built trunk topology (full_street): {len(trunk)} edges")
        return trunk
    
    if trunk_mode in ("paths_to_buildings", "selected_streets"):
        # Determine edge weight function based on cost mode
        def get_edge_weight(u, v, data):
            """Get edge weight for Dijkstra based on cost mode."""
            base_weight = data.get('length_m', 1.0)
            
            if edge_cost_mode == "avoid_primary_roads":
                highway_type = data.get('highway_type', '')
                if highway_type in ('primary', 'trunk'):
                    penalty_factor = 1.3  # Configurable: penalize major roads by 30%
                    return base_weight * penalty_factor
            
            return base_weight
        
        trunk = set()
        for attach_node in attach_nodes:
            if attach_node is None:
                continue
            try:
                # Use custom weight function for Dijkstra
                path = nx.shortest_path(
                    graph, 
                    plant_node, 
                    attach_node, 
                    weight=get_edge_weight
                )
                for i in range(len(path) - 1):
                    e = (path[i], path[i + 1])
                    trunk.add(tuple(sorted(e)))
            except nx.NetworkXNoPath:
                logger.warning(f"No path from plant {plant_node} to attach node {attach_node}")
                continue
        trunk_edges = list(trunk)
        logger.info(f"Built trunk topology ({trunk_mode}, cost_mode={edge_cost_mode}): {len(trunk_edges)} edges")
        return trunk_edges
    
    raise ValueError(f"Unknown trunk_mode: {trunk_mode}")


# ---------------------------
# Projection and edge splitting utilities
# ---------------------------


def _round_xy(x: float, y: float, precision: int = 3) -> Tuple[float, float]:
    """
    Round x, y coordinates to specified precision.
    
    Args:
        x: X coordinate
        y: Y coordinate
        precision: Number of decimal places (default: 3)
        
    Returns:
        Tuple of (rounded_x, rounded_y)
    """
    return (round(float(x), precision), round(float(y), precision))


def find_nearest_edge_for_points(
    points_gdf: gpd.GeoDataFrame,
    edges_gdf: gpd.GeoDataFrame
) -> List[Dict]:
    """
    Find nearest edge for each point using spatial indexing for performance.
    
    Returns a list of dictionaries with:
    - building_id: Building identifier
    - edge_idx: Index of nearest edge in edges_gdf
    - u: Start node of edge (from edges_gdf)
    - v: End node of edge (from edges_gdf)
    - proj_point: Point geometry of projection onto edge
    - dist_to_edge_m: Distance from point to edge in meters
    - dist_along_m: Distance along edge from start to projection point
    
    Args:
        points_gdf: GeoDataFrame with Point geometries and 'building_id' column
        edges_gdf: GeoDataFrame with LineString geometries and 'u', 'v' columns
        
    Returns:
        List of dictionaries with projection information for each point
    """
    records = []
    
    # Validate required columns
    if 'building_id' not in points_gdf.columns:
        raise ValueError("points_gdf must have 'building_id' column")
    if 'u' not in edges_gdf.columns or 'v' not in edges_gdf.columns:
        raise ValueError("edges_gdf must have 'u' and 'v' columns")
    
    # Spatial index for speed
    sindex = edges_gdf.sindex
    
    for _, row in points_gdf.iterrows():
        b_id = row["building_id"]
        p = row.geometry
        
        # Candidate edges by bbox hit
        candidate_idx = list(sindex.intersection(p.buffer(50).bounds))
        if not candidate_idx:
            # Fallback: check all edges if spatial index returns nothing
            candidate_idx = list(range(len(edges_gdf)))
        
        candidates = edges_gdf.iloc[candidate_idx]
        
        # Distance to each candidate line
        dists = candidates.geometry.distance(p)
        best_local_idx = int(dists.idxmin())
        best_edge = edges_gdf.loc[best_local_idx]
        
        line: LineString = best_edge.geometry
        proj_len = line.project(p)
        proj_point = line.interpolate(proj_len)
        
        records.append({
            "building_id": b_id,
            "edge_idx": best_local_idx,
            "u": best_edge["u"],
            "v": best_edge["v"],
            "proj_point": proj_point,
            "dist_to_edge_m": float(p.distance(proj_point)),
            "dist_along_m": float(proj_len)
        })
    
    return records


def cut_linestring(line: LineString, distances: List[float]) -> List[LineString]:
    """
    Split a LineString into segments at given distances along the line.
    
    Args:
        line: LineString to split
        distances: Sorted unique list of floats between 0 and line.length
        
    Returns:
        List of LineString segments
    """
    if not distances:
        return [line]
    
    # Filter distances to valid range
    distances = sorted(set([d for d in distances if 0 < d < line.length]))
    if not distances:
        return [line]
    
    # Check if substring method is available (Shapely >= 2.0)
    if hasattr(line, 'substring'):
        # Use native substring method
        segments = []
        last = 0.0
        for d in distances:
            seg = line.substring(last, d)
            if seg.length > 0:
                segments.append(seg)
            last = d
        tail = line.substring(last, line.length)
        if tail.length > 0:
            segments.append(tail)
        return segments
    else:
        # Fallback: manual cutting using coordinate interpolation
        return _cut_linestring_manual(line, distances)


def _cut_linestring_manual(line: LineString, distances: List[float]) -> List[LineString]:
    """
    Manual implementation of LineString cutting for Shapely versions without substring.
    
    Uses coordinate interpolation to split the line at specified distances.
    
    Args:
        line: LineString to split
        distances: Sorted unique list of distances along the line
        
    Returns:
        List of LineString segments
    """
    if not distances:
        return [line]
    
    # Get all coordinates
    coords = list(line.coords)
    if len(coords) < 2:
        return [line]
    
    segments = []
    total_length = line.length
    
    # Build list of all split points (including start and end)
    split_points = [0.0] + distances + [total_length]
    
    # Process each segment
    for i in range(len(split_points) - 1):
        start_dist = split_points[i]
        end_dist = split_points[i + 1]
        
        if end_dist <= start_dist:
            continue
        
        # Find coordinates for this segment
        segment_coords = []
        
        # Add start point
        if start_dist == 0.0:
            segment_coords.append(coords[0])
        else:
            start_point = line.interpolate(start_dist)
            segment_coords.append((start_point.x, start_point.y))
        
        # Add intermediate coordinates that fall within this segment
        cumulative_dist = 0.0
        for j in range(len(coords) - 1):
            seg_start = Point(coords[j])
            seg_end = Point(coords[j + 1])
            seg_length = seg_start.distance(seg_end)
            
            seg_start_dist = cumulative_dist
            seg_end_dist = cumulative_dist + seg_length
            
            # Check if this coordinate segment overlaps with our desired segment
            if seg_end_dist > start_dist and seg_start_dist < end_dist:
                # Add start of coordinate segment if it's within our range
                if seg_start_dist >= start_dist and seg_start_dist < end_dist:
                    if not segment_coords or segment_coords[-1] != coords[j]:
                        segment_coords.append(coords[j])
                # Add end of coordinate segment if it's within our range
                if seg_end_dist <= end_dist and seg_end_dist > start_dist:
                    if not segment_coords or segment_coords[-1] != coords[j + 1]:
                        segment_coords.append(coords[j + 1])
            
            cumulative_dist += seg_length
        
        # Add end point
        if end_dist == total_length:
            if not segment_coords or segment_coords[-1] != coords[-1]:
                segment_coords.append(coords[-1])
        else:
            end_point = line.interpolate(end_dist)
            end_coord = (end_point.x, end_point.y)
            if not segment_coords or segment_coords[-1] != end_coord:
                segment_coords.append(end_coord)
        
        # Create segment if we have at least 2 points
        if len(segment_coords) >= 2:
            # Remove duplicate consecutive points
            cleaned_coords = [segment_coords[0]]
            for coord in segment_coords[1:]:
                if coord != cleaned_coords[-1]:
                    cleaned_coords.append(coord)
            
            if len(cleaned_coords) >= 2:
                seg = LineString(cleaned_coords)
                if seg.length > 0:
                    segments.append(seg)
    
    return segments if segments else [line]

