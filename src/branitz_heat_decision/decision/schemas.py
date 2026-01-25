"""
Canonical KPI Contract Schema v1.0
All fields are required unless marked Optional.
"""

from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
import json

# Reason Code Taxonomy (complete list)
REASON_CODES = {
    # Feasibility
    "DH_OK": "District heating meets all EN 13941-1 hydraulic and thermal constraints",
    "DH_VELOCITY_VIOLATION": "DH velocity exceeds 1.5 m/s limit",
    "DH_DP_VIOLATION": "DH pressure drop per 100m exceeds EN 13941-1 envelope",
    "DH_HARD_VIOLATION": "DH has hard constraint violations (e.g., negative pressures)",
    "DH_HIGH_LOSSES_WARNING": "DH thermal losses exceed 5% threshold",
    
    "HP_OK": "Heat pumps meet all VDE-AR-N 4100 LV grid constraints",
    "HP_UNDERVOLTAGE": "HP rollout causes voltage < 0.95 pu",
    "HP_OVERCURRENT_OR_OVERLOAD": "HP rollout causes line loading > 100%",
    "HP_PLANNING_WARNING_80PCT": "HP rollout exceeds 80% planning headroom",
    
    # Decision logic
    "ONLY_DH_FEASIBLE": "Only district heating is technically feasible",
    "ONLY_HP_FEASIBLE": "Only heat pumps are technically feasible",
    "NONE_FEASIBLE": "Neither option meets technical constraints",
    
    "COST_DOMINANT_DH": "DH LCOH is >5% lower than HP (clear economic winner)",
    "COST_DOMINANT_HP": "HP LCOH is >5% lower than DH (clear economic winner)",
    "COST_CLOSE_USE_CO2": "LCOH difference ≤5% → using CO₂ as tie-breaker",
    "CO2_TIEBREAKER_DH": "DH chosen due to lower CO₂ emissions (costs close)",
    "CO2_TIEBREAKER_HP": "HP chosen due to lower CO₂ emissions (costs close)",
    
    # Robustness
    "ROBUST_DECISION": "Monte Carlo win fraction ≥70% → decision stable",
    "SENSITIVE_DECISION": "Monte Carlo win fraction 55-70% → decision sensitive",
    
    # Data quality
    "CHA_MISSING_KPIS": "Missing critical CHA KPIs (cannot assess DH feasibility)",
    "DHA_MISSING_KPIS": "Missing critical DHA KPIs (cannot assess HP feasibility)",
    "MC_MISSING": "Monte Carlo data missing → robustness cannot be assessed",

    # ---------------------------------------------------------------------
    # Additional Phase-5 reason codes (to reach 30+ and cover edge cases)
    # ---------------------------------------------------------------------
    # Data quality (4)
    "CHA_DATA_INCOMPLETE": "CHA: Missing envelope or typology data; using TABULA defaults",
    "DHA_SYNTHETIC_GRID_WARNING": "DHA: LV grid is synthetic/approximated; validation with utility data required",
    "ECON_DATA_ESTIMATED": "Economics: Annual heat demand estimated from design load; real meter data preferred",
    "MC_SAMPLE_WARNING_LT100": "Monte Carlo: <100 samples; confidence intervals may be unreliable",

    # Economics edge cases (3)
    "COST_RATIO_EXTREME_GT3X": "Economics: LCOH ratio >3x between options; sensitivity analysis strongly recommended",
    "CO2_NEGATIVE_HP": "CO2: HP emissions negative in scenario (grid factor <0); check emission factor assumptions",
    "LCOH_EQUALITY": "LCOH tie: Costs are identical; decision based purely on CO2 or robustness",

    # Technical warnings (2)
    "DH_OVERSIZED_MINOR": "DH: Network slightly oversized (v_avg <0.3 m/s); minor cost optimization possible",
    "HP_LOADING_MARGINAL_80_85": "HP: Max feeder loading 80-85%; marginal planning warning; monitor grid evolution",

    # Export/Map issues (1)
    "CHOROPLETH_MISSING": "Visualization: Interactive map missing; QGIS export failed or not requested",
}

@dataclass
class LCOHMetrics:
    """Levelized Cost of Heat with uncertainty quantiles."""
    median: float  # EUR/MWh
    p05: float     # 5th percentile
    p95: float     # 95th percentile
    mean: Optional[float] = None
    std: Optional[float] = None

@dataclass
class CO2Metrics:
    """CO₂ emissions with uncertainty quantiles."""
    median: float  # kg CO₂/MWh
    p05: float
    p95: float
    mean: Optional[float] = None
    std: Optional[float] = None

@dataclass
class HydraulicsKPIs:
    """EN 13941-1 hydraulic performance."""
    velocity_ok: bool
    dp_ok: bool
    v_max_ms: float
    v_min_ms: float
    v_share_within_limits: float  # 0-1
    dp_per_100m_max: float
    hard_violations: List[str]  # List of specific violations

@dataclass
class LossesKPIs:
    """Thermal losses and pumping energy."""
    total_length_m: float
    trunk_length_m: float
    service_length_m: float
    loss_share_pct: float  # % of delivered heat
    pump_power_kw: float

@dataclass
class LVGridKPIs:
    """VDE-AR-N 4100 LV grid performance."""
    planning_warning: bool
    max_feeder_loading_pct: float
    voltage_violations_total: int
    line_violations_total: int
    worst_bus_id: Optional[str]
    worst_line_id: Optional[str]

@dataclass
class DistrictHeatingBlock:
    """Complete DH assessment block."""
    feasible: bool
    reasons: List[str]  # From REASON_CODES
    lcoh: LCOHMetrics
    co2: CO2Metrics
    hydraulics: HydraulicsKPIs
    losses: LossesKPIs

@dataclass
class HeatPumpsBlock:
    """Complete HP assessment block."""
    feasible: bool
    reasons: List[str]
    lcoh: LCOHMetrics
    co2: CO2Metrics
    lv_grid: LVGridKPIs
    hp_system: Dict[str, float]  # e.g., hp_total_kw_design

@dataclass
class MonteCarloBlock:
    """Uncertainty propagation results."""
    dh_wins_fraction: float  # 0-1
    hp_wins_fraction: float
    n_samples: int
    seed: Optional[int]

@dataclass
class KPIContract:
    """Canonical KPI contract (root object)."""
    cluster_id: str
    metadata: Dict[str, Any]  # created_utc, inputs, notes
    district_heating: DistrictHeatingBlock
    heat_pumps: HeatPumpsBlock
    monte_carlo: Optional[MonteCarloBlock]
    version: str = "1.0"

class ContractValidator:
    """Strict schema validation for KPI contracts."""
    
    @staticmethod
    def validate(contract: Dict[str, Any]) -> None:
        """Validate entire contract. Raises ValueError with detailed message."""
        
        # Top-level keys
        required_keys = ['version', 'cluster_id', 'metadata', 'district_heating', 'heat_pumps']
        missing = [k for k in required_keys if k not in contract]
        if missing:
            raise ValueError(f"Contract missing top-level keys: {missing}")
        
        # Version check
        if contract['version'] != "1.0":
            raise ValueError(f"Unsupported contract version: {contract['version']}")
        
        # Validate metadata
        metadata = contract['metadata']
        if 'created_utc' not in metadata:
            raise ValueError("metadata must contain 'created_utc' timestamp")
        
        # Validate DH block
        ContractValidator._validate_dh_block(contract['district_heating'])
        
        # Validate HP block
        ContractValidator._validate_hp_block(contract['heat_pumps'])
        
        # Validate MC block (optional but if present must be complete)
        if 'monte_carlo' in contract and contract['monte_carlo'] is not None:
            ContractValidator._validate_mc_block(contract['monte_carlo'])
    
    @staticmethod
    def _validate_dh_block(dh: Dict[str, Any]) -> None:
        """Validate DistrictHeatingBlock."""
        if not isinstance(dh['feasible'], bool):
            raise ValueError("district_heating.feasible must be boolean")
        
        if not isinstance(dh['reasons'], list) or len(dh['reasons']) == 0:
            raise ValueError("district_heating.reasons must be non-empty list")
        
        # Validate reason codes exist
        for reason in dh['reasons']:
            if reason not in REASON_CODES:
                raise ValueError(f"Unknown reason code: {reason}")
        
        # Validate LCOH metrics
        lcoh = dh['lcoh']
        for key in ['median', 'p05', 'p95']:
            if key not in lcoh or not isinstance(lcoh[key], (int, float)):
                raise ValueError(f"district_heating.lcoh.{key} must be numeric")
        
        # Validate hydraulic constraints
        hyd = dh['hydraulics']
        if not isinstance(hyd['velocity_ok'], bool):
            raise ValueError("hydraulics.velocity_ok must be boolean")
        
        if not (0 <= hyd['v_share_within_limits'] <= 1):
            raise ValueError("hydraulics.v_share_within_limits must be between 0 and 1")
    
    @staticmethod
    def _validate_hp_block(hp: Dict[str, Any]) -> None:
        """Validate HeatPumpsBlock."""
        if not isinstance(hp['feasible'], bool):
            raise ValueError("heat_pumps.feasible must be boolean")
        
        if not isinstance(hp['reasons'], list) or len(hp['reasons']) == 0:
            raise ValueError("heat_pumps.reasons must be non-empty list")
        
        # Validate LV grid metrics
        lv = hp['lv_grid']
        # Loading percent can exceed 200% in stressed scenarios; only enforce non-negative.
        if not (0 <= lv['max_feeder_loading_pct'] <= 1000):
            raise ValueError("lv_grid.max_feeder_loading_pct must be 0-1000%")
        
        # Voltage violations: must be int or None (not missing)
        if lv['voltage_violations_total'] is not None:
            if not isinstance(lv['voltage_violations_total'], int):
                raise ValueError("lv_grid.voltage_violations_total must be int or None")
    
    @staticmethod
    def _validate_mc_block(mc: Dict[str, Any]) -> None:
        """Validate MonteCarloBlock."""
        if not (0 <= mc['dh_wins_fraction'] <= 1):
            raise ValueError("monte_carlo.dh_wins_fraction must be 0-1")
        
        if not isinstance(mc['n_samples'], int) or mc['n_samples'] < 1:
            raise ValueError("monte_carlo.n_samples must be positive integer")