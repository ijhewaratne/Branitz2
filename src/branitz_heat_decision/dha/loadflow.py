from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

try:
    import pandapower as pp
except Exception as e:  # pragma: no cover
    raise ImportError("pandapower is required for DHA loadflow") from e


def assign_hp_loads(
    hourly_heat_profiles_df: pd.DataFrame,
    building_bus_map: pd.DataFrame,
    design_hour: int,
    topn_hours: List[int],
    cop: float,
    pf: float = 0.95,
    hp_three_phase: bool = True,
    base_profiles_kw: Optional[Union[pd.Series, pd.DataFrame]] = None,
    pf_base: float = 0.95,
    pf_hp: float = 0.95,
    use_pf_split: bool = False,
) -> Dict[int, pd.DataFrame]:
    """
    Create per-hour aggregated electrical loads per LV bus from:
      - base electrical demand (optional; from gebaeude_lastphasenV2.json scenario), and
      - HP incremental electricity derived from heat demand profiles.

    For each hour:
      P_el_kw = Q_th_kw / COP
      Q_kvar  = P_el_kw * tan(arccos(pf))

    Returns:
      dict[hour] -> DataFrame columns:
        [bus_id, p_base_kw, p_hp_kw, p_total_kw, q_base_kvar, q_hp_kvar, q_total_kvar, p_mw, q_mvar]
    """
    if cop <= 0:
        raise ValueError("cop must be > 0")
    if hourly_heat_profiles_df is None or hourly_heat_profiles_df.empty:
        raise ValueError("hourly_heat_profiles_df is empty")
    if "building_id" not in building_bus_map.columns or "bus_id" not in building_bus_map.columns:
        raise ValueError("building_bus_map must contain building_id and bus_id columns")

    hours = [int(design_hour)] + [int(h) for h in topn_hours if int(h) != int(design_hour)]
    hours = list(dict.fromkeys(hours))

    bmap = building_bus_map.copy()
    bmap = bmap[bmap["mapped"] == True].copy()  # noqa: E712
    bmap = bmap[pd.notna(bmap["bus_id"])].copy()
    if bmap.empty:
        raise ValueError("No buildings mapped to LV buses (all unmapped).")
    bmap["bus_id"] = bmap["bus_id"].astype(int)

    # Ensure building ids are strings for column matching
    bmap["building_id"] = bmap["building_id"].astype(str)

    # Reactive power settings
    pf = float(pf)
    if not (0 < pf <= 1):
        raise ValueError("pf must be in (0, 1]")
    pf_base = float(pf_base)
    pf_hp = float(pf_hp)
    if not (0 < pf_base <= 1) or not (0 < pf_hp <= 1):
        raise ValueError("pf_base and pf_hp must be in (0, 1]")
    tan_phi_total = float(np.tan(np.arccos(pf)))
    tan_phi_base = float(np.tan(np.arccos(pf_base)))
    tan_phi_hp = float(np.tan(np.arccos(pf_hp)))

    # Base loads can be:
    # - Series(index=building_id): constant P_base per building (kW)
    # - DataFrame(index=hour, columns=building_id): time-varying P_base (kW)
    base_profiles_kw = base_profiles_kw if base_profiles_kw is not None else pd.Series(dtype=float)
    base_series: pd.Series = pd.Series(dtype=float)
    base_df: Optional[pd.DataFrame] = None
    if isinstance(base_profiles_kw, pd.DataFrame):
        base_df = base_profiles_kw.copy()
        base_df.columns = base_df.columns.astype(str)
    elif isinstance(base_profiles_kw, pd.Series):
        base_series = base_profiles_kw.copy()
        base_series.index = base_series.index.astype(str)

    loads_by_hour: Dict[int, pd.DataFrame] = {}
    for hour in hours:
        if hour not in hourly_heat_profiles_df.index:
            raise ValueError(f"Hour {hour} not present in hourly_heat_profiles_df index")

        # Collect per-building heat demand for this hour (kW)
        # Missing buildings default to 0
        q_th_kw = {}
        row = hourly_heat_profiles_df.loc[hour]
        for bid in bmap["building_id"].tolist():
            try:
                q_th_kw[bid] = float(row.get(bid, 0.0))
            except Exception:
                q_th_kw[bid] = 0.0

        df = bmap[["building_id", "bus_id"]].copy()
        df["q_th_kw"] = df["building_id"].map(q_th_kw).fillna(0.0).astype(float)
        df["p_hp_kw"] = df["q_th_kw"] / float(cop)
        if base_df is not None:
            if hour not in base_df.index:
                raise ValueError(f"Hour {hour} not present in base_profiles_kw DataFrame index")
            base_row = base_df.loc[hour]
            df["p_base_kw"] = df["building_id"].map(base_row.to_dict()).fillna(0.0).astype(float)
        else:
            df["p_base_kw"] = df["building_id"].map(base_series).fillna(0.0).astype(float)
        df["p_total_kw"] = (df["p_base_kw"] + df["p_hp_kw"]).astype(float)

        if use_pf_split:
            df["q_base_kvar"] = df["p_base_kw"] * tan_phi_base
            df["q_hp_kvar"] = df["p_hp_kw"] * tan_phi_hp
            df["q_total_kvar"] = (df["q_base_kvar"] + df["q_hp_kvar"]).astype(float)
        else:
            df["q_base_kvar"] = 0.0
            df["q_hp_kvar"] = 0.0
            df["q_total_kvar"] = df["p_total_kw"] * tan_phi_total

        agg = (
            df.groupby("bus_id", as_index=False)[
                ["p_base_kw", "p_hp_kw", "p_total_kw", "q_base_kvar", "q_hp_kvar", "q_total_kvar"]
            ].sum()
        )
        agg["p_mw"] = agg["p_total_kw"] / 1000.0
        agg["q_mvar"] = agg["q_total_kvar"] / 1000.0
        loads_by_hour[hour] = agg[
            [
                "bus_id",
                "p_base_kw",
                "p_hp_kw",
                "p_total_kw",
                "q_base_kvar",
                "q_hp_kvar",
                "q_total_kvar",
                "p_mw",
                "q_mvar",
            ]
        ]

    return loads_by_hour


def run_loadflow(
    net: pp.pandapowerNet,
    loads_by_hour: Dict[int, pd.DataFrame],
    *,
    hp_three_phase: bool = True,
    run_3ph_if_available: bool = False,
) -> Dict[int, Dict[str, object]]:
    """
    Run pandapower loadflow for each hour.

    Implementation notes:
    - Default is balanced `pp.create_load` and `pp.runpp`.
    - If `hp_three_phase=False` and 3-phase solver is available, we can use `asymmetric_load` and `runpp_3ph`.
      Otherwise we fallback to balanced loads and document this in the result metadata.
    - For performance, we create the load elements once and update their p/q each hour.
    """
    if not loads_by_hour:
        raise ValueError("loads_by_hour is empty")

    # Create one load per bus (balanced) and update per hour
    bus_ids = sorted({int(b) for df in loads_by_hour.values() for b in df["bus_id"].astype(int).tolist()})
    if not bus_ids:
        raise ValueError("No bus ids found in loads_by_hour")

    # Balanced loads (default)
    bus_to_load_idx: Dict[int, int] = {}
    if net.load is None or net.load.empty:
        for b in bus_ids:
            idx = pp.create_load(net, bus=int(b), p_mw=0.0, q_mvar=0.0, name=f"hp_load_bus_{b}")
            bus_to_load_idx[int(b)] = int(idx)
    else:
        # reuse existing loads where possible (by name)
        for b in bus_ids:
            existing = net.load.index[net.load.get("name", "").astype(str) == f"hp_load_bus_{b}"]
            if len(existing) > 0:
                bus_to_load_idx[int(b)] = int(existing[0])
            else:
                idx = pp.create_load(net, bus=int(b), p_mw=0.0, q_mvar=0.0, name=f"hp_load_bus_{b}")
                bus_to_load_idx[int(b)] = int(idx)

    # Decide solver
    use_3ph = False
    runpp_3ph = None
    if (not hp_three_phase) and run_3ph_if_available:
        runpp_3ph = getattr(pp, "runpp_3ph", None)
        if callable(runpp_3ph) and hasattr(pp, "create_asymmetric_load"):
            use_3ph = True

    # If using 3ph imbalance, create one asymmetric load per bus and update per hour.
    bus_to_asym_load_idx: Dict[int, int] = {}
    if use_3ph:
        # Create if empty; else reuse by name
        if not hasattr(net, "asymmetric_load") or net.asymmetric_load is None:
            # pandapower should create this table once the first element is created
            pass
        for b in bus_ids:
            name = f"hp_asym_load_bus_{b}"
            existing = []
            if hasattr(net, "asymmetric_load") and net.asymmetric_load is not None and (not net.asymmetric_load.empty):
                existing = net.asymmetric_load.index[net.asymmetric_load.get("name", "").astype(str) == name].tolist()
            if existing:
                bus_to_asym_load_idx[int(b)] = int(existing[0])
            else:
                idx = pp.create_asymmetric_load(
                    net,
                    bus=int(b),
                    p_a_mw=0.0,
                    p_b_mw=0.0,
                    p_c_mw=0.0,
                    q_a_mvar=0.0,
                    q_b_mvar=0.0,
                    q_c_mvar=0.0,
                    name=name,
                )
                bus_to_asym_load_idx[int(b)] = int(idx)

    results: Dict[int, Dict[str, object]] = {}
    for hour, df in loads_by_hour.items():
        if use_3ph:
            # reset asymmetric loads
            if bus_to_asym_load_idx:
                idxs = list(bus_to_asym_load_idx.values())
                net.asymmetric_load.loc[idxs, ["p_a_mw", "p_b_mw", "p_c_mw"]] = 0.0
                net.asymmetric_load.loc[idxs, ["q_a_mvar", "q_b_mvar", "q_c_mvar"]] = 0.0

            # Put all HP power onto phase A (worst-case imbalance), unless extended later
            for _, r in df.iterrows():
                b = int(r["bus_id"])
                li = bus_to_asym_load_idx.get(b)
                if li is None:
                    continue
                net.asymmetric_load.at[li, "p_a_mw"] = float(r["p_mw"])
                net.asymmetric_load.at[li, "q_a_mvar"] = float(r["q_mvar"])
        else:
            # reset all balanced loads to 0
            net.load.loc[list(bus_to_load_idx.values()), "p_mw"] = 0.0
            net.load.loc[list(bus_to_load_idx.values()), "q_mvar"] = 0.0

            # set bus loads for this hour
            for _, r in df.iterrows():
                b = int(r["bus_id"])
                li = bus_to_load_idx.get(b)
                if li is None:
                    continue
                net.load.at[li, "p_mw"] = float(r["p_mw"])
                net.load.at[li, "q_mvar"] = float(r["q_mvar"])

        converged = False
        error: Optional[str] = None
        try:
            if use_3ph:
                runpp_3ph(net, init="auto")
            else:
                pp.runpp(net, algorithm="nr", init="auto", calculate_voltage_angles=False)
            converged = True
        except Exception as e:
            error = f"{type(e).__name__}: {e}"

        # Extract results snapshot
        res = {
            "hour": int(hour),
            "converged": bool(converged),
            "error": error,
            "solver": "runpp_3ph" if use_3ph else "runpp",
        }

        # Bus voltages
        if converged:
            if use_3ph and hasattr(net, "res_bus_3ph") and net.res_bus_3ph is not None and not net.res_bus_3ph.empty:
                bus_res = net.res_bus_3ph[["vm_a_pu", "vm_b_pu", "vm_c_pu"]].copy()
                bus_res["v_min_pu"] = bus_res.min(axis=1)
                res["bus_results"] = bus_res
            elif hasattr(net, "res_bus") and net.res_bus is not None and not net.res_bus.empty:
                bus_res = net.res_bus[["vm_pu"]].copy()
                bus_res["v_min_pu"] = bus_res["vm_pu"]
                res["bus_results"] = bus_res
            else:
                res["bus_results"] = pd.DataFrame()

            # Line loading
            if use_3ph and hasattr(net, "res_line_3ph") and net.res_line_3ph is not None and not net.res_line_3ph.empty:
                lr = net.res_line_3ph.copy()
                # Use legacy definition if i_max present
                if "i_a_ka" in lr.columns and "i_b_ka" in lr.columns and "i_c_ka" in lr.columns:
                    i_max = net.line["max_i_ka"] if "max_i_ka" in net.line.columns else None
                    if i_max is not None:
                        loading_pct = 100.0 * lr[["i_a_ka", "i_b_ka", "i_c_ka"]].max(axis=1) / i_max
                        lr = lr.assign(loading_percent=loading_pct)
                res["line_results"] = lr
            elif hasattr(net, "res_line") and net.res_line is not None and not net.res_line.empty:
                lr = net.res_line.copy()
                res["line_results"] = lr
            else:
                res["line_results"] = pd.DataFrame()
            
            # Transformer results (NEW)
            if hasattr(net, "res_trafo") and net.res_trafo is not None and not net.res_trafo.empty:
                trafo_res = net.res_trafo[[
                    "loading_percent", 
                    "p_hv_mw", 
                    "q_hv_mvar",
                    "i_hv_ka",
                    "i_lv_ka"
                ]].copy()
                res["trafo_results"] = trafo_res
            else:
                res["trafo_results"] = pd.DataFrame()
        else:
            res["bus_results"] = pd.DataFrame()
            res["line_results"] = pd.DataFrame()

        results[int(hour)] = res

    return results

