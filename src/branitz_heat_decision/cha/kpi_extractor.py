"""
KPI Extraction Module for CHA (Central Heating Agent).

Extracts EN 13941-1 compliant key performance indicators from converged pandapipes networks.
All metrics are deterministic and traceable to simulation results.
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, Optional, Tuple, List
import pandapipes as pp
import logging

from .config import CHAConfig, get_default_config
from ..config import resolve_cluster_path

logger = logging.getLogger(__name__)

# EN 13941-1 Standard Limits
EN_13941_VELOCITY_MAX_MS = 1.5  # m/s
EN_13941_DP_PER_100M_MAX_BAR = 0.3  # bar per 100m
EN_13941_VELOCITY_SHARE_MIN = 0.95  # 95% of segments must meet velocity limit

# Physical constants
CP_WATER_KJ_KGK = 4.186  # kJ/(kg·K)
RHO_WATER_KG_M3 = 1000.0  # kg/m³


class KPIExtractor:
    """
    Extracts EN 13941-1 KPIs from pandapipes network.
    
    Provides both pipe-level detailed results and network-level aggregates.
    All calculations are vectorized for performance.
    """
    
    def __init__(self, net: pp.pandapipesNet, config: Optional[CHAConfig] = None):
        """
        Initialize KPI extractor.
        
        Args:
            net: Converged pandapipes network
            config: CHAConfig with physical parameters
        """
        self.net = net
        self.config = config or get_default_config()
        self._validate_converged()
    
    def _validate_converged(self):
        """Ensure network has converged results."""
        if self.net.converged is None or not self.net.converged:
            raise ValueError("Network has not converged. Run pipeflow() before extracting KPIs.")
        
        if self.net.res_pipe is None or self.net.res_pipe.shape[0] == 0:
            raise ValueError("No pipe results available. Network may not have converged properly.")
        
        if self.net.res_junction is None:
            raise ValueError("No junction results available.")
        
        logger.info(f"KPI extractor initialized for network with {len(self.net.pipe)} pipes")
    
    def extract_kpis(
        self,
        cluster_id: str,
        design_hour: int,
        detailed: bool = True
    ) -> Dict[str, Any]:
        """
        Extract complete EN 13941-1 KPI set.
        
        Args:
            cluster_id: Cluster identifier
            design_hour: Hour index used for design
            detailed: Include pipe-level details
            
        Returns:
            Dict with nested structure:
            {
                'cluster_id': str,
                'design_hour': int,
                'aggregate': {...},
                'hydraulics': {...},
                'thermal': {...},
                'losses': {...},
                'pump': {...},
                'en13941_compliance': {...},
                'detailed': {...}
            }
        """
        logger.info(f"Extracting KPIs for cluster {cluster_id}, design hour {design_hour}")
        
        # Extract pipe-level data
        pipe_kpis = self._extract_pipe_kpis() if detailed else None
        
        # Extract network-level KPIs
        network_kpis = self._extract_network_kpis()
        
        # Compute aggregates
        aggregate = self._compute_aggregate_kpis(pipe_kpis, network_kpis)
        
        # EN 13941-1 compliance
        compliance = self._check_en13941_compliance(aggregate, network_kpis)
        
        # Compile final result
        result = {
            'cluster_id': cluster_id,
            'design_hour': int(design_hour),
            'aggregate': aggregate,
            'hydraulics': {
                'velocity_ok': compliance['velocity_ok'],
                'dp_ok': compliance['dp_ok'],
                'max_velocity_ms': aggregate['v_max_ms'],
                'mean_velocity_ms': aggregate['v_mean_ms'],
                'min_velocity_ms': aggregate['v_min_ms'],
                'velocity_share_within_limits': aggregate['v_share_within_limits'],
                'velocity_distribution': aggregate['velocity_distribution'],
            },
            'thermal': {
                'supply_temp_c': aggregate['t_supply_c'],
                'return_temp_c': aggregate['t_return_c'],
                'temp_diff_k': aggregate['delta_t_k'],
                'max_temp_drop_c': aggregate['max_temp_drop_c'],
                'mean_temp_drop_c': aggregate['mean_temp_drop_c'],
            },
            'losses': {
                'total_thermal_loss_kw': aggregate['total_thermal_loss_kw'],
                'loss_share_percent': aggregate['loss_share_percent'],
                'loss_per_100m_kw': aggregate['loss_per_100m_kw'],
                'length_total_m': aggregate['length_total_m'],
                'length_supply_m': aggregate['length_supply_m'],
                'length_return_m': aggregate['length_return_m'],
                'length_service_m': aggregate['length_service_m'],
            },
            'pump': {
                'pump_power_kw': network_kpis['pump_power_kw'],
                'pump_power_per_kwth': network_kpis['pump_power_per_kwth'],
                'circulation_pump_efficiency': network_kpis.get('pump_efficiency', 0.75),
            },
            'en13941_compliance': compliance,
        }
        
        if detailed:
            result['detailed'] = {
                'pipes': pipe_kpis.to_dict('records') if isinstance(pipe_kpis, pd.DataFrame) else pipe_kpis,
                'junctions': self._extract_junction_kpis().to_dict('records'),
                'heat_consumers': self._extract_heat_consumer_kpis().to_dict('records'),
                'sinks': self._extract_sink_kpis().to_dict('records'),
            }
        
        logger.info(f"KPI extraction complete. Feasible: {compliance['feasible']}")
        return result
    
    def _extract_pipe_kpis(self) -> pd.DataFrame:
        """
        Extract pipe-level hydraulic and thermal KPIs.
        
        Returns:
            DataFrame with one row per pipe
        """
        pipe_data = []
        
        for pipe_idx, pipe in self.net.pipe.iterrows():
            res = self.net.res_pipe.loc[pipe_idx]
            
            # Basic pipe info
            pipe_info = {
                'pipe_id': int(pipe_idx),
                'name': pipe.get('name', f'pipe_{pipe_idx}'),
                'from_junction': int(pipe['from_junction']),
                'to_junction': int(pipe['to_junction']),
                'length_m': float(pipe['length_km'] * 1000),
                'diameter_mm': float(pipe['diameter_m'] * 1000),
                'std_type': pipe.get('std_type', 'unknown'),
                'is_service': 'service' in str(pipe.get('name', '')).lower(),
            }
            
            # Hydraulic KPIs
            # pandapipes result column names differ across versions
            v = res.get('v_mean_ms', res.get('v_mean_m_per_s', np.nan))
            mdot = res.get('mdot_from_kg_s', res.get('mdot_from_kg_per_s', np.nan))
            pipe_info.update({
                'velocity_ms': float(v),
                'mass_flow_kgs': float(mdot),
                'pressure_from_bar': float(res.get('p_from_bar', np.nan)),
                'pressure_to_bar': float(res.get('p_to_bar', np.nan)),
                'pressure_drop_bar': float(res.get('p_from_bar', 0.0) - res.get('p_to_bar', 0.0)),
                'pressure_drop_per_100m_bar': float(
                    (res.get('p_from_bar', 0.0) - res.get('p_to_bar', 0.0)) / (pipe['length_km'] * 10)
                ),
                'reynolds_number': float(res.get('reynolds', np.nan)),
                'lambda_friction': float(res.get('lambda', np.nan)),
            })
            
            # Thermal KPIs
            tfrom_k = res.get('tfrom_k', res.get('t_from_k', np.nan))
            tto_k = res.get('tto_k', res.get('t_to_k', np.nan))
            
            # Heat loss calculation:
            # Option 1: If qext_w exists in results, use it (rare in pandapipes)
            # Option 2: Compute from temperature drop: Q_loss = mdot × cp × (T_from - T_to)
            # Option 3: Compute from U-value: Q_loss = U × A × (T_fluid - T_soil) × L
            qext_w = res.get('qext_w', np.nan)
            if qext_w == qext_w:  # Not NaN
                heat_loss_w = float(qext_w)
            elif tfrom_k == tfrom_k and tto_k == tto_k and mdot == mdot:
                # Compute from temperature drop (most accurate for thermal simulation)
                t_mean_k = (tfrom_k + tto_k) / 2.0
                delta_t_pipe_k = abs(tfrom_k - tto_k)
                cp_j_per_kgk = CP_WATER_KJ_KGK * 1000.0  # Convert to J/(kg·K)
                heat_loss_w = abs(mdot) * cp_j_per_kgk * delta_t_pipe_k
            elif 'u_w_per_m2k' in pipe.index and 'text_k' in pipe.index:
                # Compute from U-value (fallback if thermal solver didn't run)
                u_w_per_m2k = pipe['u_w_per_m2k']
                text_k = pipe['text_k']
                t_mean_k = (tfrom_k + tto_k) / 2.0 if (tfrom_k == tfrom_k and tto_k == tto_k) else tfrom_k
                if t_mean_k == t_mean_k and u_w_per_m2k > 0:
                    # Use effective area convention (same as in heat_loss.py)
                    # For "d" convention: A_eff = d_o (outer diameter)
                    # For "pi_d": A_eff = π × d_o
                    d_o_m = pipe.get('diameter_m', 0.05) + 0.1  # Approximate outer diameter
                    area_conv = getattr(self.config, 'heat_loss_area_convention', 'd')
                    a_eff_per_m = (np.pi * d_o_m) if area_conv == 'pi_d' else d_o_m
                    length_m = pipe['length_km'] * 1000.0
                    delta_t_k = max(0.0, t_mean_k - text_k)
                    heat_loss_w = u_w_per_m2k * a_eff_per_m * delta_t_k * length_m
                else:
                    heat_loss_w = 0.0
            else:
                heat_loss_w = 0.0
            
            pipe_info.update({
                'temp_from_c': float(tfrom_k - 273.15) if tfrom_k == tfrom_k else np.nan,
                'temp_to_c': float(tto_k - 273.15) if tto_k == tto_k else np.nan,
                'temp_drop_c': float(tfrom_k - tto_k) if (tfrom_k == tfrom_k and tto_k == tto_k) else np.nan,
                'heat_loss_kw': float(heat_loss_w) / 1000.0,
                'heat_loss_per_m_w': float(heat_loss_w) / max((pipe['length_km'] * 1000.0), 0.001),
            })
            
            # Compliance flags
            pipe_info['velocity_within_limit'] = pipe_info['velocity_ms'] <= EN_13941_VELOCITY_MAX_MS
            pipe_info['dp_within_limit'] = pipe_info['pressure_drop_per_100m_bar'] <= EN_13941_DP_PER_100M_MAX_BAR
            
            pipe_data.append(pipe_info)
        
        return pd.DataFrame(pipe_data)
    
    def _extract_network_kpis(self) -> Dict[str, float]:
        """
        Extract network-level aggregate KPIs.
        
        Returns:
            Dict of network metrics
        """
        # Mass flow: prefer ext_grid injection (plant supply). Fallback to heat consumers.
        total_mdot_kgs = 0.0
        if hasattr(self.net, "res_ext_grid") and self.net.res_ext_grid is not None and not self.net.res_ext_grid.empty:
            mdot_col = "mdot_kg_per_s" if "mdot_kg_per_s" in self.net.res_ext_grid.columns else None
            if mdot_col:
                total_mdot_kgs = float(self.net.res_ext_grid[mdot_col].sum())
        elif hasattr(self.net, "res_heat_consumer") and self.net.res_heat_consumer is not None and not self.net.res_heat_consumer.empty:
            mdot_col = "mdot_kg_per_s" if "mdot_kg_per_s" in self.net.res_heat_consumer.columns else None
            if mdot_col:
                total_mdot_kgs = float(self.net.res_heat_consumer[mdot_col].sum())
        
        # Pump power (circulation pump)
        pump_power_kw = 0.0
        pump_efficiency = 0.75
        if hasattr(self.net, "res_circ_pump_const_pressure") and self.net.res_circ_pump_const_pressure is not None and not self.net.res_circ_pump_const_pressure.empty:
            if "p_kw" in self.net.res_circ_pump_const_pressure.columns:
                pump_power_kw = float(self.net.res_circ_pump_const_pressure["p_kw"].sum())
        
        # Heat delivered: prefer heat consumers (qext_w). Fallback to mdot*cp*ΔT.
        if hasattr(self.net, "heat_consumer") and self.net.heat_consumer is not None and not self.net.heat_consumer.empty:
            total_heat_kw = float(self.net.heat_consumer["qext_w"].sum() / 1000.0) if "qext_w" in self.net.heat_consumer.columns else 0.0
        else:
            total_heat_kw = float(total_mdot_kgs * CP_WATER_KJ_KGK * self.config.delta_t_k / 1000.0)
        
        # Heat losses: compute from temperature drop or U-value
        # pandapipes doesn't store qext_w in res_pipe, so we compute it
        total_heat_loss_kw = 0.0
        if hasattr(self.net, "res_pipe") and self.net.res_pipe is not None and not self.net.res_pipe.empty:
            # Try qext_w first (if it exists)
            if "qext_w" in self.net.res_pipe.columns:
                total_heat_loss_kw = float(self.net.res_pipe["qext_w"].sum() / 1000.0)
            else:
                # Compute from temperature drop: Q_loss = mdot × cp × ΔT
                # This is the actual heat loss computed by pandapipes thermal solver
                cp_j_per_kgk = CP_WATER_KJ_KGK * 1000.0
                for pipe_idx, pipe in self.net.pipe.iterrows():
                    res = self.net.res_pipe.loc[pipe_idx]
                    t_from_k = res.get('t_from_k', res.get('tfrom_k', np.nan))
                    t_to_k = res.get('t_to_k', res.get('tto_k', np.nan))
                    mdot = abs(res.get('mdot_from_kg_per_s', res.get('mdot_from_kg_s', 0.0)))
                    
                    if t_from_k == t_from_k and t_to_k == t_to_k and mdot > 0:
                        delta_t_k = abs(t_from_k - t_to_k)
                        pipe_loss_kw = (mdot * cp_j_per_kgk * delta_t_k) / 1000.0
                        total_heat_loss_kw += pipe_loss_kw
        
        # Temperature statistics (DH): prefer boundary supply temperature + heat consumer outlet temperature.
        t_supply_avg_c = np.nan
        t_return_avg_c = np.nan
        delta_t_avg_k = np.nan

        # Supply boundary temperature from ext_grid(s)
        if hasattr(self.net, "ext_grid") and self.net.ext_grid is not None and not self.net.ext_grid.empty:
            if "t_k" in self.net.ext_grid.columns:
                try:
                    t_supply_avg_c = float(self.net.ext_grid["t_k"].mean() - 273.15)
                except Exception:
                    pass

        # Return temperature from heat consumer outlet (t_to_k)
        if hasattr(self.net, "res_heat_consumer") and self.net.res_heat_consumer is not None and not self.net.res_heat_consumer.empty:
            if "t_to_k" in self.net.res_heat_consumer.columns:
                try:
                    t_return_avg_c = float(self.net.res_heat_consumer["t_to_k"].mean() - 273.15)
                except Exception:
                    pass

        if t_supply_avg_c == t_supply_avg_c and t_return_avg_c == t_return_avg_c:
            delta_t_avg_k = float(t_supply_avg_c - t_return_avg_c)
        
        return {
            'total_heat_demand_kw': float(total_heat_kw),
            'total_mass_flow_kgs': float(total_mdot_kgs),
            'pump_power_kw': float(pump_power_kw),
            'pump_power_per_kwth': float(pump_power_kw / total_heat_kw) if total_heat_kw > 0 else 0,
            'pump_efficiency': float(pump_efficiency),
            'total_thermal_loss_kw': float(total_heat_loss_kw),
            'efficiency_percent': float(100 * (1 - total_heat_loss_kw / total_heat_kw)) if total_heat_kw > 0 else np.nan,
            't_supply_avg_c': float(t_supply_avg_c) if t_supply_avg_c == t_supply_avg_c else np.nan,
            't_return_avg_c': float(t_return_avg_c) if t_return_avg_c == t_return_avg_c else np.nan,
            'delta_t_avg_k': float(delta_t_avg_k) if delta_t_avg_k == delta_t_avg_k else np.nan,
        }
    
    def _compute_aggregate_kpis(
        self,
        pipe_kpis: Optional[pd.DataFrame],
        network_kpis: Dict[str, float]
    ) -> Dict[str, float]:
        """
        Compute aggregated statistics from pipe-level data.
        
        Args:
            pipe_kpis: DataFrame from _extract_pipe_kpis()
            network_kpis: Dict from _extract_network_kpis()
            
        Returns:
            Dict of aggregated metrics
        """
        if pipe_kpis is None:
            return self._compute_aggregate_from_network(network_kpis)
        
        # Length statistics
        # Determine supply/return by pipe name conventions.
        name_l = pipe_kpis["name"].astype(str).str.lower()
        supply_pipes = pipe_kpis[(~pipe_kpis["is_service"]) & (name_l.str.startswith("pipe_s") | name_l.str.contains("_s_"))]
        return_pipes = pipe_kpis[(~pipe_kpis["is_service"]) & (name_l.str.startswith("pipe_r") | name_l.str.contains("_r_"))]
        service_pipes = pipe_kpis[pipe_kpis["is_service"]]
        
        # Velocity statistics
        velocity_stats = pipe_kpis['velocity_ms'].agg(['min', 'max', 'mean', 'std'])
        
        # Distribution of velocities (for histogram)
        velocity_bins = np.linspace(0, EN_13941_VELOCITY_MAX_MS * 1.5, 20)
        velocity_hist, _ = np.histogram(pipe_kpis['velocity_ms'], bins=velocity_bins)
        velocity_distribution = {
            'bins': velocity_bins.tolist(),
            'counts': velocity_hist.tolist(),
            'bin_width': float(velocity_bins[1] - velocity_bins[0]),
        }
        
        # Share within limits
        v_share = float((pipe_kpis['velocity_ms'] <= EN_13941_VELOCITY_MAX_MS).mean())
        
        # Pressure drop statistics
        dp_stats = pipe_kpis['pressure_drop_per_100m_bar'].agg(['min', 'max', 'mean', 'std'])
        
        # Temperature statistics
        temp_drop_stats = pipe_kpis['temp_drop_c'].agg(['min', 'max', 'mean', 'std'])
        
        return {
            # Lengths
            'length_total_m': float(pipe_kpis['length_m'].sum()),
            'length_supply_m': float(supply_pipes['length_m'].sum()),
            'length_return_m': float(return_pipes['length_m'].sum()),
            'length_service_m': float(service_pipes['length_m'].sum()),
            
            # Velocities
            'v_min_ms': float(velocity_stats['min']),
            'v_max_ms': float(velocity_stats['max']),
            'v_mean_ms': float(velocity_stats['mean']),
            'v_std_ms': float(velocity_stats['std']),
            'v_share_within_limits': v_share,
            'velocity_distribution': velocity_distribution,
            
            # Pressure drops
            'dp_min_bar_per_100m': float(dp_stats['min']),
            'dp_max_bar_per_100m': float(dp_stats['max']),
            'dp_mean_bar_per_100m': float(dp_stats['mean']),
            
            # Temperatures
            't_supply_c': float(network_kpis['t_supply_avg_c']),
            't_return_c': float(network_kpis['t_return_avg_c']),
            'delta_t_k': float(network_kpis['delta_t_avg_k']),
            'max_temp_drop_c': float(temp_drop_stats['max']),
            'mean_temp_drop_c': float(temp_drop_stats['mean']),
            
            # Losses
            'total_thermal_loss_kw': float(network_kpis['total_thermal_loss_kw']),
            'loss_share_percent': float(100 * network_kpis['total_thermal_loss_kw'] / network_kpis['total_heat_demand_kw'])
            if network_kpis.get('total_heat_demand_kw', 0.0) > 0 else np.nan,
            'loss_per_100m_kw': float(pipe_kpis['heat_loss_per_m_w'].sum() * 10),
        }
    
    def _check_en13941_compliance(self, aggregate: Dict[str, float], network: Dict[str, float]) -> Dict[str, Any]:
        """
        Check compliance with EN 13941-1 standard limits.
        
        Args:
            aggregate: Aggregate KPIs
            network: Network KPIs
            
        Returns:
            Dict with compliance flags and reason codes
        """
        # Velocity compliance
        velocity_ok = aggregate['v_share_within_limits'] >= EN_13941_VELOCITY_SHARE_MIN
        
        # Pressure drop compliance
        dp_ok = aggregate['dp_max_bar_per_100m'] <= EN_13941_DP_PER_100M_MAX_BAR
        
        # Overall feasibility
        feasible = velocity_ok and dp_ok
        
        # Reason codes
        reasons = []
        if feasible:
            reasons.append('DH_OK')
        else:
            if not velocity_ok:
                reasons.append('DH_VELOCITY_VIOLATION')
            if not dp_ok:
                reasons.append('DH_DP_VIOLATION')
        
        # Planning warnings (non-fatal)
        warnings = []
        if aggregate['loss_share_percent'] > 5.0:
            warnings.append('DH_HIGH_LOSSES_WARNING')
        
        if aggregate['v_max_ms'] > EN_13941_VELOCITY_MAX_MS * 1.1:
            warnings.append('DH_VELOCITY_MARGIN_EXCEEDED')
        
        return {
            'feasible': feasible,
            'velocity_ok': velocity_ok,
            'dp_ok': dp_ok,
            'reasons': reasons,
            'warnings': warnings,
            'standards': {
                'en_13941_velocity_max_ms': EN_13941_VELOCITY_MAX_MS,
                'en_13941_dp_max_bar_per_100m': EN_13941_DP_PER_100M_MAX_BAR,
                'en_13941_velocity_share_min': EN_13941_VELOCITY_SHARE_MIN,
            }
        }
    
    def _extract_junction_kpis(self) -> pd.DataFrame:
        """Extract junction-level temperature and pressure KPIs."""
        junction_data = []
        
        for junc_idx in self.net.junction.index:
            res = self.net.res_junction.loc[junc_idx]
            
            junction_data.append({
                'junction_id': int(junc_idx),
                'pressure_bar': float(res['p_bar']),
                'temperature_c': float(res['t_k'] - 273.15),
                'height_m': float(self.net.junction.loc[junc_idx, 'height_m']),
            })
        
        return pd.DataFrame(junction_data)
    
    def _extract_sink_kpis(self) -> pd.DataFrame:
        """Extract sink-level demand KPIs."""
        # Some network variants (DH heat_consumer) have no sinks at all.
        if not hasattr(self.net, "sink") or self.net.sink is None or self.net.sink.empty:
            return pd.DataFrame(columns=["sink_id", "building_id", "junction_id", "mass_flow_kgs", "heat_demand_kw"])
        sink_data = []
        
        for sink_idx, sink in self.net.sink.iterrows():
            res = self.net.res_sink.loc[sink_idx]
            building_id = sink.get('name', f'sink_{sink_idx}')
            mdot_col = 'mdot_kg_s' if 'mdot_kg_s' in res.index else 'mdot_kg_per_s'
            mdot = float(res.get(mdot_col, 0.0))
            
            sink_data.append({
                'sink_id': int(sink_idx),
                'building_id': str(building_id),
                'junction_id': int(sink['junction']),
                'mass_flow_kgs': mdot,
                'heat_demand_kw': float(mdot * CP_WATER_KJ_KGK * self.config.delta_t_k / 1000.0),
            })
        
        return pd.DataFrame(sink_data)

    def _extract_heat_consumer_kpis(self) -> pd.DataFrame:
        """Extract heat_consumer-level KPIs (district heating consumers)."""
        if not hasattr(self.net, "heat_consumer") or self.net.heat_consumer is None or self.net.heat_consumer.empty:
            return pd.DataFrame(columns=["heat_consumer_id", "building_id", "from_junction_id", "to_junction_id", "qext_kw"])

        data = []
        for hc_idx, hc in self.net.heat_consumer.iterrows():
            name = str(hc.get("name", f"hc_{hc_idx}"))
            building_id = name.replace("hc_", "") if name.startswith("hc_") else name
            qext_kw = float(hc.get("qext_w", 0.0)) / 1000.0 if "qext_w" in hc.index else 0.0
            data.append(
                {
                    "heat_consumer_id": int(hc_idx),
                    "building_id": building_id,
                    "from_junction_id": int(hc["from_junction"]),
                    "to_junction_id": int(hc["to_junction"]),
                    "qext_kw": qext_kw,
                }
            )
        return pd.DataFrame(data)


def extract_kpis(
    net: pp.pandapipesNet,
    cluster_id: str,
    design_hour: int,
    config: Optional[CHAConfig] = None,
    detailed: bool = True
) -> Dict[str, Any]:
    """
    Convenience function: extract KPIs from network.
    
    Args:
        net: Converged pandapipes network
        cluster_id: Cluster identifier
        design_hour: Design hour index
        config: CHAConfig
        detailed: Include detailed pipe/junction/sink data
        
    Returns:
        Dict with complete KPI structure
    """
    extractor = KPIExtractor(net, config)
    return extractor.extract_kpis(cluster_id, design_hour, detailed)