from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

try:
    import geopandas as gpd
except Exception as e:  # pragma: no cover
    raise ImportError("geopandas is required for building-to-bus mapping") from e

try:
    import pyproj
except Exception:
    pyproj = None


def map_buildings_to_lv_buses(
    buildings_gdf: gpd.GeoDataFrame,
    net,
    max_dist_m: float = 1000.0,
    *,
    source_crs: Optional[str] = None,
    bus_crs: Optional[str] = "EPSG:4326",
    lv_vn_kv: float = 0.4,
) -> pd.DataFrame:
    """
    Map buildings to nearest LV buses.

    Returns DataFrame with:
      [building_id, bus_id, distance_m, mapped]
    """
    if buildings_gdf is None or buildings_gdf.empty:
        raise ValueError("buildings_gdf is empty")
    if "building_id" not in buildings_gdf.columns:
        raise ValueError("buildings_gdf must contain 'building_id'")
    if not hasattr(net, "bus") or net.bus is None or net.bus.empty:
        raise ValueError("pandapower net has no buses")
    if not hasattr(net, "bus_geodata") or net.bus_geodata is None or net.bus_geodata.empty:
        raise ValueError("pandapower net has no bus_geodata (required for mapping)")

    # filter LV buses
    lv_bus_idx = net.bus.index[net.bus["vn_kv"].astype(float) <= float(lv_vn_kv) + 1e-9].tolist()
    if not lv_bus_idx:
        raise ValueError("No LV buses found (vn_kv≈0.4).")

    bus_geo = net.bus_geodata.loc[lv_bus_idx][["x", "y"]].copy()
    bus_geo["bus_id"] = bus_geo.index.astype(int)

    # Use building centroids for mapping
    b = buildings_gdf.copy()
    b["geometry"] = b.geometry.centroid

    # Convert both to projected CRS for meter distances
    if b.crs is None and source_crs:
        b = b.set_crs(source_crs)
    if b.crs is None:
        raise ValueError("buildings_gdf must have a CRS")

    # Infer bus CRS if not provided: if x/y magnitudes exceed lon/lat ranges, assume projected EPSG:25833.
    if bus_crs is None:
        try:
            x_med = float(np.nanmedian(pd.to_numeric(bus_geo["x"], errors="coerce")))
            y_med = float(np.nanmedian(pd.to_numeric(bus_geo["y"], errors="coerce")))
            if abs(x_med) > 180.0 or abs(y_med) > 90.0:
                bus_crs = "EPSG:25833"
            else:
                bus_crs = "EPSG:4326"
        except Exception:
            bus_crs = "EPSG:4326"

    bus_gdf = gpd.GeoDataFrame(
        bus_geo,
        geometry=gpd.points_from_xy(bus_geo["x"], bus_geo["y"]),
        crs=bus_crs,
    )

    # Choose a projected CRS for distance computations
    target_crs = "EPSG:25833"
    try:
        if b.crs and str(b.crs).upper().endswith("4326"):
            target_crs = "EPSG:25833"
        else:
            # If buildings already projected, keep it
            target_crs = str(b.crs)
    except Exception:
        target_crs = "EPSG:25833"

    b_proj = b.to_crs(target_crs)
    bus_proj = bus_gdf.to_crs(target_crs)

    # Brute-force nearest for moderate sizes (chunked)
    bx = b_proj.geometry.x.to_numpy()
    by = b_proj.geometry.y.to_numpy()
    busx = bus_proj.geometry.x.to_numpy()
    busy = bus_proj.geometry.y.to_numpy()
    bus_ids = bus_proj["bus_id"].to_numpy()

    out_rows = []
    chunk = 256
    for i0 in range(0, len(b_proj), chunk):
        i1 = min(i0 + chunk, len(b_proj))
        dx = bx[i0:i1, None] - busx[None, :]
        dy = by[i0:i1, None] - busy[None, :]
        d2 = dx * dx + dy * dy
        j = np.argmin(d2, axis=1)
        dist = np.sqrt(d2[np.arange(i1 - i0), j])
        for k in range(i0, i1):
            jj = int(j[k - i0])
            out_rows.append(
                {
                    "building_id": str(b.iloc[k]["building_id"]),
                    "bus_id": int(bus_ids[jj]),
                    "distance_m": float(dist[k - i0]),
                }
            )

    df = pd.DataFrame(out_rows)
    df["mapped"] = df["distance_m"] <= float(max_dist_m)

    unmapped = df[~df["mapped"]]
    if len(unmapped) > 0:
        # Keep rows but make bus_id NaN for unmapped
        df.loc[~df["mapped"], "bus_id"] = np.nan

    return df[["building_id", "bus_id", "distance_m", "mapped"]]

