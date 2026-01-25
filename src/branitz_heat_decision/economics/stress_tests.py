"""
Stress Testing Module

Evaluates decision robustness under extreme but plausible counterfactual scenarios.
Tests whether the recommended heating solution remains stable under economic shocks.
"""

import logging
from typing import Dict, Any, Tuple
import copy

logger = logging.getLogger(__name__)


# Predefined stress scenarios
STRESS_SCENARIOS = {
    "elec_shock_down": {
        "description": "Electricity price drops 20% (favorable to Heat Pumps)",
        "params": {"electricity_price_eur_per_mwh": 0.80}  # multiplier
    },
    "elec_shock_up": {
        "description": "Electricity price spikes 20% (unfavorable to Heat Pumps)",
        "params": {"electricity_price_eur_per_mwh": 1.20}
    },
    "demand_spike": {
        "description": "Peak demand increases 10% (network/grid stress)",
        "params": {"design_capacity_multiplier": 1.10}
    },
    "pipe_capex_shock": {
        "description": "Pipe costs surge 30% (unfavorable to District Heating)",
        "params": {"pipe_cost_multiplier": 1.30}
    },
    "grid_decarbonization": {
        "description": "Electricity grid CO₂ factor halves (favorable to Heat Pumps)",
        "params": {"ef_electricity_kg_per_mwh": 0.50}
    },
    "hp_tech_improvement": {
        "description": "Heat Pump COP improves 15% (favorable to Heat Pumps)",
        "params": {"cop_default": 1.15}
    }
}


def apply_stress_scenario(base_params: Dict[str, Any], scenario_params: Dict[str, str]) -> Dict[str, Any]:
    """
    Apply stress scenario parameter modifications.
    
    Args:
        base_params: Base economic parameters
        scenario_params: Dictionary of parameter multipliers/overrides
    
    Returns:
        Modified parameter dictionary
    """
    stressed_params = copy.deepcopy(base_params)
    
    for param, value in scenario_params.items():
        if param == "design_capacity_multiplier":
            # This will be handled separately in compute_lcoh call
            stressed_params["_design_capacity_multiplier"] = value
        elif param in stressed_params:
            if isinstance(value, float) and value < 2.0:  # Likely a multiplier
                stressed_params[param] = base_params[param] * value
            else:
                stressed_params[param] = value
        else:
            logger.warning(f"Parameter {param} not in base_params, creating new entry")
            stressed_params[param] = value
    
    # Handle pipe cost multiplier (affects all DN sizes)
    if "pipe_cost_multiplier" in scenario_params:
        multiplier = scenario_params["pipe_cost_multiplier"]
        if "pipe_cost_eur_per_m" in stressed_params and isinstance(stressed_params["pipe_cost_eur_per_m"], dict):
            for dn, cost in stressed_params["pipe_cost_eur_per_m"].items():
                stressed_params["pipe_cost_eur_per_m"][dn] = cost * multiplier
        # Remove the multiplier key itself (it's not a valid EconomicsParam)
        if "pipe_cost_multiplier" in stressed_params:
            del stressed_params["pipe_cost_multiplier"]
    
    return stressed_params


def compute_lcoh_stressed(
    annual_heat_mwh: float,
    design_capacity_kw: float,
    cha_kpis: Dict[str, Any],
    dha_kpis: Dict[str, Any],
    params: Dict[str, Any]
) -> Tuple[float, float]:
    """
    Compute LCoH with stress scenario adjustments.
    
    Returns:
        (lcoh_dh, lcoh_hp) in EUR/MWh
    """
    from branitz_heat_decision.economics.lcoh import compute_lcoh_dh, compute_lcoh_hp
    from branitz_heat_decision.economics import get_default_economics_params
    
    pipe_lengths_by_dn = cha_kpis.get("pipe_lengths_by_dn")
    total_pipe_length_m = cha_kpis.get("total_pipe_length_m", 0.0)
    pump_power_kw = cha_kpis.get("pump_power_kw", 0.0)
    max_feeder_loading_pct = dha_kpis.get("max_feeder_loading_pct", 0.0)
    
    # Handle design capacity multiplier
    design_capacity_adjusted = design_capacity_kw
    if "_design_capacity_multiplier" in params:
        design_capacity_adjusted = design_capacity_kw * params["_design_capacity_multiplier"]
    
    # Get default params to build params class
    default_params = get_default_economics_params()
    cop_annual_average = params.get("cop_default", default_params.cop_default)
    params_clean = {k: v for k, v in params.items() if not k.startswith("_")}
    params_obj = default_params.__class__(**params_clean)
    
    lcoh_dh, _ = compute_lcoh_dh(
        annual_heat_mwh=annual_heat_mwh,
        pipe_lengths_by_dn=pipe_lengths_by_dn,
        total_pipe_length_m=total_pipe_length_m,
        pump_power_kw=pump_power_kw,
        params=params_obj
    )
    
    lcoh_hp, _ = compute_lcoh_hp(
        annual_heat_mwh=annual_heat_mwh,
        hp_total_capacity_kw_th=design_capacity_adjusted,
        cop_annual_average=float(cop_annual_average),
        max_feeder_loading_pct=max_feeder_loading_pct,
        params=params_obj
    )
    
    return lcoh_dh, lcoh_hp


def run_stress_tests(
    cluster_id: str,
    annual_heat_mwh: float,
    design_capacity_kw: float,
    cha_kpis: Dict[str, Any],
    dha_kpis: Dict[str, Any],
    base_params: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Run predefined stress test scenarios to evaluate decision robustness.
    
    Args:
        cluster_id: Cluster identifier
        annual_heat_mwh: Annual heat demand
        design_capacity_kw: Design heating capacity
        cha_kpis: District heating KPIs
        dha_kpis: Heat pump KPIs
        base_params: Base economic parameters
    
    Returns:
        Dictionary with stress test results and robustness flag
    """
    logger.info(f"Starting stress tests for {cluster_id}")
    
    # Compute base case
    base_lcoh_dh, base_lcoh_hp = compute_lcoh_stressed(
        annual_heat_mwh, design_capacity_kw, cha_kpis, dha_kpis, base_params
    )
    base_decision = "DH" if base_lcoh_dh < base_lcoh_hp else "HP"
    base_winner_lcoh = base_lcoh_dh if base_decision == "DH" else base_lcoh_hp
    
    logger.info(f"Base case: LCoH_DH={base_lcoh_dh:.2f}, LCoH_HP={base_lcoh_hp:.2f}, Decision={base_decision}")
    
    results = {}
    flips_detected = 0
    worst_case_scenario = None
    max_cost_shift = 0.0
    
    for scenario_id, scenario in STRESS_SCENARIOS.items():
        logger.info(f"Running scenario: {scenario_id}")
        
        # Apply stress
        stressed_params = apply_stress_scenario(base_params, scenario["params"])
        
        # Compute stressed LCoH
        lcoh_dh_stressed, lcoh_hp_stressed = compute_lcoh_stressed(
            annual_heat_mwh, design_capacity_kw, cha_kpis, dha_kpis, stressed_params
        )
        
        decision_stressed = "DH" if lcoh_dh_stressed < lcoh_hp_stressed else "HP"
        flipped = (decision_stressed != base_decision)
        
        if flipped:
            flips_detected += 1
            logger.warning(f"{scenario_id}: Decision FLIPPED to {decision_stressed}")
        
        # Calculate cost shift (how much the winner's advantage changed)
        winner_lcoh_stressed = lcoh_dh_stressed if base_decision == "DH" else lcoh_hp_stressed
        cost_shift_pct = ((winner_lcoh_stressed - base_winner_lcoh) / base_winner_lcoh * 100) if base_winner_lcoh > 0 else 0
        
        if abs(cost_shift_pct) > abs(max_cost_shift):
            max_cost_shift = cost_shift_pct
            worst_case_scenario = scenario_id
        
        results[scenario_id] = {
            "description": scenario["description"],
            "parameters_changed": scenario["params"],
            "lcoh_dh": lcoh_dh_stressed,
            "lcoh_hp": lcoh_hp_stressed,
            "decision": decision_stressed,
            "flipped": flipped,
            "cost_shift_pct": cost_shift_pct
        }
    
    robust = (flips_detected == 0)
    
    logger.info(f"Stress tests complete: {len(results)} scenarios tested, flips={flips_detected}, robust={robust}")
    
    return {
        "cluster_id": cluster_id,
        "base_decision": base_decision,
        "base_lcoh_dh": base_lcoh_dh,
        "base_lcoh_hp": base_lcoh_hp,
        "scenarios_tested": len(STRESS_SCENARIOS),
        "flips_detected": flips_detected,
        "robust": robust,
        "worst_case_scenario": worst_case_scenario,
        "max_cost_shift_pct": max_cost_shift,
        "results": results
    }
