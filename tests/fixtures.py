"""
Test fixtures for CHA (Central Heating Agent) tests.
Provides network creation helpers for integration testing.
"""
import pandapipes as pp
import pandas as pd
import numpy as np
import geopandas as gpd
from shapely.geometry import Point, LineString
from pathlib import Path
from typing import Tuple
import sys

# Add src to path
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from branitz_heat_decision.cha.convergence_optimizer import ConvergenceOptimizer
from branitz_heat_decision.cha.config import CHAConfig, get_default_config


def create_converged_network(
    n_buildings: int = 5,
    converged: bool = True
) -> pp.pandapipesNet:
    """
    Create a converged pandapipes network for testing.
    
    Args:
        n_buildings: Number of building sinks
        converged: Whether to mark network as converged (with dummy results)
        
    Returns:
        pandapipesNet with converged results
    """
    net = pp.create_empty_network(fluid="water")
    config = get_default_config()
    
    # Create standard pipe type
    typedata = {
        "inner_diameter_mm": 50.0,
        "k_mm": 0.1,
        "u_w_per_m2k": 0.0
    }
    pp.create_std_type(net, component="pipe", std_type_name="test_pipe", typedata=typedata)
    
    # Create plant junction (source)
    plant_junc = pp.create_junction(
        net, pn_bar=config.system_pressure_bar, 
        tfluid_k=config.supply_temp_k, name="plant"
    )
    
    # Create trunk junction
    trunk_junc = pp.create_junction(
        net, pn_bar=config.system_pressure_bar, 
        tfluid_k=config.supply_temp_k, name="trunk"
    )
    
    # Plant to trunk pipe
    pp.create_pipe(net, plant_junc, trunk_junc, std_type="test_pipe", length_km=0.1)
    
    # Create buildings (sinks)
    building_junctions = []
    for i in range(n_buildings):
        building_junc = pp.create_junction(
            net, pn_bar=config.system_pressure_bar, 
            tfluid_k=config.supply_temp_k, name=f"building_{i}"
        )
        building_junctions.append(building_junc)
        
        # Service pipe from trunk to building
        pp.create_pipe(net, trunk_junc, building_junc, std_type="test_pipe", length_km=0.05)
        
        # Sink
        pp.create_sink(net, building_junc, mdot_kg_per_s=0.1)
    
    # Source (plant)
    pp.create_source(net, plant_junc, mdot_kg_per_s=n_buildings * 0.1)
    
    if converged:
        # Mark as converged and add dummy results
        net.converged = True
        
        # Create dummy pipe results (using column names expected by kpi_extractor)
        n_pipes = len(net.pipe)
        net.res_pipe = pd.DataFrame({
            'v_mean_ms': np.random.uniform(0.5, 1.2, n_pipes),
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
        
        # Create dummy sink results
        if 'sink' in net and not net.sink.empty:
            n_sinks = len(net.sink)
            net.res_sink = pd.DataFrame({
                'mdot_kg_s': np.random.uniform(0.05, 0.2, n_sinks),
            }, index=net.sink.index)
    
    return net


def create_simple_network_with_geodata() -> Tuple[pp.pandapipesNet, gpd.GeoDataFrame]:
    """
    Create a network with geodata for map testing.
    
    Returns:
        Tuple of (net, buildings_gdf)
    """
    net = create_converged_network(n_buildings=3)
    
    # Add geodata
    net.junction_geodata = pd.DataFrame({
        'x': [390000, 390100, 390200, 390150, 390250],
        'y': [5810000, 5810100, 5810200, 5810150, 5810250],
        'z': [0.0] * 5
    }, index=net.junction.index)
    
    # Create buildings GeoDataFrame
    buildings_data = {
        'building_id': [f'B{i:03d}' for i in range(3)],
        'annual_heat_demand_kwh_a': [15000, 18000, 20000],
        'design_load_kw': [15, 18, 20],
    }
    
    geometries = [
        Point(390200, 5810200),
        Point(390150, 5810150),
        Point(390250, 5810250),
    ]
    
    buildings_gdf = gpd.GeoDataFrame(
        buildings_data,
        geometry=geometries,
        crs='EPSG:25833'
    )
    
    return net, buildings_gdf

