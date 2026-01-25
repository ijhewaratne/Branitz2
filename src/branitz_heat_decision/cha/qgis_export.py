"""
QGIS Export and Interactive Map Generation for CHA.

Creates GeoPackage layers and HTML interactive maps with cascading colors
for velocity/temperature and pipe sizing based on DN.
"""

import folium
import branca.colormap as cm
import networkx as nx
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import geopandas as gpd
from shapely.geometry import LineString, Point
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List
import pandapipes as pp
import logging
import re

from .config import CHAConfig, get_default_config
from ..config import resolve_cluster_path

logger = logging.getLogger(__name__)

# Standard colormap for hydraulic results (coolwarm: blue=low, red=high)
VELOCITY_COLORMAP = plt.cm.coolwarm
TEMPERATURE_COLORMAP = plt.cm.RdYlBu_r

# Pipe sizing scale (DN → pixel width)
DN_TO_WIDTH = {
    20: 2, 25: 2.5, 32: 3, 40: 3.5, 50: 4,
    65: 5, 80: 6, 100: 7, 125: 8, 150: 9,
    200: 10, 250: 12, 300: 14, 400: 16
}

SUPPLY_COLOR_FIXED = "#d73027"
RETURN_COLOR_FIXED = "#2166ac"


def pipe_weight(diameter_mm: float, role: str) -> float:
    """
    Map pipe diameter (mm) to folium line weight.

    Requirements:
    - trunk: diameter_mm in [50..200] -> weight in [4..12]
    - service: diameter_mm in [20..80] -> weight in [2..7]
    - clamp to min/max
    - defaults if diameter missing: trunk=6, service=3
    """
    role = (role or "").strip().lower()
    if role not in ("trunk", "service"):
        role = "trunk"

    if diameter_mm is None or not np.isfinite(float(diameter_mm)):
        return 6.0 if role == "trunk" else 3.0

    d = float(diameter_mm)
    if role == "trunk":
        d_min, d_max = 50.0, 200.0
        w_min, w_max = 4.0, 12.0
    else:
        d_min, d_max = 20.0, 80.0
        w_min, w_max = 2.0, 7.0

    # linear scale then clamp
    if d_max <= d_min:
        return 6.0 if role == "trunk" else 3.0
    w = w_min + (d - d_min) * (w_max - w_min) / (d_max - d_min)
    return float(max(w_min, min(w_max, w)))


def _parse_dn_from_std_type(std_type: str) -> int:
    """
    Parse DN from pipe standard type string.
    
    Handles: "DN50", "NPS_2", "50mm", etc.
    Returns DN as integer.
    """
    std_type = str(std_type).upper()
    
    # Try DN format
    if "DN" in std_type:
        match = re.findall(r'DN(\d+)', std_type)
        if match:
            return int(match[0])
    
    # Try NPS to DN conversion (simplified)
    if "NPS" in std_type:
        match = re.findall(r'NPS_?(\d+)', std_type)
        if match:
            nps = int(match[0])
            # Approximate conversion: NPS 2 ≈ DN 50
            return nps * 25
    
    # Last resort: extract first number
    match = re.findall(r'(\d+)', std_type)
    if match:
        return int(match[0])
    
    return 50  # Default


def create_interactive_map(
    net: pp.pandapipesNet,
    buildings: gpd.GeoDataFrame,
    cluster_id: str,
    output_path: Optional[Path] = None,
    config: Optional[CHAConfig] = None,
    center_on_plant: bool = True,
    zoom_start: int = 15,
    add_layer_control: bool = True,
    velocity_range: Tuple[float, float] = (0.0, 1.5),
    temp_range: Tuple[float, float] = (30.0, 90.0),
    color_by: str = "velocity",
    title_suffix: str = "",
    scale_to_data_range: bool = True,
) -> str:
    """
    Create interactive HTML map for district heating network.
    
    Features:
    - Pipes colored by velocity (coolwarm colormap)
    - Pipes colored by temperature (cascading colormap)
    - Pipes colored by pressure (cascading colormap)
    - Pipe thickness ∝ DN (diameter)
    - Service pipes shown as dashed gray lines
    - Buildings sized by heat demand
    - Plant marked with red icon
    - Clickable popups with detailed metrics
    - Layer control for toggling visibility
    - Colorbar legends for velocity & temperature
    
    Args:
        net: Converged pandapipes network
        buildings: GeoDataFrame with building data (must include geometry and heat demand)
        cluster_id: Cluster identifier (used for file naming)
        output_path: Path to save HTML (default: results/interactive_maps/{cluster_id}.html)
        config: CHAConfig
        center_on_plant: Center map on plant location
        zoom_start: Initial zoom level
        add_layer_control: Add layer control widget
        velocity_range: (vmin, vmax) for velocity colormap
        temp_range: (vmin, vmax) for temperature colormap
        
    Returns:
        str: Path to generated HTML file
    """
    if config is None:
        config = get_default_config()
    
    if output_path is None:
        output_path = resolve_cluster_path(cluster_id, "interactive_maps") / f"{cluster_id}.html"
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"Creating interactive map for {cluster_id} at {output_path}")
    
    # --- 1. Identify Plant Location ---
    plant_junction_idx = _identify_plant_junction(net)
    plant_coords = _get_junction_coordinates(net, plant_junction_idx)
    
    # Transform coordinates from network CRS to WGS84 for folium
    # Buildings should be in EPSG:25833 (UTM 33N) or similar, need to transform to EPSG:4326
    if buildings.crs and buildings.crs.to_epsg() != 4326:
        buildings_wgs84 = buildings.to_crs('EPSG:4326')
    else:
        buildings_wgs84 = buildings
    
    if center_on_plant and plant_coords:
        # Transform plant coordinates to WGS84
        plant_point = gpd.GeoDataFrame([1], geometry=[Point(plant_coords)], crs=buildings.crs if buildings.crs else 'EPSG:25833')
        plant_wgs84 = plant_point.to_crs('EPSG:4326')
        plant_lon, plant_lat = plant_wgs84.geometry.iloc[0].x, plant_wgs84.geometry.iloc[0].y
        map_center = [plant_lat, plant_lon]  # folium expects [lat, lon]
    else:
        # Center on buildings centroid (already transformed to WGS84)
        centroid = buildings_wgs84.geometry.unary_union.centroid
        map_center = [centroid.y, centroid.x]
    
    # --- 2. Create Folium Map ---
    m = folium.Map(
        location=map_center,
        zoom_start=zoom_start,
        tiles="OpenStreetMap",
        control_scale=True
    )
    
    # --- 3. Prepare Data Layers ---
    
    # Pipe geometries with WGS84 coordinates for folium
    source_crs = str(buildings.crs) if buildings.crs else 'EPSG:25833'
    pipe_features_gdf, pipe_records = _extract_pipe_geometries(net, source_crs)
    
    # Create DataFrame from records (includes WGS84 coordinates)
    pipe_features_df = pd.DataFrame(pipe_records)
    
    # Separate pipes by type (with fallback if columns don't exist)
    if 'is_supply' not in pipe_features_df.columns:
        pipe_features_df['is_supply'] = False
        pipe_features_df['is_return'] = False
        pipe_features_df['is_heat_exchanger'] = False
    
    trunk_supply_pipes = pipe_features_df[~pipe_features_df['is_service'] & pipe_features_df['is_supply']].copy()
    trunk_return_pipes = pipe_features_df[~pipe_features_df['is_service'] & pipe_features_df['is_return']].copy()
    service_supply_pipes = pipe_features_df[pipe_features_df['is_service'] & pipe_features_df['is_supply']].copy()
    service_return_pipes = pipe_features_df[pipe_features_df['is_service'] & pipe_features_df['is_return']].copy()
    # Note: Heat consumers are separate components (not pipes), so no heat_exchanger_pipes
    
    logger.info(f"Pipe separation: {len(trunk_supply_pipes)} supply, {len(trunk_return_pipes)} return trunk pipes")
    logger.info(f"  Service: {len(service_supply_pipes)} supply, {len(service_return_pipes)} return")
    
    # --- 4. Add Pipe Layers ---
    # Cascading colors: either by velocity (m/s), temperature (°C), or pressure (bar).
    def _pipe_temp_value_c(pipe_row: pd.Series) -> float:
        tf = pipe_row.get("t_from_c", np.nan)
        tt = pipe_row.get("t_to_c", np.nan)
        try:
            tf = float(tf)
        except Exception:
            tf = np.nan
        try:
            tt = float(tt)
        except Exception:
            tt = np.nan
        if np.isfinite(tf) and np.isfinite(tt):
            return 0.5 * (tf + tt)
        if np.isfinite(tf):
            return tf
        if np.isfinite(tt):
            return tt
        return np.nan

    def _pipe_pressure_value_bar(pipe_row: pd.Series) -> float:
        pf = pipe_row.get("p_from_bar", np.nan)
        pt = pipe_row.get("p_to_bar", np.nan)
        try:
            pf = float(pf)
        except Exception:
            pf = np.nan
        try:
            pt = float(pt)
        except Exception:
            pt = np.nan
        if np.isfinite(pf) and np.isfinite(pt):
            return 0.5 * (pf + pt)
        if np.isfinite(pf):
            return pf
        if np.isfinite(pt):
            return pt
        return np.nan

    color_by = (color_by or "velocity").strip().lower()
    if color_by not in ("velocity", "temperature", "pressure"):
        logger.warning(f"Unknown color_by='{color_by}', falling back to 'velocity'")
        color_by = "velocity"

    if color_by == "temperature":
        t_all = pipe_features_df.apply(_pipe_temp_value_c, axis=1)
        t_all = pd.to_numeric(t_all, errors="coerce")
        t_all = t_all[np.isfinite(t_all)].dropna()
        if scale_to_data_range and len(t_all) > 0:
            tmin_used = float(t_all.min())
            tmax_used = float(t_all.max())
        else:
            tmin_used = float(temp_range[0]) if temp_range else 30.0
            tmax_used = float(temp_range[1]) if temp_range else 90.0
            if len(t_all) > 0:
                tmin_used = min(tmin_used, float(t_all.min()))
                tmax_used = max(tmax_used, float(t_all.max()))
        if not np.isfinite(tmax_used) or tmax_used <= tmin_used:
            tmax_used = tmin_used + 1e-6

        supply_cmap = cm.LinearColormap(
            # Keep supply as RED cascading shades (not yellow→red) for consistency
            colors=['#fee5d9', '#fcae91', '#fb6a4a', '#cb181d'],
            vmin=tmin_used,
            vmax=tmax_used,
            caption='Supply temperature (°C)'
        )
        return_cmap = cm.LinearColormap(
            colors=['#deebf7', '#9ecae1', '#3182bd', '#08519c'],
            vmin=tmin_used,
            vmax=tmax_used,
            caption='Return temperature (°C)'
        )
        get_value = _pipe_temp_value_c
        value_unit = "°C"
    elif color_by == "pressure":
        p_all = pipe_features_df.apply(_pipe_pressure_value_bar, axis=1)
        p_all = pd.to_numeric(p_all, errors="coerce")
        p_all = p_all[np.isfinite(p_all)].dropna()
        if scale_to_data_range and len(p_all) > 0:
            pmin_used = float(p_all.min())
            pmax_used = float(p_all.max())
        else:
            # fallback: typical district heating pressures
            pmin_used = 0.5
            pmax_used = 3.0
            if len(p_all) > 0:
                pmin_used = min(pmin_used, float(p_all.min()))
                pmax_used = max(pmax_used, float(p_all.max()))
        if not np.isfinite(pmax_used) or pmax_used <= pmin_used:
            pmax_used = pmin_used + 1e-6

        supply_cmap = cm.LinearColormap(
            colors=['#fee5d9', '#fcae91', '#fb6a4a', '#cb181d'],
            vmin=pmin_used,
            vmax=pmax_used,
            caption='Supply pressure (bar)'
        )
        return_cmap = cm.LinearColormap(
            colors=['#deebf7', '#9ecae1', '#3182bd', '#08519c'],
            vmin=pmin_used,
            vmax=pmax_used,
            caption='Return pressure (bar)'
        )
        get_value = _pipe_pressure_value_bar
        value_unit = "bar"
    else:
        v_all = pd.to_numeric(pipe_features_df.get('velocity_ms', pd.Series(dtype=float)), errors='coerce')
        v_all = v_all[np.isfinite(v_all)].dropna()
        if scale_to_data_range and len(v_all) > 0:
            vmin_used = float(v_all.min())
            vmax_used = float(v_all.max())
        else:
            vmin_used = float(velocity_range[0]) if velocity_range else 0.0
            vmax_used = float(velocity_range[1]) if velocity_range else 1.5
            if len(v_all) > 0:
                vmin_used = min(vmin_used, float(v_all.min()))
                vmax_used = max(vmax_used, float(v_all.max()))
        if not np.isfinite(vmax_used) or vmax_used <= vmin_used:
            vmax_used = vmin_used + 1e-6

        # User convention: Supply = red, Return = blue
        supply_cmap = cm.LinearColormap(
            colors=['#fee5d9', '#fcae91', '#fb6a4a', '#cb181d'],
            vmin=vmin_used,
            vmax=vmax_used,
            caption='Supply velocity (m/s)'
        )
        return_cmap = cm.LinearColormap(
            colors=['#deebf7', '#9ecae1', '#3182bd', '#08519c'],
            vmin=vmin_used,
            vmax=vmax_used,
            caption='Return velocity (m/s)'
        )
        get_value = lambda r: float(r.get("velocity_ms", np.nan))
        value_unit = "m/s"

    supply_cmap.add_to(m)
    return_cmap.add_to(m)
    
    # Fixed circuit colors (for sizing / DN thickness visualization)
    supply_fixed = SUPPLY_COLOR_FIXED
    return_fixed = RETURN_COLOR_FIXED

    # Trunk Supply Pipes (blue gradient)
    trunk_supply_layer = folium.FeatureGroup(name="Supply Pipes (Trunk)", show=True)
    
    for _, pipe in trunk_supply_pipes.iterrows():
        velocity = float(pipe.get('velocity_ms', 0.0))
        if not np.isfinite(velocity):
            velocity = vmin_used
        value = float(get_value(pipe))
        color = supply_cmap(value) if np.isfinite(value) else supply_cmap(supply_cmap.vmin)
        
        dn = pipe.get('dn', None) or _parse_dn_from_std_type(pipe.get('std_type', ''))
        diam_mm = pipe.get('diameter_mm', np.nan)
        line_weight = DN_TO_WIDTH.get(dn, 6)  # Thicker for trunk pipes
        
        # Enhanced popup with topology information
        pipe_name = pipe.get('name', f"pipe_{pipe['pipe_id']}")
        is_trunk = 'pipe_S_' in str(pipe_name) or 'pipe_R_' in str(pipe_name)
        pipe_type_label = "Trunk Supply" if is_trunk else "Supply"
        
        popup_html = f"""
        <div style="font-family: Arial, sans-serif;">
            <h4 style="margin: 0 0 10px 0; color: #cb181d;">{pipe_type_label} Pipe</h4>
            <b>ID:</b> {pipe['pipe_id']}<br>
            <b>Name:</b> {pipe_name}<br>
            <b>DN:</b> {dn if dn else pipe.get('std_type', 'N/A')}<br>
            <b>Diameter:</b> {diam_mm:.0f} mm<br>
            <b>Length:</b> {pipe['length_m']:.1f} m<br>
            <b>Velocity:</b> {velocity:.2f} m/s<br>
            <b>Pressure Drop:</b> {pipe['pressure_drop_bar']:.3f} bar<br>
            <b>T_from:</b> {pipe.get('t_from_c', float('nan')):.1f} °C<br>
            <b>T_to:</b> {pipe.get('t_to_c', float('nan')):.1f} °C<br>
            <b>ΔT (pipe):</b> {pipe.get('temp_drop_c', float('nan')):.2f} °C<br>
            <b>Flow Direction:</b> Plant → Buildings
        </div>
        """
        
        role = "trunk"
        weight = pipe_weight(pipe.get("diameter_mm", np.nan), role)
        folium.PolyLine(
            locations=pipe['coordinates'],
            color=color,
            weight=weight,
            opacity=0.95,
            popup=folium.Popup(popup_html, max_width=350),
            tooltip=(
                f"Trunk Supply: {value:.2f} {value_unit}, DN: {dn if dn else 'N/A'}"
                if np.isfinite(value) else f"Trunk Supply: DN {dn if dn else 'N/A'}"
            ),
        ).add_to(trunk_supply_layer)
    
    trunk_supply_layer.add_to(m)
    
    # Trunk Return Pipes (red gradient)
    trunk_return_layer = folium.FeatureGroup(name="Return Pipes (Trunk)", show=True)
    
    for _, pipe in trunk_return_pipes.iterrows():
        velocity = float(pipe.get('velocity_ms', 0.0))
        if not np.isfinite(velocity):
            velocity = vmin_used
        value = float(get_value(pipe))
        color = return_cmap(value) if np.isfinite(value) else return_cmap(return_cmap.vmin)
        
        dn = pipe.get('dn', None) or _parse_dn_from_std_type(pipe.get('std_type', ''))
        diam_mm = pipe.get('diameter_mm', np.nan)
        line_weight = DN_TO_WIDTH.get(dn, 6)  # Thicker for trunk pipes
        
        # Enhanced popup with topology information
        pipe_name = pipe.get('name', f"pipe_{pipe['pipe_id']}")
        is_trunk = 'pipe_S_' in str(pipe_name) or 'pipe_R_' in str(pipe_name)
        pipe_type_label = "Trunk Return" if is_trunk else "Return"
        
        popup_html = f"""
        <div style="font-family: Arial, sans-serif;">
            <h4 style="margin: 0 0 10px 0; color: #08519c;">{pipe_type_label} Pipe</h4>
            <b>ID:</b> {pipe['pipe_id']}<br>
            <b>Name:</b> {pipe_name}<br>
            <b>DN:</b> {dn if dn else pipe.get('std_type', 'N/A')}<br>
            <b>Diameter:</b> {diam_mm:.0f} mm<br>
            <b>Length:</b> {pipe['length_m']:.1f} m<br>
            <b>Velocity:</b> {velocity:.2f} m/s<br>
            <b>Pressure Drop:</b> {pipe['pressure_drop_bar']:.3f} bar<br>
            <b>T_from:</b> {pipe.get('t_from_c', float('nan')):.1f} °C<br>
            <b>T_to:</b> {pipe.get('t_to_c', float('nan')):.1f} °C<br>
            <b>ΔT (pipe):</b> {pipe.get('temp_drop_c', float('nan')):.2f} °C<br>
            <b>Flow Direction:</b> Buildings → Plant
        </div>
        """
        
        role = "trunk"
        weight = pipe_weight(pipe.get("diameter_mm", np.nan), role)
        folium.PolyLine(
            locations=pipe['coordinates'],
            color=color,
            weight=weight,
            opacity=0.95,
            popup=folium.Popup(popup_html, max_width=350),
            tooltip=(
                f"Trunk Return: {value:.2f} {value_unit}, DN: {dn if dn else 'N/A'}"
                if np.isfinite(value) else f"Trunk Return: DN {dn if dn else 'N/A'}"
            ),
        ).add_to(trunk_return_layer)
    
    trunk_return_layer.add_to(m)
    
    # Service Supply Pipes (light red, dashed)
    service_supply_layer = folium.FeatureGroup(name="Service Supply Pipes", show=False)
    
    for _, pipe in service_supply_pipes.iterrows():
        building_id = pipe.get('building_id', 'N/A')
        velocity = float(pipe.get('velocity_ms', 0.0))
        if not np.isfinite(velocity):
            velocity = vmin_used
        value = float(get_value(pipe))
        service_color = supply_cmap(value) if np.isfinite(value) else supply_cmap(supply_cmap.vmin)
        pipe_name = pipe.get('name', f"pipe_{pipe['pipe_id']}")
        dn = pipe.get('dn', 'N/A')
        
        popup_html = f"""
        <div style="font-family: Arial, sans-serif;">
            <h4 style="margin: 0 0 10px 0; color: #74add1;">Service Supply Pipe</h4>
            <b>ID:</b> {pipe['pipe_id']}<br>
            <b>Name:</b> {pipe_name}<br>
            <b>Building:</b> {building_id}<br>
            <b>DN:</b> {dn}<br>
            <b>Length:</b> {pipe['length_m']:.1f} m<br>
            <b>Velocity:</b> {velocity:.2f} m/s<br>
            <b>Flow Direction:</b> Trunk → Building<br>
            <b>Connection:</b> Trunk Service Junction → Building Supply Junction
        </div>
        """
        
        role = "service"
        weight = pipe_weight(pipe.get("diameter_mm", np.nan), role)
        folium.PolyLine(
            locations=pipe['coordinates'],
            color=service_color,
            weight=weight,
            opacity=0.75,
            dash_array='6, 6',  # Dashed line (service)
            popup=folium.Popup(popup_html, max_width=300),
            tooltip=(
                f"Service Supply to {building_id[:30]}: {value:.2f} {value_unit}"
                if np.isfinite(value) else f"Service Supply to {building_id[:30]}..."
            ),
        ).add_to(service_supply_layer)
    
    service_supply_layer.add_to(m)
    
    # Service Return Pipes (light blue, dashed)
    service_return_layer = folium.FeatureGroup(name="Service Return Pipes", show=False)
    
    for _, pipe in service_return_pipes.iterrows():
        building_id = pipe.get('building_id', 'N/A')
        velocity = float(pipe.get('velocity_ms', 0.0))
        if not np.isfinite(velocity):
            velocity = vmin_used
        value = float(get_value(pipe))
        service_color = return_cmap(value) if np.isfinite(value) else return_cmap(return_cmap.vmin)
        pipe_name = pipe.get('name', f"pipe_{pipe['pipe_id']}")
        dn = pipe.get('dn', 'N/A')
        
        popup_html = f"""
        <div style="font-family: Arial, sans-serif;">
            <h4 style="margin: 0 0 10px 0; color: #fdae61;">Service Return Pipe</h4>
            <b>ID:</b> {pipe['pipe_id']}<br>
            <b>Name:</b> {pipe_name}<br>
            <b>Building:</b> {building_id}<br>
            <b>DN:</b> {dn}<br>
            <b>Length:</b> {pipe['length_m']:.1f} m<br>
            <b>Velocity:</b> {velocity:.2f} m/s<br>
            <b>Flow Direction:</b> Building → Trunk<br>
            <b>Connection:</b> Building Return Junction → Trunk Service Junction
        </div>
        """
        
        role = "service"
        weight = pipe_weight(pipe.get("diameter_mm", np.nan), role)
        folium.PolyLine(
            locations=pipe['coordinates'],
            color=service_color,
            weight=weight,
            opacity=0.75,
            dash_array='6, 6',  # Dashed line (service)
            popup=folium.Popup(popup_html, max_width=300),
            tooltip=(
                f"Service Return from {building_id[:30]}: {value:.2f} {value_unit}"
                if np.isfinite(value) else f"Service Return from {building_id[:30]}..."
            ),
        ).add_to(service_return_layer)
    
    service_return_layer.add_to(m)
    
    # --- 5. Add Building Markers ---
    building_layer = folium.FeatureGroup(name="Buildings", show=True)
    
    for _, building in buildings_wgs84.iterrows():
        # Size ∝ sqrt(heat demand) for visual balance
        demand_kw = building.get('peak_heat_kw', building.get('annual_heat_demand_kwh_a', 25000) / 8760)
        radius = max(3, min(20, np.sqrt(demand_kw) / 2))
        
        # Get centroid for marker (buildings are polygons, already in WGS84)
        centroid = building.geometry.centroid
        location = [centroid.y, centroid.x]  # [lat, lon] for folium
        
        popup_html = f"""
        <b>Building {building['building_id']}</b><br>
        Type: {building.get('use_type', 'unknown')}<br>
        Peak demand: {demand_kw:.2f} kW<br>
        Floor area: {building.get('floor_area_m2', 'N/A')} m²<br>
        Year: {building.get('year_of_construction', 'N/A')}
        """
        
        folium.CircleMarker(
            location=location,
            radius=radius,
            color='black',
            weight=1,
            fill=True,
            fill_color='red',
            fill_opacity=0.6,
            popup=folium.Popup(popup_html, max_width=250),
            tooltip=f"Building: {demand_kw:.1f} kW",
        ).add_to(building_layer)
    
    building_layer.add_to(m)
    
    # --- 6. Add Plant Marker ---
    if center_on_plant and plant_coords:
        # Use already transformed coordinates
        folium.Marker(
            location=map_center,  # Already in [lat, lon] format
            popup=f"<b>Heat Plant</b><br>Cluster: {cluster_id}",
            icon=folium.Icon(color='red', icon='fire', prefix='fa'),
        ).add_to(m)

        # Add pump marker (conceptual, at plant)
        try:
            pump_info = _identify_circulation_pump(net, source_crs=str(buildings.crs) if buildings.crs else 'EPSG:25833')
            if pump_info is not None:
                pump_latlon, pump_popup = pump_info
                folium.Marker(
                    location=pump_latlon,
                    popup=pump_popup,
                    icon=folium.Icon(color='blue', icon='cog', prefix='fa'),
                ).add_to(m)
            else:
                # If no pump element exists (common in stable ext_grid-only hydraulics),
                # still indicate the pump position at the plant.
                folium.Marker(
                    location=map_center,
                    popup="<b>Circulation Pump</b><br>(conceptual) return → supply",
                    icon=folium.Icon(color='blue', icon='cog', prefix='fa'),
                ).add_to(m)
        except Exception:
            # keep map generation robust even if pump table differs
            pass
    
    # --- 7. Add Layer Control ---
    if add_layer_control:
        folium.LayerControl(position='topright', collapsed=False).add_to(m)
    
    # --- 8. Add Scale Bar & Title ---
    try:
        from folium.plugins import MeasureControl
        MeasureControl(position='bottomleft').add_to(m)
    except (ImportError, AttributeError):
        # MeasureControl not available, skip
        pass
    
    # Title as HTML overlay
    suffix = f" {title_suffix}".rstrip()
    title_html = f"""
    <h3 align="center" style="font-size:16px">
        <b>District Heating Network: {cluster_id}{suffix}</b>
    </h3>
    """
    m.get_root().html.add_child(folium.Element(title_html))

    # Diameter/thickness legend (map-only)
    thickness_legend = f"""
    <div style="
        position: fixed;
        bottom: 20px;
        right: 20px;
        z-index: 9999;
        background: rgba(255,255,255,0.92);
        padding: 10px 12px;
        border: 1px solid #999;
        border-radius: 6px;
        font-family: Arial, sans-serif;
        font-size: 12px;
        max-width: 260px;">
      <div style="font-weight: bold; margin-bottom: 6px;">Line thickness indicates pipe diameter (DN)</div>
      <svg width="230" height="70">
        <line x1="10" y1="12" x2="220" y2="12" stroke="#333" stroke-width="{pipe_weight(25, 'service')}" />
        <text x="10" y="9" font-size="10">DN25 (thin)</text>

        <line x1="10" y1="28" x2="220" y2="28" stroke="#333" stroke-width="{pipe_weight(50, 'trunk')}" />
        <text x="10" y="25" font-size="10">DN50 (medium)</text>

        <line x1="10" y1="44" x2="220" y2="44" stroke="#333" stroke-width="{pipe_weight(100, 'trunk')}" />
        <text x="10" y="41" font-size="10">DN100 (thick)</text>

        <line x1="10" y1="60" x2="220" y2="60" stroke="#333" stroke-width="{pipe_weight(150, 'trunk')}" />
        <text x="10" y="57" font-size="10">DN150 (extra thick)</text>
      </svg>
      <div style="margin-top: 6px; color: #444;">
        Supply = <span style="color:{SUPPLY_COLOR_FIXED}; font-weight:bold;">red</span>,
        Return = <span style="color:{RETURN_COLOR_FIXED}; font-weight:bold;">blue</span>,
        Service = dashed.
      </div>
    </div>
    """
    m.get_root().html.add_child(folium.Element(thickness_legend))
    
    # --- 9. Save to HTML ---
    m.save(str(output_path))
    logger.info(f"Interactive map saved to {output_path}")
    
    return str(output_path)


def export_pipe_velocity_csvs(
    net: pp.pandapipesNet,
    output_dir: Path,
    cluster_id: str,
    source_crs: Optional[str] = None,
    scale_to_data_range: bool = True,
) -> Dict[str, Path]:
    """
    Export pipe-level CSVs used for QA/debugging:
    - pipe_velocities_supply_return.csv
    - pipe_velocities_supply_return_with_temp.csv
    - pipe_velocities_plant_to_plant_main_path.csv
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Build a lightweight per-pipe table (avoid relying on folium records)
    junction_name = {}
    if hasattr(net, "junction") and "name" in net.junction.columns:
        junction_name = net.junction["name"].to_dict()

    def _res(pipe_idx: int) -> pd.Series:
        if hasattr(net, "res_pipe") and net.res_pipe is not None and pipe_idx in net.res_pipe.index:
            return net.res_pipe.loc[pipe_idx]
        return pd.Series({})

    def _vel_ms(res: pd.Series) -> float:
        if len(res) > 0 and "v_mean_m_per_s" in res.index:
            return float(res.get("v_mean_m_per_s", 0.0))
        if len(res) > 0 and "v_mean_ms" in res.index:
            return float(res.get("v_mean_ms", 0.0))
        return 0.0

    def _mdot_from(res: pd.Series) -> float:
        for k in ("mdot_from_kg_per_s", "mdot_from_kg_s", "mdot_kg_per_s"):
            if len(res) > 0 and k in res.index:
                return float(res.get(k))
        return float("nan")

    def _t_from_to_c(res: pd.Series) -> Tuple[float, float]:
        tf = np.nan
        tt = np.nan
        if len(res) > 0 and ("t_from_k" in res.index or "tfrom_k" in res.index):
            tf = float(res.get("t_from_k", res.get("tfrom_k", np.nan)))
        if len(res) > 0 and ("t_to_k" in res.index or "tto_k" in res.index):
            tt = float(res.get("t_to_k", res.get("tto_k", np.nan)))
        tf_c = float(tf - 273.15) if np.isfinite(tf) else np.nan
        tt_c = float(tt - 273.15) if np.isfinite(tt) else np.nan
        return tf_c, tt_c

    def _p_from_to_bar(res: pd.Series) -> Tuple[float, float]:
        pf = np.nan
        pt = np.nan
        if len(res) > 0 and "p_from_bar" in res.index:
            try:
                pf = float(res.get("p_from_bar"))
            except Exception:
                pf = np.nan
        if len(res) > 0 and "p_to_bar" in res.index:
            try:
                pt = float(res.get("p_to_bar"))
            except Exception:
                pt = np.nan
        return pf, pt

    def _pressure_value_bar(pf: float, pt: float) -> float:
        if np.isfinite(pf) and np.isfinite(pt):
            return 0.5 * (pf + pt)
        if np.isfinite(pf):
            return pf
        if np.isfinite(pt):
            return pt
        return np.nan

    def _temp_value_c(tf_c: float, tt_c: float) -> float:
        if np.isfinite(tf_c) and np.isfinite(tt_c):
            return 0.5 * (tf_c + tt_c)
        if np.isfinite(tf_c):
            return tf_c
        if np.isfinite(tt_c):
            return tt_c
        return np.nan

    rows = []
    for pipe_idx, pipe in net.pipe.iterrows():
        name = str(pipe.get("name", f"pipe_{pipe_idx}"))
        name_l = name.lower()
        is_trunk_conn = "trunk_conn" in name_l
        is_service = ("service" in name_l) and (not is_trunk_conn)
        pipe_type = "service" if is_service else "trunk"

        is_supply = ("pipe_s" in name_l) or ("service_s" in name_l) or ("trunk_conn_s" in name_l)
        is_return = ("pipe_r" in name_l) or ("service_r" in name_l) or ("trunk_conn_r" in name_l)
        direction = "supply" if is_supply and not is_return else "return" if is_return and not is_supply else "unknown"

        fj = int(pipe["from_junction"])
        tj = int(pipe["to_junction"])
        res = _res(int(pipe_idx))
        v = _vel_ms(res)
        mdot = _mdot_from(res)
        tf_c, tt_c = _t_from_to_c(res)
        tmean_c = _temp_value_c(tf_c, tt_c)
        pf_bar, pt_bar = _p_from_to_bar(res)
        pmean_bar = _pressure_value_bar(pf_bar, pt_bar)

        length_m = float(pipe["length_km"] * 1000.0)
        diam_m = float(pipe.get("diameter_m", np.nan))
        diam_mm = float(diam_m * 1000.0) if np.isfinite(diam_m) else np.nan

        rows.append(
            {
                "pipe_idx": int(pipe_idx),
                "pipe_id": int(pipe_idx),
                "pipe_name": name,
                "type": pipe_type,
                "direction": direction,
                "from_junction_idx": fj,
                "to_junction_idx": tj,
                "from_junction_id": fj,
                "to_junction_id": tj,
                "from_junction_name": junction_name.get(fj, str(fj)),
                "to_junction_name": junction_name.get(tj, str(tj)),
                "length_m": length_m,
                "diameter_m": diam_m,
                "diameter_mm": diam_mm,
                "velocity_m_per_s": float(v),
                "mdot_from_kg_per_s": mdot,
                "t_from_c": tf_c,
                "t_to_c": tt_c,
                "t_mean_c": tmean_c,
                "t_drop_c": (tf_c - tt_c) if (np.isfinite(tf_c) and np.isfinite(tt_c)) else np.nan,
                "p_from_bar": pf_bar,
                "p_to_bar": pt_bar,
                "p_mean_bar": pmean_bar,
            }
        )

    df = pd.DataFrame(rows)

    # Build colormaps (same palettes as map)
    v_all = pd.to_numeric(df["velocity_m_per_s"], errors="coerce")
    v_all = v_all[np.isfinite(v_all)].dropna()
    t_all = pd.to_numeric(df["t_mean_c"], errors="coerce")
    t_all = t_all[np.isfinite(t_all)].dropna()
    p_all = pd.to_numeric(df["p_mean_bar"], errors="coerce")
    p_all = p_all[np.isfinite(p_all)].dropna()

    # Data range scaling for better visual representation
    if scale_to_data_range and len(v_all) > 0:
        vmin_used, vmax_used = float(v_all.min()), float(v_all.max())
    else:
        vmin_used, vmax_used = 0.0, max(1.5, float(v_all.max()) if len(v_all) > 0 else 1.5)
    if not np.isfinite(vmax_used) or vmax_used <= vmin_used:
        vmax_used = vmin_used + 1e-6

    if scale_to_data_range and len(t_all) > 0:
        tmin_used, tmax_used = float(t_all.min()), float(t_all.max())
    else:
        tmin_used, tmax_used = 30.0, max(90.0, float(t_all.max()) if len(t_all) > 0 else 90.0)
    if not np.isfinite(tmax_used) or tmax_used <= tmin_used:
        tmax_used = tmin_used + 1e-6

    if scale_to_data_range and len(p_all) > 0:
        pmin_used, pmax_used = float(p_all.min()), float(p_all.max())
    else:
        pmin_used, pmax_used = 0.5, max(3.0, float(p_all.max()) if len(p_all) > 0 else 3.0)
    if not np.isfinite(pmax_used) or pmax_used <= pmin_used:
        pmax_used = pmin_used + 1e-6

    supply_vel_cmap = cm.LinearColormap(colors=["#fee5d9", "#fcae91", "#fb6a4a", "#cb181d"], vmin=vmin_used, vmax=vmax_used)
    return_vel_cmap = cm.LinearColormap(colors=["#deebf7", "#9ecae1", "#3182bd", "#08519c"], vmin=vmin_used, vmax=vmax_used)
    supply_tmp_cmap = cm.LinearColormap(colors=["#fee5d9", "#fcae91", "#fb6a4a", "#cb181d"], vmin=tmin_used, vmax=tmax_used)
    return_tmp_cmap = cm.LinearColormap(colors=["#deebf7", "#9ecae1", "#3182bd", "#08519c"], vmin=tmin_used, vmax=tmax_used)
    supply_p_cmap = cm.LinearColormap(colors=["#fee5d9", "#fcae91", "#fb6a4a", "#cb181d"], vmin=pmin_used, vmax=pmax_used)
    return_p_cmap = cm.LinearColormap(colors=["#deebf7", "#9ecae1", "#3182bd", "#08519c"], vmin=pmin_used, vmax=pmax_used)

    def _circuit(row: pd.Series) -> str:
        if row.get("direction") == "supply":
            return "supply"
        if row.get("direction") == "return":
            return "return"
        return "unknown"

    df["velocity_vmin"] = vmin_used
    df["velocity_vmax"] = vmax_used
    df["temp_vmin_c"] = tmin_used
    df["temp_vmax_c"] = tmax_used
    df["pressure_vmin_bar"] = pmin_used
    df["pressure_vmax_bar"] = pmax_used

    # Color hex values (useful for debugging + external plotting)
    def _vel_color_hex(r: pd.Series) -> str:
        v = r.get("velocity_m_per_s", np.nan)
        if not np.isfinite(v):
            v = vmin_used
        return supply_vel_cmap(v) if _circuit(r) == "supply" else return_vel_cmap(v) if _circuit(r) == "return" else "#999999"

    def _tmp_color_hex(r: pd.Series) -> str:
        t = r.get("t_mean_c", np.nan)
        if not np.isfinite(t):
            t = tmin_used
        return supply_tmp_cmap(t) if _circuit(r) == "supply" else return_tmp_cmap(t) if _circuit(r) == "return" else "#999999"

    df["color_velocity_hex"] = df.apply(_vel_color_hex, axis=1)
    df["color_temperature_hex"] = df.apply(_tmp_color_hex, axis=1)

    def _p_color_hex(r: pd.Series) -> str:
        p = r.get("p_mean_bar", np.nan)
        if not np.isfinite(p):
            p = pmin_used
        return supply_p_cmap(p) if _circuit(r) == "supply" else return_p_cmap(p) if _circuit(r) == "return" else "#999999"

    df["color_pressure_hex"] = df.apply(_p_color_hex, axis=1)

    # --- CSV 1: (legacy-ish) simple pipe list ---
    out1 = output_dir / "pipe_velocities_supply_return.csv"
    df1 = df.rename(columns={"velocity_m_per_s": "velocity_m_per_s"}).copy()
    df1["pipe_type"] = df1["direction"]
    df1["layer"] = df1["type"]
    df1 = df1[
        [
            "pipe_id",
            "pipe_name",
            "from_junction_id",
            "from_junction_name",
            "to_junction_id",
            "to_junction_name",
            "length_m",
            "diameter_m",
            "pipe_type",
            "layer",
            "velocity_m_per_s",
            "t_mean_c",
            "p_mean_bar",
            "color_velocity_hex",
            "color_temperature_hex",
            "color_pressure_hex",
            "velocity_vmin",
            "velocity_vmax",
            "temp_vmin_c",
            "temp_vmax_c",
            "pressure_vmin_bar",
            "pressure_vmax_bar",
        ]
    ]
    df1.to_csv(out1, index=False)

    # --- CSV 2: with temperature + mdot (matches earlier request) ---
    out2 = output_dir / "pipe_velocities_supply_return_with_temp.csv"
    df2 = df[
        [
            "pipe_idx",
            "pipe_name",
            "type",
            "direction",
            "from_junction_idx",
            "to_junction_idx",
            "from_junction_name",
            "to_junction_name",
            "length_m",
            "diameter_mm",
            "velocity_m_per_s",
            "mdot_from_kg_per_s",
            "t_from_c",
            "t_to_c",
            "t_mean_c",
            "t_drop_c",
            "p_from_bar",
            "p_to_bar",
            "p_mean_bar",
            "color_velocity_hex",
            "color_temperature_hex",
            "color_pressure_hex",
            "velocity_vmin",
            "velocity_vmax",
            "temp_vmin_c",
            "temp_vmax_c",
            "pressure_vmin_bar",
            "pressure_vmax_bar",
        ]
    ].copy()
    df2.to_csv(out2, index=False)

    # --- CSV 4: pressure-focused (simple view) ---
    out4 = output_dir / "pipe_pressures_supply_return.csv"
    dfp = df[
        [
            "pipe_id",
            "pipe_name",
            "type",
            "direction",
            "from_junction_id",
            "from_junction_name",
            "to_junction_id",
            "to_junction_name",
            "length_m",
            "diameter_mm",
            "p_from_bar",
            "p_to_bar",
            "p_mean_bar",
            "color_pressure_hex",
            "pressure_vmin_bar",
            "pressure_vmax_bar",
        ]
    ].copy()
    dfp.to_csv(out4, index=False)

    # --- CSV 3: plant-to-plant main path (one representative trunk path) ---
    out3 = output_dir / "pipe_velocities_plant_to_plant_main_path.csv"

    # Determine plant supply and return junctions
    plant_supply_j = None
    if hasattr(net, "ext_grid") and len(net.ext_grid) > 0:
        plant_supply_j = int(net.ext_grid.iloc[0]["junction"])
    if plant_supply_j is None:
        # fallback to named junction
        for j, nm in junction_name.items():
            if str(nm) == "plant_supply":
                plant_supply_j = int(j)
                break

    plant_return_j = None
    if hasattr(net, "circ_pump_const_pressure") and len(net.circ_pump_const_pressure) > 0:
        plant_return_j = int(net.circ_pump_const_pressure.iloc[0].get("return_junction"))
    if plant_return_j is None:
        for j, nm in junction_name.items():
            if str(nm) == "plant_return":
                plant_return_j = int(j)
                break

    # Build trunk supply/return graphs keyed by junction indices
    trunk_supply = df[(df["type"] == "trunk") & (df["direction"] == "supply")].copy()
    trunk_return = df[(df["type"] == "trunk") & (df["direction"] == "return")].copy()

    def _build_graph(sub: pd.DataFrame) -> Tuple[nx.Graph, Dict[frozenset, int]]:
        G = nx.Graph()
        edge_to_pipe = {}
        for _, r in sub.iterrows():
            u = int(r["from_junction_idx"])
            v = int(r["to_junction_idx"])
            w = float(r["length_m"])
            G.add_edge(u, v, weight=w)
            edge_to_pipe[frozenset((u, v))] = int(r["pipe_idx"])
        return G, edge_to_pipe

    Gs, edge_to_pipe_s = _build_graph(trunk_supply)
    Gr, edge_to_pipe_r = _build_graph(trunk_return)

    path_rows = []
    seg = 0
    if plant_supply_j is not None and plant_supply_j in Gs and Gs.number_of_nodes() > 0:
        d = nx.single_source_dijkstra_path_length(Gs, plant_supply_j, weight="weight")
        leaf_s = max(d.keys(), key=lambda k: d[k]) if d else plant_supply_j
        path_nodes = nx.shortest_path(Gs, plant_supply_j, leaf_s, weight="weight")
        for a, b in zip(path_nodes[:-1], path_nodes[1:]):
            seg += 1
            pid = edge_to_pipe_s.get(frozenset((a, b)))
            if pid is None:
                continue
            pr = df.loc[df["pipe_idx"] == pid].iloc[0]
            path_rows.append(
                {
                    "segment_order": seg,
                    "direction": "supply_trunk_plant_to_leaf",
                    "pipe_idx": int(pid),
                    "pipe_name": pr["pipe_name"],
                    "from_junction_idx": int(pr["from_junction_idx"]),
                    "to_junction_idx": int(pr["to_junction_idx"]),
                    "from_junction_name": pr["from_junction_name"],
                    "to_junction_name": pr["to_junction_name"],
                    "velocity_m_per_s": float(pr["velocity_m_per_s"]),
                    "diameter_mm": float(pr["diameter_mm"]),
                    "length_m": float(pr["length_m"]),
                }
            )

        # Return path: map leaf supply junction name to corresponding return junction name if possible
        leaf_s_name = junction_name.get(int(leaf_s), "")
        leaf_r = None
        if isinstance(leaf_s_name, str) and leaf_s_name.startswith("S_"):
            want = "R_" + leaf_s_name[2:]
            for j, nm in junction_name.items():
                if str(nm) == want:
                    leaf_r = int(j)
                    break
        if leaf_r is None and plant_return_j is not None and plant_return_j in Gr:
            d2 = nx.single_source_dijkstra_path_length(Gr, plant_return_j, weight="weight")
            leaf_r = max(d2.keys(), key=lambda k: d2[k]) if d2 else plant_return_j

        if plant_return_j is not None and leaf_r is not None and plant_return_j in Gr and leaf_r in Gr:
            path_nodes_r = nx.shortest_path(Gr, leaf_r, plant_return_j, weight="weight")
            seg = 0
            for a, b in zip(path_nodes_r[:-1], path_nodes_r[1:]):
                seg += 1
                pid = edge_to_pipe_r.get(frozenset((a, b)))
                if pid is None:
                    continue
                pr = df.loc[df["pipe_idx"] == pid].iloc[0]
                path_rows.append(
                    {
                        "segment_order": seg,
                        "direction": "return_trunk_leaf_to_plant",
                        "pipe_idx": int(pid),
                        "pipe_name": pr["pipe_name"],
                        "from_junction_idx": int(pr["from_junction_idx"]),
                        "to_junction_idx": int(pr["to_junction_idx"]),
                        "from_junction_name": pr["from_junction_name"],
                        "to_junction_name": pr["to_junction_name"],
                        "velocity_m_per_s": float(pr["velocity_m_per_s"]),
                        "diameter_mm": float(pr["diameter_mm"]),
                        "length_m": float(pr["length_m"]),
                    }
                )

    pd.DataFrame(path_rows).to_csv(out3, index=False)

    logger.info(f"Exported pipe CSVs: {out1.name}, {out2.name}, {out3.name}, {out4.name}")
    return {
        "supply_return": out1,
        "supply_return_with_temp": out2,
        "plant_to_plant_main_path": out3,
        "pressures_supply_return": out4,
    }


def _identify_circulation_pump(
    net: pp.pandapipesNet,
    source_crs: str,
) -> Optional[Tuple[List[float], str]]:
    """
    Identify the circulation pump and return a (lat, lon) location + popup HTML.

    For trunk-spur we create a constant-pressure circulation pump connecting:
      plant_return_junction -> plant_supply_junction
    """
    # Find pump element table
    pump_tbl_name = None
    for name in ("circ_pump_const_pressure", "circ_pump_pressure", "circ_pump"):
        if hasattr(net, name):
            tbl = getattr(net, name)
            try:
                if tbl is not None and not tbl.empty:
                    pump_tbl_name = name
                    break
            except Exception:
                continue
    if pump_tbl_name is None:
        return None

    pump_tbl = getattr(net, pump_tbl_name)
    pump = pump_tbl.iloc[0]

    # Junction column names differ across pandapipes versions
    return_j = pump.get("return_junction", pump.get("return_junctions", None))
    flow_j = pump.get("flow_junction", pump.get("flow_junctions", None))
    if return_j is None or flow_j is None:
        # common alternative naming
        return_j = pump.get("from_junction", return_j)
        flow_j = pump.get("to_junction", flow_j)
    if return_j is None or flow_j is None:
        return None

    return_coords = _get_junction_coordinates(net, int(return_j))
    flow_coords = _get_junction_coordinates(net, int(flow_j))
    if not return_coords or not flow_coords:
        return None

    # Place marker at midpoint between return and supply (in network CRS), then convert to WGS84
    midx = (return_coords[0] + flow_coords[0]) / 2.0
    midy = (return_coords[1] + flow_coords[1]) / 2.0
    mid_point = gpd.GeoDataFrame([1], geometry=[Point((midx, midy))], crs=source_crs)
    mid_wgs84 = mid_point.to_crs("EPSG:4326")
    lon, lat = mid_wgs84.geometry.iloc[0].x, mid_wgs84.geometry.iloc[0].y

    popup = (
        f"<b>Circulation Pump</b><br>"
        f"Type: {pump_tbl_name}<br>"
        f"Return → Supply (plant_return → plant_supply)"
    )
    return ([lat, lon], popup)


def _identify_plant_junction(net: pp.pandapipesNet) -> int:
    """Identify plant/source junction index."""
    # Prefer ext_grid if present (plant boundary condition)
    if 'ext_grid' in net and net.ext_grid is not None and not net.ext_grid.empty:
        return int(net.ext_grid['junction'].iloc[0])
    if 'source' in net and net.source is not None and not net.source.empty:
        return int(net.source['junction'].iloc[0])
    
    # Fallback: junction with highest pressure rating
    return net.junction['pn_bar'].idxmax()


def _get_junction_coordinates(net: pp.pandapipesNet, junction_idx: int) -> Optional[Tuple[float, float]]:
    """
    Get coordinates for junction from junction_geodata.
    
    Returns:
        (x, y) tuple or None if not found
    """
    if not net.junction_geodata.empty and junction_idx in net.junction_geodata.index:
        return (
            float(net.junction_geodata.loc[junction_idx, 'x']),
            float(net.junction_geodata.loc[junction_idx, 'y'])
        )
    return None


def _extract_pipe_geometries(
    net: pp.pandapipesNet,
    target_crs: str
) -> Tuple[gpd.GeoDataFrame, List[Dict]]:
    """
    Extract pipe geometries as GeoDataFrame with WGS84 coordinates for folium.
    
    Args:
        net: pandapipes network
        target_crs: Target CRS for output geometries
        
    Returns:
        Tuple of (GeoDataFrame with geometries in target_crs, list of pipe records with WGS84 coordinates)
    """
    pipe_records = []
    pipe_coords_wgs84 = []  # Store WGS84 coordinates separately
    
    # Determine source CRS (from network or default)
    source_crs = target_crs if target_crs else 'EPSG:25833'
    
    for pipe_idx, pipe in net.pipe.iterrows():
        from_junc = pipe['from_junction']
        to_junc = pipe['to_junction']
        
        # Get coordinates
        from_coords = _get_junction_coordinates(net, from_junc)
        to_coords = _get_junction_coordinates(net, to_junc)
        
        if from_coords and to_coords:
            geometry = LineString([from_coords, to_coords])
            
            # Determine pipe type from name (must do before getting results)
            pipe_name = str(pipe.get('name', '')).lower()
            # Trunk connection pipes are infrastructure (not service connections) - exclude from service layer
            is_trunk_conn = 'trunk_conn' in pipe_name
            is_service = ('service' in pipe_name and not is_trunk_conn)  # Service pipes only, exclude trunk_conn
            is_supply = 'pipe_s' in pipe_name or 'service_s' in pipe_name or 'trunk_conn_s' in pipe_name
            is_return = 'pipe_r' in pipe_name or 'service_r' in pipe_name or 'trunk_conn_r' in pipe_name
            # Note: Heat consumers are no longer modeled as pipes, they are separate components
            is_heat_exchanger = False  # Legacy flag, no longer used
            
            # Get results (may not exist if network didn't converge)
            if hasattr(net, 'res_pipe') and net.res_pipe is not None and pipe_idx in net.res_pipe.index:
                res = net.res_pipe.loc[pipe_idx]
            else:
                # Create empty result dict
                res = pd.Series({})
            
            # Identify building ID for service pipes
            building_id = None
            if is_service:
                # Extract from pipe name (format: "service_S_{building_id}" or "service_R_{building_id}")
                if 'service_s_' in pipe_name or 'service_r_' in pipe_name:
                    parts = pipe_name.split('_')
                    # Find building_id part (could be complex object)
                    for i, part in enumerate(parts):
                        if part in ['s', 'r'] and i + 1 < len(parts):
                            # Next part might be building_id
                            building_id = '_'.join(parts[i+1:])
                            break
                
                # Fallback: Find sink connected to this pipe
                if not building_id:
                    sinks = net.sink[net.sink['junction'] == to_junc]
                    if not sinks.empty:
                        sink_name = sinks.iloc[0].get('name', '')
                        # Extract building_id from sink name (format: "sink_{building_id}")
                        if sink_name.startswith('sink_'):
                            building_id = sink_name.replace('sink_', '')
            
            # Handle missing results columns (network may not have converged)
            # Velocity column name differs across pandapipes versions
            if len(res) > 0 and 'v_mean_ms' in res.index:
                velocity_ms = float(res.get('v_mean_ms', 0.0))
            elif len(res) > 0 and 'v_mean_m_per_s' in res.index:
                velocity_ms = float(res.get('v_mean_m_per_s', 0.0))
            else:
                velocity_ms = 0.0
            p_from = float(res.get('p_from_bar', np.nan)) if len(res) > 0 and 'p_from_bar' in res.index else np.nan
            p_to = float(res.get('p_to_bar', np.nan)) if len(res) > 0 and 'p_to_bar' in res.index else np.nan
            p_mean = 0.5 * (p_from + p_to) if (np.isfinite(p_from) and np.isfinite(p_to)) else (p_from if np.isfinite(p_from) else (p_to if np.isfinite(p_to) else np.nan))
            # Thermal columns may be missing if heat mode wasn't solved; avoid fake defaults.
            if len(res) > 0 and ('t_from_k' in res.index or 'tfrom_k' in res.index):
                tfrom = float(res.get('t_from_k', res.get('tfrom_k', np.nan)))
            else:
                tfrom = np.nan
            if len(res) > 0 and ('t_to_k' in res.index or 'tto_k' in res.index):
                tto = float(res.get('t_to_k', res.get('tto_k', np.nan)))
            else:
                tto = np.nan
            qext_w = float(res.get('qext_w', 0.0)) if len(res) > 0 and 'qext_w' in res.index else 0.0

            # Mass flow (for flow-aligned dp sign)
            mdot_from = np.nan
            if len(res) > 0:
                for k in ("mdot_from_kg_per_s", "mdot_from_kg_s", "mdot_kg_per_s"):
                    if k in res.index:
                        try:
                            mdot_from = float(res.get(k))
                        except Exception:
                            mdot_from = np.nan
                        break

            # Convert to °C for display (keep NaNs if thermal not solved)
            tfrom_c = float(tfrom - 273.15) if (tfrom == tfrom) else np.nan
            tto_c = float(tto - 273.15) if (tto == tto) else np.nan
            temp_drop_c = float(tfrom - tto) if (tfrom == tfrom and tto == tto) else np.nan
            
            # Flow-aligned pressure drop: if actual flow is opposite pipe orientation, flip dp sign.
            dp_oriented_bar = (p_from - p_to) if (np.isfinite(p_from) and np.isfinite(p_to)) else np.nan
            if np.isfinite(dp_oriented_bar) and np.isfinite(mdot_from) and mdot_from < 0:
                dp_flow_bar = -dp_oriented_bar
            else:
                dp_flow_bar = dp_oriented_bar
            
            pipe_records.append({
                'pipe_id': int(pipe_idx),
                'name': pipe.get('name', f'pipe_{pipe_idx}'),
                'std_type': pipe.get('std_type', 'unknown'),
                'is_trunk_conn': is_trunk_conn,  # Track trunk connection pipes
                # DN: prefer actual diameter if available (source of truth after sizing),
                # fallback to std_type parsing.
                'dn': int(round(float(pipe.get('diameter_m', np.nan) * 1000.0)))
                if pd.notna(pipe.get('diameter_m', np.nan))
                else _parse_dn_from_std_type(pipe.get('std_type', '')),
                'diameter_mm': float(pipe.get('diameter_m', np.nan) * 1000.0)
                if pipe.get('diameter_m', np.nan) == pipe.get('diameter_m', np.nan)
                else np.nan,
                'is_service': is_service,
                'is_supply': is_supply,
                'is_return': is_return,
                'is_heat_exchanger': is_heat_exchanger,
                'building_id': building_id,
                'length_m': float(pipe['length_km'] * 1000),
                'velocity_ms': velocity_ms,
                'mdot_from_kg_per_s': mdot_from,
                'p_from_bar': p_from,
                'p_to_bar': p_to,
                'p_mean_bar': p_mean,
                'pressure_drop_bar': dp_flow_bar,
                'pressure_drop_oriented_bar': dp_oriented_bar,
                'pressure_drop_per_100m_bar': (dp_flow_bar / max(pipe['length_km'] * 10, 0.001)) if np.isfinite(dp_flow_bar) else np.nan,
                't_from_c': tfrom_c,
                't_to_c': tto_c,
                'temp_drop_c': temp_drop_c,
                'heat_loss_kw': qext_w / 1000,
                'geometry': geometry,
            })
    
            # Transform coordinates to WGS84 for folium
            from_point = gpd.GeoDataFrame([1], geometry=[Point(from_coords)], crs=source_crs)
            to_point = gpd.GeoDataFrame([1], geometry=[Point(to_coords)], crs=source_crs)
            from_wgs84 = from_point.to_crs('EPSG:4326')
            to_wgs84 = to_point.to_crs('EPSG:4326')
            pipe_coords_wgs84.append([
                (from_wgs84.geometry.iloc[0].y, from_wgs84.geometry.iloc[0].x),  # (lat, lon)
                (to_wgs84.geometry.iloc[0].y, to_wgs84.geometry.iloc[0].x)
            ])
    
    # Create GeoDataFrame
    pipes_gdf = gpd.GeoDataFrame(pipe_records, crs=source_crs)
    
    # Add WGS84 coordinates to records
    for idx, coords in enumerate(pipe_coords_wgs84):
        pipe_records[idx]['coordinates'] = coords
    
    return pipes_gdf, pipe_records


def export_network_to_qgis(
    net: pp.pandapipesNet,
    output_dir: Path,
    cluster_id: str,
    config: Optional[CHAConfig] = None,
) -> Dict[str, Path]:
    """
    Export network to QGIS-compatible GeoPackage layers.
    
    Creates separate layers for:
    - trunk_supply (supply pipes)
    - trunk_return (return pipes)
    - service_connections
    - junctions
    - buildings (if geodata available)
    
    Args:
        net: pandapipes network
        output_dir: Directory to save GeoPackages
        cluster_id: Cluster identifier
        config: CHAConfig
        
    Returns:
        Dict mapping layer names to file paths
    """
    if config is None:
        config = get_default_config()
    
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Extract pipe geometries (returns GeoDataFrame only for QGIS export)
    pipes_gdf, _ = _extract_pipe_geometries(net, config.crs)
    
    # Separate supply/return by pipe name (proper identification)
    if 'is_supply' not in pipes_gdf.columns or 'is_return' not in pipes_gdf.columns:
        # Identify from pipe names
        pipes_gdf['is_supply'] = pipes_gdf['name'].str.contains('pipe_S|service_S|_S_|trunk_conn_S', case=False, na=False, regex=True)
        pipes_gdf['is_return'] = pipes_gdf['name'].str.contains('pipe_R|service_R|_R_|trunk_conn_R', case=False, na=False, regex=True)
    
    # Export layers
    layers = {}
    
    # Supply trunk (exclude trunk_conn pipes which are infrastructure)
    supply_pipes = pipes_gdf[
        ~pipes_gdf['is_service'] & 
        pipes_gdf['is_supply'] & 
        ~pipes_gdf['name'].str.contains('trunk_conn', case=False, na=False)
    ]
    if not supply_pipes.empty:
        path = output_dir / f"{cluster_id}_trunk_supply.gpkg"
        supply_pipes.to_file(path, driver="GPKG")
        layers['trunk_supply'] = path
        logger.info(f"Exported {len(supply_pipes)} trunk supply pipes")
    
    # Return trunk (exclude trunk_conn pipes which are infrastructure)
    return_pipes = pipes_gdf[
        ~pipes_gdf['is_service'] & 
        pipes_gdf['is_return'] & 
        ~pipes_gdf['name'].str.contains('trunk_conn', case=False, na=False)
    ]
    if not return_pipes.empty:
        path = output_dir / f"{cluster_id}_trunk_return.gpkg"
        return_pipes.to_file(path, driver="GPKG")
        layers['trunk_return'] = path
        logger.info(f"Exported {len(return_pipes)} trunk return pipes")
    
    # Service supply connections (exclude trunk_conn which are infrastructure)
    service_supply_pipes = pipes_gdf[
        pipes_gdf['is_service'] & 
        pipes_gdf['is_supply'] & 
        ~pipes_gdf['name'].str.contains('trunk_conn', case=False, na=False)
    ]
    if not service_supply_pipes.empty:
        path = output_dir / f"{cluster_id}_service_supply.gpkg"
        service_supply_pipes.to_file(path, driver="GPKG")
        layers['service_supply'] = path
        logger.info(f"Exported {len(service_supply_pipes)} service supply pipes")
    
    # Service return connections (exclude trunk_conn which are infrastructure)
    service_return_pipes = pipes_gdf[
        pipes_gdf['is_service'] & 
        pipes_gdf['is_return'] & 
        ~pipes_gdf['name'].str.contains('trunk_conn', case=False, na=False)
    ]
    if not service_return_pipes.empty:
        path = output_dir / f"{cluster_id}_service_return.gpkg"
        service_return_pipes.to_file(path, driver="GPKG")
        layers['service_return'] = path
        logger.info(f"Exported {len(service_return_pipes)} service return pipes")
    
    # All service connections (for backward compatibility)
    service_pipes = pipes_gdf[pipes_gdf['is_service']]
    if not service_pipes.empty:
        path = output_dir / f"{cluster_id}_service_connections.gpkg"
        service_pipes.to_file(path, driver="GPKG")
        layers['service_connections'] = path
    
    # Junctions
    junctions_gdf = _extract_junction_geometries(net, config.crs)
    if not junctions_gdf.empty:
        path = output_dir / f"{cluster_id}_junctions.gpkg"
        junctions_gdf.to_file(path, driver="GPKG")
        layers['junctions'] = path
    
    logger.info(f"Exported QGIS layers to {output_dir}: {list(layers.keys())}")
    
    return layers


def _extract_junction_geometries(
    net: pp.pandapipesNet,
    target_crs: str
) -> gpd.GeoDataFrame:
    """
    Extract junction geometries as GeoDataFrame.
    
    Returns:
        GeoDataFrame with junction points and attributes
    """
    if net.junction_geodata.empty:
        return gpd.GeoDataFrame()
    
    records = []
    
    for junc_idx in net.junction.index:
        coords = _get_junction_coordinates(net, junc_idx)
        if coords:
            is_plant = junc_idx == _identify_plant_junction(net)
            pressure = float(net.res_junction.loc[junc_idx, 'p_bar'])
            temp = float(net.res_junction.loc[junc_idx, 't_k'] - 273.15)
            
            records.append({
                'junction_id': int(junc_idx),
                'name': net.junction.loc[junc_idx].get('name', f'junction_{junc_idx}'),
                'is_plant': is_plant,
                'pressure_bar': pressure,
                'temperature_c': temp,
                'geometry': Point(coords),
            })
    
    return gpd.GeoDataFrame(records, crs=target_crs)