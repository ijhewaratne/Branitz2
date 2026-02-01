"""
Economics Integration — Build combined CHA+DHA results for compute_lcoh_dh_for_cluster.

Integration Checklist — ensures the pipeline passes the right data:

    1. Get pandapipes results (pipe lengths from CHA)
    2. Get pandapower LV results (upgrade needs from DHA)
    3. Combine for economics

Example usage in your main calculation pipeline:

    def process_cluster(cluster_id):
        # 1. Build combined CHA+DHA results
        combined_results = build_pipe_network_results_for_cluster(
            cluster_id=cluster_id,
            annual_heat_mwh=demand_mwh,  # from hourly profiles
            peak_load_kw=design_load_kw,  # from design hour
        )
        connection_length_m = get_trunk_connection_length_m(cluster_id)

        # 2. Get shared plant context (existing district plant)
        plant_context = PlantContext(
            total_capacity_kw=2000,
            utilized_capacity_kw=800,
            is_built=True,
        )

        # 3. Calculate with marginal cost
        economics = compute_lcoh_dh_for_cluster(
            annual_heat_demand_mwh=demand_mwh,
            pipe_network_results=combined_results,
            connection_length_m=connection_length_m,
            street_peak_load_kw=design_load_kw,
            plant_context=plant_context,
            cost_allocation_method='marginal',
        )
        return economics

Run with: python 03_run_economics.py --cluster-id X --use-cluster-method --plant-cost-allocation marginal
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from branitz_heat_decision.config import RESULTS_ROOT, resolve_cluster_path

logger = logging.getLogger(__name__)


def calculate_cluster_economics_correct(
    cluster_data: Dict[str, Any],
    params,
) -> Dict[str, Any]:
    """
    Corrected economics calculation with proper marginal cost and LV upgrade handling.

    - Fixes 0€ network cost by extracting pipe data from thermal_simulation.pipes
    - Fixes marginal cost bug by creating PlantContext when using marginal allocation
    - Fixes 0€ LV upgrade by passing max_feeder_loading_pct from lv_simulation

    Args:
        cluster_data: Dict with annual_demand_mwh, peak_load_kw, pipe_lengths_by_dn,
            total_pipe_length_m, pump_power_kw, thermal_simulation, lv_simulation
        params: EconomicParameters instance

    Returns:
        {"dh": {"lcoh": float, "breakdown": dict}, "hp": {"lcoh": float, "breakdown": dict}}
    """
    from branitz_heat_decision.economics.lcoh import (
        PlantContext,
        compute_lcoh_dh,
        compute_lcoh_hp,
        get_plant_context_for_marginal,
    )

    # ==========================================
    # 1. EXTRACT PIPE DATA (Fixes 0€ network cost)
    # ==========================================
    pipe_by_dn = cluster_data.get("pipe_lengths_by_dn") or {}
    total_pipe_m = cluster_data.get("total_pipe_length_m", 0.0)

    if not pipe_by_dn and total_pipe_m == 0:
        network_results = cluster_data.get("thermal_simulation", {})
        pipes = network_results.get("pipes", {})

        pipe_by_dn = {}
        total_pipe_m = 0.0
        for pipe_id, pipe_info in pipes.items():
            if isinstance(pipe_info, dict):
                dn = pipe_info.get("dn", "DN100")
                length = float(pipe_info.get("length_m", 0))
                pipe_by_dn[dn] = pipe_by_dn.get(dn, 0) + length
                total_pipe_m += length

        logger.info("Extracted pipes from thermal_simulation: %s, total: %.1fm", pipe_by_dn, total_pipe_m)

    # ==========================================
    # 2. CREATE PLANT CONTEXT (Cottbus CHP or from params)
    # ==========================================
    street_peak_kw = cluster_data.get("peak_load_kw", 0.0)

    if params.plant_total_capacity_kw > 0:
        plant_ctx = PlantContext(
            total_capacity_kw=float(params.plant_total_capacity_kw),
            total_cost_eur=float(params.plant_cost_base_eur),
            utilized_capacity_kw=float(params.plant_utilized_capacity_kw),
            is_built=True,
            marginal_cost_per_kw=float(params.plant_marginal_cost_per_kw_eur),
        )
    else:
        from branitz_heat_decision.economics.plant_context import get_plant_context_for_street

        plant_info = get_plant_context_for_street(street_peak_kw)
        plant_ctx = plant_info["context"]

    # ==========================================
    # 3. CALCULATE DH WITH MARGINAL COST
    # ==========================================
    try:
        lcoh_dh, dh_breakdown = compute_lcoh_dh(
            annual_heat_mwh=cluster_data["annual_demand_mwh"],
            pipe_lengths_by_dn=pipe_by_dn if pipe_by_dn else None,
            total_pipe_length_m=total_pipe_m,
            pump_power_kw=cluster_data.get("pump_power_kw", 5.0),
            params=params,
            plant_cost_allocation="marginal",
            plant_context=plant_ctx,
            street_peak_load_kw=street_peak_kw,
        )

        # Verify marginal actually worked
        if (
            dh_breakdown.get("plant_allocation", {}).get("method") == "marginal"
            and dh_breakdown.get("capex_plant", 0) >= params.plant_cost_base_eur * 0.99
        ):
            logger.error(
                "BUG: Method is marginal but full plant cost allocated! "
                "plant_context=%s, street_peak_load_kw=%s",
                plant_ctx,
                street_peak_kw,
            )

    except Exception as e:
        logger.error("DH calculation failed: %s", e)
        raise

    # ==========================================
    # 4. CALCULATE HP WITH LV UPGRADE (Fixes 0€ upgrade)
    # ==========================================
    lv_results = cluster_data.get("lv_simulation", cluster_data.get("lv_results", {}))
    max_loading_pct = lv_results.get("max_loading_pct", lv_results.get("max_feeder_loading_pct", 0.0))
    if isinstance(max_loading_pct, (int, float)):
        max_loading_pct = float(max_loading_pct)
    else:
        kpis = lv_results.get("kpis", lv_results)
        max_loading_pct = float(kpis.get("max_feeder_loading_pct", 0) if isinstance(kpis, dict) else 0)

    hp_capacity_kw = cluster_data.get("peak_load_kw", cluster_data.get("design_capacity_kw", 0.0))
    if hp_capacity_kw <= 0:
        peak_hours = cluster_data.get("peak_hours", 1800)
        hp_capacity_kw = cluster_data["annual_demand_mwh"] * 1000 / max(1, peak_hours)

    cop = getattr(params, "cop_annual_average", None) or getattr(params, "cop_default", 2.8)

    lcoh_hp, hp_breakdown = compute_lcoh_hp(
        annual_heat_mwh=cluster_data["annual_demand_mwh"],
        hp_total_capacity_kw_th=hp_capacity_kw,
        cop_annual_average=cop,
        max_feeder_loading_pct=max_loading_pct,
        params=params,
    )

    loading_threshold = params.feeder_loading_planning_limit * 100.0
    logger.info(
        "Max loading: %.1f%%, threshold: %.1f%%, LV upgrade: %.0f€",
        max_loading_pct,
        loading_threshold,
        hp_breakdown.get("capex_lv_upgrade", 0),
    )

    return {
        "dh": {"lcoh": lcoh_dh, "breakdown": dh_breakdown},
        "hp": {"lcoh": lcoh_hp, "breakdown": hp_breakdown},
    }


def calculate_economics_for_selected_street(
    cluster_id: str,
    cluster_data: Dict[str, Any],
    params,
) -> Dict[str, Any]:
    """
    Calculate economics for ANY street selected in UI.
    Uses shared Cottbus CHP plant context (sunk cost).
    """
    from branitz_heat_decision.economics.lcoh import compute_lcoh_dh, compute_lcoh_hp
    from branitz_heat_decision.economics.plant_context import COTTBUS_CHP, get_plant_context_for_street

    street_peak_kw = cluster_data.get("peak_load_kw", cluster_data.get("design_capacity_kw", 0.0))
    annual_demand_mwh = cluster_data["annual_demand_mwh"]

    # Pipe network
    pipe_network = cluster_data.get("pipe_network", cluster_data)
    pipe_by_dn = pipe_network.get("pipes_by_dn", pipe_network.get("pipe_lengths_by_dn")) or {}
    total_pipe_m = pipe_network.get("total_length_m", pipe_network.get("total_pipe_length_m", 0))

    # Fallback: extract from thermal_simulation
    if not pipe_by_dn and total_pipe_m == 0:
        pipes = cluster_data.get("thermal_simulation", {}).get("pipes", {})
        pipe_by_dn = {}
        for pid, pinfo in pipes.items():
            if isinstance(pinfo, dict):
                dn = pinfo.get("dn", "DN100")
                ln = float(pinfo.get("length_m", 0))
                pipe_by_dn[dn] = pipe_by_dn.get(dn, 0) + ln
                total_pipe_m += ln

    # 1. Get plant context (same for ALL streets)
    plant_info = get_plant_context_for_street(street_peak_kw)
    plant_ctx = plant_info["context"]

    # 2. Calculate DH with marginal cost
    lcoh_dh, dh_breakdown = compute_lcoh_dh(
        annual_heat_mwh=annual_demand_mwh,
        pipe_lengths_by_dn=pipe_by_dn if pipe_by_dn else None,
        total_pipe_length_m=total_pipe_m,
        pump_power_kw=cluster_data.get("pump_kw", cluster_data.get("pump_power_kw", 5.0)),
        params=params,
        plant_cost_allocation="marginal",
        plant_context=plant_ctx,
        street_peak_load_kw=street_peak_kw,
    )

    # 3. Calculate HP
    lv_results = cluster_data.get("lv_simulation", cluster_data.get("lv_results", {}))
    max_loading = lv_results.get("max_loading_pct", lv_results.get("max_feeder_loading_pct", 0))
    if not isinstance(max_loading, (int, float)):
        max_loading = float(lv_results.get("kpis", {}).get("max_feeder_loading_pct", 0))

    hp_cap = cluster_data.get("hp_capacity_kw", street_peak_kw)
    cop = getattr(params, "cop_annual_average", None) or getattr(params, "cop_default", 2.8)

    lcoh_hp, hp_breakdown = compute_lcoh_hp(
        annual_heat_mwh=annual_demand_mwh,
        hp_total_capacity_kw_th=hp_cap,
        cop_annual_average=cop,
        max_feeder_loading_pct=max_loading,
        params=params,
    )

    return {
        "cluster_id": cluster_id,
        "street_peak_load_kw": street_peak_kw,
        "plant_capacity_status": {
            "total_plant_kw": COTTBUS_CHP.total_capacity_kw_th,
            "available_kw": COTTBUS_CHP.available_capacity_kw,
            "street_share_pct": (street_peak_kw / COTTBUS_CHP.total_capacity_kw_th) * 100
            if COTTBUS_CHP.total_capacity_kw_th > 0
            else 0,
            "is_within_capacity": plant_info["is_within_capacity"],
        },
        "district_heating": {
            "lcoh_eur_per_mwh": lcoh_dh,
            "capex_total": dh_breakdown["capex_total"],
            "capex_plant_allocated": dh_breakdown["capex_plant"],
            "capex_pipes": dh_breakdown["capex_pipes"],
            "opex_energy_eur_per_mwh": params.gas_price_eur_per_mwh / 0.9,
            "fuel_type": "natural_gas",
            "plant_rationale": plant_info["allocation"].get("rationale", ""),
        },
        "heat_pump": {
            "lcoh_eur_per_mwh": lcoh_hp,
            "capex_total": hp_breakdown["capex_total"],
            "capex_hp": hp_breakdown["capex_hp"],
            "capex_lv_upgrade": hp_breakdown["capex_lv_upgrade"],
            "grid_loading_pct": max_loading,
        },
        "winner": "DH" if lcoh_dh < lcoh_hp else "HP",
        "cost_ratio": max(lcoh_dh, lcoh_hp) / min(lcoh_dh, lcoh_hp) if min(lcoh_dh, lcoh_hp) > 0 else 0,
    }


def build_pipe_network_results_for_cluster(
    cluster_id: str,
    annual_heat_mwh: float,
    peak_load_kw: float,
) -> Dict[str, Any]:
    """
    Build combined pipe_network_results from CHA and DHA artifacts.

    Loads:
    - CHA: pipe_velocities_supply_return_with_temp.csv → pipes dict
    - CHA: cha_kpis.json → trunk lengths, pump power
    - DHA: dha_kpis.json → mitigation/reinforcement info
    - DHA: dha_reinforcement.json → total_cost_eur (if available)

    Returns format expected by compute_lcoh_dh_for_cluster:
        {
            'pipes': {pipe_id: {'dn': 'DN100', 'length_m': 123.4}, ...},
            'total_pipe_length_m': float,
            'lv_results': {
                'transformer_upgrade_needed': bool,
                'cable_length_to_replace_m': float,
                'new_connection_length_m': float,
                'total_reinforcement_cost_eur': float,  # from DHA if available
            }
        }
    """
    cha_dir = resolve_cluster_path(cluster_id, "cha")
    dha_dir = resolve_cluster_path(cluster_id, "dha")

    pipes: Dict[str, Dict[str, Any]] = {}
    total_pipe_length_m = 0.0

    # --- 1. Load pipes from CHA pandapipes export ---
    pipe_csv = cha_dir / "pipe_velocities_supply_return_with_temp.csv"
    if pipe_csv.exists():
        import pandas as pd

        df = pd.read_csv(pipe_csv)
        for i, row in df.iterrows():
            length_m = float(row.get("length_m", 0))
            diameter_mm = float(row.get("diameter_mm", 100))
            dn = f"DN{int(round(diameter_mm))}"
            pipes[f"pipe_{i}"] = {"dn": dn, "length_m": length_m}
            total_pipe_length_m += length_m

    # --- 2. Load LV results from DHA ---
    lv_results: Dict[str, Any] = {}

    dha_kpis_path = dha_dir / "dha_kpis.json"
    if dha_kpis_path.exists():
        dha = json.loads(dha_kpis_path.read_text(encoding="utf-8"))
        kpis = dha.get("kpis", dha)
        feasible = dha.get("feasible", True)
        mitigations = dha.get("mitigations", {})
        recommendations = mitigations.get("recommendations", [])

        # Infer transformer upgrade from mitigation class or trafo violations
        lv_results["transformer_upgrade_needed"] = (
            mitigations.get("mitigation_class") in ("expansion", "reinforcement")
            and any(r.get("category") == "transformer" for r in recommendations)
        )

        # Sum estimated costs from recommendations if available
        total_rec = 0.0
        for rec in recommendations:
            if "estimated_cost_eur" in rec:
                total_rec += float(rec.get("estimated_cost_eur", 0))

        lv_results["total_reinforcement_cost_eur"] = total_rec

    # DHA reinforcement plan (if run with --plan-reinforcement)
    reinf_path = dha_dir / "dha_reinforcement.json"
    if reinf_path.exists():
        reinf = json.loads(reinf_path.read_text(encoding="utf-8"))
        total_eur = reinf.get("total_cost_eur", 0)
        lv_results["total_reinforcement_cost_eur"] = float(total_eur)
        lv_results["reinforcement_measures_count"] = len(reinf.get("measures", []))
        lv_results["is_sufficient"] = reinf.get("is_sufficient", False)

    return {
        "pipes": pipes,
        "total_pipe_length_m": total_pipe_length_m,
        "demand_mwh": annual_heat_mwh,
        "peak_load_kw": peak_load_kw,
        "lv_results": lv_results,
    }


def get_trunk_connection_length_m(cluster_id: str) -> float:
    """
    Get trunk connection length from plant to street (m).
    Uses CHA losses/aggregate length_supply_m + length_return_m.
    """
    cha_dir = resolve_cluster_path(cluster_id, "cha")
    kpi_path = cha_dir / "cha_kpis.json"
    if not kpi_path.exists():
        return 0.0
    k = json.loads(kpi_path.read_text(encoding="utf-8"))
    blk = k.get("losses") or k.get("aggregate") or {}
    length_supply_m = float(blk.get("length_supply_m", 0.0))
    length_return_m = float(blk.get("length_return_m", 0.0))
    return length_supply_m + length_return_m
