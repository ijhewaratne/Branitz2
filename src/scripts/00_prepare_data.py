#!/usr/bin/env python3
"""
Data preparation pipeline.
Loads raw data, cleans, validates, and generates processed artifacts.
"""
import sys
import argparse
import logging
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parents[1]))

from branitz_heat_decision.config import (
    DATA_PROCESSED, DATA_RAW, BUILDINGS_PATH, BUILDING_CLUSTER_MAP_PATH,
    WEATHER_PATH, DESIGN_TOPN_PATH, HOURLY_PROFILES_PATH
)
from branitz_heat_decision.data.loader import (
    load_buildings_geojson, load_streets_geojson, DataValidationError,
    filter_residential_buildings_with_heat_demand,
    load_branitzer_siedlung_attributes,
    load_gebaeudeanalyse,
)
from branitz_heat_decision.data.typology import estimate_envelope
from branitz_heat_decision.data.profiles import generate_hourly_profiles
from branitz_heat_decision.data.cluster import (
    aggregate_cluster_profiles, compute_design_and_topn,
    match_buildings_to_streets, create_street_clusters
)
import geopandas as gpd
import pandas as pd
import numpy as np
import json

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def create_street_based_clusters(
    buildings_path: Path,
    streets_path: Path,
    output_cluster_map_path: Path,
    output_street_clusters_path: Path
):
    """
    Create street-based clusters from buildings and streets geodata.
    
    Args:
        buildings_path: Path to buildings GeoJSON with addresses
        streets_path: Path to streets GeoJSON
        output_cluster_map_path: Path to save building_cluster_map.parquet
        output_street_clusters_path: Path to save street_clusters.parquet
    """
    logger.info("Creating street-based clusters...")
    
    # Load buildings (validated + stable scalar building_id extraction)
    logger.info(f"Loading buildings from {buildings_path}")
    buildings = load_buildings_geojson(buildings_path)
    
    # Transform to projected CRS if needed (for spatial operations)
    target_crs = 'EPSG:25833'
    if buildings.crs is None or buildings.crs.to_epsg() != 25833:
        if buildings.crs is None:
            logger.warning("No CRS defined for buildings, assuming WGS84")
            buildings.set_crs('EPSG:4326', inplace=True)
        if buildings.crs.to_epsg() == 4326:
            buildings = buildings.to_crs(target_crs)
            logger.info(f"Transformed buildings to {target_crs}")
    
    # Enrich buildings from available raw analysis sources (Legacy-aligned)
    # - output_branitzer_siedlungV11.json: building function, street, net floor area, volume
    # - gebaeudeanalyse.json: renovation state (sanierungszustand) + heat density (waermedichte)
    try:
        branitzer_path = DATA_RAW / "output_branitzer_siedlungV11.json"
        if branitzer_path.exists():
            attrs = load_branitzer_siedlung_attributes(branitzer_path)
            buildings = buildings.merge(attrs, on="building_id", how="left")
            logger.info(f"Enriched buildings with Branitzer attributes: matched {(buildings['building_function'].notna()).sum()}/{len(buildings)}")
            # If we got a street_name from this file, prefer it for clustering
            if "street_name" in buildings.columns:
                buildings["street_from_json"] = buildings["street_name"]
        else:
            logger.warning(f"Branitzer attributes file not found: {branitzer_path}")
    except Exception as e:
        logger.warning(f"Could not load Branitzer attributes: {e}")

    try:
        analyse_path = DATA_RAW / "gebaeudeanalyse.json"
        if analyse_path.exists():
            an = load_gebaeudeanalyse(analyse_path)
            buildings = buildings.merge(an, on="building_id", how="left")
            logger.info(f"Enriched buildings with gebaeudeanalyse: matched {(buildings['sanierungszustand'].notna()).sum()}/{len(buildings)}")

            # Derive annual_heat_demand_kwh_a from waermedichte (kWh/m²a) × floor_area_m2 if possible
            if "annual_heat_demand_kwh_a" not in buildings.columns:
                buildings["annual_heat_demand_kwh_a"] = np.nan
            if "floor_area_m2" in buildings.columns and "waermedichte" in buildings.columns:
                mask = buildings["annual_heat_demand_kwh_a"].isna() & buildings["floor_area_m2"].notna() & buildings["waermedichte"].notna()
                buildings.loc[mask, "annual_heat_demand_kwh_a"] = buildings.loc[mask, "waermedichte"].astype(float) * buildings.loc[mask, "floor_area_m2"].astype(float)
                logger.info(f"Derived annual_heat_demand_kwh_a for {mask.sum()} buildings from waermedichte × floor_area_m2")
        else:
            logger.warning(f"Gebaeudeanalyse file not found: {analyse_path}")
    except Exception as e:
        logger.warning(f"Could not load gebaeudeanalyse: {e}")

    # Run typology estimator to fill remaining missing fields (will preserve existing annual demand)
    buildings = estimate_envelope(buildings)

    buildings_before = len(buildings)
    buildings = filter_residential_buildings_with_heat_demand(buildings, min_heat_demand_kwh_a=0.0)
    buildings_after = len(buildings)
    logger.info(f"Filtered buildings: {buildings_before} -> {buildings_after} (residential with heat demand)")
    
    if len(buildings) == 0:
        raise ValueError("No residential buildings with heat demand found. Cannot create clusters.")
    
    # Load streets (robustly preserves real street names even if GeoJSON has list-valued `name`)
    logger.info(f"Loading streets from {streets_path}")
    streets = load_streets_geojson(streets_path)
    
    # Ensure CRS matches
    if streets.crs != buildings.crs:
        streets = streets.to_crs(buildings.crs)
        logger.info(f"Transformed streets CRS to match buildings: {buildings.crs}")
    
    # Match buildings to streets
    # Prefer street name from building address/analysis if available; otherwise use matching function.
    if "street_from_json" in buildings.columns and buildings["street_from_json"].notna().any():
        logger.info("Creating building-street map from enriched building street_name (street_from_json)...")
        building_street_map = pd.DataFrame({
            "building_id": buildings["building_id"].tolist(),
            "street_name": buildings["street_from_json"].tolist(),
            "street_normalized": buildings["street_from_json"].fillna("").astype(str).apply(lambda x: x),
            "matched_method": ["address_json"] * len(buildings),
        })
    else:
        logger.info("Matching buildings to streets (address + spatial fallback)...")
        building_street_map = match_buildings_to_streets(buildings, streets)
    
    # Create clusters
    logger.info("Creating street-based clusters...")
    building_cluster_map, street_clusters = create_street_clusters(
        buildings, building_street_map, streets
    )
    
    # Save filtered buildings to processed/buildings.parquet for reuse
    # This eliminates redundant filtering in downstream scripts
    logger.info(f"Saving filtered buildings to {BUILDINGS_PATH}")
    BUILDINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    # Ensure metadata is set
    if 'filtered' not in buildings.attrs:
        buildings.attrs['filtered'] = True
        buildings.attrs['filter_criteria'] = 'residential_with_heat_demand_min_0_kwh_a'
        buildings.attrs['filter_date'] = pd.Timestamp.now().isoformat()
    
    buildings.to_parquet(BUILDINGS_PATH, index=False)
    logger.info(f"Saved {len(buildings)} filtered buildings to {BUILDINGS_PATH}")
    logger.info(f"  Buildings are filtered to residential with heat demand")
    logger.info(f"  This file will be reused by CHA pipeline (no redundant filtering needed)")
    
    # Save cluster map
    output_cluster_map_path.parent.mkdir(parents=True, exist_ok=True)
    building_cluster_map.to_parquet(output_cluster_map_path, index=False)
    logger.info(f"Saved building_cluster_map to {output_cluster_map_path}")
    logger.info(f"  Mapped {len(building_cluster_map)} buildings to {building_cluster_map['cluster_id'].nunique()} clusters")
    
    # Add compatibility alias: street_id (for 01_run_cha.py which expects street_id column)
    # The actual column is cluster_id, but older code uses street_id
    if 'cluster_id' in street_clusters.columns and 'street_id' not in street_clusters.columns:
        street_clusters['street_id'] = street_clusters['cluster_id']
        logger.info("Added compatibility alias: street_id = cluster_id (for 01_run_cha.py)")
    
    # Save street clusters
    street_clusters.to_parquet(output_street_clusters_path, index=False)
    logger.info(f"Saved street_clusters to {output_street_clusters_path}")
    logger.info(f"  Created {len(street_clusters)} street clusters")
    
    return building_cluster_map, street_clusters


def generate_profiles_and_design_topn(
    buildings: gpd.GeoDataFrame,
    cluster_map: pd.DataFrame,
    N: int = 10
) -> None:
    """
    Generate and save:
    - hourly heat demand profiles per building (8760 x n_buildings)
    - per-cluster design hour and top-N hours (cluster_design_topn.json)

    This enables running CHA for ANY cluster/street consistently.
    """
    if not WEATHER_PATH.exists():
        raise FileNotFoundError(
            f"Weather file not found: {WEATHER_PATH}. "
            f"Expected a processed weather.parquet with 8760 hourly temperatures."
        )

    weather_df = pd.read_parquet(WEATHER_PATH)
    profiles_df = generate_hourly_profiles(buildings, weather_df)

    HOURLY_PROFILES_PATH.parent.mkdir(parents=True, exist_ok=True)
    profiles_df.to_parquet(HOURLY_PROFILES_PATH)
    logger.info(f"Saved hourly profiles to {HOURLY_PROFILES_PATH} with shape {profiles_df.shape}")

    cluster_profiles = aggregate_cluster_profiles(profiles_df, cluster_map)
    design_topn = compute_design_and_topn(cluster_profiles, N=N)

    DESIGN_TOPN_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DESIGN_TOPN_PATH, "w", encoding="utf-8") as f:
        json.dump(design_topn, f, indent=2, ensure_ascii=False)
    logger.info(f"Saved design/top-N to {DESIGN_TOPN_PATH} ({len(design_topn.get('clusters', {}))} clusters)")


def generate_cluster_ui_index(
    street_clusters_path: Path,
    design_topn_path: Path,
    output_index_path: Path,
    building_cluster_map_path: Path = None,
    buildings_path: Path = None
):
    """
    Generate a lightweight index of clusters for UI consumption.
    Combines street cluster metadata with calculated load metrics.
    
    Args:
        street_clusters_path: Path to street_clusters.parquet
        design_topn_path: Path to design_topn.json
        output_index_path: Path to save cluster_ui_index.parquet
        building_cluster_map_path: Path to building_cluster_map.parquet (optional, for aggregating annual demand)
        buildings_path: Path to buildings.parquet (optional, for aggregating annual demand)
    """
    logger.info("Generating Cluster UI Index...")
    
    if not street_clusters_path.exists():
        logger.warning(f"Street clusters not found at {street_clusters_path}. Skipping UI index.")
        return

    street_clusters = gpd.read_parquet(street_clusters_path)
    
    # Load design/topn data if available
    design_data = {}
    if design_topn_path.exists():
        try:
            with open(design_topn_path, "r", encoding="utf-8") as f:
                design_data = json.load(f).get("clusters", {})
        except Exception as e:
            logger.warning(f"Could not load design_topn.json: {e}")
    
    # Aggregate annual heat demand from buildings if cluster map and buildings are available
    annual_demand_by_cluster = {}
    if building_cluster_map_path and building_cluster_map_path.exists() and buildings_path and buildings_path.exists():
        try:
            cluster_map = pd.read_parquet(building_cluster_map_path)
            buildings = gpd.read_parquet(buildings_path)
            
            if "annual_heat_demand_kwh_a" in buildings.columns and "cluster_id" in cluster_map.columns:
                # Merge cluster_id into buildings
                buildings_with_cluster = buildings.merge(
                    cluster_map[["building_id", "cluster_id"]], 
                    on="building_id", 
                    how="inner"
                )
                # Aggregate annual demand per cluster
                annual_demand_by_cluster = (
                    buildings_with_cluster.groupby("cluster_id")["annual_heat_demand_kwh_a"]
                    .sum()
                    .to_dict()
                )
                logger.info(f"Aggregated annual heat demand for {len(annual_demand_by_cluster)} clusters")
        except Exception as e:
            logger.warning(f"Could not aggregate annual heat demand from buildings: {e}")
    
    # Prepare list of dicts
    ui_records = []
    
    # Reproject to WGS84 for lat/lon centroid if needed (assuming input is 25833 usually)
    # We want centroid_lat/lon for map centering in UI
    clusters_wgs84 = street_clusters.to_crs("EPSG:4326")
    
    for idx, row in clusters_wgs84.iterrows():
        c_id = row.get("cluster_id")
        if not c_id:
            continue
            
        # Get load metrics from design_topn
        metrics = design_data.get(c_id, {})
        
        # Get annual heat demand from aggregated buildings (preferred) or default to 0
        total_annual_demand = annual_demand_by_cluster.get(c_id, 0.0)
        
        # Calculate centroid
        geom = row.geometry
        centroid = geom.centroid
        
        record = {
            "cluster_id": c_id,
            "cluster_name": row.get("cluster_name", c_id),
            "building_count": row.get("building_count", 0),
            "centroid_lat": centroid.y,
            "centroid_lon": centroid.x,
            "total_annual_heat_demand_kwh_a": total_annual_demand,
            "design_load_kw": metrics.get("design_load_kw", 0.0),
            "design_hour": metrics.get("design_hour", -1),
            # Add other interesting fields if available in street_clusters or design_topn
        }
        ui_records.append(record)
        
    df = pd.DataFrame(ui_records)
    
    output_index_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(output_index_path, index=False)
    logger.info(f"Saved Cluster UI Index to {output_index_path} ({len(df)} records)")


def main():
    parser = argparse.ArgumentParser(description='Data preparation pipeline')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    parser.add_argument('--buildings', type=str, help='Path to buildings GeoJSON')
    parser.add_argument('--streets', type=str, help='Path to streets GeoJSON')
    parser.add_argument('--create-clusters', action='store_true', 
                       help='Create street-based clusters from raw data')
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    logger.info("Running data preparation pipeline...")
    
    try:
        # Create street-based clusters if requested
        if args.create_clusters:
            buildings_path = Path(args.buildings) if args.buildings else DATA_RAW / "hausumringe_mit_adressenV3.geojson"
            streets_path = Path(args.streets) if args.streets else DATA_RAW / "strassen_mit_adressenV3_fixed.geojson"
            
            if not buildings_path.exists():
                raise FileNotFoundError(f"Buildings file not found: {buildings_path}")
            if not streets_path.exists():
                raise FileNotFoundError(f"Streets file not found: {streets_path}")
            
            building_cluster_map, _street_clusters = create_street_based_clusters(
                buildings_path=buildings_path,
                streets_path=streets_path,
                output_cluster_map_path=BUILDING_CLUSTER_MAP_PATH,
                output_street_clusters_path=DATA_PROCESSED / "street_clusters.parquet"
            )

            # Generate missing core artifacts required by CHA for any cluster
            # Reload processed buildings (already filtered + enriched) to ensure alignment
            buildings_processed = gpd.read_parquet(BUILDINGS_PATH)
            generate_profiles_and_design_topn(buildings_processed, building_cluster_map, N=10)
            
            # Generate UI Index
            generate_cluster_ui_index(
                street_clusters_path=DATA_PROCESSED / "street_clusters.parquet",
                design_topn_path=DESIGN_TOPN_PATH,
                output_index_path=DATA_PROCESSED / "cluster_ui_index.parquet",
                building_cluster_map_path=BUILDING_CLUSTER_MAP_PATH,
                buildings_path=BUILDINGS_PATH
            )
        
        # Check if processed data exists
        if BUILDINGS_PATH.exists() and WEATHER_PATH.exists():
            logger.info("Processed data files already exist.")
            logger.info(f"Buildings: {BUILDINGS_PATH}")
            logger.info(f"Weather: {WEATHER_PATH}")
        else:
            logger.info("Processed buildings/weather data not found.")
            logger.info("Note: Building/weather processing not yet implemented.")
            logger.info("Use --create-clusters to generate street-based clusters from raw data.")
    
    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)
        sys.exit(1)
    
    logger.info("Done.")


if __name__ == "__main__":
    main()
