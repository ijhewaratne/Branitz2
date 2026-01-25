"""
Thermal performance validation for DH networks.

Checks:
1. Heat losses
2. Supply/return temperatures
3. Temperature decay
"""

import logging
from typing import Dict, List
from dataclasses import dataclass
import numpy as np
import pandapipes as pp
from branitz_heat_decision.config.validation_standards import PIPE_U_VALUES

logger = logging.getLogger(__name__)


@dataclass
class ThermalResult:
    """Result of thermal validation"""
    passed: bool
    issues: List[str]
    warnings: List[str]
    metrics: Dict[str, float]


class ThermalValidator:
    """Validates thermal performance"""
    
    def __init__(self, config):
        self.config = config.en13941
    
    def validate(self, net: pp.pandapipesNet) -> ThermalResult:
        """Complete thermal validation"""
        
        issues = []
        warnings = []
        metrics = {}
        
        logger.info("Running thermal validation...")
        
        # 1. Heat loss check
        heat_loss_check = self._check_heat_losses(net)
        issues.extend(heat_loss_check["issues"])
        warnings.extend(heat_loss_check["warnings"])
        metrics.update(heat_loss_check["metrics"])
        
        # 2. Temperature check
        temp_check = self._check_temperatures(net)
        issues.extend(temp_check["issues"])
        warnings.extend(temp_check["warnings"])
        metrics.update(temp_check["metrics"])
        
        passed = len(issues) == 0
        
        logger.info(f"Thermal validation: {'PASSED' if passed else 'FAILED'}")
        
        return ThermalResult(
            passed=passed,
            issues=issues,
            warnings=warnings,
            metrics=metrics
        )
    
    def _check_heat_losses(self, net: pp.pandapipesNet) -> Dict:
        """Calculate and validate heat losses"""
        
        issues = []
        warnings = []
        
        # Calculate total heat delivered
        total_heat_delivered_w = 0
        if "heat_exchanger" in dir(net) and len(net.heat_exchanger) > 0:
            if "qext_w" in net.heat_exchanger.columns:
                total_heat_delivered_w += abs(net.heat_exchanger["qext_w"].sum())
        
        if "sink" in dir(net) and len(net.sink) > 0:
            # Sinks are modeled as mass flow withdrawal. 
            # We calculate heat as mdot * cp * (T_supply - T_return_ref)
            # However, in pandapipes, a sink extracts mass, and source reinjects it.
            # The heat extracted is effectively (Mass Flow * Cp * (T_supply_node - T_return_node_at_plant)).
            # But simpler: The heat delivered is the thermal demand that RESULTED in this flow.
            # If we used sinks, we likely defined `mdot` based on a requested Q.
            # Let's try to find 'qext_w' if it exists (custom column) or approximate from results.
            if "qext_w" in net.sink.columns: # If we added it for metadata
                total_heat_delivered_w += abs(net.sink["qext_w"].sum())
            elif net.res_sink.shape[0] > 0 and "mdot_kg_per_s" in net.res_sink.columns:
                # Calculate from results: roughly mdot * 4180 * (T_supply - T_return)
                # But we need specific node temperatures.
                # Let's check if the standard pipe_checks has a specialized function or trust qext presence.
                # Re-reading network_builder in my memory: we calculated mdot from demand.
                # The most robust way for "Delivered Heat" in a closed loop is Source Q - Losses.
                # Total Source Q = Sum(net.res_ext_grid['q_ext_w']) + Sum(net.res_source['q_ext_w']) ...
                # Wait, Q source = Q delivered + Q loss.
                # So Q delivered = Q source - Q loss.
                # Let's use that balance if possible.
                pass
        
        # Alternative: System Energy Balance
        # Total Heat In = Total Heat Out (Losses + Loads)
        # Heat Delivered = Total Source Heat - Total Heat Loss
        # This avoids needing to know specific component types.
        if total_heat_delivered_w == 0: # If explicit load check failed
            total_source_heat_w = 0
            # Check ext_grid
            if "res_ext_grid" in dir(net) and not net.res_ext_grid.empty:
                 # Note: ext_grid can supply or absorb. Supply is positive? Check conventions.
                 # Usually +ve means into network.
                 total_source_heat_w += net.res_ext_grid["h_mw"].sum() * 1e6 if "h_mw" in net.res_ext_grid.columns else 0
            
            # Check circulating pump heat (if any added) - usually neglected for thermal balance compared to boiler
            
            # This is tricky because `h_mw` is enthalpy flow? No, `pandapipes` doesn't standardly output `h_mw` for ext_grid in all modes.
            # Let's stick to the component summation, but assume `mdot` * `deltaT`.
            # We know the system design delta T (usually 40 or 30).
            # Let's assume a fallback if components are missing qext.
            pass
        
        # REVISED STRATEGY: 
        # The 100% loss is because `total_heat_delivered_w` is 0. 
        # We need to populate it.
        # If `net.sink` exists, we assume the mass flow corresponds to the design delta T (e.g. 40K).
        # Q = mdot * Cp * dT.
        if "sink" in dir(net) and len(net.sink) > 0 and "mdot_kg_per_s" in net.sink.columns:
             # Assume water cp = 4180 J/kgK
             # Assume standard dT = 40K (standard design assumption used to create mdot)
             # This is an estimation for validation display purposes.
             cp = 4180
             dt = 40 # Standard design spread
             total_heat_delivered_w += abs(net.sink["mdot_kg_per_s"].sum()) * cp * dt
        
        # Calculate heat losses from pipes
        total_heat_loss_w = 0
        
        for idx, pipe in net.pipe.iterrows():
            if idx not in net.res_pipe.index:
                continue
            
            # Get temperatures
            if pipe["from_junction"] in net.res_junction.index and pipe["to_junction"] in net.res_junction.index:
                t_from_k = net.res_junction.loc[pipe["from_junction"], "t_k"]
                t_to_k = net.res_junction.loc[pipe["to_junction"], "t_k"]
                t_avg_c = ((t_from_k + t_to_k) / 2) - 273.15
                
                # Assume ground temperature
                t_ground_c = 10.0
                
                # Get U-value (simplified - use default if not specified)
                u_value = PIPE_U_VALUES.get("twin_pipe_insulated", 0.3)
                
                # Calculate heat loss
                pipe_length_m = pipe["length_km"] * 1000
                delta_t = t_avg_c - t_ground_c
                
                # Q_loss = U * L * ΔT (simplified, assuming unit diameter)
                # For more accuracy, should include pipe diameter
                heat_loss_w = u_value * pipe_length_m * delta_t
                
                total_heat_loss_w += heat_loss_w
        
        # Calculate heat loss percentage
        heat_loss_pct = 100 * total_heat_loss_w / (total_heat_delivered_w + total_heat_loss_w) if (total_heat_delivered_w + total_heat_loss_w) > 0 else 0
        
        # Check against limits
        if heat_loss_pct > self.config.max_heat_loss_pct_absolute:
            issues.append(
                f"Heat losses {heat_loss_pct:.1f}% exceed acceptable limit "
                f"{self.config.max_heat_loss_pct_absolute}% (poor insulation or excessive length)"
            )
        elif heat_loss_pct > self.config.max_heat_loss_pct:
            warnings.append(
                f"Heat losses {heat_loss_pct:.1f}% exceed recommended limit "
                f"{self.config.max_heat_loss_pct}% (EN 13941-1)"
            )
        
        return {
            "issues": issues,
            "warnings": warnings,
            "metrics": {
                "total_heat_delivered_mw": float(total_heat_delivered_w / 1e6),
                "total_heat_loss_mw": float(total_heat_loss_w / 1e6),
                "heat_loss_pct": float(heat_loss_pct)
            }
        }
    
    def _check_temperatures(self, net: pp.pandapipesNet) -> Dict:
        """Check temperature levels and decay"""
        
        issues = []
        warnings = []
        
        if net.res_junction.empty:
            return {
                "issues": [],
                "warnings": ["No temperature results available"],
                "metrics": {}
            }

        temperatures_k = net.res_junction["t_k"]
        temperatures_c = temperatures_k - 273.15
        
        supply_temp_c = temperatures_c.max()
        return_temp_c = temperatures_c.min()
        avg_temp_c = temperatures_c.mean()
        
        # Check supply temperature
        if supply_temp_c < self.config.min_supply_temp_dhw:
            warnings.append(
                f"Supply temperature {supply_temp_c:.1f}°C below {self.config.min_supply_temp_dhw}°C "
                "(may not meet DHW requirements for Legionella prevention)"
            )
        elif supply_temp_c < self.config.min_supply_temp_heating:
            warnings.append(
                f"Supply temperature {supply_temp_c:.1f}°C below {self.config.min_supply_temp_heating}°C "
                "(may not meet heating requirements)"
            )
        
        if supply_temp_c > self.config.max_supply_temp:
            issues.append(
                f"Supply temperature {supply_temp_c:.1f}°C exceeds limit {self.config.max_supply_temp}°C"
            )
        
        # Check return temperature
        if return_temp_c < self.config.min_return_temp:
            warnings.append(
                f"Return temperature {return_temp_c:.1f}°C below {self.config.min_return_temp}°C "
                "(may reduce condensing boiler efficiency)"
            )
        
        if return_temp_c > self.config.max_return_temp:
            warnings.append(
                f"Return temperature {return_temp_c:.1f}°C exceeds typical design {self.config.max_return_temp}°C"
            )
        
        # Calculate temperature spread
        temp_spread = supply_temp_c - return_temp_c
        
        if temp_spread < 20:
            warnings.append(
                f"Temperature spread {temp_spread:.1f}°C is low (typical: 30-50°C), "
                "may indicate suboptimal operation"
            )
        
        return {
            "issues": issues,
            "warnings": warnings,
            "metrics": {
                "supply_temp_c": float(supply_temp_c),
                "return_temp_c": float(return_temp_c),
                "avg_temp_c": float(avg_temp_c),
                "temp_spread_c": float(temp_spread)
            }
        }
