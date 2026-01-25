"""
Configuration for CHA (Centralised Heating Agent).
Defines physical assumptions and default parameters.
"""

from dataclasses import dataclass, field
from typing import Optional, Literal, List

# Trunk topology policy constants
TRUNK_MODE_FULL_STREET: str = "full_street"              # include all street edges (debug/visual)
TRUNK_MODE_PATHS_TO_BUILDINGS: str = "paths_to_buildings"  # minimal backbone: plant→buildings
TRUNK_MODE_SELECTED_STREETS: str = "selected_streets"    # reserved for user-selected corridors
TRUNK_MODE_STRICT_STREET: str = "strict_street"  # Alias for selected_streets (explicit)
TRUNK_MODE_STREET_PLUS_SPURS: str = "street_plus_short_spurs"  # New controlled expansion
DEFAULT_TRUNK_MODE: str = TRUNK_MODE_PATHS_TO_BUILDINGS


@dataclass
class CHAConfig:
    """
    Configuration object for CHA physical assumptions.
    
    All values are defaults and can be overridden.
    """
    # Fluid properties
    rho: float = 983.0  # kg/m³ (hot water nominal at ~70°C)
    cp: float = 4180.0  # J/(kg·K) (specific heat capacity of water)
    
    # Temperature assumptions
    delta_T_design: float = 20.0  # K (supply-return temp drop)
    t_supply_C: float = 80.0  # °C (supply temperature)
    t_return_C: float = 60.0  # °C (return temperature)
    
    # System pressure
    system_pressure_bar: float = 2.0  # bar (default: 2.0 bar = 200 kPa) - optimized based on convergence tests
    
    # Velocity constraints
    v_max: float = 1.5  # m/s (design limit)
    v_min: float = 0.1  # m/s (efficiency floor)
    
    # Pressure drop constraints
    dp_per_100m_max: float = 20000.0  # Pa/100m (placeholder; keep parameterised)
    
    # Sizing parameters
    max_resize_iters: int = 8  # Maximum iterations for pipe resizing
    
    # Service pipe defaults
    service_dn_default: str = "DN20"  # Default service pipe diameter name
    
    # NEW: Service connection attachment strategy
    attach_mode: Literal["nearest_node", "split_edge_per_building", "clustered_projection"] = "split_edge_per_building"
    
    # NEW: Geometry tolerances (meters)
    attach_snap_tol_m: float = 2.0  # If projection lands very close to an existing node, reuse it
    min_attach_spacing_m: float = 8.0  # For clustered_projection: minimum spacing between attach points
    
    # Connectivity threshold
    max_attach_distance_m: float = 500.0  # Maximum distance from trunk network to connect a building (increased to connect all buildings)
    
    # Trunk topology mode (planning backbone policy)
    trunk_mode: Literal[
        "full_street",
        "paths_to_buildings",
        "selected_streets",
        "strict_street",  # Alias for selected_streets (explicit)
        "street_plus_short_spurs"  # New mode: controlled expansion with spurs
    ] = DEFAULT_TRUNK_MODE

    # Optional street filters (used when trunk_mode == "selected_streets" or "strict_street")
    street_name: Optional[str] = None
    street_ids: Optional[list] = None
    
    # Street edge routing cost configuration
    edge_cost_mode: Literal[
        "length_only",
        "avoid_primary_roads"
    ] = "length_only"
    # length_only: use pure geometric length (length_m) as Dijkstra weight (current behaviour)
    # avoid_primary_roads: still uses length_m as base weight, but applies penalty factor
    #   to major OSM road types (e.g. highway in {"primary", "trunk"}) to reflect
    #   increased excavation cost and disruption
    
    # Spur expansion configuration (only used when trunk_mode == "street_plus_short_spurs")
    service_length_promote_threshold_m: float = 30.0  # Service length threshold to consider spur
    spur_max_depth_edges: int = 2  # Maximum edges away from main trunk
    spur_min_buildings: int = 2  # Minimum buildings served by spur
    spur_max_total_length_m: float = 100.0  # Maximum total length of all spurs
    spur_reduction_threshold_pct: float = 30.0  # Minimum service length reduction (%) to justify spur
    spur_search_buffer_m: float = 120.0  # Spatial buffer around selected street for spur candidate search
    
    # Phased spur expansion (test base trunk convergence before adding spurs)
    spur_phased_expansion: bool = False  # If True, test base trunk convergence before adding spurs
    spur_require_base_convergence: bool = True  # If True, only add spurs if base trunk converged
    
    # Network validation and stabilization
    validate_network_topology: bool = False  # If True, validate network topology before pipeflow
    stabilize_network: bool = False  # If True, apply stabilization fixes (parallel paths, short pipes, etc.)
    stabilize_fix_parallel: bool = True  # Fix parallel flow paths by adding roughness variations
    stabilize_fix_short_pipes: bool = True  # Fix very short pipes (<1m) that cause numerical issues
    stabilize_fix_loops: bool = False  # Fix network loops (more aggressive, use with caution)
    stabilize_ensure_connectivity: bool = True  # Ensure all components connected to plant (default: True)
    stabilize_improve_pressures: bool = True  # Improve initial pressure distribution (default: True)
    stabilize_loop_method: Literal["high_resistance", "remove_pipe"] = "high_resistance"  # Method for breaking loops
    stabilize_min_length_m: float = 1.0  # Minimum pipe length in meters
    stabilize_parallel_variation_pct: float = 0.01  # Percentage variation for parallel paths (1% = 0.01)
    stabilize_virtual_pipe_resistance: float = 100.0  # Roughness for virtual connecting pipes (mm)
    stabilize_pressure_drop_per_m: float = 0.001  # Pressure drop per meter in bar/m (default: 0.001 = 0.1 bar per 100m)
    stabilize_add_minimal_loop: bool = False  # Add minimal high-resistance loop for tree networks (helps with singular matrix)
    
    # Convergence Optimizer
    optimize_convergence: bool = False  # Enable integrated convergence optimizer (default: False)
    optimize_max_iterations: int = 3  # Maximum optimization iterations (default: 3)
    optimize_fix_parallel: bool = True  # Fix parallel paths during optimization (default: True)
    optimize_fix_loops: bool = True  # Fix network loops during optimization (default: True)
    optimize_fix_connectivity: bool = True  # Ensure connectivity during optimization (default: True)
    optimize_fix_pressures: bool = True  # Improve pressure distribution during optimization (default: True)
    optimize_fix_short_pipes: bool = True  # Fix short pipes during optimization (default: True)
    
    # Solver configuration
    solver_friction_models: List[str] = field(default_factory=lambda: ["nikura", "swamee-jain", "colebrook"])  # List of friction models to try
    solver_damping_values: List[float] = field(default_factory=lambda: [0.7, 0.5, 0.3])  # List of damping values to try
    solver_max_iter: int = 200  # Maximum solver iterations (default: 200)
    solver_tol_p: float = 1e-4  # Pressure tolerance (default: 1e-4)
    solver_tol_v: float = 1e-4  # Velocity tolerance (default: 1e-4)
    solver_retry_with_different_models: bool = True  # Enable retry with different friction models (default: True)
    
    # Roughness variation for numerical stability
    roughness_variation_pct: float = 0.001  # Percentage variation in roughness (0.1% = 0.001) to prevent singularity (increased from 0.01% for better numerical stability)
    
    # QGIS Export
    export_to_qgis: bool = False
    create_qgis_project: bool = False
    qgis_crs: str = "EPSG:32633"
    
    # Disconnected Component Fixing
    fix_disconnected_components: bool = False  # If True, fix disconnected components before pipeflow
    
    def __post_init__(self):
        """Validate configuration values."""
        assert self.rho > 0, "Density must be positive"
        assert self.cp > 0, "Specific heat capacity must be positive"
        assert self.delta_T_design > 0, "Temperature drop must be positive"
        assert self.v_max > self.v_min, "v_max must be greater than v_min"
        assert self.dp_per_100m_max > 0, "Pressure drop limit must be positive"
        assert self.max_resize_iters > 0, "max_resize_iters must be positive"


def get_default_config() -> CHAConfig:
    """
    Get default CHA configuration.
    
    Returns:
        CHAConfig with default values
    """
    return CHAConfig()


def create_config_from_dict(config_dict: dict) -> CHAConfig:
    """
    Create CHAConfig from dictionary.
    
    Args:
        config_dict: Dictionary with configuration values
        
    Returns:
        CHAConfig instance
    """
    return CHAConfig(**{k: v for k, v in config_dict.items() if k in CHAConfig.__dataclass_fields__})

