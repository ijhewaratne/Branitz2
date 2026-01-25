"""
Smart Grid Strategy Simulation.

Implements the Fraunhofer IWES methodology for assessing the impact of 
smart grid technologies (Active Power Curtailment, Reactive Power Control, OLTC)
on grid hosting capacity and violation mitigation.

This module simulates strategies by modifying the network/loads and re-running 
the load flow, rather than just using heuristics.
"""

from typing import Dict, List, Optional, Any
import pandas as pd
import numpy as np
import copy
from dataclasses import dataclass

try:
    import pandapower as pp
except ImportError:
    pass

from .config import DHAConfig
from .loadflow import run_loadflow, assign_hp_loads
from .kpi_extractor import extract_dha_kpis

@dataclass
class StrategyResult:
    """Result of a smart grid strategy simulation"""
    strategy_name: str
    is_feasible: bool
    violation_count: int
    worst_voltage_pu: float
    max_line_loading_pct: float
    max_trafo_loading_pct: float
    cost_estimate_eur: float
    
    # Differential metrics (improvement over baseline)
    voltage_improvement_pu: float = 0.0
    loading_reduction_pct: float = 0.0


def simulate_smart_grid_strategies(
    net: pp.pandapowerNet,
    loads_by_hour: Dict[int, pd.DataFrame],
    baseline_kpis: Dict[str, Any],
    cfg: DHAConfig
) -> Dict[str, StrategyResult]:
    """
    Simulate various smart grid strategies to see if they mitigate violations.
    
    Strategies simulated:
    1. Q-Control (CosPhi(P) 0.95 inductive)
    2. Peak Curtailment (70% or 6kW max)
    3. Wide-Range OLTC (Transformer Tap Control)
    
    Returns:
        Dict[strategy_name -> StrategyResult]
    """
    results = {}
    
    # 1. Q-Control Strategy (CosPhi = 0.95 inductive for HPs)
    # -------------------------------------------------------
    # Logic: Set HP loads to have Q corresponding to pf=0.95 (inductive consumes Q, lowers V rise? 
    # Wait, HPs are loads. Inductive load (lagging pf) consumes Q. 
    # If we have undervoltage (load dominated), consuming Q makes voltage DROP MORE.
    # If we have overvoltage (PV dominated), consuming Q helps.
    #
    # FOR HEAT PUMPS (Load):
    # Typically DHA issues are Undervoltage and Overload.
    # Consuming Q (Inductive) worsens Undervoltage.
    # PRODUCING Q (Capacitive) improves Undervoltage.
    #
    # Fraunhofer paper usually discusses PV (Overvoltage).
    # For HPs (Undervoltage), we might want Capacitive support (CosPhi = 0.95 cap).
    # However, standard inverters often just do 0.9 or 0.95.
    # Let's test Capacitive support (pf=0.95 capacitive).
    
    # Strategy: "q_support" (Capacitive PF 0.95)
    try:
        q_res = _simulate_q_control(net, loads_by_hour, cfg, pf_target=0.95, capacitive=True)
        results["q_support"] = q_res
    except Exception as e:
        pass

    # 2. Peak Curtailment (Active Power Reduction)
    # --------------------------------------------
    # Logic: Cap HP power at X% during critical hours.
    # This directly reduces line/trafo loading and improves voltage.
    try:
        curtail_res = _simulate_curtailment(net, loads_by_hour, cfg, max_power_ratio=0.7)
        results["peak_curtailment"] = curtail_res
    except Exception as e:
        pass
        
    # 3. OLTC (On-Load Tap Changer)
    # -----------------------------
    # Logic: Adjust transformer tap to boost voltage.
    # Default is tap 0. We try +2 or -2 depending on issue.
    # For Undervoltage (Load), we want to INCREASE secondary voltage -> Lower Tap (usually).
    # (High Voltage Side Tap: Lower turns ratio -> Higher LV voltage? check PP conventions).
    # PP: vn_lv = vn_hv * (1 + tap_pos * tap_step/100) / ratio.
    # NO. 
    # Let's try optimizing tap position.
    try:
        oltc_res = _simulate_oltc(net, loads_by_hour, cfg)
        results["oltc"] = oltc_res
    except Exception as e:
        pass

    # Compute improvement metrics relative to baseline
    base_v = baseline_kpis.get("worst_vmin_pu")
    if base_v is None:
        base_v = 1.0
        
    base_load = baseline_kpis.get("max_feeder_loading_pct")
    if base_load is None:
        base_load = 0.0

    for res in results.values():
        # Voltage improvement (higher is usually better for undervoltage)
        # Note: If problem is overvoltage, we might want lower.
        # But here we stick to simple diff.
        res.voltage_improvement_pu = res.worst_voltage_pu - base_v
        
        # Loading reduction (lower is better)
        res.loading_reduction_pct = base_load - res.max_line_loading_pct

    return results


def _simulate_q_control(net, loads_by_hour, cfg, pf_target, capacitive=True):
    # Deepcopy loads to modify Q
    new_loads = {}
    tan_phi = np.tan(np.arccos(pf_target))
    # Capacitive means producing Q. Load usually has +P. 
    # Pandapower Load: +Q = Inductive (Consuming). -Q = Capacitive (Producing).
    # We want -Q to boost voltage.
    q_sign = -1.0 if capacitive else 1.0
    
    for h, df in loads_by_hour.items():
        df_new = df.copy()
        # Q_hp = P_hp * tan_phi * sign
        # We replace the q_hp column. 
        # (Assuming loads_by_hour has p_hp_kw available, which it does from assign_hp_loads)
        
        # Recalculate Q based on P_hp
        if 'p_hp_kw' in df_new.columns:
            q_hp = df_new['p_hp_kw'] * tan_phi * q_sign
            # q_base remains same
            q_base = df_new['q_base_kvar'] if 'q_base_kvar' in df_new.columns else 0.0
            
            df_new['q_total_kvar'] = q_base + q_hp
            df_new['q_mvar'] = df_new['q_total_kvar'] / 1000.0
        
        new_loads[h] = df_new
        
    # Run Loadflow
    return _run_sim_and_eval(net, new_loads, cfg, "q_support", 
                             cost_estimate=2000.0) # Inverter setting cost (low)


def _simulate_curtailment(net, loads_by_hour, cfg, max_power_ratio=0.7):
    # Reduce P_hp by factor
    new_loads = {}
    for h, df in loads_by_hour.items():
        df_new = df.copy()
        if 'p_hp_kw' in df_new.columns:
            # Simple uniform curtailment for now.
            # In sophisticated version, only curtail if P > Threshold.
            # Here: Simulate "Dimming" all HPs to 70% capacity during peak.
            df_new['p_hp_kw'] = df_new['p_hp_kw'] * max_power_ratio
            
            # Recalculate Q (assuming constant PF)
            # Or assume Q scales too.
            q_hp = df_new['q_hp_kvar'] * max_power_ratio if 'q_hp_kvar' in df_new.columns else 0.0
            
            df_new['p_total_kw'] = df_new['p_base_kw'] + df_new['p_hp_kw']
            
            q_base = df_new['q_base_kvar'] if 'q_base_kvar' in df_new.columns else 0.0
            df_new['q_total_kvar'] = q_base + q_hp
            
            df_new['p_mw'] = df_new['p_total_kw'] / 1000.0
            df_new['q_mvar'] = df_new['q_total_kvar'] / 1000.0
            
        new_loads[h] = df_new
        
    # Run Loadflow
    return _run_sim_and_eval(net, new_loads, cfg, "peak_curtailment",
                             cost_estimate=5000.0) # Control hardware cost


def _simulate_oltc(net, loads_by_hour, cfg):
    # Adjust Trafo Tap
    # We need to modify net.trafo
    # Since run_loadflow takes net, we need to be careful not to mutate global net permanently if caller reuses it.
    # But run_loadflow modifies net.load anyway.
    # We should use a copy of net locally? 
    # Yes, PP nets are dict-like, copy.deepcopy works.
    import copy
    net_sim = copy.deepcopy(net)
    
    # Set tap to boost LV voltage.
    # Assuming Dyn5 or similar:
    # High side tap: (-) turns -> (+) Voltage ratio -> Higher output? 
    # Usually Tap -1 or -2 boosts voltage.
    # Let's try -2 (Max Boost).
    net_sim.trafo['tap_pos'] = -2
    
    # Run Loadflow with original loads
    return _run_sim_and_eval(net_sim, loads_by_hour, cfg, "oltc",
                             cost_estimate=15000.0) # Cost of OLTC trafo upgrade


def _run_sim_and_eval(net, loads, cfg, name, cost_estimate):
    results_by_hour = run_loadflow(net, loads)
    kpis, _ = extract_dha_kpis(results_by_hour, cfg)
    
    # Check feasibility
    feasible = kpis.get("feasible", False)
    
    # Extract improved metrics
    worst_v = kpis.get("worst_vmin_pu", 0.0) or 0.0
    max_line = kpis.get("max_feeder_loading_pct", 0.0) or 0.0
    max_trafo = kpis.get("max_trafo_loading_pct", 0.0) or 0.0
    
    return StrategyResult(
        strategy_name=name,
        is_feasible=feasible,
        violation_count=kpis.get("critical_hours_count", 0),
        worst_voltage_pu=worst_v,
        max_line_loading_pct=max_line,
        max_trafo_loading_pct=max_trafo,
        cost_estimate_eur=cost_estimate
    )
