import numpy as np
import pandas as pd
from typing import Dict, Tuple, Optional, List
import pandapipes as pp
import networkx as nx
import logging

logger = logging.getLogger(__name__), List
import pandapipes as pp
import networkx as nx
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

def size_pipes_from_catalog(
    net: pp.pandapipesNet,
    street_graph: nx.Graph,
    trunk_edges: List[tuple],
    design_loads_kw: Dict[str, float],
    pipe_catalog: pd.DataFrame,
    v_max_m_s: float = 1.5,
    fluid_density_kg_m3: float = 970
) -> Dict[tuple, str]:
    """
    Size pipes based on mass flow rates and catalog DN.
    
    Args:
        net: pandapipes network
        street_graph: Street graph
        trunk_edges: List of trunk edge tuples
        design_loads_kw: Dict mapping building_id to load
        pipe_catalog: DataFrame with dn_label, inner_diameter_m, cost_eur_per_m
        v_max_m_s: Maximum velocity (EN 13941-1: ≤1.5 m/s)
        fluid_density_kg_m3: Water density at operating temp
        
    Returns:
        Dict mapping edge (u,v) to selected DN label
    """
    logger.info(f"Sizing pipes from catalog with v_max={v_max_m_s} m/s")
    
    # Calculate mass flow rate per building
    cp_water = 4.18  # kJ/(kg·K)
    delta_t_k = 30  # 90°C - 60°C
    
    building_mdot = {}
    for building_id, load_kw in design_loads_kw.items():
        mdot_kg_s = (load_kw * 1000) / (cp_water * delta_t_k * 1000)  # kg/s
        building_mdot[building_id] = mdot_kg_s
    
    # Aggregate mass flows on edges
    # For each trunk edge, sum all building flows that pass through it
    edge_mdot = {}
    for u, v in trunk_edges:
        # Find buildings whose path includes this edge
        # Simplified: sum all downstream buildings
        # In practice, do a graph traversal from edge to leaves
        edge_mdot[(u, v)] = sum(building_mdot.values()) / len(trunk_edges)  # Placeholder
    
    # Size each edge
    edge_dn = {}
    for edge, mdot in edge_mdot.items():
        # Required diameter: D = sqrt(4 * mdot / (π * ρ * v_max))
        d_req_m = np.sqrt(4 * mdot / (np.pi * fluid_density_kg_m3 * v_max_m_s))
        
        # Select smallest DN >= d_req
        suitable = pipe_catalog[pipe_catalog['inner_diameter_m'] >= d_req_m]
        if suitable.empty:
            # Use largest available
            dn_label = pipe_catalog.loc[pipe_catalog['inner_diameter_m'].idxmax(), 'dn_label']
            logger.warning(f"No suitable DN for d_req={d_req_m*1000:.1f}mm, using largest: {dn_label}")
        else:
            dn_label = suitable.loc[suitable['inner_diameter_m'].idxmin(), 'dn_label']
        
        edge_dn[edge] = dn_label
        
        # Update net with std_type
        # Find pipes corresponding to this edge (supply and return)
        # ... mapping logic here
    
    logger.info(f"Sized {len(edge_dn)} edges")
    return edge_dn


def load_pipe_catalog(
    catalog_path: Optional[Path] = None
) -> pd.DataFrame:
    """
    Load pipe DN catalog.
    
    If catalog_path is None, use default catalog (EN 10255 steel pipes).
    
    Args:
        catalog_path: Optional path to pipe catalog Excel/CSV
        
    Returns:
        DataFrame with columns: dn_label, inner_diameter_m, cost_eur_per_m
    """
    if catalog_path is None:
        # Default EN 10255 catalog (SDR 11)
        default_catalog = [
            {'dn_label': 'DN20',  'inner_diameter_m': 0.020, 'cost_eur_per_m': 50},
            {'dn_label': 'DN25',  'inner_diameter_m': 0.025, 'cost_eur_per_m': 60},
            {'dn_label': 'DN32',  'inner_diameter_m': 0.032, 'cost_eur_per_m': 75},
            {'dn_label': 'DN40',  'inner_diameter_m': 0.040, 'cost_eur_per_m': 90},
            {'dn_label': 'DN50',  'inner_diameter_m': 0.053, 'cost_eur_per_m': 110},
            {'dn_label': 'DN65',  'inner_diameter_m': 0.065, 'cost_eur_per_m': 140},
            {'dn_label': 'DN80',  'inner_diameter_m': 0.080, 'cost_eur_per_m': 170},
            {'dn_label': 'DN100', 'inner_diameter_m': 0.101, 'cost_eur_per_m': 220},
            {'dn_label': 'DN125', 'inner_diameter_m': 0.124, 'cost_eur_per_m': 280},
            {'dn_label': 'DN150', 'inner_diameter_m': 0.148, 'cost_eur_per_m': 350},
            {'dn_label': 'DN200', 'inner_diameter_m': 0.204, 'cost_eur_per_m': 500},
        ]
        df = pd.DataFrame(default_catalog)
        logger.info("Loaded default pipe catalog (EN 10255)")
        return df
    
    # Load from file
    if catalog_path.suffix.lower() == '.xlsx':
        df = pd.read_excel(catalog_path)
    else:
        df = pd.read_csv(catalog_path)
    
    # Validate required columns
    required = ['dn_label', 'inner_diameter_m', 'cost_eur_per_m']
    for col in required:
        if col not in df.columns:
            raise ValueError(f"Pipe catalog missing column: {col}")
    
    logger.info(f"Loaded pipe catalog from {catalog_path}: {len(df)} entries")
    return df