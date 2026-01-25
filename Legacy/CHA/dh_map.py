"""
Interactive district heating map utilities.

Design goals:
- Read CHA outputs and render a layered Folium map.
- Prefer deterministic, file-based inputs.
- Degrade gracefully when simulation results or geodata are missing.

Expected CHA artefacts:
- results/cha/<cluster_id>/cha_net.pkl

Optional net attributes (created by your builder):
- net.edge_to_pipe_idx: dict with keys ((node_a, node_b), "supply"/"return") -> pipe_idx
- net.building_to_service_pipes, net.building_to_junctions

Optional tables:
- net.junction_geodata with columns ["x","y"]
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple, List

import pandas as pd
import geopandas as gpd
from shapely.geometry import LineString, Point
import folium

try:
    import pandapipes as pp
except Exception:  # pragma: no cover
    pp = None

from branitz_ai.data.preparation import load_buildings, load_building_cluster_map

logger = logging.getLogger(__name__)


@dataclass
class DHMapOptions:
    """Configuration options for DH map generation."""
    tiles: str = "CartoDB positron"
    zoom_start: int = 15
    show_streets: bool = True
    show_service_pipes: bool = True
    show_temperature: bool = True  # only used if res_junction temps exist
    max_service_length_m: float = 30.0  # Maximum service pipe length to display (m)
    fallback_supply_c: float = 70.0
    fallback_return_c: float = 45.0
    supply_color: str = "#d62728"
    return_color: str = "#1f77b4"
    service_color: str = "#2ca02c"
    street_color: str = "#808080"
    trunk_weight: int = 4
    service_weight: int = 2
    street_weight: int = 2


# ---------------------------
# Loading helpers
# ---------------------------


def _load_cha_net(cha_out_dir: str):
    """Load CHA network from pickle file."""
    if pp is None:
        raise ImportError("pandapipes is required to load CHA networks.")
    net_path = os.path.join(cha_out_dir, "cha_net.pkl")
    if not os.path.exists(net_path):
        raise FileNotFoundError(f"CHA net not found: {net_path}")
    return pp.from_pickle(net_path)


def _get_cluster_buildings(
    cluster_id: str,
    buildings_gdf: Optional[gpd.GeoDataFrame] = None,
    cluster_map_df: Optional[pd.DataFrame] = None,
) -> gpd.GeoDataFrame:
    """Get buildings for a specific cluster."""
    if buildings_gdf is None:
        buildings_gdf = load_buildings()

    # Fast path if cluster column exists
    for col in ["cluster_id", "street_cluster", "street_id"]:
        if col in buildings_gdf.columns:
            subset = buildings_gdf[buildings_gdf[col] == cluster_id].copy()
            if len(subset) > 0:
                return subset

    # Fallback join with cluster map
    if cluster_map_df is None:
        cluster_map_df = load_building_cluster_map()

    if "building_id" not in buildings_gdf.columns:
        raise ValueError("buildings_gdf must contain building_id for cluster join.")

    # Attempt to infer cluster column name in map
    map_cluster_col = None
    for c in ["cluster_id", "street_cluster", "street_id"]:
        if c in cluster_map_df.columns:
            map_cluster_col = c
            break

    if map_cluster_col is None:
        raise ValueError(
            "building_cluster_map is missing a cluster column "
            "(expected one of: cluster_id, street_cluster, street_id)."
        )

    merged = buildings_gdf.merge(
        cluster_map_df[["building_id", map_cluster_col]],
        on="building_id",
        how="left",
        validate="1:1",
    )
    subset = merged[merged[map_cluster_col] == cluster_id].copy()
    return subset


def _ensure_wgs84(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Convert GeoDataFrame to WGS84 (EPSG:4326) for Folium."""
    if gdf is None or len(gdf) == 0:
        return gdf
    if gdf.crs is None:
        # Assume UTM 33N in your project if CRS missing
        gdf = gdf.set_crs("EPSG:32633")
    return gdf.to_crs("EPSG:4326")


# ---------------------------
# Geometry extraction
# ---------------------------


def _get_junction_xy(net, junc_idx: int) -> Optional[Tuple[float, float]]:
    """
    Try to resolve junction coordinates.
    
    Priority:
    1) junction_geodata table
    2) parse from junction name like S_<x>_<y> or R_<x>_<y>
    """
    # 1) geodata
    try:
        jgd = getattr(net, "junction_geodata", None)
        if jgd is not None and len(jgd) > 0 and junc_idx in jgd.index:
            x = float(jgd.at[junc_idx, "x"])
            y = float(jgd.at[junc_idx, "y"])
            return (x, y)
    except Exception:
        pass

    # 2) parse from name
    try:
        name = str(net.junction.at[junc_idx, "name"])
        m = re.match(r"^[SR]_(?P<x>-?\d+(\.\d+)?)_(?P<y>-?\d+(\.\d+)?)$", name)
        if m:
            return (float(m.group("x")), float(m.group("y")))
    except Exception:
        pass

    return None


def _extract_trunk_lines_from_edge_map(net) -> Dict[str, List[LineString]]:
    """
    Uses net.edge_to_pipe_idx if present.
    Returns dict with keys: 'supply', 'return'
    """
    out = {"supply": [], "return": []}
    edge_map = getattr(net, "edge_to_pipe_idx", None)
    if not edge_map:
        return out

    for (edge, kind), _pipe_idx in edge_map.items():
        try:
            a, b = edge
            line = LineString([a, b])
            if kind == "supply":
                out["supply"].append(line)
            elif kind == "return":
                out["return"].append(line)
        except Exception:
            continue

    return out


def _extract_pipe_lines_from_tables(net) -> Tuple[Dict[str, List[LineString]], Dict[int, Dict]]:
    """
    Fallback if edge_to_pipe_idx missing.
    Builds geometry using from/to junction coordinates.
    Classifies by name prefix.
    Returns both geometries and pipe metadata.
    """
    out = {"supply": [], "return": [], "service": [], "hx": [], "other": []}
    pipe_metadata = {}

    for pipe_idx, row in net.pipe.iterrows():
        name = str(row.get("name", ""))
        fj = int(row["from_junction"])
        tj = int(row["to_junction"])

        a = _get_junction_xy(net, fj)
        b = _get_junction_xy(net, tj)
        if a is None or b is None:
            continue

        line = LineString([a, b])
        
        # Extract pipe details
        length_m = float(row.get("length_km", 0)) * 1000 if pd.notna(row.get("length_km")) else 0
        diameter_m = float(row.get("diameter_m", 0)) if pd.notna(row.get("diameter_m")) else 0
        
        # Get flow, pressure, temperature from results if available
        flow_kg_s = None
        pressure_from = None
        pressure_to = None
        temp_from = None
        temp_to = None
        
        try:
            resp = getattr(net, "res_pipe", None)
            resj = getattr(net, "res_junction", None)
            
            if resp is not None and len(resp) > 0 and pipe_idx in resp.index:
                flow_kg_s = float(resp.at[pipe_idx, "mdot_kg_per_s"]) if "mdot_kg_per_s" in resp.columns else None
            
            if resj is not None and len(resj) > 0:
                if fj in resj.index:
                    pressure_from = float(resj.at[fj, "p_bar"]) if "p_bar" in resj.columns else None
                    if "t_k" in resj.columns:
                        temp_from = float(resj.at[fj, "t_k"]) - 273.15
                if tj in resj.index:
                    pressure_to = float(resj.at[tj, "p_bar"]) if "p_bar" in resj.columns else None
                    if "t_k" in resj.columns:
                        temp_to = float(resj.at[tj, "t_k"]) - 273.15
        except Exception:
            pass
        
        pipe_metadata[pipe_idx] = {
            "name": name,
            "length_m": length_m,
            "diameter_m": diameter_m,
            "flow_kg_s": flow_kg_s,
            "pressure_from": pressure_from,
            "pressure_to": pressure_to,
            "temp_from": temp_from,
            "temp_to": temp_to,
        }

        if name.startswith("service_S_") or name.startswith("service_R_"):
            # Filter service pipes by length (will be filtered later in rendering)
            out["service"].append((line, pipe_idx))
        elif name.startswith("pipe_S_"):
            out["supply"].append((line, pipe_idx))
        elif name.startswith("pipe_R_"):
            out["return"].append((line, pipe_idx))
        elif name.startswith("hx_"):
            out["hx"].append((line, pipe_idx))
        else:
            out["other"].append((line, pipe_idx))

    return out, pipe_metadata


def _extract_service_lines_if_possible(net, max_length_m: float = 30.0) -> Tuple[List[LineString], Dict[str, Any]]:
    """
    Prefer service pipe geometry from pipe table + junction_geodata.
    Returns both geometries and metadata (building_id -> service pipe info).
    Filters out service pipes longer than max_length_m.
    """
    if not hasattr(net, "building_to_service_pipes"):
        return [], {}

    # Requires junction coords to be useful
    jgd = getattr(net, "junction_geodata", None)
    if jgd is None or len(jgd) == 0:
        return [], {}

    service_lines = []
    service_metadata = {}
    
    for b_id, pipes in getattr(net, "building_to_service_pipes", {}).items():
        service_metadata[b_id] = {"supply": {}, "return": {}}
        
        for key in ["supply", "return"]:
            pidx = pipes.get(key)
            if pidx is None or pidx not in net.pipe.index:
                continue
            row = net.pipe.loc[pidx]
            
            # Extract pipe details first to check length
            length_m = float(row.get("length_km", 0)) * 1000 if pd.notna(row.get("length_km")) else 0
            
            # Filter: skip if length exceeds maximum
            if length_m > max_length_m:
                continue
            
            a = _get_junction_xy(net, int(row["from_junction"]))
            b = _get_junction_xy(net, int(row["to_junction"]))
            if a and b:
                line = LineString([a, b])
                service_lines.append(line)
                
                diameter_m = float(row.get("diameter_m", 0)) if pd.notna(row.get("diameter_m")) else 0
                
                # Get flow and pressure from results if available
                flow_kg_s = None
                pressure_from = None
                pressure_to = None
                temp_from = None
                temp_to = None
                
                try:
                    resp = getattr(net, "res_pipe", None)
                    resj = getattr(net, "res_junction", None)
                    
                    if resp is not None and len(resp) > 0 and pidx in resp.index:
                        flow_kg_s = float(resp.at[pidx, "mdot_kg_per_s"]) if "mdot_kg_per_s" in resp.columns else None
                    
                    if resj is not None and len(resj) > 0:
                        fj = int(row["from_junction"])
                        tj = int(row["to_junction"])
                        if fj in resj.index:
                            pressure_from = float(resj.at[fj, "p_bar"]) if "p_bar" in resj.columns else None
                            if "t_k" in resj.columns:
                                temp_from = float(resj.at[fj, "t_k"]) - 273.15
                        if tj in resj.index:
                            pressure_to = float(resj.at[tj, "p_bar"]) if "p_bar" in resj.columns else None
                            if "t_k" in resj.columns:
                                temp_to = float(resj.at[tj, "t_k"]) - 273.15
                except Exception:
                    pass
                
                service_metadata[b_id][key] = {
                    "length_m": length_m,
                    "diameter_m": diameter_m,
                    "flow_kg_s": flow_kg_s,
                    "pressure_from": pressure_from,
                    "pressure_to": pressure_to,
                    "temp_from": temp_from,
                    "temp_to": temp_to,
                    "pipe_idx": pidx
                }

    return service_lines, service_metadata


# ---------------------------
# Temperature attachment (optional)
# ---------------------------


def _pipe_end_temperatures_c(net, pipe_idx: int, fallback_s: float, fallback_r: float) -> Tuple[float, float]:
    """
    Read endpoint temperatures from res_junction if available.
    If not, use reasonable fallbacks based on pipe name prefix.
    """
    name = str(net.pipe.at[pipe_idx, "name"]) if pipe_idx in net.pipe.index else ""

    is_supply = name.startswith("pipe_S_") or name.startswith("service_S_")
    is_return = name.startswith("pipe_R_") or name.startswith("service_R_") or name.startswith("hx_")

    t_default = fallback_s if is_supply else fallback_r if is_return else fallback_s

    try:
        resj = getattr(net, "res_junction", None)
        if resj is None or len(resj) == 0:
            return (t_default, t_default)

        fj = int(net.pipe.at[pipe_idx, "from_junction"])
        tj = int(net.pipe.at[pipe_idx, "to_junction"])

        # pandapipes typically stores t_k
        if "t_k" in resj.columns:
            t1 = float(resj.at[fj, "t_k"]) - 273.15
            t2 = float(resj.at[tj, "t_k"]) - 273.15
            return (t1, t2)

        # fallback column names
        for col in ["tfluid_k", "t"]:
            if col in resj.columns:
                t1 = float(resj.at[fj, col]) - 273.15
                t2 = float(resj.at[tj, col]) - 273.15
                return (t1, t2)

    except Exception:
        pass

    return (t_default, t_default)


def _add_gradient_polyline(
    fmap: folium.Map,
    line_wgs84: LineString,
    t_start: float,
    t_end: float,
    weight: int,
    base_color: str,
    segments: int = 10,
    layer: Optional[folium.FeatureGroup] = None,
):
    """
    Lightweight gradient approximation:
    - Splits the line into segments and interpolates temperature.
    - Uses a simple opacity ramp to suggest gradient without heavy colormap deps.
    """
    coords = list(line_wgs84.coords)
    if len(coords) < 2:
        return

    # Simple linear interpolation along the two-point line or polyline
    # We draw consecutive vertex pairs; within each pair we apply a mild opacity ramp.
    total_steps = max(segments, 2)

    # Build a densified list between first and last point for visual smoothness
    x1, y1 = coords[0]
    x2, y2 = coords[-1]
    densified = []
    for i in range(total_steps + 1):
        a = i / total_steps
        densified.append((x1 + a * (x2 - x1), y1 + a * (y2 - y1)))

    for i in range(total_steps):
        a = i / total_steps
        t_seg = t_start + a * (t_end - t_start)
        # Map temperature variation to opacity band (subtle)
        opacity = 0.35 + 0.55 * min(max((t_seg - min(t_start, t_end)) / (abs(t_end - t_start) + 1e-6), 0.0), 1.0)

        seg_line = LineString([densified[i], densified[i + 1]])
        poly = folium.PolyLine(
            locations=[(seg_line.coords[0][1], seg_line.coords[0][0]),
                       (seg_line.coords[1][1], seg_line.coords[1][0])],
            color=base_color,
            weight=weight,
            opacity=opacity,
            tooltip=f"T ≈ {t_seg:.1f} °C"
        )
        if layer is not None:
            poly.add_to(layer)
        else:
            poly.add_to(fmap)


# ---------------------------
# Main public function
# ---------------------------


def create_dh_interactive_map(
    cluster_id: str,
    cha_out_dir: str,
    *,
    buildings_gdf: Optional[gpd.GeoDataFrame] = None,
    streets_gdf: Optional[gpd.GeoDataFrame] = None,
    save_path: Optional[str] = None,
    options: Optional[DHMapOptions] = None,
) -> folium.Map:
    """
    Create an interactive DH map for a given cluster.

    Parameters
    ----------
    cluster_id:
        Cluster identifier (e.g., ST012_HEINRICH_ZILLE_STRAS)
    cha_out_dir:
        Output directory containing cha_net.pkl
    buildings_gdf:
        Optional pre-loaded buildings GeoDataFrame
    streets_gdf:
        Optional street GeoDataFrame for background context
    save_path:
        If provided, HTML file is written here
    options:
        Map styling/behavior options

    Returns
    -------
    folium.Map
    """
    options = options or DHMapOptions()

    net = _load_cha_net(cha_out_dir)

    # Load and filter buildings for this cluster
    buildings_cluster = _get_cluster_buildings(cluster_id, buildings_gdf)
    buildings_cluster_wgs = _ensure_wgs84(buildings_cluster)

    if buildings_cluster_wgs is None or len(buildings_cluster_wgs) == 0:
        raise ValueError(f"No buildings found for cluster {cluster_id} for mapping.")

    # Map center
    cent = buildings_cluster_wgs.geometry.unary_union.centroid
    m = folium.Map(
        location=[cent.y, cent.x],
        zoom_start=options.zoom_start,
        tiles=options.tiles,
        control_scale=True,
    )

    # Layers
    street_group = folium.FeatureGroup(name="Street Network", overlay=True, show=options.show_streets)
    supply_group = folium.FeatureGroup(name="Supply Pipes", overlay=True, show=True)
    return_group = folium.FeatureGroup(name="Return Pipes", overlay=True, show=True)
    service_group = folium.FeatureGroup(name="Service Pipes", overlay=True, show=options.show_service_pipes)
    buildings_group = folium.FeatureGroup(name="Buildings", overlay=True, show=True)
    plant_group = folium.FeatureGroup(name="Plant", overlay=True, show=True)

    # Streets (optional)
    if streets_gdf is not None and len(streets_gdf) > 0:
        streets_wgs = _ensure_wgs84(streets_gdf)
        for _, row in streets_wgs.iterrows():
            geom = row.geometry
            if geom is None:
                continue
            try:
                coords = list(geom.coords)
                folium.PolyLine(
                    locations=[(y, x) for x, y in coords],
                    color=options.street_color,
                    weight=options.street_weight,
                    opacity=0.6
                ).add_to(street_group)
            except Exception:
                continue

    # Pipes
    trunk_by_edge = _extract_trunk_lines_from_edge_map(net)

    if trunk_by_edge["supply"] or trunk_by_edge["return"]:
        # We can render trunk accurately from graph nodes
        # Convert to WGS84 using a GeoDataFrame conversion
        for kind, lines in trunk_by_edge.items():
            if not lines:
                continue
            gdf = gpd.GeoDataFrame({"geometry": lines}, crs="EPSG:32633")
            gdf = _ensure_wgs84(gdf)

            for idx, geom in enumerate(gdf.geometry):
                coords = list(geom.coords)
                base_color = options.supply_color if kind == "supply" else options.return_color
                weight = options.trunk_weight

                # If we can map to a pipe idx, attach temps; else basic line
                pipe_idx = None
                try:
                    # Try to locate matching pipe idx via edge_to_pipe_idx
                    # Edge map keys are (edge, kind) where edge is 2-node tuple in EPSG:32633
                    # We reconstruct a rough lookup by scanning; safe for small clusters.
                    edge_map = getattr(net, "edge_to_pipe_idx", {})
                    # Note: This loop is intentionally small. If performance becomes an issue,
                    # build an inverted index once.
                    # We cannot reliably match here without original edge coords, so we skip.
                    pipe_idx = None
                except Exception:
                    pipe_idx = None

                if options.show_temperature and pipe_idx is not None:
                    t1, t2 = _pipe_end_temperatures_c(net, pipe_idx, options.fallback_supply_c, options.fallback_return_c)
                    _add_gradient_polyline(
                        m, geom, t1, t2, weight=weight, base_color=base_color,
                        layer=supply_group if kind == "supply" else return_group
                    )
                else:
                    folium.PolyLine(
                        locations=[(y, x) for x, y in coords],
                        color=base_color,
                        weight=weight,
                        opacity=0.9
                    ).add_to(supply_group if kind == "supply" else return_group)
    else:
        # Fallback to pipe-table geometry if junction coords exist
        pipe_lines, pipe_metadata = _extract_pipe_lines_from_tables(net)

        def _draw_lines(lines_with_idx: List[Tuple[LineString, int]], group: folium.FeatureGroup, color: str, weight: int, pipe_type: str, max_service_length: Optional[float] = None):
            if not lines_with_idx:
                return
            geometries = [line for line, _ in lines_with_idx]
            gdf = gpd.GeoDataFrame({"geometry": geometries}, crs="EPSG:32633")
            gdf = _ensure_wgs84(gdf)
            for (geom, pipe_idx), (_, orig_idx) in zip(gdf.geometry.items(), lines_with_idx):
                coords = list(geom.coords)
                meta = pipe_metadata.get(orig_idx, {})
                
                # Filter service pipes by length
                if pipe_type == "Service" and max_service_length is not None:
                    if meta.get("length_m", 0) > max_service_length:
                        continue
                
                # Create detailed tooltip
                tooltip_parts = [f"<b>{pipe_type.title()} Pipe</b>"]
                if meta.get("name"):
                    tooltip_parts.append(f"Name: {meta['name']}")
                if meta.get("length_m"):
                    tooltip_parts.append(f"Length: {meta['length_m']:.1f} m")
                if meta.get("diameter_m"):
                    tooltip_parts.append(f"Diameter: {meta['diameter_m']*1000:.0f} mm")
                if meta.get("flow_kg_s") is not None:
                    tooltip_parts.append(f"Flow: {meta['flow_kg_s']:.3f} kg/s")
                if meta.get("pressure_from") is not None:
                    tooltip_parts.append(f"Pressure (from): {meta['pressure_from']:.2f} bar")
                if meta.get("pressure_to") is not None:
                    tooltip_parts.append(f"Pressure (to): {meta['pressure_to']:.2f} bar")
                if meta.get("temp_from") is not None:
                    tooltip_parts.append(f"Temperature (from): {meta['temp_from']:.1f} °C")
                if meta.get("temp_to") is not None:
                    tooltip_parts.append(f"Temperature (to): {meta['temp_to']:.1f} °C")
                
                tooltip = "<br>".join(tooltip_parts)
                
                folium.PolyLine(
                    locations=[(y, x) for x, y in coords],
                    color=color,
                    weight=weight,
                    opacity=0.9,
                    tooltip=tooltip
                ).add_to(group)

        _draw_lines(pipe_lines.get("supply", []), supply_group, options.supply_color, options.trunk_weight, "Supply")
        _draw_lines(pipe_lines.get("return", []), return_group, options.return_color, options.trunk_weight, "Return")
        _draw_lines(pipe_lines.get("service", []), service_group, options.service_color, options.service_weight, "Service", max_service_length=options.max_service_length_m)

    # Service pipes (best-effort enhancement)
    service_metadata = {}
    if options.show_service_pipes:
        svc_lines, service_metadata = _extract_service_lines_if_possible(net, max_length_m=options.max_service_length_m)
        if svc_lines:
            svc_gdf = gpd.GeoDataFrame({"geometry": svc_lines}, crs="EPSG:32633")
            svc_gdf = _ensure_wgs84(svc_gdf)
            for idx, geom in enumerate(svc_gdf.geometry):
                coords = list(geom.coords)
                
                # Create tooltip from metadata (if available)
                tooltip = "Service Pipe"
                # Note: We can't easily match individual service lines to buildings here
                # The metadata is keyed by building_id, not by line index
                
                folium.PolyLine(
                    locations=[(y, x) for x, y in coords],
                    color=options.service_color,
                    weight=options.service_weight,
                    opacity=0.8,
                    tooltip=tooltip
                ).add_to(service_group)

    # Buildings
    # Try to show an informative tooltip with common columns if present
    tip_cols = [c for c in [
        "building_id", "use_type", "construction_period",
        "renovation_state", "floor_area_m2", "baseline_heat_demand_kwh_a"
    ] if c in buildings_cluster_wgs.columns]

    for _, row in buildings_cluster_wgs.iterrows():
        geom = row.geometry
        if geom is None:
            continue
        pt = geom.centroid if geom.geom_type != "Point" else geom
        
        # Build tooltip with building info
        tooltip_parts = []
        for c in tip_cols:
            val = row.get(c, None)
            if pd.notna(val):
                # Format specific columns nicely
                if c == "floor_area_m2":
                    tooltip_parts.append(f"Floor Area: {val:.1f} m²")
                elif c == "baseline_heat_demand_kwh_a":
                    tooltip_parts.append(f"Heat Demand: {val:.0f} kWh/a")
                else:
                    tooltip_parts.append(f"{c.replace('_', ' ').title()}: {val}")
        
        # Add service pipe information if available (only if length <= max_service_length_m)
        building_id = row.get("building_id", None)
        if building_id and building_id in service_metadata:
            svc_info = service_metadata[building_id]
            tooltip_parts.append("<br><b>Service Pipes:</b>")
            
            for pipe_type in ["supply", "return"]:
                if pipe_type in svc_info and svc_info[pipe_type]:
                    info = svc_info[pipe_type]
                    length_m = info.get("length_m", 0)
                    
                    # Filter: only show if length <= max_service_length_m
                    if length_m > options.max_service_length_m:
                        continue
                    
                    pipe_parts = [f"<b>{pipe_type.title()}:</b>"]
                    if length_m:
                        pipe_parts.append(f"Length: {length_m:.1f} m")
                    if info.get("diameter_m"):
                        pipe_parts.append(f"Diameter: {info['diameter_m']*1000:.0f} mm")
                    if info.get("flow_kg_s") is not None:
                        pipe_parts.append(f"Flow: {info['flow_kg_s']:.3f} kg/s")
                    if info.get("pressure_from") is not None:
                        pipe_parts.append(f"Pressure: {info['pressure_from']:.2f} bar")
                    if info.get("temp_from") is not None:
                        pipe_parts.append(f"Temperature: {info['temp_from']:.1f} °C")
                    tooltip_parts.append(" | ".join(pipe_parts))
        
        # Add service length from buildings dataframe if available (only if <= max_service_length_m)
        if "service_length_m" in row and pd.notna(row["service_length_m"]):
            service_length = row["service_length_m"]
            if service_length <= options.max_service_length_m:
                tooltip_parts.append(f"<b>Service Length:</b> {service_length:.1f} m")
        
        tooltip = "<br>".join(tooltip_parts) if tooltip_parts else "Building"

        folium.CircleMarker(
            location=[pt.y, pt.x],
            radius=3,
            weight=1,
            opacity=0.9,
            fill=True,
            fill_opacity=0.7,
            tooltip=tooltip
        ).add_to(buildings_group)

    # Plant marker (best-effort location)
    plant_point = None
    try:
        # If your plant junction has a geodata entry, use it
        # With edge-based trunk mapping, plant is typically embedded in trunk nodes.
        # To keep this robust, we approximate plant position as cluster centroid.
        plant_point = Point(cent.x, cent.y)
    except Exception:
        plant_point = Point(cent.x, cent.y)

    folium.Marker(
        location=[plant_point.y, plant_point.x],
        tooltip="District Heating Plant (approx.)",
        icon=folium.Icon(icon="fire", prefix="fa")
    ).add_to(plant_group)

    # Add groups
    if streets_gdf is not None and len(streets_gdf) > 0:
        street_group.add_to(m)
    supply_group.add_to(m)
    return_group.add_to(m)
    if options.show_service_pipes:
        service_group.add_to(m)
    buildings_group.add_to(m)
    plant_group.add_to(m)

    folium.LayerControl().add_to(m)

    if save_path:
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        m.save(save_path)
        logger.info(f"DH interactive map saved to {save_path}")

    return m

