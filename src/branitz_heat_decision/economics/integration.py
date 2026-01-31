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
from pathlib import Path
from typing import Any, Dict, Optional

from branitz_heat_decision.config import RESULTS_ROOT, resolve_cluster_path


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
