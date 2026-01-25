"""
Standards and limits for DH network validation.

Based on:
- EN 13941-1: Design and installation of district heating networks
- VDI 2067: Economic efficiency of building services
- VDI 4640: Thermal use of the underground
"""

from dataclasses import dataclass
from typing import Dict


@dataclass
class EN13941Standards:
    """EN 13941-1 Design standards for district heating"""
    
    # Velocity limits (m/s)
    max_velocity_recommended: float = 1.5  # Recommended max
    max_velocity_absolute: float = 3.0     # Absolute max
    min_velocity: float = 0.2               # Avoid sedimentation
    
    # Pressure limits (bar)
    max_pressure_drop_per_km: float = 1.0  # bar/km
    max_total_pressure_drop: float = 2.0   # bar
    min_pressure: float = 1.0               # bar (avoid cavitation)
    max_pressure: float = 16.0              # bar (typical PN16 pipes)
    
    # Temperature limits (°C)
    min_supply_temp_dhw: float = 65.0      # For DHW (Legionella prevention)
    min_supply_temp_heating: float = 55.0  # For space heating
    max_supply_temp: float = 130.0         # Typical limit
    min_return_temp: float = 30.0          # Condensing boiler efficiency
    max_return_temp: float = 70.0          # Typical design
    
    # Heat loss limits (%)
    max_heat_loss_pct: float = 5.0         # Recommended
    max_heat_loss_pct_absolute: float = 10.0  # Acceptable limit
    
    # Pump power limits
    max_specific_pump_power: float = 30.0  # W per kW thermal capacity
    
    # Pipe sizing
    min_pipe_diameter_mm: float = 25.0     # DN25 minimum for DH
    max_pipe_diameter_mm: float = 1000.0   # DN1000 typical max
    
    # Network topology
    max_pipe_length_km: float = 5.0        # Single feeder max length
    min_redundancy: bool = False            # Redundancy required?


@dataclass
class GeospatialTolerances:
    """Tolerances for geospatial checks"""
    
    # Street alignment
    street_buffer_m: float = 10.0          # Max distance from street centerline
    allow_private_property: bool = False    # Allow pipes on private land?
    
    # Building connectivity
    max_connection_distance_m: float = 50.0  # Max service pipe length
    min_connection_distance_m: float = 1.0   # Min distance from building
    
    # Topology
    max_segment_length_m: float = 500.0     # Max pipe segment without junction


@dataclass
class RobustnessThresholds:
    """Thresholds for robustness validation"""
    
    # Monte Carlo
    n_scenarios: int = 50                   # Number of MC scenarios
    demand_variation_pct: float = 20.0      # ±20% demand variation
    min_success_rate: float = 0.95          # 95% scenarios must succeed
    
    # Sensitivity analysis
    temperature_variation_c: float = 5.0    # ±5°C temperature variation
    flow_variation_pct: float = 15.0        # ±15% flow variation


@dataclass
class ValidationConfig:
    """Complete validation configuration"""
    
    en13941: EN13941Standards = None
    geospatial: GeospatialTolerances = None
    robustness: RobustnessThresholds = None
    
    # Economic thresholds (from your existing config)
    max_lcoh_eur_per_mwh: float = 120.0
    max_co2_kg_per_mwh: float = 100.0
    
    # Validation strictness
    fail_on_warnings: bool = False          # Treat warnings as failures?
    require_expert_review: bool = False     # Flag for human review?
    
    def __post_init__(self):
        if self.en13941 is None:
            self.en13941 = EN13941Standards()
        if self.geospatial is None:
            self.geospatial = GeospatialTolerances()
        if self.robustness is None:
            self.robustness = RobustnessThresholds()


def get_default_validation_config() -> ValidationConfig:
    """Get default validation configuration"""
    return ValidationConfig()


# Standard pipe roughness values (mm) for different materials
PIPE_ROUGHNESS = {
    "steel": 0.045,
    "steel_new": 0.02,
    "steel_old": 0.1,
    "plastic": 0.007,
    "PE": 0.007,
    "PEX": 0.007,
    "copper": 0.0015,
}

# Typical U-values for insulated pipes (W/m·K)
PIPE_U_VALUES = {
    "twin_pipe_insulated": 0.3,
    "single_pipe_insulated": 0.4,
    "twin_pipe_pre_insulated": 0.2,
    "uninsulated": 2.0,
}
