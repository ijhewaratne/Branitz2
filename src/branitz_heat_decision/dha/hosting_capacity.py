"""
Monte Carlo Hosting Capacity Analysis.

Implements the Fraunhofer IWES methodology (Scheidler et al., 2016) for
probabilistic assessment of grid hosting capacity.

Instead of checking just one "Design Scenario", this module:
1. Generates N random scenarios of Heat Pump adoption (varying location and penetration).
2. Runs load flow for each scenario.
3. Determines the statistical likelihood of voltage/loading violations.
4. Estimates the maximum safe hosting capacity (kW) and penetration (%).
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Any
import random
import numpy as np
import pandas as pd

try:
    import pandapower as pp
except ImportError:
    pass

from .config import DHAConfig
from .loadflow import run_loadflow, assign_hp_loads
# from .kpi_extractor import extract_kpis # Unused

logger = logging.getLogger(__name__)

@dataclass
class HostingCapacityResult:
    """Results of Monte Carlo hosting capacity analysis"""
    scenarios_analyzed: int
    safe_scenarios: int
    violation_scenarios: int
    
    # Hosting Capacity (Max Safe Load)
    safe_capacity_min_kw: float
    safe_capacity_median_kw: float
    safe_capacity_max_kw: float
    
    # Critical Penetration Stats
    safe_penetration_median_pct: float
    
    # Detailed scenario results
    scenario_details: List[Dict[str, Any]]
    
    @property
    def safety_score(self) -> float:
        """Percentage of scenarios that were violation-free"""
        if self.scenarios_analyzed == 0:
            return 0.0
        return self.safe_scenarios / self.scenarios_analyzed


def run_monte_carlo_hosting_capacity(
    net: pp.pandapowerNet,
    building_bus_map: pd.DataFrame,
    hourly_heat_profiles: pd.DataFrame,
    base_load_profiles: Optional[pd.DataFrame],
    cfg: DHAConfig,
    n_scenarios: int = 50,
    penetration_range: Tuple[float, float] = (0.1, 1.0),
    design_cop: float = 3.0,
    design_hour_idx: int = 0,
    top_n_hours: Optional[List[int]] = None
) -> HostingCapacityResult:
    """
    Execute Monte Carlo simulation to determine hosting capacity.
    
    Args:
        net: Base pandapower network
        building_bus_map: Mapping of buildings to buses
        hourly_heat_profiles: Heat demand profiles
        base_load_profiles: Electrical base load profiles
        cfg: DHA Configuration
        n_scenarios: Number of random scenarios to run
        penetration_range: Min/Max penetration to sample (0.1 = 10%, 1.0 = 100%)
        design_cop: COP to use for conversion
        design_hour_idx: Index of design hour used for load assignment
        top_n_hours: List of critical hour indices to simulate
        
    Returns:
        HostingCapacityResult object
    """
    logger.info(f"Starting Monte Carlo analysis with {n_scenarios} scenarios...")
    
    if top_n_hours is None:
        top_n_hours = [design_hour_idx]

    results = []
    
    # Get list of all mappable buildings
    all_buildings = building_bus_map[building_bus_map['mapped'] == True]['building_id'].unique().tolist()
    total_buildings = len(all_buildings)
    
    if total_buildings == 0:
        logger.warning("No mapped buildings found. Returning empty result.")
        return HostingCapacityResult(
            scenarios_analyzed=n_scenarios, safe_scenarios=n_scenarios, violation_scenarios=0,
            safe_capacity_min_kw=0, safe_capacity_median_kw=0, safe_capacity_max_kw=0,
            safe_penetration_median_pct=1.0, scenario_details=[]
        )

    for i in range(n_scenarios):
        # 1. Randomly sample penetration level for this scenario
        target_penetration = np.random.uniform(*penetration_range)
        
        # 2. Randomly select buildings
        n_adoption = int(total_buildings * target_penetration)
        adopted_buildings = random.sample(all_buildings, max(1, n_adoption))
        
        # 3. Create a filtered map where only adopted buildings map to buses
        # (Non-adopted buildings basically don't get HPs in assign_hp_loads logic)
        # Efficient way: Pass a filtered set of heat profiles ONLY for adopted buildings.
        
        scenario_heat_profiles = hourly_heat_profiles.copy()
        # Set non-adopted buildings to 0 heat demand (so 0 HP load)
        non_adopted = set(all_buildings) - set(adopted_buildings)
        # Only zero out columns that exist in DataFrame
        cols_to_zero = [c for c in non_adopted if c in scenario_heat_profiles.columns]
        if cols_to_zero:
            scenario_heat_profiles[cols_to_zero] = 0.0
            
        # Calculate total HP capacity for this scenario (sum of max load)
        max_q_th = scenario_heat_profiles[adopted_buildings].max().sum()
        installed_hp_kw = max_q_th / design_cop
        
        # 4. Run Load Flow (Top-N hours only for speed)
        try:
            loads = assign_hp_loads(
                scenario_heat_profiles,
                building_bus_map,
                design_hour=design_hour_idx,
                topn_hours=top_n_hours,
                cop=design_cop,
                base_profiles_kw=base_load_profiles
            )
            
            # Helper to run just valid hours
            lf_res = run_loadflow(net, loads)
            
            # 5. Extract KPIs / Check Violations
            has_violation = False
            violation_details = []
            
            for hour, res in lf_res.items():
                if not res['converged']:
                    has_violation = True
                    violation_details.append(f"Hour {hour}: Diverged")
                    continue
                
                # Voltage Check
                vm_pu = res['bus_results']['vm_pu']
                if (vm_pu < cfg.v_min_pu).any() or (vm_pu > cfg.v_max_pu).any():
                    has_violation = True
                    val = vm_pu.min()
                    violation_details.append(f"Hour {hour}: Voltage {val:.3f} pu")
                
                # Line Loading Check
                if not res['line_results'].empty:
                    loading = res['line_results'].get('loading_percent')
                    if loading is not None and (loading > cfg.line_loading_limit_pct).any():
                        has_violation = True
                        val = loading.max()
                        violation_details.append(f"Hour {hour}: Line {val:.1f}%")
                        
                # Trafo Loading Check
                if not res['trafo_results'].empty:
                    t_loading = res['trafo_results'].get('loading_percent')
                    if t_loading is not None and (t_loading > cfg.trafo_loading_limit_pct).any():
                        has_violation = True
                        val = t_loading.max()
                        violation_details.append(f"Hour {hour}: Trafo {val:.1f}%")
            
            results.append({
                "scenario_idx": i,
                "penetration_pct": target_penetration,
                "n_buildings": n_adoption,
                "installed_hp_kw": installed_hp_kw,
                "has_violation": has_violation,
                "violations": violation_details
            })
            
        except Exception as e:
            logger.error(f"Scenario {i} failed: {e}")
            results.append({
                "scenario_idx": i,
                "penetration_pct": target_penetration,
                "error": str(e),
                "has_violation": True # Count error as fail safety
            })
            
    # Analyze Results
    df_res = pd.DataFrame(results)
    safe_runs = df_res[~df_res['has_violation']]
    failed_runs = df_res[df_res['has_violation']]
    
    if not safe_runs.empty:
        safe_caps = safe_runs['installed_hp_kw']
        safe_pens = safe_runs['penetration_pct']
        return HostingCapacityResult(
            scenarios_analyzed=n_scenarios,
            safe_scenarios=len(safe_runs),
            violation_scenarios=len(failed_runs),
            safe_capacity_min_kw=safe_caps.min(),
            safe_capacity_median_kw=safe_caps.median(),
            safe_capacity_max_kw=safe_caps.max(),
            safe_penetration_median_pct=safe_pens.median(),
            scenario_details=results
        )
    else:
        # No scenarios were safe
        return HostingCapacityResult(
            scenarios_analyzed=n_scenarios,
            safe_scenarios=0,
            violation_scenarios=len(results),
            safe_capacity_min_kw=0.0,
            safe_capacity_median_kw=0.0,
            safe_capacity_max_kw=0.0,
            safe_penetration_median_pct=0.0,
            scenario_details=results
        )
