"""
Pipe heat loss modeling for district heating networks.

Supports two methods:
1. Planning method (catalog/linear): q' [W/m] from datasheet
2. Physics method (thermal resistance): U from layers → q'

References:
- Energies 13, 4505 (2020): Thermal resistance formulation
- Aquatherm Blog (2025): W/m planning method
- EN 13941: TwinPipe thermal interaction (Wallentén model)
"""

import math
from dataclasses import dataclass, astuple
from functools import lru_cache
from typing import Optional, Dict, Any, Tuple
import logging

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HeatLossInputs:
    """Inputs for heat loss calculation per pipe segment."""
    dn_mm: float
    length_m: float
    t_fluid_k: float
    t_soil_k: float
    role: str  # "trunk" | "service"
    circuit: str  # "supply" | "return"
    std_type: Optional[str] = None
    outer_diameter_m: Optional[float] = None
    insulation_thickness_m: Optional[float] = None
    burial_depth_m: float = 1.0
    soil_k_w_mk: float = 1.5
    velocity_m_s: Optional[float] = None  # for h_i if needed
    pair_id: Optional[int] = None  # for TwinPipe pairing


@dataclass(frozen=True)
class HeatLossResult:
    """Result of heat loss calculation."""
    method: str  # "linear" | "thermal_resistance"
    q_loss_w_per_m: float  # Linear heat loss [W/m]
    q_loss_w: float  # Total segment loss [W] = q' × L
    u_w_per_m2k: float  # Overall heat transfer coefficient [W/m²K]
    text_k: float  # External temperature [K]
    delta_t_k: Optional[float] = None  # Temperature drop [K] (if mdot provided)
    diagnostics: Optional[Dict[str, float]] = None  # Additional diagnostics


def compute_heat_loss(
    in_: HeatLossInputs,
    cfg: Any,  # CHAConfig
    catalog: Optional[Dict[str, Any]] = None
) -> HeatLossResult:
    """
    Compute pipe heat loss parameters using selected method.
    
    This is the single public entry point. It selects Method 1 (linear) or
    Method 2 (thermal_resistance) based on config.heat_loss_method.
    
    For performance with >1000 pipes, results are cached based on input parameters.
    
    Args:
        in_: HeatLossInputs dataclass with pipe segment parameters
        cfg: CHAConfig instance (must have heat_loss_method, defaults, etc.)
        catalog: Optional dict mapping DN -> q' [W/m] at reference temp
    
    Returns:
        HeatLossResult with u_w_per_m2k, text_k, q', and diagnostics
    """
    # For large networks (>1000 pipes), enable caching via config flag
    # Cache key is based on inputs + config params (cfg itself not hashable)
    use_cache = getattr(cfg, "_enable_heat_loss_cache", False)
    
    if use_cache:
        # Create hashable cache key (exclude cfg and catalog)
        cache_key = _make_cache_key(in_, cfg)
        return _compute_heat_loss_cached(cache_key, catalog)
    else:
        # Direct call (no caching overhead for small networks)
        return _compute_heat_loss_impl(in_, cfg, catalog)


def _make_cache_key(in_: HeatLossInputs, cfg: Any) -> Tuple:
    """Create hashable cache key from HeatLossInputs and relevant cfg attributes."""
    # Extract relevant config attributes for cache key
    method = getattr(cfg, "heat_loss_method", "linear")
    area_conv = getattr(cfg, "heat_loss_area_convention", "d")
    t_ref = getattr(cfg, "t_linear_ref_k", 353.15)
    t_soil_ref = getattr(cfg, "t_soil_ref_k", 285.15)
    twinpipe_enabled = getattr(cfg, "supply_return_interaction", True)
    twinpipe_factor = getattr(cfg, "twinpipe_loss_factor", 0.9)
    default_q_trunk = getattr(cfg, "default_q_linear_trunk_w_per_m", 30.0)
    default_q_service = getattr(cfg, "default_q_linear_service_w_per_m", 25.0)
    
    # Convert HeatLossInputs to tuple (frozen dataclass is hashable via astuple)
    in_tuple = astuple(in_)
    
    # Combine into cache key (method, cfg params, inputs)
    # Note: catalog is excluded (too large, not hashable)
    return (method, area_conv, t_ref, t_soil_ref, twinpipe_enabled, twinpipe_factor,
            default_q_trunk, default_q_service, in_tuple)


@lru_cache(maxsize=512)
def _compute_heat_loss_cached(
    cache_key: Tuple,
    catalog: Optional[Dict[str, Any]] = None
) -> HeatLossResult:
    """
    Cached version of compute_heat_loss for large networks (>1000 pipes).
    
    Cache key includes method, config parameters, and input parameters.
    Max cache size 512 entries (sufficient for typical DN/role/role combinations).
    Note: cfg is reconstructed from cache_key, catalog passed separately (not cached).
    """
    # Extract config params and inputs from cache key
    (method, area_conv, t_ref, t_soil_ref, twinpipe_enabled, twinpipe_factor,
     default_q_trunk, default_q_service, in_tuple) = cache_key
    
    # Reconstruct minimal config-like object (only for internal use)
    # This is a lightweight dict, not the full CHAConfig
    cfg_dict = {
        "heat_loss_method": method,
        "heat_loss_area_convention": area_conv,
        "t_linear_ref_k": t_ref,
        "t_soil_ref_k": t_soil_ref,
        "supply_return_interaction": twinpipe_enabled,
        "twinpipe_loss_factor": twinpipe_factor,
        "default_q_linear_trunk_w_per_m": default_q_trunk,
        "default_q_linear_service_w_per_m": default_q_service,
    }
    
    # Reconstruct HeatLossInputs
    in_ = HeatLossInputs(*in_tuple)
    
    # Create a simple config-like object with getattr support
    class SimpleConfig:
        def __init__(self, d):
            self._d = d
        def __getattr__(self, key):
            return self._d.get(key)
    
    cfg = SimpleConfig(cfg_dict)
    
    return _compute_heat_loss_impl(in_, cfg, catalog)


def _compute_heat_loss_impl(
    in_: HeatLossInputs,
    cfg: Any,
    catalog: Optional[Dict[str, Any]] = None
) -> HeatLossResult:
    """Internal implementation (non-cached)."""
    method = getattr(cfg, "heat_loss_method", "linear")
    
    if method == "linear":
        return _compute_linear_heat_loss(in_, cfg, catalog)
    elif method == "thermal_resistance":
        return _compute_thermal_resistance_heat_loss(in_, cfg)
    else:
        logger.warning(
            f"Unknown heat_loss_method='{method}', falling back to 'linear'"
        )
        return _compute_linear_heat_loss(in_, cfg, catalog)


def _compute_linear_heat_loss(
    in_: HeatLossInputs,
    cfg: Any,
    catalog: Optional[Dict[str, Any]] = None
) -> HeatLossResult:
    """
    Method 1: Planning method using linear heat loss q' [W/m].
    
    Sources:
    - Catalog datasheets: DN-specific q' [W/m] at reference temperature
    - Aquatherm blog: ~30 W/m for typical insulated DH pipe (90/70°C, buried)
    
    Temperature correction (if catalog value is at different temp):
    q'(T) ≈ q'(T_ref) × (T_fluid - T_soil) / (T_ref - T_soil_ref)
    """
    # Try catalog lookup first
    dn_label = f"DN{int(in_.dn_mm)}"
    q_ref_w_per_m = None
    
    # Get reference temperatures from config (standardized, no hidden defaults)
    t_ref_k = getattr(cfg, "t_linear_ref_k", 353.15)  # 80°C default
    t_soil_ref_k_config = getattr(cfg, "t_soil_ref_k", 285.15)  # 12°C default
    
    if catalog is not None:
        if dn_label in catalog:
            q_ref_w_per_m = catalog[dn_label].get("q_linear_w_per_m_ref")
            # Override with catalog-specific reference temps if provided
            t_ref_k = catalog[dn_label].get("t_ref_k", t_ref_k)
            t_soil_ref_k_catalog = catalog[dn_label].get("t_soil_ref_k", t_soil_ref_k_config)
            if "t_soil_ref_k" in catalog[dn_label]:
                t_soil_ref_k_config = t_soil_ref_k_catalog
    
    # Fallback to role-based defaults
    if q_ref_w_per_m is None:
        if in_.role == "trunk":
            q_ref_w_per_m = getattr(
                cfg, "default_q_linear_trunk_w_per_m", 30.0
            )
        else:  # service
            q_ref_w_per_m = getattr(
                cfg, "default_q_linear_service_w_per_m", 25.0
            )
        # Use config reference temperatures (already set above)
    
    # Always apply temperature scaling when ΔT differs (not conditional)
    # q'(T) = q'(T_ref) × (T_fluid - T_soil) / (T_ref - T_soil_ref)
    delta_t_ref = t_ref_k - t_soil_ref_k_config
    delta_t_actual = in_.t_fluid_k - in_.t_soil_k
    if delta_t_ref > 0 and delta_t_actual > 0:
        q_loss_w_per_m = q_ref_w_per_m * (delta_t_actual / delta_t_ref)
    else:
        # If ΔT <= 0, no heat loss (shouldn't happen in DH but handle gracefully)
        q_loss_w_per_m = 0.0
    
    # Compute outer diameter consistently (remove DN+0.1 guess when possible)
    # Priority: outer_diameter_m (provided) > insulation_thickness_m (compute) > DN+0.1 (fallback)
    if in_.outer_diameter_m is not None:
        d_o_m = in_.outer_diameter_m
    elif in_.insulation_thickness_m is not None:
        # Compute from DN inner radius + wall + insulation + casing
        d_i_m = in_.dn_mm / 1000.0
        wall_thickness_m = 0.003  # 3mm typical steel pipe wall
        casing_thickness_m = 0.003  # 3mm PE casing
        d_o_m = d_i_m + (2.0 * wall_thickness_m) + (2.0 * in_.insulation_thickness_m) + (2.0 * casing_thickness_m)
    else:
        # Fallback: estimate from DN (typical insulation adds ~100mm total diameter)
        d_o_m = (in_.dn_mm / 1000.0) + 0.1
    
    # Convert q' [W/m] to U [W/m²K] for pandapipes
    # pandapipes convention: u_w_per_m2k is multiplied by effective area A_eff
    # q' = U × A_eff × (T_fluid - T_soil) for Δx = 1 m
    # => U = q' / (A_eff × ΔT)
    # Effective area convention (configurable to verify pandapipes mapping):
    # "pi_d": A_eff = π × d_o (outer surface area per meter) - standard convention
    # "d": A_eff = d_o (alternative convention, rarely used)
    area_convention = getattr(cfg, "heat_loss_area_convention", "pi_d")
    a_eff_per_m = (math.pi * d_o_m) if area_convention == "pi_d" else d_o_m
    
    delta_t_k = in_.t_fluid_k - in_.t_soil_k
    if delta_t_k > 0 and a_eff_per_m > 0:
        u_w_per_m2k = q_loss_w_per_m / (a_eff_per_m * delta_t_k)
    else:
        u_w_per_m2k = 0.7  # Fallback default
    
    # Store effective area for diagnostics (per meter)
    a_o_m2 = a_eff_per_m * 1.0  # For backwards compatibility with diagnostics
    
    # TwinPipe correction (MVP Phase 1): apply correction factor if paired
    # Uses adjust_for_pairing() function for stable signature (Phase 3 ready)
    q_loss_w_per_m = adjust_for_pairing(q_loss_w_per_m, in_, cfg)
    # Recompute U to match adjusted q'
    if delta_t_k > 0 and a_eff_per_m > 0:
        u_w_per_m2k = q_loss_w_per_m / (a_eff_per_m * delta_t_k)
    
    q_loss_w = q_loss_w_per_m * in_.length_m
    
    diagnostics = {
        "q_ref_w_per_m": q_ref_w_per_m,
        "t_ref_k": t_ref_k,
        "d_o_m": d_o_m,
        "a_o_m2": a_o_m2,
    }
    
    return HeatLossResult(
        method="linear",
        q_loss_w_per_m=q_loss_w_per_m,
        q_loss_w=q_loss_w,
        u_w_per_m2k=u_w_per_m2k,
        text_k=in_.t_soil_k,
        delta_t_k=None,
        diagnostics=diagnostics,
    )


def _compute_thermal_resistance_heat_loss(
    in_: HeatLossInputs,
    cfg: Any
) -> HeatLossResult:
    """
    Method 2: Detailed physics using thermal resistance layers.
    
    Thermal resistance R = R_conv,i + R_pipe + R_insulation + R_casing + R_soil
    U = 1 / R
    q' = U × A_o × (T_fluid - T_soil) for Δx = 1 m
    
    Components:
    - R_conv,i: Internal convection (Dittus-Boelter, Nu correlation)
    - R_pipe: Steel/PEX pipe wall conduction (cylindrical)
    - R_insulation: Insulation layer (cylindrical, e.g., PUR foam)
    - R_casing: Outer casing (PE/steel) conduction
    - R_soil: Soil resistance (shape factor, depends on burial depth)
    
    TwinPipe (supply/return interaction):
    - Apply correction factor to R_soil (EN 13941 approximation)
    """
    # Pipe dimensions
    d_i_m = in_.dn_mm / 1000.0  # Inner diameter (nominal)
    
    # Default wall thicknesses (typical DH pipes)
    wall_thickness_mm = 3.0  # Steel pipe wall
    
    # Fix: HeatLossInputs uses insulation_thickness_m (meters), not mm
    ins_th_m = in_.insulation_thickness_m
    insulation_thickness_mm = (ins_th_m * 1000.0) if ins_th_m is not None else None
    
    if insulation_thickness_mm is None:
        # DN-based defaults (more insulation for larger pipes)
        default_ins_mm = getattr(cfg, "default_insulation_thickness_mm", 50.0)
        if in_.role == "trunk":
            insulation_thickness_mm = max(default_ins_mm, in_.dn_mm * 0.1)
        else:  # service
            insulation_thickness_mm = 40.0
    casing_thickness_mm = 3.0  # PE outer casing
    
    # Radial layers (from inner to outer)
    r_i_m = d_i_m / 2.0
    r_pipe_outer_m = r_i_m + (wall_thickness_mm / 1000.0)
    r_ins_outer_m = r_pipe_outer_m + (insulation_thickness_mm / 1000.0)
    r_o_m = r_ins_outer_m + (casing_thickness_mm / 1000.0)
    d_o_m = 2.0 * r_o_m
    
    # Material thermal conductivities [W/(m·K)]
    k_water = 0.6  # Water (at ~80°C)
    k_pipe = 50.0  # Steel
    k_insulation = 0.025  # PUR foam (typical)
    k_casing = 0.4  # PE
    k_soil = in_.soil_k_w_mk
    
    # 1. Internal convection resistance R_conv,i
    # h_i from Dittus-Boelter (turbulent flow, cooling case)
    # Nu = 0.023 × Re^0.8 × Pr^0.3
    # h_i = (Nu × k_water) / d_i
    if in_.velocity_m_s is not None and in_.velocity_m_s > 0:
        v = in_.velocity_m_s
        rho_water = 970.0  # kg/m³ at 80°C
        mu_water = 3.5e-4  # Pa·s at 80°C
        Pr = 2.2  # Prandtl number at 80°C
        
        Re = (rho_water * v * d_i_m) / mu_water
        if Re > 2300:  # Turbulent
            Nu = 0.023 * (Re ** 0.8) * (Pr ** 0.3)
        else:  # Laminar (fallback)
            Nu = 4.36  # Constant wall temp, fully developed
        h_i_w_m2k = (Nu * k_water) / d_i_m
    else:
        # Default h_i for typical DH flow
        h_i_w_m2k = 2000.0  # W/(m²K) typical for turbulent water flow
    
    a_i_m2 = math.pi * d_i_m * 1.0  # Inner surface per meter
    r_conv_i = 1.0 / (h_i_w_m2k * a_i_m2)
    
    # 2. Pipe wall conduction (cylindrical)
    # R = ln(r_o/r_i) / (2πkL) for L=1m → R = ln(r_o/r_i) / (2πk)
    r_pipe = math.log(r_pipe_outer_m / r_i_m) / (2.0 * math.pi * k_pipe)
    
    # 3. Insulation conduction (cylindrical)
    r_insulation = (
        math.log(r_ins_outer_m / r_pipe_outer_m) / (2.0 * math.pi * k_insulation)
    )
    
    # 4. Casing conduction (cylindrical, thin wall approximation)
    if casing_thickness_mm > 0:
        r_casing = (
            math.log(r_o_m / r_ins_outer_m) / (2.0 * math.pi * k_casing)
        )
    else:
        r_casing = 0.0
    
    # 5. Soil resistance (shape factor formulation)
    # For buried pipe: R_soil ≈ (1 / (2πk_soil)) × ln(4Z / d_o)
    # where Z is burial depth (centerline to surface)
    z_m = in_.burial_depth_m
    if z_m > 0 and z_m > r_o_m:
        r_soil_shape = (1.0 / (2.0 * math.pi * k_soil)) * math.log(
            4.0 * z_m / d_o_m
        )
    else:
        # Above-ground or shallow burial (use air convection)
        r_soil_shape = 1.0 / (2.0 * math.pi * d_o_m * 10.0)  # h_air ≈ 10 W/(m²K)
    
    # TwinPipe correction (MVP Phase 1): apply correction factor if paired
    # Phase 3 will replace this with full EN 13941 / Wallentén model
    # For now, use configurable factor to adjust R_soil (affects overall U)
    if (
        getattr(cfg, "supply_return_interaction", True)
        and in_.pair_id is not None
    ):
        # Apply factor to soil resistance (reduces R_soil, increases U, increases q')
        # Default factor 0.9 means 10% reduction in R_soil (equivalent to ~10% increase in q')
        twinpipe_factor = getattr(cfg, "twinpipe_loss_factor", 0.9)
        # Convert loss factor to resistance factor (inverse relationship)
        # If q' is reduced by factor, R_soil should be increased by 1/factor
        # But we want to reduce R_soil, so multiply by factor
        r_soil_shape = r_soil_shape * twinpipe_factor
    
    # Total thermal resistance (per meter)
    r_total = r_conv_i + r_pipe + r_insulation + r_casing + r_soil_shape
    
    # Overall heat transfer coefficient
    u_w_per_m2k = 1.0 / r_total if r_total > 0 else 0.7
    
    # Outer surface area per meter
    a_o_m2 = math.pi * d_o_m * 1.0
    
    # Linear heat loss q' [W/m]
    delta_t_k = in_.t_fluid_k - in_.t_soil_k
    q_loss_w_per_m = u_w_per_m2k * a_o_m2 * delta_t_k if delta_t_k > 0 else 0.0
    
    # TwinPipe correction (MVP Phase 1): apply correction factor if paired
    # Uses adjust_for_pairing() function for stable signature (Phase 3 ready)
    q_loss_w_per_m = adjust_for_pairing(q_loss_w_per_m, in_, cfg)
    
    # Total segment loss
    q_loss_w = q_loss_w_per_m * in_.length_m
    
    diagnostics = {
        "r_conv_i": r_conv_i,
        "r_pipe": r_pipe,
        "r_insulation": r_insulation,
        "r_casing": r_casing,
        "r_soil": r_soil_shape,
        "r_total": r_total,
        "h_i_w_m2k": h_i_w_m2k,
        "d_i_m": d_i_m,
        "d_o_m": d_o_m,
        "insulation_thickness_mm": insulation_thickness_mm,
        "burial_depth_m": z_m,
    }
    
    return HeatLossResult(
        method="thermal_resistance",
        q_loss_w_per_m=q_loss_w_per_m,
        q_loss_w=q_loss_w,
        u_w_per_m2k=u_w_per_m2k,
        text_k=in_.t_soil_k,
        delta_t_k=None,
        diagnostics=diagnostics,
    )


def adjust_for_pairing(
    q_loss_w_per_m: float,
    in_: HeatLossInputs,
    cfg: Any
) -> float:
    """
    Adjust heat loss for TwinPipe / supply-return interaction.
    
    MVP (Phase 1): Simple correction factor
        q_adj' = q' × twinpipe_loss_factor
    
    Phase 3 (future): Full EN 13941 / Wallentén model
        Will use: center distance s, burial depth Z, insulation radii, soil conductivity
    
    Args:
        q_loss_w_per_m: Base heat loss [W/m] (before pairing correction)
        in_: HeatLossInputs with pair_id
        cfg: CHAConfig with supply_return_interaction and twinpipe_loss_factor
    
    Returns:
        Adjusted heat loss [W/m]
    """
    if not getattr(cfg, "supply_return_interaction", True):
        return q_loss_w_per_m
    
    if in_.pair_id is None:
        return q_loss_w_per_m
    
    # MVP Phase 1: Simple correction factor
    twinpipe_factor = getattr(cfg, "twinpipe_loss_factor", 0.9)
    q_adj_w_per_m = q_loss_w_per_m * twinpipe_factor
    
    # Phase 3 TODO: Replace with EN 13941 / Wallentén model
    # Will need: center distance s, burial depth Z, insulation radii, soil conductivity
    # Function signature remains stable: adjust_for_pairing(q', in_, cfg) -> q'
    
    return q_adj_w_per_m


def compute_temperature_drop_along_pipe(
    q_loss_w: float,
    mdot_kg_per_s: float,
    cp_j_per_kgk: float = 4180.0
) -> float:
    """
    Compute temperature drop ΔT [K] along a pipe segment.
    
    ΔT ≈ Q_loss / (m_dot × cp)
    
    Args:
        q_loss_w: Total heat loss [W] for the segment
        mdot_kg_per_s: Mass flow rate [kg/s]
        cp_j_per_kgk: Specific heat capacity [J/(kg·K)]
    
    Returns:
        Temperature drop [K]
    """
    if mdot_kg_per_s > 0 and cp_j_per_kgk > 0:
        return q_loss_w / (mdot_kg_per_s * cp_j_per_kgk)
    return 0.0


def compute_temperature_profile_exponential(
    t_in_k: float,
    t_soil_k: float,
    u_w_per_m2k: float,
    a_o_m2: float,
    mdot_kg_per_s: float,
    length_m: float,
    cp_j_per_kgk: float = 4180.0
) -> float:
    """
    Compute outlet temperature using exponential decay model.
    
    T_out = T_soil + (T_in - T_soil) × exp(-(U×A_o)/(m_dot×cp) × L)
    
    This is the continuous form of distributed heat loss along a pipe.
    
    Args:
        t_in_k: Inlet temperature [K]
        t_soil_k: Soil/ambient temperature [K]
        u_w_per_m2k: Overall heat transfer coefficient [W/(m²K)]
        a_o_m2: Outer surface area per meter [m²/m]
        mdot_kg_per_s: Mass flow rate [kg/s]
        length_m: Pipe length [m]
        cp_j_per_kgk: Specific heat capacity [J/(kg·K)]
    
    Returns:
        Outlet temperature [K]
    """
    if mdot_kg_per_s > 0 and cp_j_per_kgk > 0 and a_o_m2 > 0:
        exponent = -(u_w_per_m2k * a_o_m2) / (mdot_kg_per_s * cp_j_per_kgk) * length_m
        t_out_k = t_soil_k + (t_in_k - t_soil_k) * math.exp(exponent)
        return max(t_out_k, t_soil_k)
    return t_in_k
