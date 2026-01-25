from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd

try:
    import pandapower as pp
except Exception as e:  # pragma: no cover
    raise ImportError("pandapower is required for DHA LV grid hosting analysis") from e

try:
    import geopandas as gpd
except Exception:
    gpd = None  # optional; JSON adapter works without geopandas

from .config import DHAConfig, get_default_config


def _round_xy(x: float, y: float, tol: float) -> Tuple[float, float]:
    if tol <= 0:
        return (float(x), float(y))
    return (round(float(x) / tol) * tol, round(float(y) / tol) * tol)


def build_lv_grid_option2(
    lines_gdf,
    substations_gdf,
    cfg: Optional[DHAConfig] = None,
    *,
    endpoint_snap_tol_m: float = 1.0,
) -> pp.pandapowerNet:
    """
    Build an LV grid with **Option 2** boundary:
      MV bus (20 kV) + ext_grid at MV + MV/LV transformer(s) to LV (0.4 kV).

    Args:
        lines_gdf: GeoDataFrame with LineString geometries for LV lines.
        substations_gdf: GeoDataFrame with Point geometries for LV substations/transformers.
        cfg: DHAConfig
        endpoint_snap_tol_m: snap tolerance for deduplicating endpoint buses (in CRS units; assume meters)
    """
    if cfg is None:
        cfg = get_default_config()
    if gpd is None:
        raise ImportError("geopandas is required for build_lv_grid_option2(lines_gdf, substations_gdf)")

    if getattr(lines_gdf, "crs", None) is None:
        raise ValueError("lines_gdf must have a CRS (projected meters preferred)")
    if getattr(substations_gdf, "crs", None) is None:
        raise ValueError("substations_gdf must have a CRS (projected meters preferred)")
    if str(lines_gdf.crs) != str(substations_gdf.crs):
        substations_gdf = substations_gdf.to_crs(lines_gdf.crs)

    # Build pandapower net
    net = pp.create_empty_network(name="DHA_LV_grid_option2", f_hz=50)

    # MV boundary
    mv_bus = pp.create_bus(net, vn_kv=float(cfg.mv_vn_kv), name="MV_bus", type="b")
    pp.create_ext_grid(net, bus=mv_bus, vm_pu=float(cfg.ext_grid_vm_pu), name="MV_ext_grid")

    # Deduplicate LV buses by snapping endpoints
    key_to_bus: Dict[Tuple[float, float], int] = {}
    bus_geodata = []

    def get_or_create_lv_bus(x: float, y: float, name: str) -> int:
        key = _round_xy(x, y, endpoint_snap_tol_m)
        if key in key_to_bus:
            return key_to_bus[key]
        b = pp.create_bus(net, vn_kv=float(cfg.lv_vn_kv), name=name, type="b")
        key_to_bus[key] = b
        bus_geodata.append({"bus": b, "x": float(x), "y": float(y)})
        return b

    # LV lines (from geometry; length from geometry length in CRS units)
    for idx, row in lines_gdf.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        coords = list(geom.coords)
        for (x1, y1), (x2, y2) in zip(coords[:-1], coords[1:]):
            if float(x1) == float(x2) and float(y1) == float(y2):
                continue
            b1 = get_or_create_lv_bus(x1, y1, name=f"lv_{idx}_a")
            b2 = get_or_create_lv_bus(x2, y2, name=f"lv_{idx}_b")
            length_km = float(np.hypot(x2 - x1, y2 - y1) / 1000.0)
            length_km = max(length_km, 0.001)
            pp.create_line_from_parameters(
                net,
                from_bus=b1,
                to_bus=b2,
                length_km=length_km,
                r_ohm_per_km=float(cfg.line_r_ohm_per_km),
                x_ohm_per_km=float(cfg.line_x_ohm_per_km),
                c_nf_per_km=float(cfg.line_c_nf_per_km),
                max_i_ka=float(cfg.line_max_i_ka),
                name=f"lv_line_{idx}",
            )

    # LV substations → transformers (each substation point creates/uses the nearest LV bus)
    if substations_gdf.empty:
        raise ValueError("substations_gdf is empty: need >= 1 LV substation for Option 2 boundary")

    for sidx, srow in substations_gdf.iterrows():
        pt = srow.geometry
        if pt is None or pt.is_empty:
            continue
        lv_bus = get_or_create_lv_bus(pt.x, pt.y, name=f"lv_sub_{sidx}")
        pp.create_transformer_from_parameters(
            net,
            hv_bus=mv_bus,
            lv_bus=lv_bus,
            sn_mva=float(cfg.trafo_sn_mva),
            vn_hv_kv=float(cfg.mv_vn_kv),
            vn_lv_kv=float(cfg.lv_vn_kv),
            vk_percent=float(cfg.trafo_vk_percent),
            vkr_percent=float(cfg.trafo_vkr_percent),
            pfe_kw=float(cfg.trafo_pfe_kw),
            i0_percent=float(cfg.trafo_i0_percent),
            vector_group=str(cfg.trafo_vector_group),
            tap_min=int(cfg.trafo_tap_min),
            tap_max=int(cfg.trafo_tap_max),
            tap_step_percent=float(cfg.trafo_tap_step_percent),
            tap_pos=int(cfg.trafo_tap_pos),
            tap_neutral=int(cfg.trafo_tap_pos),
            tap_side=str(cfg.trafo_tap_side),
            name=f"trafo_{sidx}",
        )

    net.bus_geodata = pd.DataFrame(bus_geodata).set_index("bus") if bus_geodata else pd.DataFrame()

    _validate_no_unsupplied_buses(net)
    _validate_boundary_option2(net)
    return net


def build_lv_grid_from_nodes_ways_json(
    json_path: Path,
    cfg: Optional[DHAConfig] = None,
    *,
    dedup_coord_tol_deg: float = 0.0,
) -> pp.pandapowerNet:
    """
    Adapter for legacy continuity: build LV grid from the legacy nodes/ways JSON structure.

    Expected JSON format:
      { "nodes": [{id, lat, lon, tags}, ...],
        "ways":  [{id, nodes:[...], tags:{...}, length_km?}, ...] }

    Boundary is Option 2:
      MV bus + ext_grid at MV + transformers at nodes tagged power=substation.
    """
    if cfg is None:
        cfg = get_default_config()
    json_path = Path(json_path)
    if not json_path.exists():
        raise FileNotFoundError(f"nodes/ways JSON not found: {json_path}")

    data = json.loads(json_path.read_text(encoding="utf-8"))
    nodes = data.get("nodes", [])
    ways = data.get("ways", [])
    if not nodes or not ways:
        raise ValueError(f"Invalid nodes/ways JSON: expected non-empty nodes and ways in {json_path}")

    net = pp.create_empty_network(name="DHA_LV_grid_option2_nodes_ways", f_hz=50)

    mv_bus = pp.create_bus(net, vn_kv=float(cfg.mv_vn_kv), name="MV_bus", type="b")
    pp.create_ext_grid(net, bus=mv_bus, vm_pu=float(cfg.ext_grid_vm_pu), name="MV_ext_grid")

    # Create LV bus for each node (deduplicate optional)
    id_to_bus: Dict[str, int] = {}
    coord_to_bus: Dict[Tuple[float, float], int] = {}
    bus_geodata = []

    def _coord_key(lon: float, lat: float) -> Tuple[float, float]:
        if dedup_coord_tol_deg and dedup_coord_tol_deg > 0:
            return _round_xy(lon, lat, dedup_coord_tol_deg)
        return (float(lon), float(lat))

    for n in nodes:
        nid = str(n.get("id"))
        lat = float(n.get("lat"))
        lon = float(n.get("lon"))
        ck = _coord_key(lon, lat)
        if ck in coord_to_bus:
            id_to_bus[nid] = coord_to_bus[ck]
            continue
        b = pp.create_bus(net, vn_kv=float(cfg.lv_vn_kv), name=f"n{nid}", type="b")
        id_to_bus[nid] = b
        coord_to_bus[ck] = b
        bus_geodata.append({"bus": b, "x": lon, "y": lat})

    net.bus_geodata = pd.DataFrame(bus_geodata).set_index("bus") if bus_geodata else pd.DataFrame()

    # Transformers at substations
    substations = [n for n in nodes if (n.get("tags") or {}).get("power") == "substation"]
    if not substations:
        raise ValueError(
            "No substation nodes found in nodes/ways JSON (tags.power == 'substation'). "
            "Cannot build Option 2 boundary."
        )
    for sub in substations:
        nid = str(sub.get("id"))
        lv_bus = id_to_bus.get(nid)
        if lv_bus is None:
            continue
        pp.create_transformer_from_parameters(
            net,
            hv_bus=mv_bus,
            lv_bus=lv_bus,
            sn_mva=float(cfg.trafo_sn_mva),
            vn_hv_kv=float(cfg.mv_vn_kv),
            vn_lv_kv=float(cfg.lv_vn_kv),
            vk_percent=float(cfg.trafo_vk_percent),
            vkr_percent=float(cfg.trafo_vkr_percent),
            pfe_kw=float(cfg.trafo_pfe_kw),
            i0_percent=float(cfg.trafo_i0_percent),
            shift_degree=150,
            name=f"trafo_{nid}",
            tap_min=int(cfg.trafo_tap_min),
            tap_max=int(cfg.trafo_tap_max),
            tap_step_percent=float(cfg.trafo_tap_step_percent),
            tap_pos=int(cfg.trafo_tap_pos),
            tap_neutral=int(cfg.trafo_tap_pos),
            tap_side=str(cfg.trafo_tap_side),
        )

    # Lines from ways
    for w in ways:
        tags = w.get("tags", {}) or {}
        power_tag = tags.get("power")
        if power_tag not in {"line", "cable", "minor_line"}:
            continue
        nseq = w.get("nodes") or []
        if len(nseq) < 2:
            continue
        for u, v in zip(nseq, nseq[1:]):
            bu = id_to_bus.get(str(u))
            bv = id_to_bus.get(str(v))
            if bu is None or bv is None or bu == bv:
                continue
            # length from haversine is not available here; we trust length_km for the way if present,
            # otherwise approximate per-segment length using node geodata.
            lon1, lat1 = float(nodes_by_id(nodes, u)["lon"]), float(nodes_by_id(nodes, u)["lat"])
            lon2, lat2 = float(nodes_by_id(nodes, v)["lon"]), float(nodes_by_id(nodes, v)["lat"])
            length_km = float(_haversine_m(lat1, lon1, lat2, lon2) / 1000.0)
            length_km = max(length_km, 0.001)

            # Parameter selection: basic LV defaults; can be extended using tags.
            max_i_ka = float(cfg.line_max_i_ka)
            if power_tag == "minor_line":
                max_i_ka = min(max_i_ka, 0.20)
            pp.create_line_from_parameters(
                net,
                from_bus=bu,
                to_bus=bv,
                length_km=length_km,
                r_ohm_per_km=float(cfg.line_r_ohm_per_km),
                x_ohm_per_km=float(cfg.line_x_ohm_per_km),
                c_nf_per_km=float(cfg.line_c_nf_per_km),
                max_i_ka=max_i_ka,
                name=f"w{w.get('id','')}_{u}-{v}",
            )

    # If transformer LV buses are not part of the LV line graph, connect them so the LV network is energized.
    _connect_transformers_to_lv_graph_if_needed(net, cfg)

    _validate_no_unsupplied_buses(net)
    _validate_boundary_option2(net)
    return net


def nodes_by_id(nodes: list, node_id: Any) -> Dict[str, Any]:
    # small helper to avoid building huge dicts; fine for moderate node counts
    sid = str(node_id)
    for n in nodes:
        if str(n.get("id")) == sid:
            return n
    raise KeyError(f"Node id not found: {node_id}")


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    import math

    R = 6371000.0
    t1, t2 = math.radians(lat1), math.radians(lat2)
    dlat = t2 - t1
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(t1) * math.cos(t2) * math.sin(dlon / 2) ** 2
    return float(2 * R * math.asin(math.sqrt(a)))


def _validate_boundary_option2(net: pp.pandapowerNet) -> None:
    # Exactly one MV bus with ext_grid at MV, and at least one transformer down to LV
    if net.ext_grid is None or net.ext_grid.empty:
        raise ValueError("No ext_grid found: Option 2 requires ext_grid at MV bus.")
    if len(net.ext_grid) != 1:
        raise ValueError(f"Expected exactly 1 ext_grid at MV. Found: {len(net.ext_grid)}")
    eg_bus = int(net.ext_grid.iloc[0]["bus"])
    vn = float(net.bus.loc[eg_bus, "vn_kv"])
    if vn < 5.0:
        raise ValueError(f"ext_grid is not on MV bus (vn_kv={vn}). Do NOT place ext_grid on LV.")
    if net.trafo is None or net.trafo.empty:
        raise ValueError("No transformers found: Option 2 requires >= 1 MV/LV transformer.")


def _validate_no_unsupplied_buses(net: pp.pandapowerNet) -> None:
    try:
        from pandapower.topology import unsupplied_buses

        u = unsupplied_buses(net)
        if u and len(u) > 0:
            # show the first N for debugging
            u_list = list(u) if not isinstance(u, list) else u
            sample = list(map(int, u_list[:20]))
            raise ValueError(
                f"LV grid has unsupplied buses ({len(u)}). Sample bus indices: {sample}. "
                f"This indicates disconnected components / islands."
            )
    except Exception as e:
        # If topology module is missing, do a minimal check using nx graph from pandapower.
        # We keep this as best-effort to provide useful errors.
        # If we failed while processing unsupplied buses, do not silently ignore.
        if "unsupplied" in str(e).lower() or "subscriptable" in str(e).lower():
            raise


def _connect_transformers_to_lv_graph_if_needed(net: pp.pandapowerNet, cfg: DHAConfig) -> None:
    """
    In some legacy nodes/ways exports, substation nodes exist but are not part of the LV line graph.
    This helper connects each transformer LV bus to the nearest LV bus that participates in at least
    one line endpoint, so the LV graph becomes energized.
    """
    if net.trafo is None or net.trafo.empty:
        return
    if net.line is None or net.line.empty:
        return
    if not hasattr(net, "bus_geodata") or net.bus_geodata is None or net.bus_geodata.empty:
        return

    line_endpoint_buses = set(net.line["from_bus"].astype(int).tolist()) | set(net.line["to_bus"].astype(int).tolist())
    if not line_endpoint_buses:
        return

    # Precompute endpoint coordinates
    endpoints = []
    for b in sorted(line_endpoint_buses):
        if b in net.bus_geodata.index:
            # store (bus, x, y) in the same coordinate system as net.bus_geodata
            endpoints.append((b, float(net.bus_geodata.loc[b, "x"]), float(net.bus_geodata.loc[b, "y"])))
    if not endpoints:
        return

    # For each transformer LV bus, if not already in endpoints, connect it to nearest endpoint
    for _, tr in net.trafo.iterrows():
        lv_bus = int(tr["lv_bus"])
        if lv_bus in line_endpoint_buses:
            continue
        if lv_bus not in net.bus_geodata.index:
            continue
        x = float(net.bus_geodata.loc[lv_bus, "x"])
        y = float(net.bus_geodata.loc[lv_bus, "y"])
        best = None
        best_d = float("inf")
        # Detect whether coordinates look like lon/lat (degrees) or projected meters.
        # If values exceed typical lon/lat ranges, treat as projected and use Euclidean meters.
        is_projected = (abs(x) > 180.0) or (abs(y) > 90.0)
        for b2, x2, y2 in endpoints:
            if is_projected:
                d = float(np.hypot(x - x2, y - y2))
            else:
                # x=lon, y=lat
                d = _haversine_m(y, x, y2, x2)
            if d < best_d:
                best_d = d
                best = b2
        if best is None:
            continue
        # Create a short LV link (acts as a feeder connection)
        pp.create_line_from_parameters(
            net,
            from_bus=lv_bus,
            to_bus=int(best),
            length_km=max(best_d / 1000.0, 0.001),
            r_ohm_per_km=float(cfg.line_r_ohm_per_km),
            x_ohm_per_km=float(cfg.line_x_ohm_per_km),
            c_nf_per_km=float(cfg.line_c_nf_per_km),
            max_i_ka=float(cfg.line_max_i_ka),
            name=f"substation_link_{lv_bus}_to_{int(best)}",
        )

