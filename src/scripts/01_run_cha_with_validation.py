"""
Run CHA simulation with integrated design validation.

Modified version of 01_run_cha.py that includes Document 24 validation.
"""

import logging
from pathlib import Path
import pandapipes as pp
import geopandas as gpd

# Adjust path to include src
import sys
sys.path.insert(0, str(Path(__file__).parents[1]))

from branitz_heat_decision.cha.network_builder_trunk_spur import build_trunk_spur_network
from branitz_heat_decision.cha.design_validator import DHNetworkDesignValidator
from branitz_heat_decision.config.validation_standards import get_default_validation_config
import importlib
run_cha_module = importlib.import_module("scripts.01_run_cha")

from branitz_heat_decision.cha.config import get_default_config
from branitz_heat_decision.cha.sizing import load_pipe_catalog
from branitz_heat_decision.config import (
    DATA_PROCESSED, DATA_RAW, DESIGN_TOPN_PATH, HOURLY_PROFILES_PATH, resolve_cluster_path
)
from branitz_heat_decision.data.loader import (
    load_streets_geojson, load_processed_buildings
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def build_dh_network(
    cluster_id: str,
    streets_gdf: gpd.GeoDataFrame,
    buildings_gdf: gpd.GeoDataFrame,
    data_dir: Path
):
    """
    Build DH network for validation.
    Wraps network_builder with necessary parameter preparation.
    """
    
    # Needs plant coords
    cluster_centroid = buildings_gdf.geometry.union_all().centroid
    plant_coords = (cluster_centroid.x, cluster_centroid.y)
    
    config = get_default_config()
    pipe_catalog = load_pipe_catalog()
    
    # Calculate loads BEFORE building (trunk_spur builder needs them for sizing)
    # Quick load assignment logic closely matching 01_run_cha
    design_load_kw_default = 100.0
    design_loads_kw = {}
    
    try:
        import json
        with open(DESIGN_TOPN_PATH, 'r') as f:
            design_topn = json.load(f)
        if cluster_id in design_topn.get('clusters', {}):
            design_load_kw_default = design_topn['clusters'][cluster_id].get('design_load_kw', 100.0)
    except:
        pass
        
    per_building_load = design_load_kw_default / len(buildings_gdf) if len(buildings_gdf) > 0 else 0
    for idx, row in buildings_gdf.iterrows():
        design_loads_kw[row['building_id']] = per_building_load

    # Use enhanced trunk-spur builder
    net, _ = build_trunk_spur_network(
        cluster_id=cluster_id,
        buildings=buildings_gdf,
        streets=streets_gdf,
        plant_coords=plant_coords,
        selected_street_name=None, # Auto-detected or irrelevant for validation dump
        design_loads_kw=design_loads_kw,
        pipe_catalog=pipe_catalog,
        config=config,
        attach_mode='split_edge_per_building',
        street_buffer_m=50.0,  # Increased buffer to capture outlying buildings
        max_spur_length_m=100.0, # Increased spur length for better connectivity
        disable_auto_plant_siting=True # Keep centroid for consistency
    )
    
    # Note: build_trunk_spur_network already creates heat_consumers and runs initial pipeflow.
    # It sets qext based on design_loads_kw.
            
    return net


def run_cha_with_validation(
    cluster_id: str,
    data_dir: Path,
    output_dir: Path,
    validate_design: bool = True,
    run_robustness: bool = False  # Optional, slower
):
    """
    Run CHA simulation with design validation.
    
    Args:
        cluster_id: Cluster to analyze
        data_dir: Data directory
        output_dir: Output directory
        validate_design: Whether to run validation
        run_robustness: Whether to run Monte Carlo robustness check
    """
    
    logger.info(f"Running CHA for cluster: {cluster_id}")
    
    # Create output directory
    cluster_output = output_dir / "cha" / cluster_id
    cluster_output.mkdir(parents=True, exist_ok=True)
    
    # 1. LOAD DATA
    logger.info("Loading data...")
    
    streets_path = DATA_PROCESSED / "streets.parquet"
    if not streets_path.exists():
         # Fallback to geojson if parquet not found
         streets_path = DATA_PROCESSED / "streets.geojson"
         if not streets_path.exists():
             # Fallback to raw data
             logger.info(f"Checking raw data at: {DATA_RAW}")
             streets_path = DATA_RAW / "strassen_mit_adressenV3.geojson"
             if not streets_path.exists():
                 logger.warning("Streets file not found (checked processed/streets.parquet, processed/streets.geojson, raw/strassen_mit_adressenV3.geojson)")
             try:
                 streets = gpd.read_file(streets_path)
             except Exception as e:
                 logger.error(f"Failed to read streets from {streets_path}: {e}")
                 # Last resort: try street_clusters_summary.parquet or street_clusters.parquet
                 streets_path = DATA_PROCESSED / "street_clusters.parquet"
                 if streets_path.exists():
                     logger.info(f"Falling back to street_clusters.parquet: {streets_path}")
                     streets = gpd.read_parquet(streets_path)
                     # Filter for this cluster if column exists
                     if "cluster_id" in streets.columns:
                         streets = streets[streets["cluster_id"] == cluster_id]
                         logger.info(f"Filtered streets by cluster_id {cluster_id}: {len(streets)} segments")
                 else:
                     return None
    else:
         streets = gpd.read_parquet(streets_path)

    # Buildings
    buildings = load_processed_buildings() # Loads all residential with heat demand
    logger.info(f"Loaded buildings columns: {buildings.columns.tolist()}")
    # Filter to cluster
    # cluster map
    import pandas as pd
    from branitz_heat_decision.config import BUILDING_CLUSTER_MAP_PATH
    cluster_map = pd.read_parquet(BUILDING_CLUSTER_MAP_PATH)
    cluster_bids = cluster_map[cluster_map['cluster_id'] == cluster_id]['building_id'].tolist()
    
    cluster_buildings = buildings[buildings['building_id'].isin(cluster_bids)]
    
    if len(cluster_buildings) == 0:
        logger.error(f"No buildings found for cluster {cluster_id}")
        return None
        
    # Ensure CRS
    if streets.crs != cluster_buildings.crs:
        streets = streets.to_crs(cluster_buildings.crs)

    # 2. BUILD NETWORK
    logger.info("Building DH network...")
    
    net = build_dh_network(
        cluster_id=cluster_id,
        streets_gdf=streets,
        buildings_gdf=cluster_buildings,
        data_dir=data_dir
    )
    
    # 3. RUN SIMULATION
    logger.info("Running pipeflow simulation...")
    # 3. RUN SIMULATION
    logger.info("Running pipeflow simulation...")
    # New builder creates ext_grid and circ_pump, so no manual fixup needed.
    
    # Debug: Check network setup
    if hasattr(net, "ext_grid") and not net.ext_grid.empty:
         eg_junc = net.ext_grid.junction.iloc[0]
         logger.info(f"Ext_grid connected to junction {eg_junc}")
    
    n_sinks = len(net.sink) if hasattr(net, "sink") else 0
    n_hc = len(net.heat_consumer) if hasattr(net, "heat_consumer") else 0 # (Legacy check)
    n_hex = len(net.heat_exchanger) if hasattr(net, "heat_exchanger") else 0
    logger.info(f"Network Diagnostics: Sinks={n_sinks}, HX={n_hex}")

    try:
        pp.pipeflow(net, mode='all')
        
        if not net.converged:
            logger.error("Pipeflow did not converge! Attempting sequential...")
            pp.pipeflow(net, mode='sequential')
            if not net.converged:
                 logger.error("Pipeflow still did not converge.")
                 return None
        
        logger.info("✅ Pipeflow converged successfully")
        
    except Exception as e:
        logger.error(f"Pipeflow failed: {e}")
        return None
    
    # 4. VALIDATE DESIGN (NEW)
    validation_report = None
    if validate_design:
        logger.info("Running design validation...")
        
        # Initialize validator
        validation_config = get_default_validation_config()
        # Ensure fail_on_warnings is False by default
        validation_config.fail_on_warnings = False
        
        validator = DHNetworkDesignValidator(validation_config)
        
        # Run validation
        validation_report = validator.validate_design(
            net=net,
            cluster_id=cluster_id,
            streets_gdf=streets,
            buildings_gdf=cluster_buildings,
            run_robustness=run_robustness
        )
        
        # Save validation report
        validator.save_report(validation_report, cluster_output)
        
        # Print summary
        print("\n" + validation_report.generate_summary())
        
        # Check if validation passed
        if not validation_report.passed:
            logger.error("❌ Design validation FAILED")
            logger.error(f"Issues: {len(validation_report.all_issues)}")
            for issue in validation_report.all_issues:
                logger.error(f"  - {issue}")
        else:
            logger.info("✅ Design validation PASSED")
            if validation_report.all_warnings:
                logger.warning(f"⚠️  {len(validation_report.all_warnings)} warnings:")
                for warning in validation_report.all_warnings:
                    logger.warning(f"  - {warning}")
    
    logger.info(f"CHA complete. Results saved to: {cluster_output}")
    
    return {
        "net": net,
        "validation_report": validation_report if validate_design else None
    }


if __name__ == "__main__":
    import argparse
    import os
    
    parser = argparse.ArgumentParser(description="Run CHA with design validation")
    parser.add_argument("--cluster-id", required=True, help="Cluster ID")
    parser.add_argument("--data-dir", default="data", help="Data directory")
    parser.add_argument("--output-dir", default="results", help="Output directory")
    parser.add_argument("--no-validation", action="store_true", help="Skip validation")
    parser.add_argument("--with-robustness", action="store_true", help="Run Monte Carlo robustness")
    
    args = parser.parse_args()
    
    # Resolve paths
    # If scripts is run from root, data is likely ./data or from env
    # Use BRANITZ_DATA_ROOT if set
    data_root = os.getenv("BRANITZ_DATA_ROOT", args.data_dir)
    
    result = run_cha_with_validation(
        cluster_id=args.cluster_id,
        data_dir=Path(data_root),
        output_dir=Path(args.output_dir),
        validate_design=not args.no_validation,
        run_robustness=args.with_robustness
    )
