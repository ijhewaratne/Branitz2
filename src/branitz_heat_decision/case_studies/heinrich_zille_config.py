"""
Configuration for Heinrich-Zille-Straße demonstrating marginal cost principles.

Evaluates three cost allocation scenarios:
- marginal: True marginal cost (only incremental capacity)
- proportional: Proportional allocation by capacity share
- none: No plant cost (pure street infrastructure)
"""

from __future__ import annotations

from typing import Dict

from branitz_heat_decision.economics import PlantContext, get_default_economics_params
from branitz_heat_decision.economics.lcoh import compute_lcoh_dh, compute_lcoh_dh_for_cluster


def evaluate_heinrich_zille_scenarios(
    street_demand_mwh: float = 7907.0,
    street_peak_load_kw: float = 2700.0,
    pipe_lengths: Dict[str, float] | None = None,
    total_pipe_length_m: float = 6314.0,
    pump_power_kw: float = 0.0,
) -> Dict[str, Dict]:
    """
    Evaluate cost allocation scenarios for Heinrich-Zille-Straße.

    Args:
        street_demand_mwh: Annual heat demand (MWh)
        street_peak_load_kw: Design peak load (kW)
        pipe_lengths: Dict of {DN: length_m}
        total_pipe_length_m: Total pipe length fallback
        pump_power_kw: Pump power (kW)

    Returns:
        Dict of scenario_name -> compute_lcoh_dh result breakdown
    """
    if pipe_lengths is None:
        pipe_lengths = {"DN100": 3043.0, "DN50": 3005.0, "DN110": 211.0, "DN125": 55.0}

    params = get_default_economics_params()

    # Scenario 1: Existing plant with spare capacity (no marginal expansion)
    # Remaining 4000 kW > street need 3240 kW (2700*1.2) -> capex_plant=0
    existing_plant = PlantContext(
        total_capacity_kw=5000.0,
        total_cost_eur=1_500_000.0,
        utilized_capacity_kw=1000.0,
        is_built=True,
        marginal_cost_per_kw=150.0,  # €/kW for expansion
    )

    # Scenario 2: Constrained plant (marginal capacity triggered)
    constrained_plant = PlantContext(
        total_capacity_kw=2500.0,
        total_cost_eur=1_500_000.0,
        utilized_capacity_kw=2400.0,
        is_built=True,
        marginal_cost_per_kw=150.0,  # €/kW for expansion
    )

    results = {}

    # Marginal (spare capacity)
    lcoh, br = compute_lcoh_dh(
        annual_heat_mwh=street_demand_mwh,
        pipe_lengths_by_dn=pipe_lengths,
        total_pipe_length_m=total_pipe_length_m,
        pump_power_kw=pump_power_kw,
        params=params,
        plant_cost_allocation="marginal",
        plant_context=existing_plant,
        street_peak_load_kw=street_peak_load_kw,
    )
    br["lcoh_eur_per_mwh"] = lcoh
    results["marginal_spare_capacity"] = br

    # Marginal (capacity constrained)
    lcoh2, br2 = compute_lcoh_dh(
        annual_heat_mwh=street_demand_mwh,
        pipe_lengths_by_dn=pipe_lengths,
        total_pipe_length_m=total_pipe_length_m,
        pump_power_kw=pump_power_kw,
        params=params,
        plant_cost_allocation="marginal",
        plant_context=constrained_plant,
        street_peak_load_kw=street_peak_load_kw,
    )
    br2["lcoh_eur_per_mwh"] = lcoh2
    results["marginal_capacity_constrained"] = br2

    # Proportional (using existing plant capacity share)
    district_capacity = 5000.0
    lcoh3, br3 = compute_lcoh_dh(
        annual_heat_mwh=street_demand_mwh,
        pipe_lengths_by_dn=pipe_lengths,
        total_pipe_length_m=total_pipe_length_m,
        pump_power_kw=pump_power_kw,
        params=params,
        plant_cost_allocation="proportional",
        plant_context=existing_plant,
        street_peak_load_kw=street_peak_load_kw,
        district_total_design_capacity_kw=district_capacity,
    )
    br3["lcoh_eur_per_mwh"] = lcoh3
    results["proportional"] = br3

    # No plant cost
    lcoh4, br4 = compute_lcoh_dh(
        annual_heat_mwh=street_demand_mwh,
        pipe_lengths_by_dn=pipe_lengths,
        total_pipe_length_m=total_pipe_length_m,
        pump_power_kw=pump_power_kw,
        params=params,
        plant_cost_allocation="none",
    )
    results["no_plant"] = br4

    # Full (default)
    lcoh5, br5 = compute_lcoh_dh(
        annual_heat_mwh=street_demand_mwh,
        pipe_lengths_by_dn=pipe_lengths,
        total_pipe_length_m=total_pipe_length_m,
        pump_power_kw=pump_power_kw,
        params=params,
        plant_cost_allocation="full",
    )
    br5["lcoh_eur_per_mwh"] = lcoh5
    results["full"] = br5

    return results


def print_comparison(results: Dict[str, Dict]) -> None:
    """Pretty print the scenario comparison."""
    print("\n" + "=" * 80)
    print("HEINRICH-ZILLE-STRAßE: Marginal Cost vs Sunk Cost Analysis")
    print("=" * 80)

    for scenario, data in results.items():
        lcoh = data.get("lcoh_eur_per_mwh")
        if lcoh is None:
            lcoh = (data.get("capex_total", 0) * data.get("crf", 0) + data.get("opex_annual", 0)) / max(
                1, data.get("annual_heat_mwh", 1)
            )
        cap = data
        print(f"\n--- {scenario.upper().replace('_', ' ')} ---")
        print(f"LCOH: {lcoh:.2f} €/MWh")
        print(f"  Capex pipes: {cap.get('capex_pipes', 0):>10,.0f} €")
        print(f"  Capex pump:  {cap.get('capex_pump', 0):>10,.0f} €")
        print(f"  Capex plant: {cap.get('capex_plant', 0):>10,.0f} €")
        pa = data.get("plant_allocation", {})
        if isinstance(pa, dict):
            print(f"  Rationale:   {pa.get('rationale', 'N/A')}")

    print("\n" + "=" * 80)
    print("KEY: Marginal cost avoids over-penalizing individual streets for shared plant.")
    print("=" * 80)


if __name__ == "__main__":
    res = evaluate_heinrich_zille_scenarios()
    print_comparison(res)
