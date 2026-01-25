import geopandas as gpd
import pandas as pd
import numpy as np
import networkx as nx
from shapely.geometry import Point, LineString
from typing import List, Tuple, Dict, Any, Optional
import logging
from pathlib import Path
import pandapipes as pp

logger = logging.getLogger(__name__)

def build_dh_network_for_cluster(
    cluster_id: str,
    buildings: gpd.GeoDataFrame,
    streets: gpd.GeoDataFrame,
    plant_coords: Tuple[float, float],
    pipe_catalog: pd.DataFrame,
    attach_mode: str = 'split_edge_per_building',
    trunk_mode: str = 'paths_to_buildings',
    config: Optional[Any] = None
) -> Tuple[pp.pandapipesNet, Dict[str, Any]]:
    """
    Complete DH network builder from GIS data.
    
    Returns:
        Tuple of (pandapipesNet, topology_info_dict)
    """
    logger.info(f"Building DH network for cluster {cluster_id}")
    
    # Step 1: Build street graph
    street_graph = build_street_graph(streets)
    logger.info(f"Street graph: {street_graph.number_of_nodes()} nodes, {street_graph.number_of_edges()} edges")
    
    # Step 2: Select plant node (find nearest street node to plant_coords)
    plant_node = snap_plant_to_graph(street_graph, plant_coords)
    logger.info(f"Plant node: {plant_node}")
    
    # Step 3: Attach buildings to street graph
    buildings_snapped = attach_buildings_to_street(
        buildings, street_graph, attach_mode
    )
    logger.info(f"Attached {len(buildings_snapped)} buildings to street graph")
    
    # Step 4: Build trunk topology
    trunk_edges, service_connections = build_trunk_topology(
        street_graph, plant_node, buildings_snapped, trunk_mode
    )
    logger.info(f"Trunk: {len(trunk_edges)} edges, Service: {len(service_connections)} connections")
    
    # Step 5: Create pandapipes network
    net = create_pandapipes_network(
        street_graph, trunk_edges, service_connections, 
        buildings_snapped, plant_node, pipe_catalog, config
    )
    
    # Store topology info for later use
    topology_info = {
        'street_graph': street_graph,
        'plant_node': plant_node,
        'trunk_edges': trunk_edges,
        'service_connections': service_connections,
        'buildings_snapped': buildings_snapped
    }
    
    return net, topology_info


def build_street_graph(streets: gpd.GeoDataFrame) -> nx.Graph:
    """
    Convert street GeoDataFrame to NetworkX graph.
    
    Each LineString becomes an edge between its endpoints.
    """
    G = nx.Graph()
    
    for idx, row in streets.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        
        # Handle both LineString and MultiLineString
        if geom.geom_type == 'LineString':
            coords = list(geom.coords)
        elif geom.geom_type == 'MultiLineString':
            coords = []
            for line in geom.geoms:
                coords.extend(list(line.coords))
        else:
            logger.warning(f"Skipping invalid geometry type: {geom.geom_type}")
            continue
        
        # Add nodes for start and end points
        start = tuple(coords[0])  # (x, y)
        end = tuple(coords[-1])   # (x, y)
        
        # Round coordinates to avoid floating point issues
        start = (round(start[0], 3), round(start[1], 3))
        end = (round(end[0], 3), round(end[1], 3))
        
        # Add edge with attributes
        length_m = geom.length
        G.add_edge(start, end, 
                  length_m=length_m,
                  street_id=row.get('street_id', f'street_{idx}'),
                  geometry=LineString([start, end]))
    
    logger.info(f"Built street graph with {G.number_of_nodes()} nodes and {G.number_of_edges()} edges")
    return G


def snap_plant_to_graph(
    G: nx.Graph, 
    plant_coords: Tuple[float, float]
) -> Tuple[float, float]:
    """
    Find nearest node in graph to plant coordinates.
    
    If no node within 100m, creates new node at plant_coords.
    """
    plant_point = Point(plant_coords)
    
    # Find nearest node
    min_dist = float('inf')
    nearest_node = None
    
    for node in G.nodes():
        node_point = Point(node)
        dist = plant_point.distance(node_point)
        if dist < min_dist:
            min_dist = dist
            nearest_node = node
    
    # If too far (>100m), add new node
    if min_dist > 100:
        logger.warning(f"Plant is {min_dist:.1f}m from nearest street, adding new node")
        new_node = (round(plant_coords[0], 3), round(plant_coords[1], 3))
        
        # Connect to nearest street
        if nearest_node:
            # Find nearest point on edge to connect
            connecting_edge = None
            min_edge_dist = float('inf')
            
            for u, v, data in G.edges(data=True):
                line = data['geometry']
                dist = line.distance(plant_point)
                if dist < min_edge_dist:
                    min_edge_dist = dist
                    connecting_edge = (u, v)
            
            if connecting_edge:
                # Split edge and add plant node
                u, v = connecting_edge
                old_data = G[u][v]
                G.remove_edge(u, v)
                G.add_edge(u, new_node, length_m=min_edge_dist, street_id='plant_connection',
                          geometry=LineString([u, new_node]))
                G.add_edge(new_node, v, length_m=old_data.get('length_m', min_edge_dist) - min_edge_dist, 
                          street_id='plant_connection', geometry=LineString([new_node, v]))
                logger.info(f"Split edge to connect plant: {new_node}")
        
        return new_node
    else:
        logger.info(f"Snapped plant to existing node: {nearest_node} (distance={min_dist:.1f}m)")
        return nearest_node


def attach_buildings_to_street(
    buildings: gpd.GeoDataFrame,
    G: nx.Graph,
    attach_mode: str = 'split_edge_per_building'
) -> gpd.GeoDataFrame:
    """
    Attach buildings to nearest point on street graph.
    
    Modes:
    - 'nearest_node': Attach to nearest existing node
    - 'split_edge_per_building': Split edge at projection point for each building
    """
    buildings = buildings.copy()
    attach_nodes = []
    
    for idx, building in buildings.iterrows():
        building_id = building['building_id']
        building_point = building.geometry.centroid
        
        # Find nearest edge
        min_dist = float('inf')
        nearest_edge = None
        nearest_point = None
        
        for u, v, data in G.edges(data=True):
            line = data['geometry']
            dist = line.distance(building_point)
            if dist < min_dist:
                min_dist = dist
                nearest_edge = (u, v)
                nearest_point = line.interpolate(line.project(building_point))
        
        if nearest_edge is None:
            logger.warning(f"No street edge found for building {building_id}")
            attach_nodes.append(None)
            continue
        
        if min_dist > 500:  # 500m threshold
            logger.warning(f"Building {building_id} is {min_dist:.1f}m from nearest street")
        
        # Handle attachment modes
        if attach_mode == 'nearest_node':
            # Choose closest endpoint
            u, v = nearest_edge
            dist_u = Point(u).distance(building_point)
            dist_v = Point(v).distance(building_point)
            attach_node = u if dist_u < dist_v else v
            attach_nodes.append(attach_node)
            
        elif attach_mode == 'split_edge_per_building':
            # Split edge at projection point
            u, v = nearest_edge
            G.remove_edge(u, v)
            
            # New node at projection point
            new_node = (round(nearest_point.x, 3), round(nearest_point.y, 3))
            G.add_edge(u, new_node, length_m=LineString([u, new_node]).length, street_id=f'attach_{building_id}',
                      geometry=LineString([u, new_node]))
            G.add_edge(new_node, v, length_m=LineString([new_node, v]).length, street_id=f'attach_{building_id}',
                      geometry=LineString([new_node, v]))
            
            attach_nodes.append(new_node)
            logger.debug(f"Split edge for building {building_id}: added node {new_node}")
        
        else:
            raise ValueError(f"Unknown attach_mode: {attach_mode}")
    
    buildings['attach_node'] = attach_nodes
    return buildings


def build_trunk_topology(
    G: nx.Graph,
    plant_node: Tuple[float, float],
    buildings: gpd.GeoDataFrame,
    mode: str = 'paths_to_buildings'
) -> Tuple[List[Tuple], List[Tuple]]:
    """
    Build trunk edges connecting plant to building attachment points.
    
    Modes:
    - 'paths_to_buildings': Minimal tree connecting plant to all attach nodes
    - 'selected_streets': Use pre-selected street segments (not implemented here)
    """
    attach_nodes = buildings['attach_node'].dropna().unique()
    logger.info(f"Building trunk topology mode={mode} for {len(attach_nodes)} attach nodes")
    
    if mode == 'paths_to_buildings':
        # Build minimal spanning tree from plant to all attach nodes
        # First, compute shortest paths from plant to each attach node
        paths = {}
        for attach_node in attach_nodes:
            try:
                path = nx.shortest_path(G, plant_node, attach_node, weight='length_m')
                paths[attach_node] = path
            except nx.NetworkXNoPath:
                logger.warning(f"No path from plant to attach_node {attach_node}")
                continue
        
        # Union all paths to get trunk edges
        trunk_nodes = set()
        for path in paths.values():
            trunk_nodes.update(path)
        
        trunk_edges = []
        for path in paths.values():
            edges = list(zip(path[:-1], path[1:]))
            trunk_edges.extend(edges)
        
        # Remove duplicates
        trunk_edges = list(set(trunk_edges))
        
    else:
        raise ValueError(f"Unknown trunk_mode: {mode}")
    
    # Build service connections (building_id -> attach_node)
    service_connections = []
    for _, building in buildings.iterrows():
        building_id = building['building_id']
        attach_node = building.get('attach_node')
        if attach_node:
            service_connections.append((building_id, attach_node))
    
    return trunk_edges, service_connections


def create_pandapipes_network(
    G: nx.Graph,
    trunk_edges: List[Tuple],
    service_connections: List[Tuple],
    buildings: gpd.GeoDataFrame,
    plant_node: Tuple[float, float],
    pipe_catalog: pd.DataFrame,
    config: Optional[Any] = None
) -> pp.pandapipesNet:
    """
    Create pandapipes network from topology.
    """
    # Initialize network
    net = pp.create_empty_network("district_heating", fluid="water")
    
    # Create pipe standard types
    # Default trunk pipe type (DN50 = 50mm inner diameter)
    trunk_typedata = {
        'inner_diameter_mm': 50.0,
        'roughness_mm': 0.1,
        'u_w_per_m2k': 0.0,  # Heat loss coefficient (W/(m²·K)) - 0 for insulated pipes
    }
    pp.create_std_type(net, component="pipe", std_type_name="DN50_trunk", typedata=trunk_typedata)
    
    # Default service pipe type (DN32 = 32mm inner diameter)
    service_typedata = {
        'inner_diameter_mm': 32.0,
        'roughness_mm': 0.1,
        'u_w_per_m2k': 0.0,  # Heat loss coefficient (W/(m²·K)) - 0 for insulated pipes
    }
    pp.create_std_type(net, component="pipe", std_type_name="DN32_service", typedata=service_typedata)
    
    # Add junctions for all nodes in trunk
    node_to_junction = {}
    junction_idx = 0
    
    for node in G.nodes():
        if node in [e[0] for e in trunk_edges] or node in [e[1] for e in trunk_edges]:
            # Calculate elevation (simplified: flat)
            elevation_m = 0.0
            
            # Create junction
            pp.create_junction(
                net, 
                pn_bar=10, 
                tfluid_k=353.15,  # 80°C
                name=f"junction_{node}",
                geodata=(node[0], node[1])
            )
            node_to_junction[node] = junction_idx
            junction_idx += 1
    
    # Add plant junction (source)
    if plant_node not in node_to_junction:
        pp.create_junction(
            net, 
            pn_bar=10, 
            tfluid_k=353.15,
            name=f"plant_{plant_node}",
            geodata=(plant_node[0], plant_node[1])
        )
        node_to_junction[plant_node] = junction_idx
    
    # Add trunk pipes
    for u, v in trunk_edges:
        from_junc = node_to_junction[u]
        to_junc = node_to_junction[v]
        
        # Get pipe length from graph
        length_m = G[u][v].get('length_m', 50.0)  # Default 50m
        
        # Add pipe (will size later)
        pp.create_pipe(
            net,
            from_junction=from_junc,
            to_junction=to_junc,
            length_km=length_m / 1000.0,
            std_type="DN50_trunk",
            name=f"pipe_{u}_{v}"
        )
    
    # Add service connections
    for building_id, attach_node in service_connections:
        building = buildings.loc[buildings['building_id'] == building_id].iloc[0]
        attach_junc = node_to_junction[attach_node]
        
        # Get building location
        building_point = building.geometry.centroid
        
        # Create building junction (sink)
        pp.create_junction(
            net,
            pn_bar=10,
            tfluid_k=323.15,  # 50°C return
            name=f"building_{building_id}",
            geodata=(building_point.x, building_point.y)
        )
        building_junc = len(net.junction) - 1
        
        # Add service pipe
        service_length = building_point.distance(Point(attach_node))
        pp.create_pipe(
            net,
            from_junction=attach_junc,
            to_junction=building_junc,
            length_km=service_length / 1000.0,
            std_type="DN32_service",
            name=f"service_{building_id}"
        )
        
        # Add sink (consumer)
        design_load_kw = building.get('design_load_kw', 50.0)  # Default
        pp.create_sink(
            net,
            junction=building_junc,
            mdot_kg_per_s=0.0,  # Will be set during simulation
            name=f"sink_{building_id}"
        )
    
    # Add source (plant)
    plant_junc = node_to_junction[plant_node]
    pp.create_source(
        net,
        junction=plant_junc,
        mdot_kg_per_s=0.0,  # Will be set
        t_k=353.15,  # 80°C supply
        name="plant"
    )
    
    logger.info(f"Created pandapipes network: {len(net.junction)} junctions, {len(net.pipe)} pipes")
    logger.info(f"Network has {len([c for c in net.controller])} controllers")
    
    return net