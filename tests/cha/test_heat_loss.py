"""
Unit tests for pipe heat loss modeling.

Validates:
- W/m → u_w_per_m2k conversion (pandapipes convention)
- Temperature scaling correctness
- Outer diameter computation consistency
- Method 1 (linear) and Method 2 (thermal_resistance) produce reasonable results
"""

import pytest
import math
from branitz_heat_decision.cha.heat_loss import (
    compute_heat_loss,
    HeatLossInputs,
    HeatLossResult,
    compute_temperature_drop_along_pipe,
    compute_temperature_profile_exponential,
)
from branitz_heat_decision.cha.config import CHAConfig


def test_linear_method_dn50_trunk_default():
    """Test Method 1 (linear) with DN50 trunk at reference temperature."""
    cfg = CHAConfig(heat_loss_method="linear")
    
    # Aquatherm typical: 30 W/m for DN50 trunk at 80/12°C (T_ref=80°C, T_soil_ref=12°C)
    in_ = HeatLossInputs(
        dn_mm=50.0,
        length_m=100.0,
        t_fluid_k=353.15,  # 80°C (reference temp)
        t_soil_k=285.15,  # 12°C (reference soil temp)
        role="trunk",
        circuit="supply",
    )
    
    result = compute_heat_loss(in_, cfg)
    
    assert result.method == "linear"
    assert abs(result.q_loss_w_per_m - 30.0) < 0.1  # Should match Aquatherm default
    assert result.u_w_per_m2k > 0
    assert result.text_k == 285.15


def test_linear_method_temperature_scaling():
    """Test that temperature scaling is applied correctly."""
    cfg = CHAConfig(heat_loss_method="linear")
    
    # Reference: 30 W/m at 80/12°C (ΔT=68K)
    # At 90/12°C (ΔT=78K): q' should scale proportionally
    in_ref = HeatLossInputs(
        dn_mm=50.0,
        length_m=1.0,
        t_fluid_k=353.15,  # 80°C
        t_soil_k=285.15,  # 12°C
        role="trunk",
        circuit="supply",
    )
    result_ref = compute_heat_loss(in_ref, cfg)
    q_ref = result_ref.q_loss_w_per_m
    
    # Higher temperature
    in_hot = HeatLossInputs(
        dn_mm=50.0,
        length_m=1.0,
        t_fluid_k=363.15,  # 90°C (+10K)
        t_soil_k=285.15,  # 12°C (same)
        role="trunk",
        circuit="supply",
    )
    result_hot = compute_heat_loss(in_hot, cfg)
    q_hot = result_hot.q_loss_w_per_m
    
    # Scaling factor: ΔT_hot / ΔT_ref = 78 / 68 ≈ 1.147
    delta_t_ref = 353.15 - 285.15
    delta_t_hot = 363.15 - 285.15
    expected_scaling = delta_t_hot / delta_t_ref
    
    assert abs(q_hot / q_ref - expected_scaling) < 0.01  # Within 1%


def test_w_per_m_to_u_conversion_pandapipes_convention():
    """
    Verify W/m → u_w_per_m2k conversion matches pandapipes convention.
    
    pandapipes interprets u_w_per_m2k as: heat loss = U × A_o × (T_fluid - T_soil)
    where A_o = π × d_o × L (outer surface area)
    
    For a 1-meter segment: q' [W/m] = U [W/m²K] × A_o [m²] × ΔT [K]
    => U = q' / (A_o × ΔT) where A_o = π × d_o × 1 m
    """
    cfg = CHAConfig(heat_loss_method="linear")
    
    # Known inputs
    q_ref_w_per_m = 30.0  # W/m
    dn_mm = 50.0
    d_o_m = 0.15  # Outer diameter (DN50 + insulation ≈ 0.15m)
    t_fluid_k = 353.15  # 80°C
    t_soil_k = 285.15  # 12°C
    delta_t_k = t_fluid_k - t_soil_k  # 68K
    
    in_ = HeatLossInputs(
        dn_mm=dn_mm,
        length_m=1.0,
        t_fluid_k=t_fluid_k,
        t_soil_k=t_soil_k,
        role="trunk",
        circuit="supply",
        outer_diameter_m=d_o_m,
    )
    
    result = compute_heat_loss(in_, cfg)
    
    # Expected conversion
    a_o_m2 = math.pi * d_o_m * 1.0  # Outer surface area per meter
    u_expected = q_ref_w_per_m / (a_o_m2 * delta_t_k)
    
    # Actual result should match (within tolerance for rounding)
    assert abs(result.u_w_per_m2k - u_expected) < 0.01, (
        f"U-value mismatch: expected {u_expected:.4f}, got {result.u_w_per_m2k:.4f}"
    )
    
    # Verify round-trip: U × A_o × ΔT should equal q'
    q_roundtrip = result.u_w_per_m2k * a_o_m2 * delta_t_k
    assert abs(q_roundtrip - q_ref_w_per_m) < 0.1, (
        f"Round-trip check failed: q'={q_ref_w_per_m} W/m, "
        f"U×A_o×ΔT={q_roundtrip:.2f} W/m"
    )


def test_outer_diameter_computation_priority():
    """Test that outer diameter computation follows priority: provided > insulation > DN+0.1."""
    cfg = CHAConfig(heat_loss_method="linear")
    
    # Case 1: outer_diameter_m provided → use it
    in1 = HeatLossInputs(
        dn_mm=50.0,
        length_m=1.0,
        t_fluid_k=353.15,
        t_soil_k=285.15,
        role="trunk",
        circuit="supply",
        outer_diameter_m=0.18,  # Explicit value
    )
    result1 = compute_heat_loss(in1, cfg)
    assert abs(result1.diagnostics["d_o_m"] - 0.18) < 0.001
    
    # Case 2: insulation_thickness_m provided → compute from layers
    in2 = HeatLossInputs(
        dn_mm=50.0,
        length_m=1.0,
        t_fluid_k=353.15,
        t_soil_k=285.15,
        role="trunk",
        circuit="supply",
        insulation_thickness_m=0.05,  # 50mm insulation
    )
    result2 = compute_heat_loss(in2, cfg)
    # Expected: d_i + 2×wall + 2×insulation + 2×casing
    # = 0.05 + 0.006 + 0.10 + 0.006 = 0.162 m
    expected_d_o = 0.05 + (2.0 * 0.003) + (2.0 * 0.05) + (2.0 * 0.003)
    assert abs(result2.diagnostics["d_o_m"] - expected_d_o) < 0.001
    
    # Case 3: neither provided → fallback DN+0.1
    in3 = HeatLossInputs(
        dn_mm=50.0,
        length_m=1.0,
        t_fluid_k=353.15,
        t_soil_k=285.15,
        role="trunk",
        circuit="supply",
    )
    result3 = compute_heat_loss(in3, cfg)
    expected_fallback = (50.0 / 1000.0) + 0.1  # 0.15 m
    assert abs(result3.diagnostics["d_o_m"] - expected_fallback) < 0.001


def test_thermal_resistance_method_basic():
    """Test Method 2 (thermal_resistance) produces reasonable U-value."""
    cfg = CHAConfig(heat_loss_method="thermal_resistance")
    
    in_ = HeatLossInputs(
        dn_mm=50.0,
        length_m=100.0,
        t_fluid_k=353.15,
        t_soil_k=285.15,
        role="trunk",
        circuit="supply",
        insulation_thickness_m=0.05,  # 50mm
        burial_depth_m=1.0,
        velocity_m_s=1.5,
    )
    
    result = compute_heat_loss(in_, cfg)
    
    assert result.method == "thermal_resistance"
    assert result.u_w_per_m2k > 0
    assert result.u_w_per_m2k < 5.0  # Reasonable upper bound for insulated DH pipe
    assert result.q_loss_w_per_m > 0
    # Typical insulated DH pipe: q' should be 5-50 W/m for DN50 (thermal resistance method can be conservative)
    assert 3.0 <= result.q_loss_w_per_m <= 50.0


def test_temperature_drop_helper():
    """Test temperature drop calculation helper."""
    q_loss_w = 3000.0  # 3 kW loss
    mdot_kg_per_s = 1.0  # 1 kg/s
    cp_j_per_kgk = 4180.0
    
    delta_t = compute_temperature_drop_along_pipe(q_loss_w, mdot_kg_per_s, cp_j_per_kgk)
    
    expected = q_loss_w / (mdot_kg_per_s * cp_j_per_kgk)  # ≈ 0.72 K
    assert abs(delta_t - expected) < 0.01


def test_temperature_profile_exponential():
    """Test exponential temperature decay along pipe."""
    t_in_k = 363.15  # 90°C
    t_soil_k = 285.15  # 12°C
    u_w_per_m2k = 0.7
    d_o_m = 0.15
    a_o_m2 = math.pi * d_o_m * 1.0
    mdot_kg_per_s = 1.0
    length_m = 1000.0  # 1 km
    cp_j_per_kgk = 4180.0
    
    t_out_k = compute_temperature_profile_exponential(
        t_in_k, t_soil_k, u_w_per_m2k, a_o_m2, mdot_kg_per_s, length_m, cp_j_per_kgk
    )
    
    # Outlet should be between inlet and soil temp
    assert t_soil_k <= t_out_k <= t_in_k
    # For a long pipe, outlet should be closer to soil temp than inlet
    assert (t_out_k - t_soil_k) < (t_in_k - t_soil_k)


def test_catalog_lookup_with_temperature_scaling():
    """Test catalog lookup with custom reference temperatures."""
    cfg = CHAConfig(heat_loss_method="linear")
    
    catalog = {
        "DN50": {
            "q_linear_w_per_m_ref": 35.0,  # Higher than default
            "t_ref_k": 363.15,  # 90°C reference
            "t_soil_ref_k": 283.15,  # 10°C reference
        }
    }
    
    # Test at reference conditions (should get catalog value exactly)
    in_ref = HeatLossInputs(
        dn_mm=50.0,
        length_m=1.0,
        t_fluid_k=363.15,  # Catalog reference
        t_soil_k=283.15,  # Catalog reference
        role="trunk",
        circuit="supply",
    )
    result_ref = compute_heat_loss(in_ref, cfg, catalog)
    assert abs(result_ref.q_loss_w_per_m - 35.0) < 0.01
    
    # Test at different temperature (should scale)
    in_different = HeatLossInputs(
        dn_mm=50.0,
        length_m=1.0,
        t_fluid_k=353.15,  # 80°C (lower than catalog reference)
        t_soil_k=283.15,  # Same soil temp
        role="trunk",
        circuit="supply",
    )
    result_diff = compute_heat_loss(in_different, cfg, catalog)
    
    # Scaling: ΔT_actual / ΔT_ref = (353.15-283.15) / (363.15-283.15) = 70/80 = 0.875
    assert result_diff.q_loss_w_per_m < result_ref.q_loss_w_per_m
    expected_scaled = 35.0 * (70.0 / 80.0)
    assert abs(result_diff.q_loss_w_per_m - expected_scaled) < 0.1
