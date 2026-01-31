#!/usr/bin/env python3
"""
Phase 4 — Economics & Monte Carlo

Computes:
- LCOH (CRF method) for DH and HP
- CO2 (t/a) for DH and HP
- Monte Carlo uncertainty propagation (N default = 500)

Outputs:
results/economics/<cluster_id>/
  - economics_deterministic.json
  - economics_monte_carlo.json
  - economics_monte_carlo_samples.csv
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1]))

from branitz_heat_decision.config import (
    BUILDING_CLUSTER_MAP_PATH,
    DESIGN_TOPN_PATH,
    HOURLY_PROFILES_PATH,
    RESULTS_ROOT,
    resolve_cluster_path,
)
from branitz_heat_decision.economics import (
    DHInputs,
    HPInputs,
    get_default_economics_params,
    get_default_monte_carlo_params,
    compute_lcoh_dh,
    compute_lcoh_hp,
    compute_co2_dh,
    compute_co2_hp,
    lcoh_dh_crf,
    lcoh_hp_crf,
    co2_dh,
    co2_hp,
    run_monte_carlo,
)
from branitz_heat_decision.economics.lcoh import build_plant_context_from_params
from branitz_heat_decision.economics.co2 import DHCO2Inputs, HPCO2Inputs


def _load_cluster_building_ids(cluster_id: str) -> List[str]:
    df = pd.read_parquet(BUILDING_CLUSTER_MAP_PATH)
    df = df[df["cluster_id"] == cluster_id]
    return [str(x) for x in df["building_id"].tolist()]


def _load_cluster_design_hour(cluster_id: str) -> int:
    obj = json.loads(Path(DESIGN_TOPN_PATH).read_text(encoding="utf-8"))
    return int(obj["clusters"][cluster_id]["design_hour"])


def _load_annual_heat_mwh(cluster_building_ids: List[str]) -> float:
    # hourly_heat_profiles.parquet: index hour (0..8759), columns building_id, values kW
    prof = pd.read_parquet(HOURLY_PROFILES_PATH)
    cols = [c for c in prof.columns if str(c) in set(cluster_building_ids)]
    if not cols:
        raise ValueError("No hourly heat profiles found for cluster buildings (no matching building_id columns).")
    heat_kw = prof[cols].sum(axis=1)  # kW per hour
    heat_kwh = float(heat_kw.sum())  # (kW) summed over hours -> kWh
    return heat_kwh / 1000.0


def _load_design_capacity_kw(cluster_building_ids: List[str], design_hour: int) -> float:
    prof = pd.read_parquet(HOURLY_PROFILES_PATH)
    cols = [c for c in prof.columns if str(c) in set(cluster_building_ids)]
    if not cols:
        raise ValueError("No hourly heat profiles found for cluster buildings (no matching building_id columns).")
    return float(prof.loc[int(design_hour), cols].sum())


def _load_dh_lengths_m_from_cha(cluster_id: str) -> Dict[str, float]:
    """
    Best-effort extraction from CHA KPIs.
    If not present, returns zeros (then DH capex is driven only by plant in this MVP).
    """
    kpi_path = resolve_cluster_path(cluster_id, "cha") / "cha_kpis.json"
    if not kpi_path.exists():
        return {"trunk_m": 0.0, "service_m": 0.0}
    k = json.loads(kpi_path.read_text(encoding="utf-8"))
    # Preferred: current CHA KPI schema has lengths under "losses" (and repeated in "aggregate").
    blk = k.get("losses") or k.get("aggregate") or {}
    length_supply_m = float(blk.get("length_supply_m", 0.0))
    length_return_m = float(blk.get("length_return_m", 0.0))
    length_service_m = float(blk.get("length_service_m", 0.0))

    # Interpretation (as currently exported by kpi_extractor):
    # - length_supply_m: trunk supply (excludes service)
    # - length_return_m: trunk return (excludes service)
    # - length_service_m: service pipes total (supply+return)
    trunk_m = length_supply_m + length_return_m
    service_m = length_service_m

    # Fallbacks if schema differs.
    if trunk_m <= 0.0 and service_m <= 0.0:
        total_m = float(blk.get("length_total_m", 0.0)) or float(k.get("total_pipe_length_m", 0.0))
        trunk_m = total_m
        service_m = 0.0
    return {"trunk_m": trunk_m, "service_m": service_m}


def _load_dh_pipe_capex_eur_from_cha(cluster_id: str, params) -> float:
    """
    Compute DH pipe CAPEX using per-pipe length and diameter exported by CHA:
      results/cha/<cluster>/pipe_velocities_supply_return_with_temp.csv
        - length_m
        - diameter_mm

    DN key is derived as f"DN{int(round(diameter_mm))}" and looked up in params.pipe_cost_eur_per_m.
    """
    p = resolve_cluster_path(cluster_id, "cha") / "pipe_velocities_supply_return_with_temp.csv"
    if not p.exists():
        lengths = _load_dh_lengths_m_from_cha(cluster_id)
        avg_cost = float(sum(params.pipe_cost_eur_per_m.values()) / max(1, len(params.pipe_cost_eur_per_m)))
        return float((lengths["trunk_m"] + lengths["service_m"]) * avg_cost)

    df = pd.read_csv(p)
    capex = 0.0
    for _, r in df.iterrows():
        dn_key = f"DN{int(round(float(r['diameter_mm'])))}"
        cost_per_m = params.pipe_cost_eur_per_m.get(dn_key)
        if cost_per_m is None:
            continue
        capex += float(r["length_m"]) * float(cost_per_m)
    return float(capex)


def _load_pump_power_kw_from_cha(cluster_id: str) -> float:
    kpi_path = resolve_cluster_path(cluster_id, "cha") / "cha_kpis.json"
    if not kpi_path.exists():
        return 0.0
    k = json.loads(kpi_path.read_text(encoding="utf-8"))
    return float((k.get("pump") or {}).get("pump_power_kw", 0.0))


def _load_pipe_lengths_by_dn_from_cha(cluster_id: str) -> Dict[str, float]:
    """
    Build {DNxxx: length_m} from CHA per-pipe export (length_m + diameter_mm).
    Uses DN = int(round(diameter_mm)).
    """
    p = resolve_cluster_path(cluster_id, "cha") / "pipe_velocities_supply_return_with_temp.csv"
    if not p.exists():
        return {}
    df = pd.read_csv(p)
    if "length_m" not in df.columns or "diameter_mm" not in df.columns:
        return {}
    out: Dict[str, float] = {}
    for _, r in df.iterrows():
        dn_key = f"DN{int(round(float(r['diameter_mm'])))}"
        out[dn_key] = out.get(dn_key, 0.0) + float(r["length_m"])
    return out


def _load_total_pipe_length_m_from_cha(cluster_id: str) -> float:
    p = resolve_cluster_path(cluster_id, "cha") / "pipe_velocities_supply_return_with_temp.csv"
    if not p.exists():
        return 0.0
    df = pd.read_csv(p)
    if "length_m" not in df.columns:
        return 0.0
    return float(df["length_m"].sum())


def _load_max_feeder_loading_pct_from_dha(cluster_id: str) -> float:
    p = resolve_cluster_path(cluster_id, "dha") / "dha_kpis.json"
    if not p.exists():
        return 0.0
    obj = json.loads(p.read_text(encoding="utf-8"))
    return float((obj.get("kpis") or {}).get("max_feeder_loading_pct", 0.0))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cluster-id", required=True, type=str)
    ap.add_argument("--n", type=int, default=500, help="Monte Carlo samples (default 500)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument(
        "--plant-cost-allocation",
        type=str,
        default="full",
        choices=["full", "marginal", "proportional", "none"],
        help="Plant cost allocation: full (default), marginal, proportional, none",
    )
    ap.add_argument("--sensitivity", action="store_true", help="Run sensitivity analysis (±5% parameter variations)")
    ap.add_argument("--stress-tests", action="store_true", help="Run stress test scenarios")
    ap.add_argument("--full-validation", action="store_true", help="Run all validation: Monte Carlo + Sensitivity + Stress Tests")
    args = ap.parse_args()

    cluster_id = args.cluster_id
    cluster_building_ids = _load_cluster_building_ids(cluster_id)
    design_hour = _load_cluster_design_hour(cluster_id)
    annual_heat_mwh = _load_annual_heat_mwh(cluster_building_ids)
    design_capacity_kw = _load_design_capacity_kw(cluster_building_ids, design_hour)

    from dataclasses import replace

    params = get_default_economics_params()
    params = replace(params, plant_cost_allocation=args.plant_cost_allocation)

    lengths = _load_dh_lengths_m_from_cha(cluster_id)
    pipe_lengths_by_dn = _load_pipe_lengths_by_dn_from_cha(cluster_id)
    total_pipe_length_m = _load_total_pipe_length_m_from_cha(cluster_id)
    pump_power_kw = _load_pump_power_kw_from_cha(cluster_id)

    dh_inputs = DHInputs(
        heat_mwh_per_year=annual_heat_mwh,
        pipe_lengths_by_dn=pipe_lengths_by_dn or None,
        total_pipe_length_m=total_pipe_length_m,
        pump_power_kw=pump_power_kw,
    )

    max_feeder_loading_pct = _load_max_feeder_loading_pct_from_dha(cluster_id)
    hp_inputs = HPInputs(
        heat_mwh_per_year=annual_heat_mwh,
        hp_total_capacity_kw_th=design_capacity_kw,
        cop_annual_average=float(params.cop_default),
        max_feeder_loading_pct=max_feeder_loading_pct,
    )

    plant_ctx = build_plant_context_from_params(params)
    lcoh_dh, lcoh_dh_breakdown = compute_lcoh_dh(
        annual_heat_mwh=annual_heat_mwh,
        pipe_lengths_by_dn=pipe_lengths_by_dn or None,
        total_pipe_length_m=total_pipe_length_m,
        pump_power_kw=pump_power_kw,
        params=params,
        plant_cost_allocation=params.plant_cost_allocation,
        plant_context=plant_ctx,
        street_peak_load_kw=design_capacity_kw,
        district_total_design_capacity_kw=params.district_total_design_capacity_kw or None,
    )
    lcoh_hp, lcoh_hp_breakdown = compute_lcoh_hp(
        annual_heat_mwh=annual_heat_mwh,
        hp_total_capacity_kw_th=design_capacity_kw,
        cop_annual_average=float(params.cop_default),
        max_feeder_loading_pct=max_feeder_loading_pct,
        params=params,
    )

    co2_dh_kg_per_mwh, co2_dh_breakdown = compute_co2_dh(
        annual_heat_mwh=annual_heat_mwh,
        params=params,
    )
    co2_hp_kg_per_mwh, co2_hp_breakdown = compute_co2_hp(
        annual_heat_mwh=annual_heat_mwh,
        cop_annual_average=float(params.cop_default),
        params=params,
    )

    det = {
        "cluster_id": cluster_id,
        "annual_heat_mwh": annual_heat_mwh,
        "design_capacity_kw": design_capacity_kw,
        "dh_lengths_m": lengths,
        "pump_power_kw": pump_power_kw,
        "total_pipe_length_m": total_pipe_length_m,
        "pipe_lengths_by_dn_m": pipe_lengths_by_dn,
        "max_feeder_loading_pct": max_feeder_loading_pct,
        "lcoh_dh_eur_per_mwh": float(lcoh_dh),
        "lcoh_hp_eur_per_mwh": float(lcoh_hp),
        "lcoh_dh_breakdown": lcoh_dh_breakdown,
        "lcoh_hp_breakdown": lcoh_hp_breakdown,
        "co2_dh_kg_per_mwh": float(co2_dh_kg_per_mwh),
        "co2_hp_kg_per_mwh": float(co2_hp_kg_per_mwh),
        "co2_dh_breakdown": co2_dh_breakdown,
        "co2_hp_breakdown": co2_hp_breakdown,
        # Back-compat totals (t/a)
        "co2_dh_t_per_a": co2_dh(DHCO2Inputs(heat_mwh_per_year=annual_heat_mwh), params),
        "co2_hp_t_per_a": co2_hp(HPCO2Inputs(heat_mwh_per_year=annual_heat_mwh), params),
        "params": {
            "discount_rate": params.discount_rate,
            "lifetime_years": params.lifetime_years,
            "dh_generation_type": params.dh_generation_type,
            "pipe_cost_eur_per_m": params.pipe_cost_eur_per_m,
            "plant_cost_base_eur": params.plant_cost_base_eur,
            "pump_cost_per_kw": params.pump_cost_per_kw,
            "dh_om_frac_per_year": params.dh_om_frac_per_year,
            "hp_cost_eur_per_kw_th": params.hp_cost_eur_per_kw_th,
            "hp_om_frac_per_year": params.hp_om_frac_per_year,
            "cop_default": params.cop_default,
            "electricity_price_eur_per_mwh": params.electricity_price_eur_per_mwh,
            "gas_price_eur_per_mwh": params.gas_price_eur_per_mwh,
            "biomass_price_eur_per_mwh": params.biomass_price_eur_per_mwh,
            "ef_electricity_kg_per_mwh": params.ef_electricity_kg_per_mwh,
            "ef_gas_kg_per_mwh": params.ef_gas_kg_per_mwh,
            "ef_biomass_kg_per_mwh": params.ef_biomass_kg_per_mwh,
            "feeder_loading_planning_limit": params.feeder_loading_planning_limit,
        "plant_cost_allocation": params.plant_cost_allocation,
        "plant_allocation": lcoh_dh_breakdown.get("plant_allocation", {}),
        },
    }

    mc = get_default_monte_carlo_params()
    mc = mc.__class__(**{**mc.__dict__, "n": int(args.n), "seed": int(args.seed)})

    mc_res = run_monte_carlo(dh_inputs=dh_inputs, hp_inputs=hp_inputs, base_params=params, mc=mc)

    out_dir = RESULTS_ROOT / "economics" / cluster_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "economics_deterministic.json").write_text(json.dumps(det, indent=2), encoding="utf-8")
    (out_dir / "economics_monte_carlo.json").write_text(json.dumps(mc_res.summary, indent=2), encoding="utf-8")

    pd.DataFrame(mc_res.samples).to_csv(out_dir / "economics_monte_carlo_samples.csv", index=False)
    print(f"Wrote: {out_dir}")
    
    # NEW: Sensitivity Analysis
    if args.sensitivity or args.full_validation:
        print("Running sensitivity analysis...")
        from branitz_heat_decision.economics.sensitivity import run_sensitivity_analysis
        
        # Prepare KPIs for sensitivity module
        cha_kpis = {"pipe_lengths_by_dn": pipe_lengths_by_dn, "total_pipe_length_m": total_pipe_length_m, "pump_power_kw": pump_power_kw}
        dha_kpis = {"max_feeder_loading_pct": max_feeder_loading_pct}
        
        sens_results = run_sensitivity_analysis(
            cluster_id=cluster_id,
            annual_heat_mwh=annual_heat_mwh,
            design_capacity_kw=design_capacity_kw,
            cha_kpis=cha_kpis,
            dha_kpis=dha_kpis,
            base_params=params.__dict__
        )
        
        (out_dir / "sensitivity_analysis.json").write_text(json.dumps(sens_results, indent=2), encoding="utf-8")
        print(f"  ✓ Sensitivity: any_flip={sens_results['any_flip_detected']}")
    
    # NEW: Stress Tests
    if args.stress_tests or args.full_validation:
        print("Running stress tests...")
        from branitz_heat_decision.economics.stress_tests import run_stress_tests
        
        # Prepare KPIs
        cha_kpis = {"pipe_lengths_by_dn": pipe_lengths_by_dn, "total_pipe_length_m": total_pipe_length_m, "pump_power_kw": pump_power_kw}
        dha_kpis = {"max_feeder_loading_pct": max_feeder_loading_pct}
        
        stress_results = run_stress_tests(
            cluster_id=cluster_id,
            annual_heat_mwh=annual_heat_mwh,
            design_capacity_kw=design_capacity_kw,
            cha_kpis=cha_kpis,
            dha_kpis=dha_kpis,
            base_params=params.__dict__
        )
        
        (out_dir / "stress_tests.json").write_text(json.dumps(stress_results, indent=2), encoding="utf-8")
        print(f"  ✓ Stress: robust={stress_results['robust']}, flips={stress_results['flips_detected']}")


if __name__ == "__main__":
    main()

