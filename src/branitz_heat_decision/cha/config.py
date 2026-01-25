# src/branitz_heat_decision/cha/config.py
from dataclasses import dataclass

@dataclass
class CHAConfig:
    """Configuration for Central Heating Agent."""
    # DH networks typically operate at several bar. Using too low a pressure level can
    # produce negative absolute pressures in the model for long networks.
    system_pressure_bar: float = 8.0
    # Plant pump differential pressure (return -> supply) in bar.
    # Must be large enough to overcome network friction losses.
    pump_plift_bar: float = 3.0
    # Minimum acceptable absolute pressure anywhere in the network (sanity gate).
    # If the solver produces pressures below this, we auto-increase plant pressure/lift and retry.
    p_min_bar_allowed: float = 1.5
    supply_temp_k: float = 363.15  # 90°C
    return_temp_k: float = 323.15  # 50°C
    fluid: str = "water"
    # Default physical parameters
    default_diameter_m: float = 0.05
    default_roughness_mm: float = 0.1
    min_pipe_length_m: float = 1.0

    # Thermal losses (pipes)
    # pandapipes (v0.12) uses net.pipe.u_w_per_m2k (overall heat transfer coefficient)
    # and net.pipe.text_k (external/soil temperature) for heat losses.
    soil_temp_k: float = 285.15  # 12°C conservative buried soil temperature
    pipe_u_w_per_m2k: float = 0.7  # baseline overall U-value (W/m²K) for insulated district heating pipes (deprecated: use heat_loss_method instead)
    
    # Heat loss method selection
    heat_loss_method: str = "linear"  # "linear" | "thermal_resistance"
    
    # Linear method defaults (if catalog missing)
    default_q_linear_trunk_w_per_m: float = 30.0  # Aquatherm typical
    default_q_linear_service_w_per_m: float = 25.0
    # Reference temperatures for catalog/datasheet W/m values
    t_linear_ref_k: float = 353.15  # Catalog reference fluid temp (e.g., 80°C)
    t_soil_ref_k: float = 285.15  # Catalog reference soil temp (e.g., 12°C)
    # Effective area convention for u_w_per_m2k conversion (pandapipes mapping)
    # "pi_d": A_eff = π × d_o (outer surface area per meter) - theoretical convention
    # "d": A_eff = d_o (pandapipes internal convention - verified via integration test)
    # NOTE: Integration test shows "d" convention matches pandapipes simulation results
    # better (16.5% error vs 62.3% error). This reflects pandapipes' internal implementation.
    heat_loss_area_convention: str = "d"  # "pi_d" | "d" (default: "d" verified)
    
    # Thermal resistance method defaults
    default_insulation_thickness_mm: float = 50.0  # Standard PUR foam
    default_burial_depth_m: float = 1.0
    soil_k_w_mk: float = 1.5  # Typical soil thermal conductivity
    supply_return_interaction: bool = True  # Enable TwinPipe correction (EN 13941)
    # TwinPipe loss factor (MVP Phase 1): correction factor for supply-return interaction
    # q_adj' = q' × twinpipe_loss_factor
    # Typical range: 0.9-1.0 (0.9 = 10% reduction due to thermal interaction)
    # Phase 3 will replace this with full EN 13941 / Wallentén model
    twinpipe_loss_factor: float = 0.9  # Default 10% reduction for paired pipes

    # Sizing targets (role-based)
    # target velocities used for initial sizing (noise + erosion friendly)
    v_limit_trunk_ms: float = 1.5
    v_limit_service_ms: float = 1.5
    # absolute hard cap (flag if exceeded even after selecting largest available DN)
    v_abs_max_ms: float = 2.5
    # optional pressure gradient sanity limit for sizing-stage estimates (Pa/m)
    dp_per_m_max_pa: float = 200.0
    # optional "eco-mode" (more conservative sizing, larger pipes)
    sizing_eco_mode: bool = False
    v_eco_mode_ms: float = 1.2
    # Geographic parameters
    crs: str = "EPSG:25833"  # UTM Zone 33N (default for Germany)

    # Topology hygiene (design runs)
    # When True, prune trunk edges that are not required to connect plant root to any service tee.
    # This removes dead-end trunk stubs that would otherwise carry zero flow (often yielding NaN
    # thermal results on those pipes).
    prune_trunk_to_service_subtree: bool = True
    
    @property
    def delta_t_k(self) -> float:
        """Temperature difference between supply and return."""
        return self.supply_temp_k - self.return_temp_k

def get_default_config() -> CHAConfig:
    """Return default CHA configuration."""
    return CHAConfig()