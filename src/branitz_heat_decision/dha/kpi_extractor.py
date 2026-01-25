from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

from .config import DHAConfig, get_default_config


def extract_dha_kpis(
    results_by_hour: Dict[int, Dict[str, object]],
    cfg: DHAConfig | None = None,
    net=None,  # NEW: Optional pandapower network for feeder distance calculation
) -> Tuple[Dict[str, object], pd.DataFrame]:
    """
    Extract auditable DHA KPIs + a violations table from per-hour loadflow results.
    
    Args:
        results_by_hour: Dictionary mapping hour to loadflow results
        cfg: DHA configuration
        net: Optional pandapower network for computing feeder metrics
    
    Returns:
        (kpis_dict, violations_dataframe)
    """
    if cfg is None:
        cfg = get_default_config()
    if not results_by_hour:
        raise ValueError("results_by_hour is empty")

    violations: List[dict] = []
    worst_vmin = float("inf")
    worst_vmin_hour = None
    max_loading = 0.0
    max_loading_hour = None
    converged_hours = 0

    for hour, res in results_by_hour.items():
        conv = bool(res.get("converged", False))
        if not conv:
            violations.append(
                {
                    "hour": int(hour),
                    "type": "non_convergence",
                    "element": "",
                    "name": "",
                    "value": str(res.get("error", "")),
                    "limit": "",
                    "severity": "critical",
                }
            )
            continue
        converged_hours += 1

        bus_df = res.get("bus_results")
        if isinstance(bus_df, pd.DataFrame) and not bus_df.empty:
            if "v_min_pu" in bus_df.columns:
                vmin = float(pd.to_numeric(bus_df["v_min_pu"], errors="coerce").min())
            elif "vm_pu" in bus_df.columns:
                vmin = float(pd.to_numeric(bus_df["vm_pu"], errors="coerce").min())
            else:
                vmin = np.nan

            if np.isfinite(vmin) and vmin < worst_vmin:
                worst_vmin = vmin
                worst_vmin_hour = int(hour)

            # Voltage violations per bus
            for b_idx, row in bus_df.iterrows():
                v = float(row.get("v_min_pu", row.get("vm_pu", np.nan)))
                if not np.isfinite(v):
                    continue
                if v < float(cfg.v_min_pu) or v > float(cfg.v_max_pu):
                    violations.append(
                        {
                            "hour": int(hour),
                            "type": "voltage",
                            "element": f"bus_{int(b_idx)}",
                            "name": "",
                            "value": f"{v:.4f} pu",
                            "limit": f"[{cfg.v_min_pu:.2f}, {cfg.v_max_pu:.2f}] pu",
                            "severity": "critical" if v < float(cfg.v_min_pu) else "warning",
                        }
                    )

        line_df = res.get("line_results")
        if isinstance(line_df, pd.DataFrame) and not line_df.empty:
            loading_col = None
            for c in ("loading_percent", "loading_pct", "loading_percent_a", "loading_percent_b"):
                if c in line_df.columns:
                    loading_col = c
                    break
            if loading_col:
                m = float(pd.to_numeric(line_df[loading_col], errors="coerce").max())
                if np.isfinite(m) and m > max_loading:
                    max_loading = m
                    max_loading_hour = int(hour)

                for li, row in line_df.iterrows():
                    val = float(pd.to_numeric(row.get(loading_col, np.nan), errors="coerce"))
                    if not np.isfinite(val):
                        continue
                    if val > float(cfg.line_loading_limit_pct):
                        violations.append(
                            {
                                "hour": int(hour),
                                "type": "line_overload",
                                "element": f"line_{int(li)}",
                                "name": "",
                                "value": f"{val:.1f}%",
                                "limit": f"{cfg.line_loading_limit_pct:.1f}%",
                                "severity": "critical" if val > 120.0 else "warning",
                            }
                        )
                    elif val > float(cfg.planning_warning_pct):
                        violations.append(
                            {
                                "hour": int(hour),
                                "type": "line_planning_warning",
                                "element": f"line_{int(li)}",
                                "name": "",
                                "value": f"{val:.1f}%",
                                "limit": f"{cfg.planning_warning_pct:.1f}%",
                                "severity": "warning",
                            }
                        )
        
        # Transformer overload detection (NEW)
        trafo_df = res.get("trafo_results")
        if isinstance(trafo_df, pd.DataFrame) and not trafo_df.empty and "loading_percent" in trafo_df.columns:
            for ti, row in trafo_df.iterrows():
                val = float(pd.to_numeric(row.get("loading_percent", np.nan), errors="coerce"))
                if not np.isfinite(val):
                    continue
                if val > float(cfg.trafo_loading_limit_pct):
                    violations.append(
                        {
                            "hour": int(hour),
                            "type": "trafo_overload",
                            "element": f"trafo_{int(ti)}",
                            "name": "",
                            "value": f"{val:.1f}%",
                            "limit": f"{cfg.trafo_loading_limit_pct:.1f}%",
                            "severity": "critical" if val > float(cfg.loading_severe_threshold) else "warning",
                        }
                    )

    violations_df = pd.DataFrame(violations)
    if violations_df.empty:
        violations_df = pd.DataFrame(
            columns=["hour", "type", "element", "name", "value", "limit", "severity"]
        )
    feasible = (
        len(
            violations_df[
                violations_df["type"].isin(["voltage", "line_overload", "trafo_overload", "non_convergence"])
            ]
        )
        == 0
    )

    # Enhanced KPIs with frequency analysis (NEW)
    voltage_hours = set(violations_df[violations_df["type"] == "voltage"]["hour"]) if not violations_df.empty else set()
    line_hours = set(violations_df[violations_df["type"] == "line_overload"]["hour"]) if not violations_df.empty else set()
    trafo_hours = set(violations_df[violations_df["type"] == "trafo_overload"]["hour"]) if not violations_df.empty else set()
    
    # Critical hours = voltage OR trafo OR line (all are critical violations)
    critical_hours = voltage_hours | trafo_hours | line_hours
    
    # Worst-case element tracking
    worst_vmin_bus = None
    worst_vmin_hour_final = None
    if not violations_df.empty and len(violations_df[violations_df["type"] == "voltage"]) > 0:
        voltage_vios = violations_df[violations_df["type"] == "voltage"].copy()
        # Extract numeric voltage from string format "0.8500 pu"
        voltage_vios["v_numeric"] = voltage_vios["value"].str.replace(" pu", "").astype(float)
        worst_idx = voltage_vios["v_numeric"].idxmin()
        worst_vmin = float(voltage_vios.loc[worst_idx, "v_numeric"])
        worst_vmin_bus = str(voltage_vios.loc[worst_idx, "element"]).replace("bus_", "")
        worst_vmin_hour_final = int(voltage_vios.loc[worst_idx, "hour"])
    
    max_loading_line = None
    max_loading_hour_final = None
    if not violations_df.empty and len(violations_df[violations_df["type"] == "line_overload"]) > 0:
        line_vios = violations_df[violations_df["type"] == "line_overload"].copy()
        line_vios["loading_numeric"] = line_vios["value"].str.replace("%", "").astype(float)
        worst_idx = line_vios["loading_numeric"].idxmax()
        max_loading = float(line_vios.loc[worst_idx, "loading_numeric"])
        max_loading_line = str(line_vios.loc[worst_idx, "element"]).replace("line_", "")
        max_loading_hour_final = int(line_vios.loc[worst_idx, "hour"])
    
    max_loading_trafo = None
    max_trafo_loading_pct = None
    max_loading_trafo_hour = None
    if not violations_df.empty and len(violations_df[violations_df["type"] == "trafo_overload"]) > 0:
        trafo_vios = violations_df[violations_df["type"] == "trafo_overload"].copy()
        trafo_vios["loading_numeric"] = trafo_vios["value"].str.replace("%", "").astype(float)
        worst_idx = trafo_vios["loading_numeric"].idxmax()
        max_trafo_loading_pct = float(trafo_vios.loc[worst_idx, "loading_numeric"])
        max_loading_trafo = str(trafo_vios.loc[worst_idx, "element"]).replace("trafo_", "")
        max_loading_trafo_hour = int(trafo_vios.loc[worst_idx, "hour"])
    
    kpis = {
        "feasible": bool(feasible),
        "hours_total": int(len(results_by_hour)),
        "hours_converged": int(converged_hours),
        
        # Violation counts (total rows)
        "voltage_violations_total": int((violations_df["type"] == "voltage").sum()) if not violations_df.empty else 0,
        "line_violations_total": int((violations_df["type"] == "line_overload").sum()) if not violations_df.empty else 0,
        "trafo_violations_total": int((violations_df["type"] == "trafo_overload").sum()) if not violations_df.empty else 0,
        "planning_warnings_total": int((violations_df["type"] == "line_planning_warning").sum()) if not violations_df.empty else 0,
        
        # Frequency analysis (unique hours affected) - NEW
        "voltage_violated_hours": len(voltage_hours),
        "line_overload_hours": len(line_hours),
        "trafo_overload_hours": len(trafo_hours),
        "critical_hours_count": len(critical_hours),
        "critical_hours_fraction": len(critical_hours) / len(results_by_hour) if len(results_by_hour) > 0 else 0.0,
        
        # Worst-case values with element tracking
        "worst_vmin_pu": float(worst_vmin) if np.isfinite(worst_vmin) else None,
        "worst_vmin_bus": worst_vmin_bus,
        "worst_vmin_hour": worst_vmin_hour_final,
        
        "max_feeder_loading_pct": float(max_loading) if np.isfinite(max_loading) else None,
        "max_loading_line": max_loading_line,
        "max_feeder_loading_hour": max_loading_hour_final,
        
        "max_trafo_loading_pct": max_trafo_loading_pct,
        "max_loading_trafo": max_loading_trafo,
        "max_loading_trafo_hour": max_loading_trafo_hour,
    }
    
    # Feeder distance metrics (NEW)
    if net is not None and worst_vmin_bus is not None:
        kpis["feeder_metrics"] = _compute_feeder_distance(net, worst_vmin_bus, cfg)
    
    return kpis, violations_df


def _compute_feeder_distance(net, worst_bus: str, cfg: DHAConfig) -> Dict[str, object]:
    """
    Compute distance from transformer to worst-case voltage bus using networkx.
    
    Args:
        net: pandapower network
        worst_bus: Bus ID (as string) with worst voltage violation
        cfg: DHA configuration
        
    Returns:
        Dictionary with distance_km, long_feeder flag, and threshold
    """
    try:
        import networkx as nx
    except ImportError:
        return {"long_feeder": False, "distance_km": None, "warning": "networkx not available"}
    
    # Build networkx graph from LV lines
    G = nx.Graph()
    
    if not hasattr(net, "line") or net.line.empty:
        return {"long_feeder": False, "distance_km": None, "warning": "No lines in network"}
    
    for idx, line in net.line.iterrows():
        length_km = float(line.get("length_km", 0.0))
        G.add_edge(int(line["from_bus"]), int(line["to_bus"]), weight=length_km)
    
    # Find transformer LV buses
    trafo_lv_buses = []
    if hasattr(net, "trafo") and not net.trafo.empty:
        trafo_lv_buses = [int(b) for b in net.trafo["lv_bus"].tolist()]
    
    if not trafo_lv_buses:
        # No transformers - try external grid connection buses
        if hasattr(net, "ext_grid") and not net.ext_grid.empty:
            trafo_lv_buses = [int(b) for b in net.ext_grid["bus"].tolist()]
    
    if not trafo_lv_buses:
        return {"long_feeder": False, "distance_km": None, "warning": "No transformers or ext_grid found"}
    
    worst_bus_int = int(worst_bus)
    
    # Compute shortest path from any transformer/source to worst bus
    min_distance = float("inf")
    
    for trafo_bus in trafo_lv_buses:
        try:
            if nx.has_path(G, trafo_bus, worst_bus_int):
                distance = nx.shortest_path_length(G, trafo_bus, worst_bus_int, weight="weight")
                min_distance = min(min_distance, distance)
        except (nx.NetworkXError, KeyError, ValueError):
            continue
    
    if min_distance == float("inf"):
        return {"long_feeder": False, "distance_km": None, "warning": "No path to worst bus"}
    
    long_feeder = min_distance >= float(cfg.long_feeder_km_threshold)
    
    return {
        "distance_km": round(min_distance, 3),
        "long_feeder": long_feeder,
        "threshold_km": float(cfg.long_feeder_km_threshold)
    }
