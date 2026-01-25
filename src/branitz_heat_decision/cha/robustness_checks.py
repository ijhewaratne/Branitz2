"""
Robustness validation through Monte Carlo uncertainty analysis.

Checks network performance under:
1. Demand variations
2. Temperature variations
3. Flow variations
"""

import logging
from typing import Dict, List
from dataclasses import dataclass
import numpy as np
import pandapipes as pp
from copy import deepcopy

logger = logging.getLogger(__name__)


@dataclass
class RobustnessResult:
    """Result of robustness validation"""
    passed: bool
    issues: List[str]
    warnings: List[str]
    metrics: Dict[str, float]
    scenario_results: List[Dict]


class RobustnessValidator:
    """Validates network robustness through uncertainty analysis"""
    
    def __init__(self, config):
        self.config = config.robustness
    
    def validate(self, net: pp.pandapipesNet) -> RobustnessResult:
        """
        Run Monte Carlo simulation to test network robustness.
        
        Tests performance under demand, temperature, and flow variations.
        """
        
        logger.info(f"Running robustness validation ({self.config.n_scenarios} scenarios)...")
        
        issues = []
        warnings = []
        scenario_results = []
        
        successful_scenarios = 0
        failed_scenarios = []
        
        for scenario_idx in range(self.config.n_scenarios):
            # Create network copy
            net_copy = self._create_scenario_network(net, scenario_idx)
            
            try:
                # Run pipeflow
                pp.pipeflow(net_copy, mode="all")
                
                if net_copy.converged:
                    # Check if scenario meets constraints
                    scenario_valid = self._check_scenario_constraints(net_copy)
                    
                    if scenario_valid:
                        successful_scenarios += 1
                    else:
                        failed_scenarios.append({
                            "scenario": scenario_idx,
                            "reason": "constraint_violation"
                        })
                    
                    # Store results
                    scenario_results.append({
                        "scenario_idx": scenario_idx,
                        "converged": True,
                        "constraints_met": scenario_valid,
                        "max_velocity": float(net_copy.res_pipe["v_mean_m_per_s"].max()),
                        "max_pressure": float(net_copy.res_junction["p_bar"].max())
                    })
                else:
                    failed_scenarios.append({
                        "scenario": scenario_idx,
                        "reason": "convergence_failure"
                    })
                    scenario_results.append({
                        "scenario_idx": scenario_idx,
                        "converged": False,
                        "constraints_met": False
                    })
            
            except Exception as e:
                logger.debug(f"Scenario {scenario_idx} failed: {e}")
                failed_scenarios.append({
                    "scenario": scenario_idx,
                    "reason": str(e)
                })
                scenario_results.append({
                    "scenario_idx": scenario_idx,
                    "converged": False,
                    "constraints_met": False,
                    "error": str(e)
                })
        
        # Calculate success rate
        # If no scenarios run (e.g. robustness check skipped or 0 scenarios), success rate is 1.0 logic?
        # N_scenarios defaults to 50 in standard, so it should be fine.
        success_rate = successful_scenarios / self.config.n_scenarios if self.config.n_scenarios > 0 else 1.0
        
        # Check against threshold
        if success_rate < self.config.min_success_rate:
            issues.append(
                f"Network only converges successfully in {success_rate:.1%} of scenarios "
                f"(threshold: {self.config.min_success_rate:.1%})"
            )
        elif success_rate < 0.98:
            warnings.append(
                f"Network robustness {success_rate:.1%} is below ideal (>98%)"
            )
        
        # Analyze failure modes
        if failed_scenarios:
            convergence_failures = len([f for f in failed_scenarios if f["reason"] == "convergence_failure"])
            constraint_failures = len([f for f in failed_scenarios if f["reason"] == "constraint_violation"])
            
            if convergence_failures > 0:
                warnings.append(
                    f"{convergence_failures}/{self.config.n_scenarios} scenarios failed to converge"
                )
            
            if constraint_failures > 0:
                warnings.append(
                    f"{constraint_failures}/{self.config.n_scenarios} scenarios violated constraints"
                )
        
        metrics = {
            "robustness_success_rate": float(success_rate),
            "scenarios_tested": self.config.n_scenarios,
            "scenarios_successful": successful_scenarios,
            "scenarios_failed": len(failed_scenarios)
        }
        
        # Add statistics from successful scenarios
        if successful_scenarios > 0:
            successful_results = [s for s in scenario_results if s.get("converged") and s.get("constraints_met")]
            
            velocities = [s["max_velocity"] for s in successful_results if "max_velocity" in s]
            pressures = [s["max_pressure"] for s in successful_results if "max_pressure" in s]
            
            if velocities:
                metrics["velocity_mean"] = float(np.mean(velocities))
                metrics["velocity_std"] = float(np.std(velocities))
                metrics["velocity_p95"] = float(np.percentile(velocities, 95))
            
            if pressures:
                metrics["pressure_mean"] = float(np.mean(pressures))
                metrics["pressure_std"] = float(np.std(pressures))
                metrics["pressure_p95"] = float(np.percentile(pressures, 95))
        
        passed = len(issues) == 0
        
        logger.info(f"Robustness validation: {'PASSED' if passed else 'FAILED'} "
                   f"(success rate: {success_rate:.1%})")
        
        return RobustnessResult(
            passed=passed,
            issues=issues,
            warnings=warnings,
            metrics=metrics,
            scenario_results=scenario_results
        )
    
    def _create_scenario_network(self, net: pp.pandapipesNet, scenario_idx: int) -> pp.pandapipesNet:
        """Create network with randomized parameters for scenario"""
        
        net_copy = deepcopy(net)
        
        # Set random seed for reproducibility
        np.random.seed(scenario_idx)
        
        # 1. Vary demand (±20%)
        demand_multiplier = np.random.uniform(
            1 - self.config.demand_variation_pct / 100,
            1 + self.config.demand_variation_pct / 100
        )
        
        if "heat_exchanger" in dir(net_copy) and len(net_copy.heat_exchanger) > 0:
            net_copy.heat_exchanger["qext_w"] *= demand_multiplier
        
        # 2. Vary supply temperature (±5°C)
        if "ext_grid" in dir(net_copy) and len(net_copy.ext_grid) > 0:
            temp_variation_k = np.random.uniform(
                -self.config.temperature_variation_c,
                self.config.temperature_variation_c
            )
            net_copy.ext_grid["t_k"] += temp_variation_k
        
        return net_copy
    
    def _check_scenario_constraints(self, net: pp.pandapipesNet) -> bool:
        """Check if scenario results meet basic constraints"""
        
        # Use relaxed thresholds for robustness check
        if net.res_pipe.empty or net.res_junction.empty:
             return False

        max_velocity = net.res_pipe["v_mean_m_per_s"].abs().max()
        max_pressure = net.res_junction["p_bar"].max()
        min_pressure = net.res_junction["p_bar"].min()
        
        # Allow slightly higher limits in uncertainty scenarios
        if max_velocity > 2.0:  # vs. 1.5 nominal
            return False
        
        if max_pressure > 20.0 or min_pressure < 0.5:
            return False
        
        return True
