"""
Hydraulic validation based on EN 13941-1 standards.

Checks:
1. Velocity limits
2. Pressure drops
3. Pump power
4. Flow distribution
"""

import logging
from typing import Dict, List
from dataclasses import dataclass
import numpy as np
import pandapipes as pp

logger = logging.getLogger(__name__)


@dataclass
class HydraulicResult:
    """Result of hydraulic validation"""
    passed: bool
    issues: List[str]
    warnings: List[str]
    metrics: Dict[str, float]


class HydraulicValidator:
    """Validates hydraulic performance against EN 13941-1"""
    
    def __init__(self, config):
        self.config = config.en13941
    
    def validate(self, net: pp.pandapipesNet) -> HydraulicResult:
        """
        Complete hydraulic validation.
        
        Requires that pipeflow has already been run successfully.
        """
        
        if not net.converged:
            return HydraulicResult(
                passed=False,
                issues=["Hydraulic simulation did not converge"],
                warnings=[],
                metrics={}
            )
        
        issues = []
        warnings = []
        metrics = {}
        
        logger.info("Running hydraulic validation (EN 13941-1)...")
        
        # 1. Velocity checks
        velocity_check = self._check_velocities(net)
        issues.extend(velocity_check["issues"])
        warnings.extend(velocity_check["warnings"])
        metrics.update(velocity_check["metrics"])
        
        # 2. Pressure checks
        pressure_check = self._check_pressures(net)
        issues.extend(pressure_check["issues"])
        warnings.extend(pressure_check["warnings"])
        metrics.update(pressure_check["metrics"])
        
        # 3. Pump power check
        pump_check = self._check_pump_power(net)
        issues.extend(pump_check["issues"])
        warnings.extend(pump_check["warnings"])
        metrics.update(pump_check["metrics"])
        
        # 4. Flow distribution check
        flow_check = self._check_flow_distribution(net)
        warnings.extend(flow_check["warnings"])
        metrics.update(flow_check["metrics"])
        
        passed = len(issues) == 0
        
        logger.info(f"Hydraulic validation: {'PASSED' if passed else 'FAILED'}")
        
        return HydraulicResult(
            passed=passed,
            issues=issues,
            warnings=warnings,
            metrics=metrics
        )
    
    def _check_velocities(self, net: pp.pandapipesNet) -> Dict:
        """Check velocity limits (EN 13941-1 Section 5.3.2)"""
        
        issues = []
        warnings = []
        
        velocities = net.res_pipe["v_mean_m_per_s"].abs()
        
        max_velocity = velocities.max()
        min_velocity = velocities[velocities > 0].min() if (velocities > 0).any() else 0
        avg_velocity = velocities.mean()
        
        # Check maximum velocity
        if max_velocity > self.config.max_velocity_absolute:
            issues.append(
                f"Maximum velocity {max_velocity:.2f} m/s exceeds absolute limit "
                f"{self.config.max_velocity_absolute} m/s (EN 13941-1)"
            )
        elif max_velocity > self.config.max_velocity_recommended:
            warnings.append(
                f"Maximum velocity {max_velocity:.2f} m/s exceeds recommended limit "
                f"{self.config.max_velocity_recommended} m/s (EN 13941-1)"
            )
        
        # Check minimum velocity (avoid sedimentation)
        pipes_too_slow = velocities[(velocities > 0) & (velocities < self.config.min_velocity)]
        if len(pipes_too_slow) > 0:
            # Check if this is a trunk-spur network (context-aware warning)
            # Trunk-spur networks typically have dual pipes (supply S and return R)
            pipe_names = net.pipe['name'].astype(str)
            has_supply_return = (pipe_names.str.startswith('pipe_S_').any() and 
                               pipe_names.str.startswith('pipe_R_').any())
            has_spur_trunk = any('spur' in name.lower() or 'trunk' in name.lower() 
                               for name in pipe_names)
            is_trunk_spur = has_supply_return or has_spur_trunk
            
            # Check if low-velocity pipes are primarily return pipes (R) or spurs
            low_v_pipe_names = net.pipe.loc[pipes_too_slow.index, 'name'].astype(str)
            # Return pipes: name starts with "pipe_R_" or contains "return"
            # Spur pipes: name contains "spur"
            return_or_spur_count = sum(1 for name in low_v_pipe_names 
                                       if name.startswith('pipe_R_') or 'return' in name.lower() or 'spur' in name.lower())
            return_or_spur_pct = (return_or_spur_count / len(pipes_too_slow) * 100) if len(pipes_too_slow) > 0 else 0
            
            # In trunk-spur networks, low velocities are expected due to:
            # 1. Return pipes (lower flow than supply)
            # 2. End-of-line pipes (both supply and return)
            # 3. Spur pipes serving single buildings
            # If >30% of low-velocity pipes are return/spur, or if network has dual pipes (S+R), it's expected
            low_v_pct_of_total = (len(pipes_too_slow) / len(net.pipe) * 100) if len(net.pipe) > 0 else 0
            
            if is_trunk_spur and (return_or_spur_pct > 30 or low_v_pct_of_total > 50):
                # Context-aware warning: Expected in trunk-spur networks
                warnings.append(
                    f"{len(pipes_too_slow)} pipes have velocity < {self.config.min_velocity} m/s "
                    f"(expected in trunk-spur networks: return pipes and spurs naturally have lower flow; "
                    f"sedimentation risk mitigated by periodic flushing)"
                )
            else:
                warnings.append(
                    f"{len(pipes_too_slow)} pipes have velocity < {self.config.min_velocity} m/s "
                    f"(risk of sedimentation)"
                )
        
        # Identify specific problematic pipes but pass as dict to metrics
        high_velocity_pipes = velocities[velocities > self.config.max_velocity_recommended]
        top_5_pipes = {}
        if len(high_velocity_pipes) > 0:
            top_5 = high_velocity_pipes.nlargest(5)
            top_5_pipes = {int(idx): float(vel) for idx, vel in top_5.items()}
            
        metrics = {
            "max_velocity_m_per_s": float(max_velocity),
            "min_velocity_m_per_s": float(min_velocity),
            "avg_velocity_m_per_s": float(avg_velocity),
            "pipes_exceeding_velocity": int((velocities > self.config.max_velocity_recommended).sum()),
            "pipes_below_min_velocity": int(len(pipes_too_slow))
        }
        if top_5_pipes:
            metrics["high_velocity_pipes"] = top_5_pipes
            
        return {
            "issues": issues,
            "warnings": warnings,
            "metrics": metrics
        }
    
    def _check_pressures(self, net: pp.pandapipesNet) -> Dict:
        """Check pressure limits and drops"""
        
        issues = []
        warnings = []
        
        pressures = net.res_junction["p_bar"]
        
        max_pressure = pressures.max()
        min_pressure = pressures.min()
        
        # Check absolute pressure limits
        if max_pressure > self.config.max_pressure:
            issues.append(
                f"Maximum pressure {max_pressure:.2f} bar exceeds limit {self.config.max_pressure} bar"
            )
        
        if min_pressure < self.config.min_pressure:
            issues.append(
                f"Minimum pressure {min_pressure:.2f} bar below limit {self.config.min_pressure} bar "
                f"(risk of cavitation)"
            )
        
        # Check pressure drops along pipes
        pressure_drops = []
        pressure_drop_per_km = []
        
        for idx, pipe in net.pipe.iterrows():
            if pipe["from_junction"] in net.res_junction.index and pipe["to_junction"] in net.res_junction.index:
                p_from = net.res_junction.loc[pipe["from_junction"], "p_bar"]
                p_to = net.res_junction.loc[pipe["to_junction"], "p_bar"]
                
                dp = abs(p_from - p_to)
                pressure_drops.append(dp)
                
                dp_per_km = dp / pipe["length_km"] if pipe["length_km"] > 0 else 0
                pressure_drop_per_km.append(dp_per_km)
            else:
                 # Should not happen in converged net
                pressure_drops.append(0)
                pressure_drop_per_km.append(0)
        
        max_dp = max(pressure_drops) if pressure_drops else 0
        max_dp_per_km = max(pressure_drop_per_km) if pressure_drop_per_km else 0
        
        # Check against limits
        if max_dp > self.config.max_total_pressure_drop:
            warnings.append(
                f"Maximum pressure drop {max_dp:.2f} bar exceeds recommended "
                f"{self.config.max_total_pressure_drop} bar"
            )
        
        if max_dp_per_km > self.config.max_pressure_drop_per_km:
            warnings.append(
                f"Maximum pressure gradient {max_dp_per_km:.2f} bar/km exceeds recommended "
                f"{self.config.max_pressure_drop_per_km} bar/km"
            )
        
        return {
            "issues": issues,
            "warnings": warnings,
            "metrics": {
                "max_pressure_bar": float(max_pressure),
                "min_pressure_bar": float(min_pressure),
                "max_pressure_drop_bar": float(max_dp),
                "max_pressure_drop_per_km": float(max_dp_per_km),
                "avg_pressure_bar": float(pressures.mean())
            }
        }
    
    def _check_pump_power(self, net: pp.pandapipesNet) -> Dict:
        """Check pump power requirements"""
        
        issues = []
        warnings = []
        
        # Calculate total pump power
        pump_power_mw = 0
        
        if "circ_pump_mass" in dir(net) and len(net.circ_pump_mass) > 0:
            if "res_circ_pump_mass" in dir(net) and not net.res_circ_pump_mass.empty:
                # p_mw might not exist if simulation failed or mode is different, check columns
                if "p_mw" in net.res_circ_pump_mass.columns:
                     pump_power_mw = net.res_circ_pump_mass["p_mw"].sum()
        
        pump_power_kw = pump_power_mw * 1000
        
        # Calculate total thermal capacity
        total_thermal_mw = 0
        if "heat_exchanger" in dir(net) and len(net.heat_exchanger) > 0:
            total_thermal_mw = abs(net.heat_exchanger["qext_w"].sum()) / 1e6
        
        # Specific pump power (W per kW thermal)
        specific_pump_power = (pump_power_kw / (total_thermal_mw * 1000) * 1000) if total_thermal_mw > 0 else 0 
        # Wait, formula: Watts / kW_thermal.
        # Pump power in kW -> *1000 -> Watts. 
        # Thermal in MW -> *1000 -> kW.
        # So (kw_pump * 1000) / (mw_thermal * 1000) = kw/mw = w/kw. Yes.
        
        if specific_pump_power > self.config.max_specific_pump_power:
            warnings.append(
                f"Specific pump power {specific_pump_power:.1f} W/kW_th exceeds recommended "
                f"{self.config.max_specific_pump_power} W/kW_th (network may be inefficient)"
            )
        
        # Absolute pump power check (heuristic)
        if pump_power_kw > 100 and total_thermal_mw < 1:
            warnings.append(
                f"Pump power {pump_power_kw:.1f} kW seems excessive for "
                f"{total_thermal_mw:.2f} MW thermal capacity"
            )
        
        return {
            "issues": issues,
            "warnings": warnings,
            "metrics": {
                "total_pump_power_kw": float(pump_power_kw),
                "total_thermal_capacity_mw": float(total_thermal_mw),
                "specific_pump_power_w_per_kw": float(specific_pump_power)
            }
        }
    
    def _check_flow_distribution(self, net: pp.pandapipesNet) -> Dict:
        """Check flow distribution balance"""
        
        warnings = []
        
        # Calculate flow imbalance
        mass_flows = net.res_pipe["mdot_from_kg_per_s"].abs()
        
        if len(mass_flows) > 0:
            flow_std = mass_flows.std()
            flow_mean = mass_flows.mean()
            flow_cv = flow_std / flow_mean if flow_mean > 0 else 0  # Coefficient of variation
            
            if flow_cv > 1.0:
                # Check if this is a trunk-spur network (context-aware warning)
                # Trunk-spur networks typically have dual pipes (supply S and return R)
                pipe_names = net.pipe['name'].astype(str)
                has_supply_return = (pipe_names.str.startswith('pipe_S_').any() and 
                                   pipe_names.str.startswith('pipe_R_').any())
                has_spur_trunk = any('spur' in name.lower() or 'trunk' in name.lower() 
                                   for name in pipe_names)
                is_trunk_spur = has_supply_return or has_spur_trunk
                
                if is_trunk_spur:
                    # Context-aware warning: Expected in trunk-spur networks
                    warnings.append(
                        f"High flow distribution imbalance (CV={flow_cv:.2f}), "
                        "expected in trunk-spur networks: trunk pipes carry aggregated high flow, "
                        "spur pipes carry single-building low flow (design feature, not a flaw)"
                    )
                else:
                    warnings.append(
                        f"High flow distribution imbalance (CV={flow_cv:.2f}), "
                        "may indicate suboptimal network layout"
                    )
        else:
            flow_cv = 0
        
        return {
            "warnings": warnings,
            "metrics": {
                "flow_coefficient_of_variation": float(flow_cv)
            }
        }
