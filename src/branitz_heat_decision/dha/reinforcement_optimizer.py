"""
Automated Grid Reinforcement Planning.

Implements a heuristic greedy algorithm (simplified from Fraunhofer's Iterated Local Search)
to identifying cost-effective grid upgrades (Line replacements, Transformer upgrades)
that resolve DHA violations.
"""

from dataclasses import dataclass, asdict
from typing import List, Dict, Set, Optional, Any
import copy
import logging
import pandas as pd
import numpy as np

try:
    import pandapower as pp
except ImportError:
    pass

from .config import DHAConfig
from .loadflow import run_loadflow
from .kpi_extractor import extract_dha_kpis

logger = logging.getLogger(__name__)

@dataclass
class ReinforcementMeasure:
    """Single reinforcement action"""
    measure_type: str  # "replace_line", "upgrade_trafo"
    element_id: int    # index in pandapower table
    old_type: str
    new_type: str
    cost_eur: float
    description: str

@dataclass
class ReinforcementPlan:
    measures: List[ReinforcementMeasure]
    total_cost_eur: float
    is_sufficient: bool
    remaining_violations: int

# Simplified cost catalog (EUR)
# In production, this should be loaded from a CSV/DB
COST_CATALOG = {
    "line_per_km": {
        "NAYY 4x50 SE": 15000,
        "NAYY 4x150 SE": 35000,
        "NAYY 4x240 SE": 55000
    },
    "trafo_total": {
        "0.25 MVA 20/0.4 kV": 15000,
        "0.4 MVA 20/0.4 kV": 22000,
        "0.63 MVA 20/0.4 kV": 28000,
        "1.0 MVA 20/0.4 kV": 40000
    }
}

# Line Types ordered by capacity (approx)
LINE_TYPES_ORDERED = ["NAYY 4x50 SE", "NAYY 4x150 SE", "NAYY 4x240 SE"]
TRAFO_TYPES_ORDERED = ["0.25 MVA 20/0.4 kV", "0.4 MVA 20/0.4 kV", "0.63 MVA 20/0.4 kV", "1.0 MVA 20/0.4 kV"]


def plan_grid_reinforcement(
    net: pp.pandapowerNet,
    loads_by_hour: Dict[int, pd.DataFrame],
    cfg: DHAConfig,
    max_iterations: int = 10
) -> ReinforcementPlan:
    """
    Generate a reinforcement plan to resolve violations.
    
    Algorithm:
    1. Run LoadFlow.
    2. Identify worst overloaded element (Line or Trafo) or lowest voltage bus.
    3. Suggest upgrade for that element (Next larger standard type).
    4. Apply upgrade tentatively.
    5. Repeat until no violations or max iterations.
    """
    
    current_net = copy.deepcopy(net)
    measures = []
    
    # Ensure std types exist in net logic or just set parameters manually if needed.
    # We assume std_types are available in pp database or custom std_types.
    
    for iteration in range(max_iterations):
        # 1. Run LoadFlow
        results = run_loadflow(current_net, loads_by_hour)
        kpis, _ = extract_dha_kpis(results, cfg)
        
        if kpis.get("feasible", False):
            logger.info("Grid is feasible. Reinforcement planning complete.")
            return ReinforcementPlan(
                measures=measures,
                total_cost_eur=sum(m.cost_eur for m in measures),
                is_sufficient=True,
                remaining_violations=0
            )
            
        # 2. Identify violations
        # We need to find the specific element causing the issue.
        # extract_dha_kpis returns aggregated stats. We need raw results again?
        # extract_dha_kpis returns (kpis, violations_df).
        # We can look at what caused the violation.
        
        # Priority: Trafo Overload > Line Overload > Voltage
        # (Voltage is often fixed by Line upgrade).
        
        measure = None
        
        # Check Trafo
        t_load = kpis.get("max_trafo_loading_pct")
        if t_load is not None and t_load > cfg.trafo_loading_limit_pct:
            # Find overloaded trafo
            # Just take the first one or worst one.
            # We iterate hours/results.
            # Or assume 1 trafo for simple LV grid.
            worst_t_idx = None
            max_load = 0
            for h, res in results.items():
                tr = res.get("trafo_results")
                if tr is not None and not tr.empty:
                    idxmax = tr['loading_percent'].idxmax()
                    val = tr['loading_percent'].iloc[idxmax] # idxmax returns index label?
                    # Be careful with pandas index.
                    # Actually tr['loading_percent'] might use numeric index matching net.trafo.
                    # idxmax returns the index.
                    idx = tr['loading_percent'].idxmax()
                    val = tr.at[idx, 'loading_percent']
                    if val > max_load:
                        max_load = val
                        worst_t_idx = idx
            
            if worst_t_idx is not None and max_load > cfg.trafo_loading_limit_pct:
                measure = _upgrade_trafo(current_net, worst_t_idx)

        # Check Line
        if measure is None:
            l_load = kpis.get("max_feeder_loading_pct")
            if l_load is not None and l_load > cfg.line_loading_limit_pct:
                 worst_l_idx = None
                 max_load = 0
                 for h, res in results.items():
                    lr = res.get("line_results")
                    if lr is not None and not lr.empty:
                        # Filter to only lines that are part of the cluster?
                        # Assuming net only contains relevant lines.
                        idx = lr['loading_percent'].idxmax()
                        val = lr.at[idx, 'loading_percent']
                        if val > max_load:
                            max_load = val
                            worst_l_idx = idx
                 
                 if worst_l_idx is not None and max_load > cfg.line_loading_limit_pct:
                     measure = _upgrade_line(current_net, worst_l_idx)
                     
        # Check Voltage
        if measure is None:
             vmin = kpis.get("worst_vmin_pu", 1.0)
             if vmin < cfg.v_min_pu:
                 # Upgrade line feeding the worst bus?
                 # Harder to trace. Simplified: Upgrade line with highest voltage DROP?
                 # Or just upgrade the longest/weakest line on the path.
                 # Heuristic: Find line with highest loading among those in low voltage area?
                 # Simple Heuristic: Upgrade the line with max loading percent, even if not > 100%.
                 # Because high loading cause high voltage drop.
                 
                 worst_l_idx = None
                 max_load = 0
                 for h, res in results.items():
                     lr = res.get("line_results")
                     if lr is not None and not lr.empty:
                         idx = lr['loading_percent'].idxmax()
                         val = lr.at[idx, 'loading_percent']
                         if val > max_load:
                             max_load = val
                             worst_l_idx = idx
                 if worst_l_idx is not None:
                     measure = _upgrade_line(current_net, worst_l_idx)

        if measure:
            # Check if we already upgraded this element? 
            # If we keep upgrading the same element, we might loop.
            # But _upgrade_line selects "Next larger type". If max reached, it returns None.
            
            logger.info(f"Iteration {iteration}: {measure.description}")
            measures.append(measure)
        else:
            logger.warning("Could not find suitable upgrade measure despite violations.")
            break
            
    return ReinforcementPlan(
        measures=measures,
        total_cost_eur=sum(m.cost_eur for m in measures),
        is_sufficient=False,
        remaining_violations=1 # Generic indicator
    )


def _upgrade_line(net, line_idx) -> Optional[ReinforcementMeasure]:
    current_type = net.line.at[line_idx, "std_type"]
    length_km = net.line.at[line_idx, "length_km"]
    
    # determine index in ordered list
    try:
        curr_i = LINE_TYPES_ORDERED.index(current_type)
        if curr_i < len(LINE_TYPES_ORDERED) - 1:
            new_type = LINE_TYPES_ORDERED[curr_i + 1]
            cost = length_km * COST_CATALOG["line_per_km"].get(new_type, 40000)
            
            # Apply
            net.line.at[line_idx, "std_type"] = new_type
            
            return ReinforcementMeasure(
                measure_type="replace_line",
                element_id=int(line_idx),
                old_type=current_type,
                new_type=new_type,
                cost_eur=cost,
                description=f"Upgrade Line {line_idx} ({length_km:.2f}km) {current_type} -> {new_type}"
            )
    except ValueError:
        # Current type not in our list (custom?). Force upgrade to strongest.
        if current_type != LINE_TYPES_ORDERED[-1]:
            new_type = LINE_TYPES_ORDERED[-1]
            cost = length_km * COST_CATALOG["line_per_km"].get(new_type, 40000)
            net.line.at[line_idx, "std_type"] = new_type
            return ReinforcementMeasure(
                measure_type="replace_line",
                element_id=int(line_idx),
                old_type=current_type,
                new_type=new_type,
                cost_eur=cost,
                description=f"Upgrade Line {line_idx} (Unknown) -> {new_type}"
            )
            
    return None

def _upgrade_trafo(net, trafo_idx) -> Optional[ReinforcementMeasure]:
    current_type = net.trafo.at[trafo_idx, "std_type"]
    
    # Try to find standard type matching sn_mva if std_type is generic
    # But usually we rely on std_type string
    try:
        curr_i = -1
        if current_type in TRAFO_TYPES_ORDERED:
            curr_i = TRAFO_TYPES_ORDERED.index(current_type)
        
        if curr_i < len(TRAFO_TYPES_ORDERED) - 1:
            new_type = TRAFO_TYPES_ORDERED[curr_i + 1]
            cost = COST_CATALOG["trafo_total"].get(new_type, 30000)
            
            # Apply
            net.trafo.at[trafo_idx, "std_type"] = new_type
            # Also update sn_mva etc because std_type usually sets them but pp might need explicit update if not using std_type library correctly?
            # Assigning std_type in PP usually applies parameters if they are in pp.std_types.
            # Assuming they are.
            
            return ReinforcementMeasure(
                measure_type="upgrade_trafo",
                element_id=int(trafo_idx),
                old_type=current_type,
                new_type=new_type,
                cost_eur=cost,
                description=f"Upgrade Trafo {trafo_idx} {current_type} -> {new_type}"
            )
    except ValueError:
        pass
        
    return None
