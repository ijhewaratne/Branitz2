"""
Interactive pipeline workflow for Branitz Energy Decision AI.

This script provides an interactive command-line interface to:
1. List available streets/clusters
2. Select a street
3. Show building statistics
4. Run HDA → CHA → Map generation → KPIs
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import geopandas as gpd

# Add project root to path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from branitz_ai.data.preparation import (
    load_buildings,
    load_building_cluster_map,
    load_hourly_heat_profiles,
    load_design_topn,
    filter_residential_buildings
)
import subprocess
from branitz_ai.viz.dh_map import create_dh_interactive_map, DHMapOptions
from branitz_ai.cha.kpi_extractor import extract_kpis

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_available_streets() -> pd.DataFrame:
    """Get list of all available streets/clusters."""
    cluster_map = load_building_cluster_map()
    buildings = load_buildings()
    
    # Merge to get street names if available
    if 'street_name' in buildings.columns:
        merged = cluster_map.merge(
            buildings[['building_id', 'street_name']],
            on='building_id',
            how='left'
        )
    else:
        merged = cluster_map.copy()
    
    # Get cluster column name (prefer street_id, fallback to cluster_id)
    cluster_col = None
    for col in ['street_id', 'cluster_id', 'street_cluster']:
        if col in merged.columns:
            cluster_col = col
            break
    
    if cluster_col is None:
        raise ValueError("No cluster column found in cluster map")
    
    # Aggregate by cluster
    cluster_stats = merged.groupby(cluster_col).agg({
        'building_id': 'count'
    }).rename(columns={'building_id': 'n_buildings'}).reset_index()
    
    # Add street name if available
    if 'street_name' in merged.columns:
        street_map = merged.groupby(cluster_col)['street_name'].first().reset_index()
        cluster_stats = cluster_stats.merge(street_map, on=cluster_col, how='left')
    
    cluster_stats = cluster_stats.sort_values('n_buildings', ascending=False)
    
    return cluster_stats


def show_street_list(streets_df: pd.DataFrame):
    """Display available streets in a formatted table."""
    print("\n" + "="*80)
    print("AVAILABLE STREETS/CLUSTERS")
    print("="*80)
    
    cluster_col = [c for c in streets_df.columns if 'cluster' in c.lower() or 'street' in c.lower()][0]
    
    for idx, row in streets_df.iterrows():
        cluster_id = row[cluster_col]
        n_buildings = row['n_buildings']
        street_name = row.get('street_name', 'N/A')
        
        print(f"{idx+1:3d}. {cluster_id:30s} | Buildings: {n_buildings:4d} | Street: {street_name}")
    
    print("="*80 + "\n")


def show_building_statistics(cluster_id: str, residential_only: bool = False):
    """Show detailed building statistics for a cluster."""
    buildings = load_buildings()
    cluster_map = load_building_cluster_map()
    
    # Get cluster column name (prefer street_id, fallback to cluster_id)
    cluster_col = None
    for col in ['street_id', 'cluster_id', 'street_cluster']:
        if col in cluster_map.columns:
            cluster_col = col
            break
    
    if cluster_col is None:
        raise ValueError("No cluster column found")
    
    # Filter buildings in cluster
    # Handle both street_id and cluster_id column names
    if cluster_col == 'street_id':
        cluster_buildings = cluster_map[cluster_map[cluster_col] == cluster_id]
    elif cluster_col == 'cluster_id':
        # If using cluster_id, also check if cluster_id matches
        cluster_buildings = cluster_map[cluster_map[cluster_col] == cluster_id]
    else:
        cluster_buildings = cluster_map[cluster_map[cluster_col] == cluster_id]
    
    building_ids = cluster_buildings['building_id'].tolist()
    buildings_in_cluster = buildings[buildings['building_id'].isin(building_ids)].copy()
    
    # Apply residential filter if requested
    if residential_only:
        original_count = len(buildings_in_cluster)
        buildings_in_cluster = filter_residential_buildings(buildings_in_cluster)
        filtered_count = len(buildings_in_cluster)
        print(f"\n⚠️  Residential filter applied: {original_count} → {filtered_count} buildings")
    
    print("\n" + "="*80)
    print(f"BUILDING STATISTICS FOR: {cluster_id}")
    if residential_only:
        print("(RESIDENTIAL BUILDINGS ONLY)")
    print("="*80)
    
    print(f"\nTotal Buildings: {len(buildings_in_cluster)}")
    
    # Building types
    if 'use_type' in buildings_in_cluster.columns:
        type_counts = buildings_in_cluster['use_type'].value_counts()
        print("\nBuilding Types:")
        for use_type, count in type_counts.items():
            print(f"  - {use_type}: {count}")
    
    if 'building_type' in buildings_in_cluster.columns:
        type_counts = buildings_in_cluster['building_type'].value_counts()
        print("\nBuilding Types (building_type column):")
        for btype, count in type_counts.items():
            print(f"  - {btype}: {count}")
    
    # Heat demand statistics
    heat_cols = [
        'baseline_heat_demand_kwh_a',
        'baseline_heat_kwh_a',
        'annual_heat_demand_kwh_a'
    ]
    
    heat_col = None
    for col in heat_cols:
        if col in buildings_in_cluster.columns:
            heat_col = col
            break
    
    if heat_col:
        heat_demands = buildings_in_cluster[heat_col].dropna()
        if len(heat_demands) > 0:
            print(f"\nHeat Demand Statistics ({heat_col}):")
            print(f"  - Total: {heat_demands.sum():,.0f} kWh/a")
            print(f"  - Mean: {heat_demands.mean():,.0f} kWh/a")
            print(f"  - Median: {heat_demands.median():,.0f} kWh/a")
            print(f"  - Min: {heat_demands.min():,.0f} kWh/a")
            print(f"  - Max: {heat_demands.max():,.0f} kWh/a")
    
    # Floor area statistics
    if 'floor_area_m2' in buildings_in_cluster.columns:
        areas = buildings_in_cluster['floor_area_m2'].dropna()
        if len(areas) > 0:
            print(f"\nFloor Area Statistics:")
            print(f"  - Total: {areas.sum():,.0f} m²")
            print(f"  - Mean: {areas.mean():,.0f} m²")
            print(f"  - Median: {areas.median():,.0f} m²")
    
    print("="*80 + "\n")


def filter_streets_for_cluster(
    streets_gdf: gpd.GeoDataFrame,
    buildings_in_cluster: gpd.GeoDataFrame,
    street_name: Optional[str] = None,
    street_ids: Optional[List[str]] = None,
    buffer_m: float = 500.0
) -> gpd.GeoDataFrame:
    """
    Filter streets to match the same logic used in CHA.
    
    This ensures the map displays the same topology that is simulated.
    
    Args:
        streets_gdf: GeoDataFrame with street geometries
        buildings_in_cluster: GeoDataFrame with buildings in cluster
        street_name: Optional street name filter (case-insensitive, partial match)
        street_ids: Optional list of street IDs to filter
        buffer_m: Buffer distance in meters for spatial filtering
        
    Returns:
        Filtered GeoDataFrame with streets
    """
    from shapely.geometry import box
    
    # Step 1: Spatial filter by cluster bounds
    if len(buildings_in_cluster) > 0 and not buildings_in_cluster.geometry.isna().all():
        # Ensure CRS match
        if streets_gdf.crs != buildings_in_cluster.crs:
            if streets_gdf.crs is None:
                streets_gdf = streets_gdf.set_crs(buildings_in_cluster.crs, allow_override=True)
            else:
                streets_gdf = streets_gdf.to_crs(buildings_in_cluster.crs)
        
        cluster_bounds = buildings_in_cluster.geometry.total_bounds
        bbox = box(
            cluster_bounds[0] - buffer_m,
            cluster_bounds[1] - buffer_m,
            cluster_bounds[2] + buffer_m,
            cluster_bounds[3] + buffer_m
        )
        streets_gdf = streets_gdf[streets_gdf.geometry.intersects(bbox)].copy()
    
    # Step 2: Filter by street name (if provided)
    if street_name:
        name_col = "name" if "name" in streets_gdf.columns else None
        if name_col:
            mask = streets_gdf[name_col].astype(str).str.contains(street_name, case=False, na=False)
            streets_gdf = streets_gdf[mask].copy()
            logger.info(f"Filtered streets by name '{street_name}': {len(streets_gdf)} segments")
        else:
            logger.warning("Cannot filter streets by name: 'name' column not found")
    
    # Step 3: Filter by street IDs (if provided)
    if street_ids:
        id_col = "street_id" if "street_id" in streets_gdf.columns else None
        if id_col:
            streets_gdf = streets_gdf[streets_gdf[id_col].isin(street_ids)].copy()
            logger.info(f"Filtered streets by IDs '{street_ids}': {len(streets_gdf)} segments")
        else:
            logger.warning("Cannot filter streets by IDs: 'street_id' column not found")
    
    return streets_gdf


def run_full_pipeline(
    cluster_id: str,
    output_base: str = "results",
    residential_only: bool = False,
    trunk_mode: Optional[str] = None,
    street_name: Optional[str] = None,
    street_ids: Optional[List[str]] = None
):
    """Run the complete pipeline: HDA → CHA → Map → KPIs."""
    
    hda_out = os.path.join(output_base, "hda", cluster_id)
    cha_out = os.path.join(output_base, "cha", cluster_id)
    
    print("\n" + "="*80)
    print(f"RUNNING FULL PIPELINE FOR: {cluster_id}")
    if trunk_mode:
        print(f"Trunk Mode: {trunk_mode}")
    if street_name:
        print(f"Street Filter: {street_name}")
    if street_ids:
        print(f"Street IDs: {', '.join(street_ids)}")
    print("="*80)
    
    # Step 1: Run HDA
    # Note: HDA processes all clusters by default, but we can filter results later
    print("\n[1/4] Running HDA (Heat Demand Agent)...")
    if residential_only:
        print("      ⚠️  Residential-only mode: Only processing residential buildings")
    print("      (Note: HDA processes all clusters; results will be filtered for this cluster)")
    try:
        # Build HDA command
        hda_cmd = [
            sys.executable,
            "-m", "branitz_ai.cli.hda_cli",
            "--cluster-id", cluster_id
        ]
        if residential_only:
            hda_cmd.append("--residential-only")
        
        result = subprocess.run(
            hda_cmd,
            check=True,
            capture_output=True,
            text=True
        )
        print("✅ HDA completed successfully")
        if result.stdout:
            # Only show last few lines to avoid clutter
            lines = result.stdout.strip().split('\n')
            if len(lines) > 10:
                print("  ... (output truncated)")
                for line in lines[-5:]:
                    print(f"  {line}")
            else:
                for line in lines:
                    print(f"  {line}")
    except subprocess.CalledProcessError as e:
        logger.error(f"HDA failed: {e}")
        if e.stderr:
            print(f"Error output: {e.stderr}")
        raise
    
    # Step 2: Run CHA
    print("\n[2/4] Running CHA (Centralised Heating Agent)...")
    try:
        cha_cmd = [
            sys.executable,
            "-m", "branitz_ai.cli.cha_cli",
            "--cluster-id", cluster_id,
            "--out", cha_out,
            "--max-attach-distance", "1000.0",  # Increased to connect all buildings
        ]
        if trunk_mode:
            cha_cmd.extend(["--trunk-mode", trunk_mode])
        if street_name:
            cha_cmd.extend(["--street-name", street_name])
        if street_ids:
            for s_id in street_ids:
                cha_cmd.extend(["--street-ids", s_id])
        if residential_only:
            cha_cmd.append("--residential-only")
        
        result = subprocess.run(
            cha_cmd,
            check=True,
            capture_output=True,
            text=True
        )
        print("✅ CHA completed successfully")
        if result.stdout:
            print(result.stdout)
    except subprocess.CalledProcessError as e:
        logger.error(f"CHA failed: {e}")
        if e.stderr:
            print(f"Error output: {e.stderr}")
        raise
    
    # Step 3: Generate Map
    print("\n[3/4] Generating interactive map...")
    try:
        from branitz_ai.data.preparation import load_buildings, load_building_cluster_map, filter_residential_buildings
        from branitz_ai.cli.cha_cli import load_streets
        
        # Load buildings and apply same filter as CHA
        buildings = load_buildings()
        cluster_map = load_building_cluster_map()
        
        # Filter to cluster
        cluster_buildings_map = cluster_map[cluster_map['street_id'] == cluster_id]
        building_ids = cluster_buildings_map['building_id'].tolist()
        buildings_in_cluster = buildings[buildings['building_id'].isin(building_ids)].copy()
        
        # Apply residential filter if requested
        if residential_only:
            buildings_in_cluster = filter_residential_buildings(buildings_in_cluster)
        
        # Load and filter streets using the SAME logic as CHA
        # This ensures the map displays the same topology that is simulated
        streets_gdf = load_streets()
        streets_gdf_filtered = filter_streets_for_cluster(
            streets_gdf=streets_gdf,
            buildings_in_cluster=buildings_in_cluster,
            street_name=street_name,
            street_ids=street_ids,
            buffer_m=500.0
        )
        logger.info(f"Filtered streets for map: {len(streets_gdf)} → {len(streets_gdf_filtered)} segments")
        
        map_path = os.path.join(cha_out, "maps", f"{cluster_id}_dh_map.html")
        
        # Use the existing function signature - it loads network from pickle
        # but we pass filtered streets_gdf to ensure map shows same streets as simulation
        create_dh_interactive_map(
            cluster_id=cluster_id,
            cha_out_dir=cha_out,
            buildings_gdf=buildings_in_cluster,  # Use filtered buildings
            streets_gdf=streets_gdf_filtered,  # Use filtered streets matching CHA simulation
            save_path=map_path,
            options=DHMapOptions()
        )
        print(f"✅ Map saved to: {map_path}")
    except Exception as e:
        logger.warning(f"Map generation failed (non-critical): {e}")
        print(f"⚠️  Map generation skipped: {e}")
    
    # Step 4: Extract and display KPIs
    print("\n[4/4] Extracting KPIs...")
    try:
        kpis_path = os.path.join(cha_out, "cha_kpis.json")
        if os.path.exists(kpis_path):
            with open(kpis_path, 'r') as f:
                kpis = json.load(f)
            
            print("\n" + "="*80)
            print("KEY PERFORMANCE INDICATORS (KPIs)")
            print("="*80)
            
            # Network metrics
            if 'network' in kpis:
                net = kpis['network']
                print("\nNetwork Metrics:")
                total_len = net.get('total_length_m', 'N/A')
                trunk_len = net.get('trunk_length_m', 'N/A')
                service_len = net.get('service_length_m', 'N/A')
                print(f"  - Total Length: {total_len:,.0f} m" if isinstance(total_len, (int, float)) else f"  - Total Length: {total_len}")
                print(f"  - Trunk Length: {trunk_len:,.0f} m" if isinstance(trunk_len, (int, float)) else f"  - Trunk Length: {trunk_len}")
                print(f"  - Service Length: {service_len:,.0f} m" if isinstance(service_len, (int, float)) else f"  - Service Length: {service_len}")
                print(f"  - Number of Pipes: {net.get('n_pipes', 'N/A')}")
                print(f"  - Number of Junctions: {net.get('n_junctions', 'N/A')}")
            
            # Aggregate metrics
            if 'aggregate' in kpis:
                agg = kpis['aggregate']
                print("\nAggregate Metrics:")
                max_vel = agg.get('max_velocity_ms', 'N/A')
                max_dp = agg.get('max_dp_per_100m_pa', 'N/A')
                thermal_loss = agg.get('thermal_loss_total_kw', 'N/A')
                design_load = agg.get('design_load_kw', 'N/A')
                print(f"  - Max Velocity: {max_vel:.2f} m/s" if isinstance(max_vel, (int, float)) else f"  - Max Velocity: {max_vel}")
                print(f"  - Max Pressure Drop: {max_dp:,.0f} Pa/100m" if isinstance(max_dp, (int, float)) else f"  - Max Pressure Drop: {max_dp}")
                print(f"  - Total Thermal Loss: {thermal_loss:,.2f} kW" if isinstance(thermal_loss, (int, float)) else f"  - Total Thermal Loss: {thermal_loss}")
                print(f"  - Design Load: {design_load:,.2f} kW" if isinstance(design_load, (int, float)) else f"  - Design Load: {design_load}")
            
            # Feasibility
            if 'aggregate' in kpis:
                agg = kpis['aggregate']
                print("\nFeasibility:")
                print(f"  - Velocity OK: {agg.get('velocity_ok', 'N/A')}")
                print(f"  - Pressure Drop OK: {agg.get('dp_ok', 'N/A')}")
                print(f"  - Overall Feasible: {agg.get('feasible', 'N/A')}")
            
            print("="*80 + "\n")
        else:
            print(f"⚠️  KPIs file not found: {kpis_path}")
    except Exception as e:
        logger.warning(f"KPI extraction failed (non-critical): {e}")
        print(f"⚠️  KPI display skipped: {e}")
    
    print("\n✅ Pipeline completed successfully!")
    print(f"\nOutputs:")
    print(f"  - HDA: {hda_out}")
    print(f"  - CHA: {cha_out}")
    print(f"  - Map: {os.path.join(cha_out, 'maps', f'{cluster_id}_dh_map.html')}")


def main():
    parser = argparse.ArgumentParser(
        description="Interactive pipeline workflow for Branitz Energy Decision AI"
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="Only list available streets, then exit"
    )
    parser.add_argument(
        "--cluster-id",
        type=str,
        help="Skip selection and run directly for this cluster ID"
    )
    parser.add_argument(
        "--stats-only",
        type=str,
        help="Only show statistics for this cluster ID"
    )
    parser.add_argument(
        "--output-base",
        type=str,
        default="results",
        help="Base directory for outputs (default: results)"
    )
    parser.add_argument(
        "--residential-only",
        action="store_true",
        help="Filter to only residential buildings (building_type='sfh' or building_function contains 'Wohn')"
    )
    parser.add_argument(
        "--trunk-mode",
        type=str,
        choices=["paths_to_buildings", "selected_streets", "full_street"],
        default=None,
        help="Strategy for building the trunk network. Options: 'paths_to_buildings' (minimal backbone), 'selected_streets' (only specified streets), 'full_street' (all streets in cluster bounds)."
    )
    parser.add_argument(
        "--street-name",
        type=str,
        default=None,
        help="Optional: restrict DH trunk to streets matching this name (case-insensitive, partial match)."
    )
    parser.add_argument(
        "--street-ids",
        nargs="*",
        default=None,
        help="Optional: restrict DH trunk to explicit street IDs (space-separated list)."
    )
    
    args = parser.parse_args()
    
    # Get available streets
    streets_df = get_available_streets()
    
    # List only mode
    if args.list_only:
        show_street_list(streets_df)
        return
    
    # Stats only mode
    if args.stats_only:
        show_building_statistics(args.stats_only, residential_only=args.residential_only)
        return
    
    # Interactive mode
    if args.cluster_id:
        cluster_id = args.cluster_id
    else:
        # Show list and prompt for selection
        show_street_list(streets_df)
        
        cluster_col = [c for c in streets_df.columns if 'cluster' in c.lower() or 'street' in c.lower()][0]
        
        while True:
            try:
                choice = input(f"Select street/cluster (1-{len(streets_df)}): ").strip()
                idx = int(choice) - 1
                if 0 <= idx < len(streets_df):
                    cluster_id = streets_df.iloc[idx][cluster_col]
                    break
                else:
                    print(f"Invalid choice. Please enter a number between 1 and {len(streets_df)}")
            except ValueError:
                print("Invalid input. Please enter a number.")
            except KeyboardInterrupt:
                print("\nCancelled by user.")
                return
    
    # Show building statistics
    show_building_statistics(cluster_id, residential_only=args.residential_only)
    
    # Confirm before running pipeline
    if not args.cluster_id:
        response = input("\nProceed with full pipeline (HDA → CHA → Map → KPIs)? [y/N]: ").strip().lower()
        if response != 'y':
            print("Cancelled.")
            return
    
    # Run full pipeline
    run_full_pipeline(
        cluster_id,
        args.output_base,
        residential_only=args.residential_only,
        trunk_mode=args.trunk_mode,
        street_name=args.street_name,
        street_ids=args.street_ids
    )


if __name__ == "__main__":
    main()

