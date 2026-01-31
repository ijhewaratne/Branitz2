#!/usr/bin/env python3
"""
Street-level LV grid feasibility for Heat Pumps (HPs) using pandapower (3-phase) + OSM inputs.

Inputs (put these in ./data/):
- branitzer_siedlung_ns_v3_ohne_UW.json   (nodes & ways for LV grid; from your repo)
- gebaeude_lastphasenV2.json              (per-building base electrical loads per scenario)
Optional:
- output_branitzer_siedlungV11.json       (building coords; preferred if available)
- branitzer_siedlung.osm                  (fallback to extract building centroids)

Outputs:
- results/lines_results.geojson           (LV segments with loading, voltage drop proxy)
- results/buses_results.geojson           (LV buses with per-phase voltages and min pu)
- maps/street_hp_lv_map.html              (interactive Folium map with color gradients)
"""

import json, math, os, sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional

# Optional deps
try:
    import pandas as pd  # only used if present
except Exception:
    pd = None

# Required deps
try:
    import pandapower as pp
    # pandapower 3.x has runpp_3ph directly in main module
    pp3 = pp  # alias for compatibility
except Exception:
    print("[ERROR] pandapower is required. Install with: pip install pandapower")
    sys.exit(1)

# Optional for mapping
try:
    import folium
    from branca.colormap import LinearColormap
except Exception:
    folium = None

# Optional geometry parsing
try:
    import shapely.geometry as geom
    from shapely.geometry import Point, Polygon
except Exception:
    geom = None

import xml.etree.ElementTree as ET

ROOT = Path(".")
DATA_NODES_WAYS = ROOT / "data" / "branitzer_siedlung_ns_v3_ohne_UW.json"
DATA_LOADS = ROOT / "data" / "gebaeude_lastphasenV2.json"
DATA_BUILDINGS = ROOT / "data" / "output_branitzer_siedlungV11.json"  # optional
DATA_OSM = ROOT / "data" / "branitzer_siedlung.osm"                   # optional

OUT_DIR = ROOT / "results"; OUT_DIR.mkdir(exist_ok=True)
MAP_DIR = ROOT / "maps"; MAP_DIR.mkdir(exist_ok=True)


# --------------------------- helpers ---------------------------

def haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000.0
    t1, t2 = math.radians(lat1), math.radians(lat2)
    dlat = t2 - t1
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(t1)*math.cos(t2)*math.sin(dlon/2)**2
    return 2*R*math.asin(math.sqrt(a))

def load_nodes_ways(path: Path):
    with path.open("r", encoding="utf-8") as f:
        j = json.load(f)
    nodes = j["nodes"]  # list of {lon,lat,id,tags}
    ways = j["ways"]    # list of {id,nodes[],tags{power},length_km}
    id_to_node = {n["id"]: n for n in nodes}
    return id_to_node, ways

def parse_buildings_from_json(path: Path):
    """
    Read building coordinates from a variety of JSON shapes, e.g.:
      {"buildings":[{"id":"DEB...","lat":51.7,"lon":14.4}, ...]}
      {"DEB...":{"lat":51.7,"lon":14.4}, ...}
      {"features":[{"properties":{"id":"DEB..."}, "geometry":{"type":"Point","coordinates":[lon,lat]}}, ...]}
      {"DEB...":{"Gebaeudeteile":[{"Koordinaten":[{"latitude":51.7,"longitude":14.4}, ...]}]}}
    """
    def find_lat_lon(obj):
        # returns (lat, lon) or None
        if not isinstance(obj, dict):
            return None
        # direct keys (case-insensitive)
        keys = {k.lower(): k for k in obj.keys()}
        latk = next((keys[k] for k in keys if k in ("lat","latitude","y","y_wgs84","lat_wgs84")), None)
        lonk = next((keys[k] for k in keys if k in ("lon","lng","longitude","x","x_wgs84","lon_wgs84")), None)
        if latk and lonk:
            try:
                return float(obj[latk]), float(obj[lonk])
            except Exception:
                pass
        # GeoJSON-like
        if "geometry" in obj and isinstance(obj["geometry"], dict):
            g = obj["geometry"]
            if g.get("type") == "Point" and isinstance(g.get("coordinates"), (list, tuple)) and len(g["coordinates"])>=2:
                lon, lat = g["coordinates"][:2]
                return float(lat), float(lon)
        return None

    def find_id(obj):
        if not isinstance(obj, dict):
            return None
        for k in ("id","building_id","osm_id","ID","Id","GebaeudeID"):
            if k in obj:
                return str(obj[k])
        return None

    def get_building_centroid(building_data):
        """Extract centroid from German building data structure"""
        if not isinstance(building_data, dict):
            return None
        
        # Check for Gebaeudeteile structure (German building data)
        if "Gebaeudeteile" in building_data:
            gebaeudeteile = building_data["Gebaeudeteile"]
            if isinstance(gebaeudeteile, list) and len(gebaeudeteile) > 0:
                # Get first building part
                first_part = gebaeudeteile[0]
                if "Koordinaten" in first_part:
                    koordinaten = first_part["Koordinaten"]
                    if isinstance(koordinaten, list) and len(koordinaten) > 0:
                        # Calculate centroid from all coordinates
                        lats = [float(coord.get("latitude", 0)) for coord in koordinaten if "latitude" in coord]
                        lons = [float(coord.get("longitude", 0)) for coord in koordinaten if "longitude" in coord]
                        if lats and lons:
                            return sum(lats)/len(lats), sum(lons)/len(lons)
        return None

    try:
        import json
        J = json.load(open(path,"r",encoding="utf-8"))
    except Exception:
        return []

    out = []

    # 1) Common: {"buildings":[ ... ]}
    if isinstance(J, dict) and isinstance(J.get("buildings"), list):
        for rec in J["buildings"]:
            latlon = find_lat_lon(rec)
            bid = find_id(rec)
            if latlon and bid:
                lat, lon = latlon
                out.append({"id": bid, "lat": lat, "lon": lon})
        if out:
            return out

    # 2) GeoJSON-like: {"features":[ ... ]}
    if isinstance(J, dict) and isinstance(J.get("features"), list):
        for feat in J["features"]:
            props = feat.get("properties", {})
            bid = find_id(props) or find_id(feat)
            latlon = find_lat_lon(feat) or find_lat_lon(props)
            if latlon and bid:
                lat, lon = latlon
                out.append({"id": bid, "lat": lat, "lon": lon})
        if out:
            return out

    # 3) Dict-of-dicts keyed by building id (including German building data)
    if isinstance(J, dict):
        for k,v in J.items():
            # Try standard lat/lon first
            latlon = find_lat_lon(v)
            if not latlon:
                # Try German building structure
                latlon = get_building_centroid(v)
            
            bid = find_id(v) or str(k)
            if latlon:
                lat, lon = latlon
                out.append({"id": bid, "lat": lat, "lon": lon})
        if out:
            return out

    return out

def parse_buildings_from_osm(osm_path: Path, bbox: Optional[Tuple[float,float,float,float]]=None):
    """Fallback: parse building polygons from OSM and use centroids."""
    if not osm_path.exists():
        return []
    tree = ET.parse(str(osm_path))
    root = tree.getroot()

    node_coords = {}
    for n in root.findall("node"):
        nid = int(n.attrib["id"])
        lat = float(n.attrib["lat"]); lon = float(n.attrib["lon"])
        node_coords[nid] = (lat, lon)

    def in_bbox(lat, lon):
        if bbox is None: return True
        minlat, minlon, maxlat, maxlon = bbox
        return (minlat <= lat <= maxlat) and (minlon <= lon <= maxlon)

    buildings = []
    for w in root.findall("way"):
        tags = {t.attrib["k"]: t.attrib["v"] for t in w.findall("tag")}
        if tags.get("building"):
            nds = [int(nd.attrib["ref"]) for nd in w.findall("nd")]
            coords = [(node_coords[nid][0], node_coords[nid][1]) for nid in nds if nid in node_coords]  # (lat,lon)
            if len(coords) >= 3:
                if geom:
                    poly = Polygon([(lon, lat) for lat, lon in coords])
                    if not poly.is_valid: poly = poly.buffer(0)
                    c = poly.centroid
                    if in_bbox(c.y, c.x):
                        buildings.append({"id": str(w.attrib["id"]), "lat": c.y, "lon": c.x})
                else:
                    lats = [lat for lat, lon in coords]; lons = [lon for lat, lon in coords]
                    clat = sum(lats)/len(lats); clon = sum(lons)/len(lons)
                    if in_bbox(clat, clon):
                        buildings.append({"id": str(w.attrib["id"]), "lat": clat, "lon": clon})
    return buildings

def nearest_node_id(id_to_node: Dict[int,dict], lat: float, lon: float):
    best = None; best_d = 1e18
    for nid, nd in id_to_node.items():
        d = haversine_m(lat, lon, nd["lat"], nd["lon"])
        if d < best_d:
            best_d = d; best = nid
    return best, best_d

def build_lv_net(id_to_node: Dict[int,dict], ways: List[dict], buildings: List[dict], vn_kv=0.4):
    net = pp.create_empty_network()
    # Create buses with geodata
    nodeid_to_bus = {}
    for nid, nd in id_to_node.items():
        nodeid_to_bus[nid] = pp.create_bus(net, vn_kv=vn_kv, geodata=(nd["lon"], nd["lat"]), name=f"n{nid}")

    # Single MV bus + MV/LV transformer (placeholder params; adjust to your DSO)
    # NOTE: These are synthetic values for demonstration. Replace with your DSO's actual data
    # for accurate unbalance and short-circuit calculations.
    b_mv = pp.create_bus(net, vn_kv=20.0, name="MV")
    pp.create_ext_grid(net, bus=b_mv, vm_pu=1.02, name="MV Slack", 
                      s_sc_max_mva=1000.0, s_sc_min_mva=1000.0, 
                      rx_max=0.1, rx_min=0.1,
                      x0x_max=1.0, x0x_min=1.0,
                      r0x0_max=0.1, r0x0_min=0.1)
    
    # Choose LV bus closest to building cluster centroid for transformer
    if buildings:
        # centroid of building points
        clat = sum(b["lat"] for b in buildings)/len(buildings)
        clon = sum(b["lon"] for b in buildings)/len(buildings)
        # nearest LV node to centroid
        nid_ref, _ = nearest_node_id(id_to_node, clat, clon)
        b_lv_ref = nodeid_to_bus.get(nid_ref, list(nodeid_to_bus.values())[0])
    else:
        b_lv_ref = list(nodeid_to_bus.values())[0]
    
    # NOTE: Transformer parameters are placeholders. Replace with your DSO's standard types
    # for accurate unbalance and short-circuit calculations.
    pp.create_transformer_from_parameters(
        net, hv_bus=b_mv, lv_bus=b_lv_ref,
        sn_mva=0.63, vn_hv_kv=20.0, vn_lv_kv=0.4,
        vk_percent=6.0, vkr_percent=0.5,
        pfe_kw=1.0, i0_percent=0.1, 
        vector_group="Dyn",  # Supported by pandapower 3-phase (Dyn5 not supported)
        vk0_percent=6.0, vkr0_percent=0.5, mag0_percent=100, mag0_rx=0, si0_hv_partial=0.9, name="T1"
    )

    # Lines from ways: split each way into segments between consecutive nodes
    for w in ways:
        tags = w.get("tags", {})
        if tags.get("power") not in {"line","cable","minor_line"}:
            continue
        nseq = w["nodes"]
        for u, v in zip(nseq, nseq[1:]):
            if u not in id_to_node or v not in id_to_node or \
               u not in nodeid_to_bus or v not in nodeid_to_bus:
                continue
            nu, nv = id_to_node[u], id_to_node[v]
            seg_len_km = haversine_m(nu["lat"], nu["lon"], nv["lat"], nv["lon"]) / 1000.0
            # Generic LV cable (Cu 4x150 mm²). Replace with your std-types for accuracy.
            pp.create_line_from_parameters(
                net, nodeid_to_bus[u], nodeid_to_bus[v], length_km=seg_len_km,
                r_ohm_per_km=0.206, x_ohm_per_km=0.080, c_nf_per_km=210, max_i_ka=0.27,
                r0_ohm_per_km=0.206, x0_ohm_per_km=0.080, c0_nf_per_km=210,
                name=f"w{w['id']}_{u}-{v}"
            )
    return net, nodeid_to_bus


# --------------------------- main ---------------------------

def main(selected_scenario="winter_werktag_abendspitze",
         selected_street_name: Optional[str]=None,
         load_unit: Optional[str]=None,  # None for auto-detect, "MW" or "kW" to override
         hp_add_kw_th: float = 6.0, # thermal kW per building (example)
         hp_cop: float = 2.8,       # worst-case COP
         hp_three_phase: bool = True,
         limit_to_bbox: Optional[Tuple[float,float,float,float]] = None,
         v_min_limit_pu: float = 0.90,  # undervoltage threshold for violations.csv
         line_loading_limit_pct: float = 100.0):  # line overload threshold for violations.csv
    """
    selected_street_name: if provided and branitzer_siedlung.osm exists, limit buildings near that street
    limit_to_bbox: (minlat, minlon, maxlat, maxlon) to limit study area if street name absent
    """
    # Load LV topology
    id_to_node, ways = load_nodes_ways(DATA_NODES_WAYS)

    # Build or filter building list
    buildings = []
    if DATA_BUILDINGS.exists():
        buildings = parse_buildings_from_json(DATA_BUILDINGS)
    if not buildings and DATA_OSM.exists():
        buildings = parse_buildings_from_osm(DATA_OSM, bbox=limit_to_bbox)

    # If a street name is given, filter buildings near that street (~40 m)
    if selected_street_name and DATA_OSM.exists():
        buf_m = 40.0
        tree = ET.parse(str(DATA_OSM)); root = tree.getroot()
        node_coords = {int(n.attrib["id"]):(float(n.attrib["lat"]), float(n.attrib["lon"])) for n in root.findall("node")}
        street_lines = []
        for w in root.findall("way"):
            tags = {t.attrib["k"]: t.attrib["v"] for t in w.findall("tag")}
            if tags.get("highway") and tags.get("name") == selected_street_name:
                nds = [int(nd.attrib["ref"]) for nd in w.findall("nd")]
                coords = [(node_coords[nid][1], node_coords[nid][0]) for nid in nds if nid in node_coords]  # (lon,lat)
                if len(coords) >= 2:
                    street_lines.append(coords)

        def near_street(lat, lon):
            for coords in street_lines:
                for (x1,y1),(x2,y2) in zip(coords, coords[1:]):
                    if geom:
                        # Use shapely for true point-to-segment distance
                        point = Point(lon, lat)
                        line = geom.LineString([(x1,y1), (x2,y2)])
                        d = point.distance(line) * 111000  # rough conversion to meters
                    else:
                        # Fallback to distance to endpoints
                        d = min(
                            haversine_m(lat, lon, y1, x1),
                            haversine_m(lat, lon, y2, x2)
                        )
                    if d <= buf_m:
                        return True
            return False

        buildings = [b for b in buildings if near_street(b["lat"], b["lon"])]

    # Build network
    net, nodeid_to_bus = build_lv_net(id_to_node, ways, buildings)

    # Load scenarios (building_id → scenario_name → value)
    with DATA_LOADS.open("r", encoding="utf-8") as f:
        load_scen = json.load(f)

    # Unit multiplier with auto-detection
    if load_unit is None:  # optional: auto
        import statistics
        # sample some values across buildings
        vals = []
        for i, prof in zip(range(500), load_scen.values()):
            v = float(prof.get(selected_scenario, 0.0))
            vals.append(abs(v))
        med = statistics.median(vals) if vals else 0.0
        # Heuristic: tiny medians likely MW (0.0x); larger ~1–10 are kW
        load_unit = "MW" if med < 0.1 else "kW"
        print(f"Auto-detected load_unit='{load_unit}' (median={med:.3f})")
    
    mult = 1000.0 if load_unit.lower() == "mw" else 1.0

    # Map buildings to nearest LV node
    building_to_bus = {}
    for b in buildings:
        nid, _ = nearest_node_id(id_to_node, b["lat"], b["lon"])
        if nid is not None and nid in nodeid_to_bus:
            building_to_bus[b["id"]] = nodeid_to_bus[nid]

    # Attach loads (+ HPs)
    num_attached = 0
    for bid, prof in load_scen.items():
        if bid not in building_to_bus:
            continue
        p_kw = float(prof.get(selected_scenario, 0.0)) * mult
        hp_kw_el = (float(hp_add_kw_th) / float(hp_cop)) if hp_add_kw_th and hp_cop > 0 else 0.0
        p_total_kw = max(p_kw + hp_kw_el, 0.0)

        bus = building_to_bus[bid]
        if hp_three_phase:
            # split evenly among phases (3-phase HP)
            p_phase_mw = (p_total_kw / 3.0) / 1000.0
            pp3.create_asymmetric_load(
                net, bus=bus,
                p_a_mw=p_phase_mw, p_b_mw=p_phase_mw, p_c_mw=p_phase_mw,
                q_a_mvar=0.0, q_b_mvar=0.0, q_c_mvar=0.0, name=f"{bid}"
            )
        else:
            # single-phase worst-case on phase A
            pp3.create_asymmetric_load(
                net, bus=bus,
                p_a_mw=p_total_kw / 1000.0, p_b_mw=0.0, p_c_mw=0.0,
                q_a_mvar=0.0, q_b_mvar=0.0, q_c_mvar=0.0, name=f"{bid}"
            )
        num_attached += 1

    print(f"Attached {num_attached} building loads for '{selected_scenario}' "
          f"(unit={load_unit}, +HP_th={hp_add_kw_th} kW, COP={hp_cop}, 3φ={hp_three_phase}).")
    
    if num_attached == 0:
        print("[WARN] 0 building loads attached. This usually means building IDs in "
              "gebaeude_lastphasenV2.json don't match the IDs used for coordinates. "
              "Add data/output_branitzer_siedlungV11.json so IDs line up.")

    # Solve 3-phase power flow
    pp3.runpp_3ph(net, init="auto")

    # Export results as GeoJSON
    def buses_geojson():
        feats = []
        for b_idx, bus in net.bus.iterrows():
            # Skip buses without geodata (MV bus)
            if pd.isna(bus.get("geo")) or bus["geo"] is None:
                continue
            
            # Parse geodata from GeoJSON string
            try:
                geo_data = json.loads(bus["geo"])
                if geo_data.get("type") == "Point" and "coordinates" in geo_data:
                    lon, lat = geo_data["coordinates"]
                else:
                    continue
            except (json.JSONDecodeError, (ValueError, TypeError)):
                continue
                
            res = net.res_bus_3ph.loc[b_idx]
            vmin = min(res["vm_a_pu"], res["vm_b_pu"], res["vm_c_pu"])
            feats.append({
                "type":"Feature",
                "geometry":{"type":"Point","coordinates":[float(lon), float(lat)]},
                "properties":{
                    "bus": int(b_idx), "name": bus["name"],
                    "vm_a_pu": float(res["vm_a_pu"]),
                    "vm_b_pu": float(res["vm_b_pu"]),
                    "vm_c_pu": float(res["vm_c_pu"]),
                    "v_min_pu": float(vmin)
                }
            })
        return {"type":"FeatureCollection","features":feats}

    def lines_geojson():
        feats = []
        for li, line in net.line.iterrows():
            from_bus = int(line.from_bus); to_bus = int(line.to_bus)
            
            # Get coordinates from bus geodata
            try:
                from_bus_data = net.bus.loc[from_bus, "geo"]
                to_bus_data = net.bus.loc[to_bus, "geo"]
                
                if pd.isna(from_bus_data) or pd.isna(to_bus_data):
                    continue
                    
                from_geo = json.loads(from_bus_data)
                to_geo = json.loads(to_bus_data)
                
                if (from_geo.get("type") == "Point" and "coordinates" in from_geo and
                    to_geo.get("type") == "Point" and "coordinates" in to_geo):
                    x1, y1 = from_geo["coordinates"]  # lon, lat
                    x2, y2 = to_geo["coordinates"]    # lon, lat
                else:
                    continue
            except (json.JSONDecodeError, (ValueError, TypeError)):
                continue
                
            res = net.res_line_3ph.loc[li]
            i_max = float(line["max_i_ka"]) if "max_i_ka" in line else 0.0
            i_a = float(res["i_a_ka"]); i_b = float(res["i_b_ka"]); i_c = float(res["i_c_ka"])
            loading_pct = 100.0*max(i_a, i_b, i_c)/i_max if i_max>0 else 0.0
            feats.append({
                "type":"Feature",
                "geometry":{"type":"LineString","coordinates":[[float(x1), float(y1)], [float(x2), float(y2)]]},
                "properties":{
                    "line": int(li), "name": str(line.get("name","")), "length_km": float(line["length_km"]),
                    "i_a_ka": i_a, "i_b_ka": i_b, "i_c_ka": i_c, "max_i_ka": i_max,
                    "loading_pct": float(loading_pct)
                }
            })
        return {"type":"FeatureCollection","features":feats}

    buses_fc = buses_geojson()
    lines_fc = lines_geojson()
    (OUT_DIR/"buses_results.geojson").write_text(json.dumps(buses_fc), encoding="utf-8")
    (OUT_DIR/"lines_results.geojson").write_text(json.dumps(lines_fc), encoding="utf-8")
    print(f"Wrote: {OUT_DIR/'buses_results.geojson'}  {OUT_DIR/'lines_results.geojson'}")

    # Export violations.csv
    violations = []
    
    # Check bus voltage violations
    for b_idx, bus in net.bus.iterrows():
        if pd.isna(bus.get("geo")) or bus["geo"] is None:
            continue
        res = net.res_bus_3ph.loc[b_idx]
        vmin = min(res["vm_a_pu"], res["vm_b_pu"], res["vm_c_pu"])
        if vmin < v_min_limit_pu:
            violations.append({
                "type": "undervoltage",
                "element": f"bus_{b_idx}",
                "name": bus["name"],
                "value": f"{vmin:.3f} pu",
                "limit": f"{v_min_limit_pu:.3f} pu",
                "severity": "critical" if vmin < 0.85 else "warning"
            })
    
    # Check line loading violations
    for li, line in net.line.iterrows():
        res = net.res_line_3ph.loc[li]
        i_max = float(line["max_i_ka"]) if "max_i_ka" in line else 0.0
        if i_max > 0:
            i_a = float(res["i_a_ka"]); i_b = float(res["i_b_ka"]); i_c = float(res["i_c_ka"])
            loading_pct = 100.0 * max(i_a, i_b, i_c) / i_max
            if loading_pct > line_loading_limit_pct:
                violations.append({
                    "type": "overload",
                    "element": f"line_{li}",
                    "name": str(line.get("name", "")),
                    "value": f"{loading_pct:.1f}%",
                    "limit": f"{line_loading_limit_pct:.1f}%",
                    "severity": "critical" if loading_pct > 120 else "warning"
                })
    
    # Write violations.csv
    if violations:
        import csv
        with (OUT_DIR/"violations.csv").open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["type", "element", "name", "value", "limit", "severity"])
            writer.writeheader()
            writer.writerows(violations)
        print(f"Wrote: {OUT_DIR/'violations.csv'} ({len(violations)} violations found)")
    else:
        print("No violations found - all buses and lines within limits")

    # Interactive map
    if folium and len(net.bus) > 0:
        # center map on first bus with geodata
        first_bus = None
        for b_idx, bus in net.bus.iterrows():
            if not pd.isna(bus.get("geo")) and bus["geo"] is not None:
                try:
                    geo_data = json.loads(bus["geo"])
                    if geo_data.get("type") == "Point" and "coordinates" in geo_data:
                        lon, lat = geo_data["coordinates"]
                        first_bus = (lat, lon)
                        break
                except (json.JSONDecodeError, (ValueError, TypeError)):
                    continue
        
        if first_bus:
            cx, cy = first_bus
            m = folium.Map(location=[cx, cy], zoom_start=15, tiles="OpenStreetMap")

            # Lines colored by loading
            col = LinearColormap(["#2ECC71","#F1C40F","#E67E22","#E74C3C"], vmin=0, vmax=120, index=[0, 50, 100, 120])
            def style_line(feat):
                return {"color": col(feat["properties"]["loading_pct"]), "weight": 4, "opacity": 0.9}

            folium.GeoJson(
                lines_fc, name="LV lines (loading %)",
                style_function=style_line,
                tooltip=folium.GeoJsonTooltip(
                    fields=["name","loading_pct","i_a_ka","i_b_ka","i_c_ka","length_km"],
                    aliases=["Line","Loading %","Ia (kA)","Ib (kA)","Ic (kA)","Length (km)"]
                )
            ).add_to(m)

            # Buses colored by v_min_pu
            def get_voltage_color(v):
                if v < 0.90:
                    return "#E74C3C"  # Red for critical
                elif v < 0.95:
                    return "#E67E22"  # Orange for warning
                elif v < 1.00:
                    return "#F1C40F"  # Yellow for caution
                else:
                    return "#2ECC71"  # Green for good
            
            for f in buses_fc["features"]:
                v = f["properties"]["v_min_pu"]
                folium.CircleMarker(
                    location=[f["geometry"]["coordinates"][1], f["geometry"]["coordinates"][0]],
                    radius=4, fill=True, fill_opacity=0.9, color="#333", fill_color=get_voltage_color(v),
                    tooltip=f"Bus {f['properties']['bus']} — v_min={v:.3f} pu"
                ).add_to(m)

            col.add_to(m); folium.LayerControl().add_to(m)
            out_html = MAP_DIR/"street_hp_lv_map.html"
            m.save(str(out_html))
            print(f"Wrote: {out_html}")
        else:
            print("No buses with geodata found; skipping map.")
    else:
        print("folium not installed or no geodata; skipping map. Install with: pip install folium branca")


if __name__ == "__main__":
    # Update the run parameters to match the street + scenario you want to study.
    main(
        selected_scenario="winter_werktag_abendspitze",  # which load slice to simulate
        selected_street_name=None,                       # only buildings near this street (≈40 m buffer)
        load_unit="MW",                                  # set "kW" if your JSON values are already kW
        hp_add_kw_th=6.0,                                # EXTRA thermal kW PER BUILDING to model new HPs
        hp_cop=2.8,                                      # COP used to convert thermal→electric (P_el = kW_th / COP)
        hp_three_phase=True,                             # False = put HP on one phase (show imbalance)
        limit_to_bbox=None,                              # or (minlat, minlon, maxlat, maxlon) if no street name
        v_min_limit_pu=0.90,                             # undervoltage threshold for violations.csv
        line_loading_limit_pct=100.0                     # line overload threshold for violations.csv
    )
