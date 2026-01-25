"""
Sensitivity Analysis Module

Performs One-At-A-Time (OAT) parameter variation to assess decision robustness.
Varies each economic parameter by ±5% while holding others constant.
"""

import logging
from typing import Dict, Any, List, Tuple
import copy

logger = logging.getLogger(__name__)


def compute_lcoh(
    annual_heat_mwh: float,
    design_capacity_kw: float,
    cha_kpis: Dict[str, Any],
    dha_kpis: Dict[str, Any],
    params: Dict[str, Any]
) -> Tuple[float, float]:
    """
    Compute LCoH for both DH and HP given parameters.
    
    Returns:
        (lcoh_dh, lcoh_hp) in EUR/MWh
    """
    from branitz_heat_decision.economics.lcoh import compute_lcoh_dh, compute_lcoh_hp
    from branitz_heat_decision.economics import get_default_economics_params
    
    pipe_lengths_by_dn = cha_kpis.get("pipe_lengths_by_dn")
    total_pipe_length_m = cha_kpis.get("total_pipe_length_m", 0.0)
    pump_power_kw = cha_kpis.get("pump_power_kw", 0.0)
    max_feeder_loading_pct = dha_kpis.get("max_feeder_loading_pct", 0.0)
    
    # Get default params to build params class
    default_params = get_default_economics_params()
    cop_annual_average = params.get("cop_default", default_params.cop_default)
    params_obj = default_params.__class__(**params)
    
    lcoh_dh, _ = compute_lcoh_dh(
        annual_heat_mwh=annual_heat_mwh,
        pipe_lengths_by_dn=pipe_lengths_by_dn,
        total_pipe_length_m=total_pipe_length_m,
        pump_power_kw=pump_power_kw,
        params=params_obj
    )
    
    lcoh_hp, _ = compute_lcoh_hp(
        annual_heat_mwh=annual_heat_mwh,
        hp_total_capacity_kw_th=design_capacity_kw,
        cop_annual_average=float(cop_annual_average),
        max_feeder_loading_pct=max_feeder_loading_pct,
        params=params_obj
    )
    
    return lcoh_dh, lcoh_hp


def run_sensitivity_analysis(
    cluster_id: str,
    annual_heat_mwh: float,
    design_capacity_kw: float,
    cha_kpis: Dict[str, Any],
    dha_kpis: Dict[str, Any],
    base_params: Dict[str, Any],
    variation_percent: float = 0.05
) -> Dict[str, Any]:
    """
    Perform One-At-A-Time sensitivity analysis on key economic parameters.
    
    Varies each parameter by ±variation_percent (default ±5%) while holding
    others constant. Tracks decision stability and cost sensitivity.
    
    Args:
        cluster_id: Cluster identifier
        annual_heat_mwh: Annual heat demand
        design_capacity_kw: Design heating capacity
        cha_kpis: District heating KPIs
        dha_kpis: Heat pump KPIs
        base_params: Base economic parameters
        variation_percent: Variation magnitude (default 0.05 = 5%)
    
    Returns:
        Dictionary with sensitivity analysis results
    """
    logger.info(f"Starting sensitivity analysis for {cluster_id}")
    
    # Parameters to vary (numeric only)
    parameters_to_test = [
        'electricity_price_eur_per_mwh',
        'discount_rate',
        'hp_cost_eur_per_kw_th',
        'ef_electricity_kg_per_mwh',
        'gas_price_eur_per_mwh',
        'biomass_price_eur_per_mwh'
    ]
    
    # Compute base case
    base_lcoh_dh, base_lcoh_hp = compute_lcoh(
        annual_heat_mwh, design_capacity_kw, cha_kpis, dha_kpis, base_params
    )
    base_decision = "DH" if base_lcoh_dh < base_lcoh_hp else "HP"
    
    logger.info(f"Base case: LCoH_DH={base_lcoh_dh:.2f}, LCoH_HP={base_lcoh_hp:.2f}, Decision={base_decision}")
    
    results = {}
    any_flip = False
    
    for param in parameters_to_test:
        if param not in base_params:
            logger.warning(f"Parameter {param} not in base_params, skipping")
            continue
        
        base_value = base_params[param]
        
        # High scenario (+variation_percent)
        params_high = copy.deepcopy(base_params)
        params_high[param] = base_value * (1 + variation_percent)
        
        lcoh_dh_high, lcoh_hp_high = compute_lcoh(
            annual_heat_mwh, design_capacity_kw, cha_kpis, dha_kpis, params_high
        )
        decision_high = "DH" if lcoh_dh_high < lcoh_hp_high else "HP"
        flip_high = (decision_high != base_decision)
        
        # Low scenario (-variation_percent)
        params_low = copy.deepcopy(base_params)
        params_low[param] = base_value * (1 - variation_percent)
        
        lcoh_dh_low, lcoh_hp_low = compute_lcoh(
            annual_heat_mwh, design_capacity_kw, cha_kpis, dha_kpis, params_low
        )
        decision_low = "DH" if lcoh_dh_low < lcoh_hp_low else "HP"
        flip_low = (decision_low != base_decision)
        
        # Calculate sensitivity index (max relative change in winner's LCoH)
        winner_base = base_lcoh_dh if base_decision == "DH" else base_lcoh_hp
        winner_high = lcoh_dh_high if base_decision == "DH" else lcoh_hp_high
        winner_low = lcoh_dh_low if base_decision == "DH" else lcoh_hp_low
        
        change_high_pct = abs((winner_high - winner_base) / winner_base) if winner_base > 0 else 0
        change_low_pct = abs((winner_low - winner_base) / winner_base) if winner_base > 0 else 0
        sensitivity_index = max(change_high_pct, change_low_pct)
        
        flipped = flip_high or flip_low
        if flipped:
            any_flip = True
            logger.warning(f"{param}: Decision FLIPPED (high={decision_high}, low={decision_low})")
        
        results[param] = {
            "base_value": base_value,
            "high_scenario": {
                "value": params_high[param],
                "lcoh_dh": lcoh_dh_high,
                "lcoh_hp": lcoh_hp_high,
                "decision": decision_high,
                "flipped": flip_high
            },
            "low_scenario": {
                "value": params_low[param],
                "lcoh_dh": lcoh_dh_low,
                "lcoh_hp": lcoh_hp_low,
                "decision": decision_low,
                "flipped": flip_low
            },
            "sensitivity_index": sensitivity_index,
            "flipped": flipped
        }
    
    logger.info(f"Sensitivity analysis complete: {len(results)} parameters tested, any_flip={any_flip}")
    
    return {
        "cluster_id": cluster_id,
        "variation_percent": variation_percent,
        "base_decision": base_decision,
        "base_lcoh_dh": base_lcoh_dh,
        "base_lcoh_hp": base_lcoh_hp,
        "parameters_tested": len(results),
        "any_flip_detected": any_flip,
        "results": results
    }
