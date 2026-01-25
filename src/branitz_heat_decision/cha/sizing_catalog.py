"""
Catalog-based sizing for trunk and spur pipes.
Uses the technical catalog Excel file.
"""

import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import logging
import pandapipes as pp

logger = logging.getLogger(__name__)

def load_technical_catalog(catalog_path: Path) -> pd.DataFrame:
    """
    Load DN catalog from technical catalog Excel.
    The Baden-Württemberg Technikkatalog is not organized as a simple DN table.
    We support two formats:
      1) Simple DN sheet (DN_Catalog / Rohrkatalog / Pipe_Catalog) with columns:
         DN, inner_diameter_mm, cost_eur_per_m
      2) Technikkatalog Wärmeplanung (Version 1.1): extract the DN series and €/m costs
         from Tab 45 ("Wärmenetze Kalte Nahwärme"), rows:
           - "Entsprechende DN"
           - "Hauptleitungsstrang (bis 13 kW Stichleitung)" (€/m)
    """
    if not catalog_path.exists():
        logger.warning(f"Catalog not found at {catalog_path}, using defaults")
        return _get_default_catalog()
    
    # Try multiple sheet names
    for sheet_name in ['DN_Catalog', 'Rohrkatalog', 'Pipe_Catalog']:
        try:
            df = pd.read_excel(catalog_path, sheet_name=sheet_name)
            if 'DN' in df.columns and 'inner_diameter_mm' in df.columns:
                df['inner_diameter_m'] = df['inner_diameter_mm'] / 1000.0
                logger.info(f"Loaded {len(df)} pipe types from {catalog_path}")
                return df
        except Exception:
            continue

    # Try Technikkatalog Wärmeplanung layout (Tab 45 has explicit DN series)
    try:
        df = _load_technikkatalog_tab45(catalog_path)
        if df is not None and not df.empty:
            logger.info(f"Loaded {len(df)} DN steps from Technikkatalog Tab 45: {catalog_path}")
            return df
    except Exception as e:
        logger.warning(f"Failed to parse Technikkatalog Tab 45: {e}")
    
    logger.warning("No valid catalog sheet found, using defaults")
    return _get_default_catalog()


def _load_technikkatalog_tab45(catalog_path: Path) -> Optional[pd.DataFrame]:
    """
    Parse Technikkatalog Wärmeplanung v1.1 "Tab 45" (Wärmenetze Kalte Nahwärme).

    Extracts:
      - DN series from the first "Entsprechende DN" row
      - €/m costs from the first "Hauptleitungsstrang (bis 13 kW Stichleitung)" row
        (if present; cost can be NaN if missing)

    Returns a normalized catalog DataFrame with columns:
      DN (int), inner_diameter_mm (float), inner_diameter_m (float), cost_eur_per_m (float)
    """
    raw = pd.read_excel(catalog_path, sheet_name="Tab 45", header=None)
    txt = raw.astype(str)

    def _find_row(label: str) -> Optional[int]:
        # label is expected in column 1 in this workbook
        for i in range(len(raw)):
            if str(raw.iloc[i, 1]).strip().lower() == label.strip().lower():
                return i
        return None

    dn_row = _find_row("Entsprechende DN")
    if dn_row is None:
        return None

    # Find the first row that contains "Hauptleitungsstrang" text (costs €/m)
    cost_row = None
    for i in range(len(raw)):
        cell = str(raw.iloc[i, 1]).strip().lower()
        if "hauptleitungsstrang" in cell:
            cost_row = i
            break

    # In this workbook, the DN values and the aligned cost values share the same columns.
    dn_cols: List[int] = []
    for j, v in enumerate(raw.iloc[dn_row, :].tolist()):
        if isinstance(v, (int, float)) and not isinstance(v, bool) and 10 <= float(v) <= 1000:
            dn_cols.append(j)

    dn_vals = [int(round(raw.iloc[dn_row, j])) for j in dn_cols]
    if not dn_vals:
        return None

    cost_vals: List[Optional[float]] = []
    if cost_row is not None:
        for j in dn_cols:
            v = raw.iloc[cost_row, j]
            if isinstance(v, (int, float)) and not isinstance(v, bool) and 0.0 <= float(v) <= 20000.0:
                cost_vals.append(float(v))
            else:
                cost_vals.append(np.nan)

    # align costs to dn positions (if costs missing/short -> NaNs)
    rows = []
    for i, dn in enumerate(dn_vals):
        cost = cost_vals[i] if i < len(cost_vals) else np.nan
        # We do not have inner diameters in the Technikkatalog; use DN as a proxy (mm).
        inner_mm = float(dn)
        rows.append(
            {
                "DN": int(dn),
                "inner_diameter_mm": inner_mm,
                "cost_eur_per_m": float(cost) if pd.notna(cost) else np.nan,
                "material": "steel",
            }
        )

    df = pd.DataFrame(rows).drop_duplicates(subset=["DN"]).sort_values("DN").reset_index(drop=True)
    df["inner_diameter_m"] = df["inner_diameter_mm"] / 1000.0
    return df

def _get_default_catalog() -> pd.DataFrame:
    """Default EN 10255 catalog if Excel not available."""
    data = [
        {'DN': 20, 'inner_diameter_mm': 21.3, 'cost_eur_per_m': 45, 'material': 'steel'},
        {'DN': 25, 'inner_diameter_mm': 26.9, 'cost_eur_per_m': 58, 'material': 'steel'},
        {'DN': 32, 'inner_diameter_mm': 33.7, 'cost_eur_per_m': 75, 'material': 'steel'},
        {'DN': 40, 'inner_diameter_mm': 42.4, 'cost_eur_per_m': 92, 'material': 'steel'},
        {'DN': 50, 'inner_diameter_mm': 53.0, 'cost_eur_per_m': 115, 'material': 'steel'},
        {'DN': 65, 'inner_diameter_mm': 66.7, 'cost_eur_per_m': 145, 'material': 'steel'},
        {'DN': 80, 'inner_diameter_mm': 80.0, 'cost_eur_per_m': 178, 'material': 'steel'},
        {'DN': 100, 'inner_diameter_mm': 106.0, 'cost_eur_per_m': 235, 'material': 'steel'},
        {'DN': 125, 'inner_diameter_mm': 132.0, 'cost_eur_per_m': 295, 'material': 'steel'},
        {'DN': 150, 'inner_diameter_mm': 158.0, 'cost_eur_per_m': 365, 'material': 'steel'},
    ]
    df = pd.DataFrame(data)
    df['inner_diameter_m'] = df['inner_diameter_mm'] / 1000.0
    return df

def size_trunk_and_spurs(
    net: pp.pandapipesNet,
    design_loads_kw: Dict[str, float],
    trunk_edges: List[Tuple],
    spur_buildings: List[str],
    catalog: pd.DataFrame,
    spur_assignments: Optional[Dict] = None,
    v_limit_trunk_ms: float = 1.5,
    v_limit_service_ms: float = 1.5,
    v_abs_max_ms: float = 2.5,
    dp_per_m_max_pa: float = 200.0,
    trunk_root: Optional[Tuple] = None,
    delta_t_k: float = 30.0,
    fluid_density_kg_m3: float = 970.0
) -> Dict[str, Dict[str, Any]]:
    """
    Size trunk pipes by aggregate flow, spurs by individual building flow.
    Returns mapping of edge/building to selected DN.
    """
    # sizing uses a design mass flow from heat demand: mdot = Q / (cp * ΔT)
    # (cp in J/kgK, Q in W)
    cp_j_per_kgk = 4180.0
    delta_t = float(delta_t_k)
    
    # Create spur_assignments dict if not provided
    if spur_assignments is None:
        spur_assignments = {bid: None for bid in spur_buildings}
    
    results: Dict[str, Any] = {'trunk': {}, 'spurs': {}, 'rationale': []}

    def _diameter_m_for_dn(dn: int) -> float:
        try:
            row = catalog.loc[catalog["DN"] == int(dn)]
            if len(row) > 0 and "inner_diameter_m" in row.columns and pd.notna(row.iloc[0]["inner_diameter_m"]):
                return float(row.iloc[0]["inner_diameter_m"])
        except Exception:
            pass
        return float(dn) / 1000.0

    def _velocity_ms(mdot_kg_s: float, d_m: float, rho: float) -> float:
        if d_m <= 0:
            return float("inf")
        area = np.pi * (d_m ** 2) / 4.0
        if area <= 0:
            return float("inf")
        return float((mdot_kg_s / rho) / area)

    def _friction_factor_swamee_jain(re: float, rel_eps: float) -> float:
        # Conservative: if laminar, use 64/Re. Otherwise Swamee-Jain.
        if re <= 0:
            return 0.02
        if re < 2300:
            return float(64.0 / re)
        return float(0.25 / (np.log10(rel_eps / 3.7 + 5.74 / (re ** 0.9)) ** 2))

    def _dp_per_m_pa(mdot_kg_s: float, d_m: float, rho: float, mu_pa_s: float, eps_m: float) -> float:
        v = _velocity_ms(mdot_kg_s, d_m, rho)
        if not np.isfinite(v) or v <= 0 or d_m <= 0:
            return 0.0
        re = rho * v * d_m / max(mu_pa_s, 1e-9)
        rel_eps = eps_m / max(d_m, 1e-9)
        f = _friction_factor_swamee_jain(re, rel_eps)
        return float(f * (rho * v * v / 2.0) / d_m)

    # DN steps (int) from catalog
    if "DN" not in catalog.columns:
        logger.warning(f"Catalog missing 'DN' column, using defaults.")
        catalog = _get_default_catalog()
    dn_steps = sorted({int(x) for x in catalog["DN"].tolist() if pd.notna(x)})
    if not dn_steps:
        dn_steps = sorted({int(x) for x in _get_default_catalog()["DN"].tolist()})
    
    # Ensure large sizes are available (fallback to theoretical DN if catalog is limited)
    # This prevents sizing from capping at e.g. DN80 for large clusters.
    fallback_sizes = {100, 125, 150, 200, 250, 300, 350, 400}
    dn_steps = sorted(set(dn_steps) | fallback_sizes)
    
    # 1) Trunk sizing (tree accumulation)
    # - compute downstream load per edge (rooted at trunk_root)
    # - choose smallest DN that keeps v <= v_limit_trunk_ms (flag if v > v_abs_max_ms)
    if trunk_root is not None and trunk_edges:
        try:
            import networkx as nx
            from shapely.geometry import Point
            from collections import deque

            # Build trunk graph with lengths
            T = nx.Graph()
            for u, v in trunk_edges:
                T.add_edge(u, v, length_m=float(Point(u).distance(Point(v))))

            # Map each building to its trunk tee node (preferred) or fallback endpoint
            building_to_node: Dict[str, Tuple] = {}
            if spur_assignments:
                for bid, a in spur_assignments.items():
                    tee = a.get("trunk_attach_node")
                    if tee is not None:
                        building_to_node[bid] = tee
                        continue
                    edge = a.get("edge")
                    if not edge:
                        continue
                    u, v = edge
                    ap = a.get("attach_point")
                    if ap is not None:
                        ap_pt = Point(ap)
                        building_to_node[bid] = u if ap_pt.distance(Point(u)) <= ap_pt.distance(Point(v)) else v
                    else:
                        bp = a.get("building_point")
                        if bp is not None:
                            bp_pt = Point(bp)
                            building_to_node[bid] = u if bp_pt.distance(Point(u)) <= bp_pt.distance(Point(v)) else v

            # Rooted tree structure
            parent: Dict[Tuple, Optional[Tuple]] = {trunk_root: None}
            children: Dict[Tuple, List[Tuple]] = {n: [] for n in T.nodes()}
            q = deque([trunk_root])
            bfs_nodes: List[Tuple] = []
            while q:
                n = q.popleft()
                bfs_nodes.append(n)
                for nbr in T.neighbors(n):
                    if nbr in parent:
                        continue
                    parent[nbr] = n
                    children[n].append(nbr)
                    q.append(nbr)

            # Postorder for subtree loads
            node_subtree_load_kw = {n: 0.0 for n in T.nodes()}
            for bid, load in design_loads_kw.items():
                tn = building_to_node.get(bid)
                if tn in node_subtree_load_kw:
                    node_subtree_load_kw[tn] += float(load)
            for n in reversed(bfs_nodes):
                for c in children.get(n, []):
                    node_subtree_load_kw[n] += node_subtree_load_kw.get(c, 0.0)

            # Edge index lookup (both orientations)
            edge_to_idx: Dict[Tuple[Tuple, Tuple], int] = {}
            for idx, (u, v) in enumerate(trunk_edges):
                edge_to_idx[(u, v)] = idx
                edge_to_idx[(v, u)] = idx

            for node in bfs_nodes:
                p = parent.get(node)
                if p is None:
                    continue
                idx = edge_to_idx.get((p, node))
                if idx is None:
                    continue

                # Subtree flow through this edge = subtree load at child node
                load_kw = float(node_subtree_load_kw.get(node, 0.0))
                mdot = (load_kw * 1000.0) / (cp_j_per_kgk * delta_t) if load_kw > 0 else 0.0

                # Choose DN by BOTH target velocity and dp/m constraint (upsizing until satisfied)
                dn_choice = dn_steps[0]
                v_choice = 0.0
                dp_pm = 0.0
                for dn in dn_steps:
                    if dn < 100:  # Minimum trunk size DN100 to avoid velocity bottlenecks
                        continue
                    d_m = _diameter_m_for_dn(dn)
                    v = _velocity_ms(mdot, d_m, fluid_density_kg_m3) if mdot > 0 else 0.0
                    dp = _dp_per_m_pa(
                        mdot_kg_s=float(mdot),
                        d_m=d_m,
                        rho=float(fluid_density_kg_m3),
                        mu_pa_s=1e-3,
                        eps_m=1e-4,
                    )
                    dn_choice, v_choice, dp_pm = int(dn), float(v), float(dp)
                    ok_v = (v_choice <= float(v_limit_trunk_ms) + 1e-9) or (mdot <= 0)
                    ok_dp = (not dp_per_m_max_pa) or (dp_pm <= float(dp_per_m_max_pa) + 1e-9) or (mdot <= 0)
                    if ok_v and ok_dp:
                        break
                status = "ok"
                if v_choice > float(v_abs_max_ms) + 1e-9:
                    status = "v_abs_max_exceeded"
                elif dp_per_m_max_pa and dp_pm > float(dp_per_m_max_pa):
                    status = "dp_per_m_exceeded"

                results["trunk"][f"edge_{idx}"] = int(dn_choice)
                results["rationale"].append({
                    "role": "trunk",
                    "edge_idx": int(idx),
                    "Q_down_kw": float(load_kw),
                    "mdot_design_kg_per_s": float(mdot),
                    "chosen_DN": int(dn_choice),
                    "inner_diameter_mm": float(_diameter_m_for_dn(dn_choice) * 1000.0),
                    "v_calc_m_per_s": float(v_choice),
                    "v_limit_ms": float(v_limit_trunk_ms),
                    "v_abs_max_ms": float(v_abs_max_ms),
                    "dp_per_m_est_pa": float(dp_pm),
                    "dp_per_m_max_pa": float(dp_per_m_max_pa),
                    "status": status,
                })
        except Exception as e:
            logger.warning(f"Trunk sizing (downstream accumulation) failed, falling back: {e}")

    # Fallback sizing if no trunk_root or failure above
    if not results["trunk"]:
        for i, edge in enumerate(trunk_edges):
            total_load_kw = float(sum(design_loads_kw.values()))
            mdot_kg_s = (total_load_kw * 1000.0) / (cp_j_per_kgk * delta_t)
            # pick smallest DN meeting v_limit_trunk_ms
            dn_choice = dn_steps[0]
            v_choice = 0.0
            for dn in dn_steps:
                if dn < 100:
                    continue
                d_m = _diameter_m_for_dn(dn)
                v = _velocity_ms(mdot_kg_s, d_m, fluid_density_kg_m3) if mdot_kg_s > 0 else 0.0
                dn_choice, v_choice = int(dn), float(v)
                if v <= float(v_limit_trunk_ms) + 1e-9:
                    break
            results["trunk"][f"edge_{i}"] = int(dn_choice)
            results["rationale"].append({
                "role": "trunk",
                "edge_idx": int(i),
                "Q_down_kw": float(total_load_kw),
                "mdot_design_kg_per_s": float(mdot_kg_s),
                "chosen_DN": int(dn_choice),
                "inner_diameter_mm": float(_diameter_m_for_dn(dn_choice) * 1000.0),
                "v_calc_m_per_s": float(v_choice),
                "v_limit_ms": float(v_limit_trunk_ms),
                "v_abs_max_ms": float(v_abs_max_ms),
                "dp_per_m_est_pa": float("nan"),
                "dp_per_m_max_pa": float(dp_per_m_max_pa),
                "status": "fallback",
            })

    # 2) Service sizing (building-level)
    for building_id in spur_buildings:
        load_kw = design_loads_kw.get(building_id, 50.0)
        mdot_kg_s = (float(load_kw) * 1000.0) / (cp_j_per_kgk * delta_t) if float(load_kw) > 0 else 0.0

        dn_choice = dn_steps[0]
        v_choice = 0.0
        dp_pm = 0.0
        for dn in dn_steps:
            if dn < 20:
                continue
            d_m = _diameter_m_for_dn(dn)
            v = _velocity_ms(mdot_kg_s, d_m, fluid_density_kg_m3) if mdot_kg_s > 0 else 0.0
            dp = _dp_per_m_pa(
                mdot_kg_s=float(mdot_kg_s),
                d_m=d_m,
                rho=float(fluid_density_kg_m3),
                mu_pa_s=1e-3,
                eps_m=1e-4,
            )
            dn_choice, v_choice, dp_pm = int(dn), float(v), float(dp)
            ok_v = (v_choice <= float(v_limit_service_ms) + 1e-9) or (mdot_kg_s <= 0)
            ok_dp = (not dp_per_m_max_pa) or (dp_pm <= float(dp_per_m_max_pa) + 1e-9) or (mdot_kg_s <= 0)
            if ok_v and ok_dp:
                break
        status = "ok"
        if v_choice > float(v_abs_max_ms) + 1e-9:
            status = "v_abs_max_exceeded"
        elif dp_per_m_max_pa and dp_pm > float(dp_per_m_max_pa):
            status = "dp_per_m_exceeded"

        results['spurs'][building_id] = int(dn_choice)
        results["rationale"].append({
            "role": "service",
            "building_id": str(building_id),
            "Q_building_kw": float(load_kw),
            "mdot_design_kg_per_s": float(mdot_kg_s),
            "chosen_DN": int(dn_choice),
            "inner_diameter_mm": float(_diameter_m_for_dn(dn_choice) * 1000.0),
            "v_calc_m_per_s": float(v_choice),
            "v_limit_ms": float(v_limit_service_ms),
            "v_abs_max_ms": float(v_abs_max_ms),
            "dp_per_m_est_pa": float(dp_pm),
            "dp_per_m_max_pa": float(dp_per_m_max_pa),
            "status": status,
        })
    
    return results

def _get_downstream_buildings(
    edge: Tuple,
    spur_assignments: Dict,
    loads_kw: Dict[str, float]
) -> Dict[str, float]:
    """Get all buildings whose spur attaches to this edge or downstream."""
    # Legacy placeholder (kept for backward-compat); use trunk_root logic in size_trunk_and_spurs instead.
    total_buildings = len(spur_assignments)
    load_per_building = sum(loads_kw.values()) / max(total_buildings, 1)
    return {'proportional': load_per_building * len(edge)}

def _select_dn_from_catalog(
    d_req_m: float,
    catalog: pd.DataFrame,
    min_dn: int = 20,
    max_dn: Optional[int] = None
) -> int:
    """Select smallest DN >= required diameter."""
    # Handle different catalog formats (DN column or dn_label)
    dn_col = 'DN' if 'DN' in catalog.columns else 'dn_label' if 'dn_label' in catalog.columns else None
    if dn_col is None:
        raise ValueError(f"Catalog must have 'DN' or 'dn_label' column. Found: {list(catalog.columns)}")
    
    # Filter catalog
    suitable = catalog[catalog['inner_diameter_m'] >= d_req_m].copy()
    
    # Handle string DN labels like "DN50" vs integer DN values
    is_string_dn = suitable[dn_col].dtype == 'object'
    
    if is_string_dn:
        # Convert string labels to integers for comparison
        suitable['_dn_int'] = suitable[dn_col].str.replace('DN', '').astype(int)
        if max_dn:
            suitable = suitable[suitable['_dn_int'] <= max_dn]
        if min_dn:
            suitable = suitable[suitable['_dn_int'] >= min_dn]
    else:
        # Integer DN values
        if max_dn:
            suitable = suitable[suitable[dn_col] <= max_dn]
    if min_dn:
            suitable = suitable[suitable[dn_col] >= min_dn]
    
    if suitable.empty:
        # Use largest available
        dn = catalog.loc[catalog['inner_diameter_m'].idxmax(), dn_col]
        if isinstance(dn, str):
            dn = int(dn.replace('DN', ''))
        logger.warning(f"No suitable DN for d_req={d_req_m*1000:.1f}mm, using DN{dn}")
        return int(dn)
    
    # Return smallest suitable DN
    dn = suitable.loc[suitable['inner_diameter_m'].idxmin(), dn_col]
    if isinstance(dn, str):
        dn = int(dn.replace('DN', ''))
    return int(dn)

def apply_pipe_sizes_to_network(
    net: pp.pandapipesNet,
    pipe_sizes: Dict[str, Dict[str, int]]
):
    """Apply the selected DNs to network pipes."""
    # Apply trunk sizes
    for edge_key, dn in pipe_sizes['trunk'].items():
        # Find pipes matching this edge
        # Note: edge_key is string like "edge_0", needs mapping to actual edges
        mask = net.pipe['name'].str.contains(f"trunk_")
        net.pipe.loc[mask, 'diameter_m'] = dn / 1000.0
    
    # Apply spur sizes
    for building_id, dn in pipe_sizes['spurs'].items():
        mask = net.pipe['name'].str.contains(f"spur_supply_{building_id}")
        net.pipe.loc[mask, 'diameter_m'] = dn / 1000.0
        
        mask_return = net.pipe['name'].str.contains(f"spur_return_{building_id}")
        net.pipe.loc[mask_return, 'diameter_m'] = dn / 1000.0