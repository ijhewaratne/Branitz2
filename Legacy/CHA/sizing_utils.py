"""
Sizing utilities for CHA pipe diameter selection.
Handles mass flow calculations and pipe diameter selection from catalog.
"""

import logging
from typing import Dict, List, Tuple, Optional

import numpy as np
import pandas as pd
import networkx as nx

from branitz_ai.cha.config import CHAConfig

logger = logging.getLogger(__name__)


def estimate_building_mdot_kgs(
    hourly_profiles_df: pd.DataFrame,
    cluster_id: str,
    buildings_in_cluster: pd.DataFrame,
    design_hour: int,
    config: CHAConfig
) -> pd.Series:
    """
    Estimate mass flow rate per building in kg/s.
    
    Formula: m_dot = Q / (cp * delta_T)
    - Q in W (convert from kW_th if needed)
    - cp in J/(kg·K)
    - delta_T in K
    
    Args:
        hourly_profiles_df: DataFrame with index=hours, columns=building_id, values=kW_th
        cluster_id: Cluster identifier (for logging)
        buildings_in_cluster: DataFrame with building_id column
        design_hour: Hour index for design load
        config: CHAConfig with physical parameters
        
    Returns:
        Series with index=building_id, values=m_dot in kg/s
    """
    building_ids = buildings_in_cluster['building_id'].tolist()
    mdot_dict = {}
    
    for building_id in building_ids:
        if building_id not in hourly_profiles_df.columns:
            logger.warning(f"Building {building_id} not in hourly_profiles_df, using zero flow")
            mdot_dict[building_id] = 0.0
            continue
        
        # Get heat demand at design hour (in kW_th)
        Q_kw = hourly_profiles_df.loc[design_hour, building_id]
        
        # Convert to W
        Q_w = Q_kw * 1000.0
        
        # Compute mass flow: m_dot = Q / (cp * delta_T)
        m_dot_kgs = Q_w / (config.cp * config.delta_T_design)
        
        # Ensure non-negative
        m_dot_kgs = max(0.0, m_dot_kgs)
        
        mdot_dict[building_id] = m_dot_kgs
    
    mdot_series = pd.Series(mdot_dict, name='m_dot_kgs')
    logger.info(f"Estimated mass flows for {len(mdot_series)} buildings (cluster {cluster_id})")
    return mdot_series


def compute_edge_mdot_from_tree(
    graph: nx.Graph,
    plant_node: Tuple,
    attach_nodes: List[Tuple],
    building_mdot: pd.Series,
    building_to_attach_node: Dict[str, Tuple]
) -> Dict[Tuple, float]:
    """
    Compute mass flow accumulation on trunk tree.
    
    Flow accumulation: For each edge, sum all building flows downstream.
    
    Args:
        graph: NetworkX street graph
        plant_node: Node identifier for plant location
        attach_nodes: List of node identifiers for building attachment points
        building_mdot: Series with building_id -> m_dot (kg/s)
        building_to_attach_node: Dict mapping building_id -> attach_node
        
    Returns:
        Dict mapping edge (start, end) -> m_dot (kg/s)
    """
    edge_mdot = {}
    
    # Build mapping: attach_node -> list of buildings
    attach_to_buildings = {}
    for building_id, attach_node in building_to_attach_node.items():
        if attach_node is None:
            continue
        if attach_node not in attach_to_buildings:
            attach_to_buildings[attach_node] = []
        attach_to_buildings[attach_node].append(building_id)
    
    # For each edge, compute total flow downstream
    # Strategy: For each building, trace path from plant to attach_node
    # and accumulate flows on each edge
    
    # Initialize all edges with zero flow
    for edge in graph.edges():
        edge_normalized = tuple(sorted(edge))
        edge_mdot[edge_normalized] = 0.0
    
    # Accumulate flows
    for attach_node, building_ids in attach_to_buildings.items():
        if attach_node is None:
            continue
        
        try:
            # Get path from plant to attach node
            path = nx.shortest_path(graph, plant_node, attach_node, weight='length_m')
            
            # Sum flows for all buildings attached at this node
            total_flow = sum(building_mdot.get(bid, 0.0) for bid in building_ids)
            
            # Add flow to all edges in path
            for i in range(len(path) - 1):
                edge = (path[i], path[i + 1])
                edge_normalized = tuple(sorted(edge))
                edge_mdot[edge_normalized] = edge_mdot.get(edge_normalized, 0.0) + total_flow
        except nx.NetworkXNoPath:
            logger.warning(f"No path from plant to attach node {attach_node}")
            continue
    
    logger.info(f"Computed edge mass flows for {len(edge_mdot)} edges")
    return edge_mdot


def select_diameter_from_catalog(
    m_dot_kgs: float,
    pipe_catalog: pd.DataFrame,
    config: CHAConfig,
    v_target: Optional[float] = None
) -> str:
    """
    Select pipe diameter from catalog based on velocity constraint.
    
    Formula: D_req = sqrt(4 * m_dot / (π * ρ * v_target))
    
    Choose smallest catalog DN with inner_diameter_m >= D_req.
    
    Args:
        m_dot_kgs: Mass flow rate in kg/s
        pipe_catalog: DataFrame with columns: dn_label, inner_diameter_m
        config: CHAConfig with physical parameters
        v_target: Target velocity (m/s). If None, uses config.v_max
        
    Returns:
        dn_label (string) from catalog
    """
    if v_target is None:
        v_target = config.v_max
    
    if m_dot_kgs <= 0:
        # Return smallest diameter for zero flow
        return pipe_catalog.loc[pipe_catalog['inner_diameter_m'].idxmin(), 'dn_label']
    
    # Compute required diameter
    # D_req = sqrt(4 * m_dot / (π * ρ * v_target))
    D_req = np.sqrt(4.0 * m_dot_kgs / (np.pi * config.rho * v_target))
    
    # Find smallest catalog diameter >= D_req
    suitable = pipe_catalog[pipe_catalog['inner_diameter_m'] >= D_req]
    
    if len(suitable) == 0:
        # Use largest available diameter
        logger.warning(f"Required diameter {D_req:.4f}m exceeds catalog max. Using largest diameter.")
        return pipe_catalog.loc[pipe_catalog['inner_diameter_m'].idxmax(), 'dn_label']
    
    # Return smallest suitable diameter
    return suitable.loc[suitable['inner_diameter_m'].idxmin(), 'dn_label']


def size_trunk_pipes(
    trunk_edges: List[Tuple],
    edge_mdot: Dict[Tuple, float],
    pipe_catalog: pd.DataFrame,
    config: CHAConfig
) -> Dict[Tuple, str]:
    """
    Size trunk pipes based on mass flow rates.
    
    Args:
        trunk_edges: List of edge tuples (start, end)
        edge_mdot: Dict mapping edge -> m_dot (kg/s)
        pipe_catalog: DataFrame with dn_label, inner_diameter_m
        config: CHAConfig with physical parameters
        
    Returns:
        Dict mapping edge -> dn_label
    """
    edge_dn = {}
    
    for edge in trunk_edges:
        edge_normalized = tuple(sorted(edge))
        m_dot = edge_mdot.get(edge_normalized, 0.0)
        dn_label = select_diameter_from_catalog(m_dot, pipe_catalog, config)
        edge_dn[edge_normalized] = dn_label
    
    logger.info(f"Sized {len(edge_dn)} trunk pipes")
    return edge_dn

