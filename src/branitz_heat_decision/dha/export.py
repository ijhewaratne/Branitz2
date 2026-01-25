from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional, Set, Tuple

import numpy as np
import pandas as pd

try:
    import folium
    from branca.colormap import LinearColormap
except Exception:
    folium = None


def export_dha_outputs(
    net,
    results_by_hour: Dict[int, Dict[str, object]],
    kpis: Dict[str, object],
    violations_df: pd.DataFrame,
    output_dir: Path,
    *,
    title: str = "HP LV Grid Hosting",
    geodata_crs: str = "EPSG:25833",
    focus_bus_ids: Optional[Set[int]] = None,
) -> Dict[str, Path]:
    """
    Export:
      - dha_kpis.json
      - network.pickle
      - buses_results.geojson / lines_results.geojson (worst-case across hours)
      - violations.csv
      - hp_lv_map.html (folium)
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Determine worst-case hour (prioritize: worst voltage, then max loading, else first)
    hours = sorted(results_by_hour.keys())
    worst_hour = None
    worst_vmin = float("inf")
    worst_loading = 0.0
    for h in hours:
        r = results_by_hour[h]
        if not r.get("converged"):
            continue
        bdf = r.get("bus_results")
        if isinstance(bdf, pd.DataFrame) and not bdf.empty and "v_min_pu" in bdf.columns:
            v = float(pd.to_numeric(bdf["v_min_pu"], errors="coerce").min())
            if np.isfinite(v) and v < worst_vmin:
                worst_vmin = v
                worst_hour = h
        ldf = r.get("line_results")
        if isinstance(ldf, pd.DataFrame) and not ldf.empty:
            col = "loading_percent" if "loading_percent" in ldf.columns else "loading_pct" if "loading_pct" in ldf.columns else None
            if col:
                m = float(pd.to_numeric(ldf[col], errors="coerce").max())
                if np.isfinite(m) and m > worst_loading:
                    worst_loading = m
                    if worst_hour is None:
                        worst_hour = h
    if worst_hour is None:
        worst_hour = hours[0]

    # Optional focus: restrict exported GeoJSON/map to the sub-network that is relevant
    # for the selected cluster (buses that receive loads and the lines connecting them).
    focus = set(int(b) for b in focus_bus_ids) if focus_bus_ids else None
    if focus:
        focus_buses, focus_lines = _compute_focus_subgraph(net, focus)
    else:
        focus_buses, focus_lines = None, None

    buses_geojson = _buses_geojson(
        net,
        results_by_hour[worst_hour].get("bus_results"),
        worst_hour,
        geodata_crs=geodata_crs,
        focus_buses=focus_buses,
    )
    lines_geojson = _lines_geojson(
        net,
        results_by_hour[worst_hour].get("line_results"),
        worst_hour,
        geodata_crs=geodata_crs,
        focus_lines=focus_lines,
    )

    buses_path = output_dir / "buses_results.geojson"
    lines_path = output_dir / "lines_results.geojson"
    buses_path.write_text(json.dumps(buses_geojson), encoding="utf-8")
    lines_path.write_text(json.dumps(lines_geojson), encoding="utf-8")

    viol_path = output_dir / "violations.csv"
    violations_df.to_csv(viol_path, index=False)

    kpis_path = output_dir / "dha_kpis.json"
    # Write kpis directly (it already contains all fields including mitigations)
    # Add worst_hour for backward compatibility
    kpis_with_context = {**kpis, "worst_hour": int(worst_hour)}
    kpis_path.write_text(json.dumps(kpis_with_context, indent=2), encoding="utf-8")

    # network pickle
    import pickle

    net_path = output_dir / "network.pickle"
    with open(net_path, "wb") as f:
        pickle.dump(net, f)

    map_path = output_dir / "hp_lv_map.html"
    if folium is not None:
        _create_map(map_path, buses_geojson, lines_geojson, title=title)

    return {
        "kpis": kpis_path,
        "network": net_path,
        "buses_geojson": buses_path,
        "lines_geojson": lines_path,
        "violations": viol_path,
        "map": map_path,
    }


def _buses_geojson(
    net,
    bus_df: Optional[pd.DataFrame],
    hour: int,
    *,
    geodata_crs: str,
    focus_buses: Optional[Set[int]] = None,
) -> Dict:
    feats = []
    if not hasattr(net, "bus_geodata") or net.bus_geodata is None or net.bus_geodata.empty:
        return {"type": "FeatureCollection", "features": []}

    to_wgs84 = _make_transformer_to_wgs84(geodata_crs)
    for b_idx, geo in net.bus_geodata.iterrows():
        if focus_buses is not None and int(b_idx) not in focus_buses:
            continue
        x = float(geo["x"])
        y = float(geo["y"])
        # skip MV bus if at origin (common placeholder) or vn_kv > 1
        try:
            if float(net.bus.loc[b_idx, "vn_kv"]) > 1.0:
                continue
        except Exception:
            pass
        lon, lat = to_wgs84(x, y)
        props = {"bus": int(b_idx), "hour": int(hour)}
        if isinstance(bus_df, pd.DataFrame) and (b_idx in bus_df.index):
            row = bus_df.loc[b_idx]
            for k in ("vm_pu", "vm_a_pu", "vm_b_pu", "vm_c_pu", "v_min_pu"):
                if k in row.index:
                    try:
                        props[k] = float(row[k])
                    except Exception:
                        pass
        feats.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": props,
            }
        )
    return {"type": "FeatureCollection", "features": feats}


def _lines_geojson(
    net,
    line_df: Optional[pd.DataFrame],
    hour: int,
    *,
    geodata_crs: str,
    focus_lines: Optional[Set[int]] = None,
) -> Dict:
    feats = []
    if not hasattr(net, "bus_geodata") or net.bus_geodata is None or net.bus_geodata.empty:
        return {"type": "FeatureCollection", "features": []}
    if not hasattr(net, "line") or net.line is None or net.line.empty:
        return {"type": "FeatureCollection", "features": []}

    to_wgs84 = _make_transformer_to_wgs84(geodata_crs)
    for li, line in net.line.iterrows():
        if focus_lines is not None and int(li) not in focus_lines:
            continue
        fb = int(line["from_bus"])
        tb = int(line["to_bus"])
        if fb not in net.bus_geodata.index or tb not in net.bus_geodata.index:
            continue
        x1, y1 = float(net.bus_geodata.loc[fb, "x"]), float(net.bus_geodata.loc[fb, "y"])
        x2, y2 = float(net.bus_geodata.loc[tb, "x"]), float(net.bus_geodata.loc[tb, "y"])
        lon1, lat1 = to_wgs84(x1, y1)
        lon2, lat2 = to_wgs84(x2, y2)
        props = {"line": int(li), "name": str(line.get("name", "")), "hour": int(hour)}
        if isinstance(line_df, pd.DataFrame) and (li in line_df.index):
            row = line_df.loc[li]
            for k in ("loading_percent", "i_ka", "p_from_mw", "p_to_mw"):
                if k in row.index:
                    try:
                        props[k] = float(row[k])
                    except Exception:
                        pass
            if "loading_percent" not in props and "loading_pct" in row.index:
                try:
                    props["loading_percent"] = float(row["loading_pct"])
                except Exception:
                    pass
        # Ensure required fields exist for map tooltips even if results table doesn't provide them
        if "loading_percent" not in props:
            props["loading_percent"] = 0.0
        feats.append(
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[lon1, lat1], [lon2, lat2]]},
                "properties": props,
            }
        )
    return {"type": "FeatureCollection", "features": feats}


def _make_transformer_to_wgs84(geodata_crs: str):
    """
    Return a function (x,y)->(lon,lat) transforming from geodata_crs to EPSG:4326.
    If geodata_crs already looks like WGS84, returns identity.
    """
    crs = (geodata_crs or "").upper()
    if crs.endswith("4326") or "WGS84" in crs:
        return lambda x, y: (float(x), float(y))
    try:
        import pyproj

        tr = pyproj.Transformer.from_crs(geodata_crs, "EPSG:4326", always_xy=True)
        return lambda x, y: tr.transform(float(x), float(y))
    except Exception:
        # Best-effort fallback (assume already lon/lat)
        return lambda x, y: (float(x), float(y))


def _compute_focus_subgraph(net, focus_bus_ids: Set[int]) -> Tuple[Optional[Set[int]], Optional[Set[int]]]:
    """
    Compute a focused subgraph of the LV network to show on the map:
    - include all focus buses (where loads are attached)
    - include all transformer LV buses
    - include all buses/lines on shortest paths between each focus bus and the nearest transformer LV bus
    """
    try:
        import networkx as nx
    except Exception:
        # If networkx is missing, fall back to just showing focus buses and incident lines
        focus_lines = set()
        for li, line in net.line.iterrows():
            fb = int(line["from_bus"])
            tb = int(line["to_bus"])
            if fb in focus_bus_ids or tb in focus_bus_ids:
                focus_lines.add(int(li))
        return set(focus_bus_ids), focus_lines

    if not hasattr(net, "line") or net.line is None or net.line.empty:
        return set(focus_bus_ids), set()

    # Build LV graph
    G = nx.Graph()
    for li, line in net.line.iterrows():
        fb = int(line["from_bus"])
        tb = int(line["to_bus"])
        w = float(line.get("length_km", 0.001))
        G.add_edge(fb, tb, weight=w, line_id=int(li))

    trafo_lv_buses = set()
    if hasattr(net, "trafo") and net.trafo is not None and not net.trafo.empty:
        trafo_lv_buses = set(net.trafo["lv_bus"].astype(int).tolist())

    focus_buses = set(int(b) for b in focus_bus_ids)
    focus_lines: Set[int] = set()

    # For each focus bus, connect to nearest LV trafo bus (by shortest path length)
    targets = [b for b in trafo_lv_buses if b in G]
    if not targets:
        # no trafo nodes in graph; just include incident lines
        for li, line in net.line.iterrows():
            fb = int(line["from_bus"])
            tb = int(line["to_bus"])
            if fb in focus_buses or tb in focus_buses:
                focus_lines.add(int(li))
                focus_buses.add(fb)
                focus_buses.add(tb)
        return focus_buses, focus_lines

    for b in list(focus_bus_ids):
        if b not in G:
            continue
        # Pick nearest transformer bus
        best_t = None
        best_d = float("inf")
        for t in targets:
            try:
                d = nx.shortest_path_length(G, b, t, weight="weight")
            except Exception:
                continue
            if d < best_d:
                best_d = float(d)
                best_t = t
        if best_t is None:
            continue
        try:
            path = nx.shortest_path(G, b, best_t, weight="weight")
        except Exception:
            continue
        for u, v in zip(path[:-1], path[1:]):
            focus_buses.add(int(u))
            focus_buses.add(int(v))
            data = G.get_edge_data(u, v) or {}
            lid = data.get("line_id")
            if lid is not None:
                focus_lines.add(int(lid))

    # Also include transformer LV buses themselves
    focus_buses |= set(int(x) for x in trafo_lv_buses)
    return focus_buses, focus_lines


def _create_map(out_html: Path, buses_geojson: Dict, lines_geojson: Dict, *, title: str) -> None:
    # Center on first bus
    coords = [f["geometry"]["coordinates"] for f in buses_geojson.get("features", [])]
    if not coords:
        return
    lon0, lat0 = coords[0]
    m = folium.Map(location=[lat0, lon0], zoom_start=16, tiles="OpenStreetMap")
    m.get_root().html.add_child(folium.Element(f"<h3 align='center'><b>{title}</b></h3>"))

    # Line colormap by loading
    col = LinearColormap(["#2ECC71", "#F1C40F", "#E67E22", "#E74C3C"], vmin=0, vmax=120, index=[0, 50, 100, 120])

    def style_line(feat):
        v = feat["properties"].get("loading_percent", 0.0)
        try:
            v = float(v)
        except Exception:
            v = 0.0
        if not np.isfinite(v):
            v = 0.0
        return {"color": col(v), "weight": 5, "opacity": 0.9}

    folium.GeoJson(
        lines_geojson,
        name="LV Lines (Loading %)",
        style_function=style_line,
        tooltip=folium.GeoJsonTooltip(fields=["name", "loading_percent", "hour"], aliases=["Line", "Loading %", "Hour"]),
    ).add_to(m)

    def bus_color(v):
        try:
            v = float(v)
        except Exception:
            return "#999999"
        if v < 0.90:
            return "#E74C3C"
        if v < 0.95:
            return "#E67E22"
        if v < 1.00:
            return "#F1C40F"
        return "#2ECC71"

    for f in buses_geojson.get("features", []):
        lon, lat = f["geometry"]["coordinates"]
        v = f["properties"].get("v_min_pu", f["properties"].get("vm_pu", None))
        folium.CircleMarker(
            location=[lat, lon],
            radius=6,
            fill=True,
            fill_opacity=0.9,
            color="#333",
            fill_color=bus_color(v),
            tooltip=f"Bus {f['properties'].get('bus')} — Vmin: {v}",
        ).add_to(m)

    legend_html = """
    <div style="position: fixed;
                bottom: 50px; left: 50px; width: 210px; height: 140px;
                background-color: white; border:2px solid grey; z-index:9999;
                font-size:12px; padding: 10px">
      <h4>Voltage Legend</h4>
      <p><span style="color:#2ECC71">●</span> Good (≥1.00 pu)</p>
      <p><span style="color:#F1C40F">●</span> Caution (0.95–1.00 pu)</p>
      <p><span style="color:#E67E22">●</span> Warning (0.90–0.95 pu)</p>
      <p><span style="color:#E74C3C">●</span> Critical (&lt;0.90 pu)</p>
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))
    col.caption = "Line loading (%)"
    col.add_to(m)

    folium.LayerControl().add_to(m)
    m.save(str(out_html))

