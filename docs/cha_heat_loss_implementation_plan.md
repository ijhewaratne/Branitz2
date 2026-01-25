# CHA Pipe Heat Loss Implementation Plan

## Overview
Incorporate proper pipe heat loss modeling into the CHA pipeline, supporting both **planning method (W/m × length)** and **detailed physics method (U·A·ΔT via thermal resistance)** as described in Energies 13, 4505 (2020) and Aquatherm (2025).

## Current State
- `_apply_pipe_thermal_losses()` in `network_builder_trunk_spur.py` uses constant `u_w_per_m2k = 0.7 W/m²K` for all pipes
- No differentiation by DN, insulation thickness, or pipe role (trunk/service, supply/return)
- No support for catalog-based linear heat loss (W/m) or detailed thermal resistance calculation

## Target Architecture

### 1. New Module: `src/branitz_heat_decision/cha/heat_loss.py`

**Method 1: Linear Heat Loss (W/m) — Planning Method**
```python
def compute_linear_heat_loss_w_per_m(
    dn_mm: float,
    t_fluid_k: float,
    t_soil_k: float,
    pipe_role: str = "trunk",
    catalog_lookup: Optional[Dict] = None
) -> float:
    """
    Compute linear heat loss q' [W/m] using planning method.
    
    Sources:
    - Aquatherm blog: 30 W/m for typical insulated DH pipe (90/70°C, buried)
    - Catalog datasheets: DN-specific q' values for standard operating temps
    
    Args:
        dn_mm: Nominal diameter in mm
        t_fluid_k: Fluid temperature (average of supply/return)
        t_soil_k: Soil temperature
        pipe_role: "trunk" or "service" (may have different insulation standards)
        catalog_lookup: Optional dict mapping DN -> q' [W/m] at reference temp
    
    Returns:
        Linear heat loss q' [W/m]
    """
```

**Method 2: Thermal Resistance → U-value → q' — Detailed Physics**
```python
def compute_thermal_resistance_u_value(
    dn_mm: float,
    t_fluid_k: float,
    t_soil_k: float,
    pipe_role: str = "trunk",
    insulation_thickness_mm: Optional[float] = None,
    burial_depth_m: float = 1.0,
    soil_conductivity_w_mk: float = 1.5,
    fluid_velocity_m_s: float = 1.0,
    supply_return_interaction: bool = False
) -> Tuple[float, float]:
    """
    Compute U-value [W/m²K] from thermal resistance layers.
    
    Thermal resistance R = R_conv,i + R_pipe + R_insulation + R_casing + R_soil
    
    Components:
    - R_conv,i: Internal convection (Dittus-Boelter, Nu correlation)
    - R_pipe: Steel/PEX pipe wall conduction (cylindrical)
    - R_insulation: Insulation layer (cylindrical, e.g., PUR foam)
    - R_casing: Outer casing (PE/steel) conduction
    - R_soil: Soil resistance (shape factor, depends on burial depth)
    
    For TwinPipe (supply/return interaction):
    - Use EN 13941 Wallentén model approximation
    - Or apply correction factor to single-pipe R_soil
    
    Args:
        dn_mm: Nominal diameter (inner)
        t_fluid_k: Fluid temperature
        t_soil_k: Soil temperature
        pipe_role: "trunk" or "service"
        insulation_thickness_mm: Insulation thickness (if None, use DN-based defaults)
        burial_depth_m: Burial depth (centerline to surface)
        soil_conductivity_w_mk: Soil thermal conductivity
        fluid_velocity_m_s: Fluid velocity (for internal convection)
        supply_return_interaction: True if TwinPipe configuration (adjacent supply/return)
    
    Returns:
        Tuple of (U [W/m²K], q' [W/m])
        where q' = U * A_o * (T_fluid - T_soil) for Δx = 1 m
    """
```

**Main Interface**
```python
def compute_pipe_heat_loss_params(
    dn_mm: float,
    length_m: float,
    t_fluid_k: float,
    t_soil_k: float,
    pipe_role: str = "trunk",
    circuit: str = "supply",
    method: str = "linear",  # "linear" or "thermal_resistance"
    catalog_lookup: Optional[Dict] = None,
    **kwargs
) -> Dict[str, float]:
    """
    Compute heat loss parameters for a single pipe segment.
    
    Returns:
        {
            "u_w_per_m2k": U-value [W/m²K] (pandapipes input)
            "text_k": External temperature [K] (pandapipes input)
            "q_loss_w_per_m": Linear heat loss [W/m]
            "q_loss_w": Total segment loss [W] (q' × L)
            "delta_t_k": Temperature drop [K] (approximate, if mass flow provided)
        }
    """
```

### 2. Catalog Integration

**Extend `sizing_catalog.py`** to include heat loss specs:
```python
def load_pipe_catalog_with_heat_loss(
    catalog_path: Optional[Path] = None
) -> pd.DataFrame:
    """
    Load pipe catalog with DN, diameter, cost, and heat loss specs.
    
    Columns:
    - dn_label: "DN50", "DN65", ...
    - inner_diameter_mm, outer_diameter_mm
    - insulation_thickness_mm (default if missing)
    - q_linear_w_per_m_ref: Linear heat loss [W/m] at reference temp (e.g., 80°C mean)
    - u_value_w_per_m2k_ref: U-value [W/m²K] at reference conditions (optional)
    """
```

### 3. Integration into Network Builder

**Update `_apply_pipe_thermal_losses()` in `network_builder_trunk_spur.py`**:
```python
def _apply_pipe_thermal_losses(
    net: pp.pandapipesNet,
    config: CHAConfig,
    pipe_dn_map: Optional[Dict[int, str]] = None,
    pipe_role_map: Optional[Dict[int, str]] = None,
    pipe_circuit_map: Optional[Dict[int, str]] = None,
    heat_loss_method: str = "linear"
) -> None:
    """
    Apply per-pipe heat loss parameters based on DN, role, and circuit.
    
    For each pipe in net.pipe:
    1. Determine DN (from pipe_dn_map or net.pipe.std_type)
    2. Determine role (trunk/service) and circuit (supply/return)
    3. Compute u_w_per_m2k using selected method
    4. Set net.pipe.u_w_per_m2k and net.pipe.text_k
    
    Supply/return thermal interaction (TwinPipe):
    - If supply and return pipes are adjacent (same street segment), apply
      correction factor to R_soil (EN 13941 approximation)
    - Or use separate calculation for paired pipes
    """
```

### 4. Configuration

**Update `config.py`**:
```python
@dataclass
class CHAConfig:
    # ... existing fields ...
    
    # Heat loss method selection
    heat_loss_method: str = "linear"  # "linear" or "thermal_resistance"
    
    # Linear method defaults (if catalog missing)
    default_q_linear_trunk_w_per_m: float = 30.0  # Aquatherm typical
    default_q_linear_service_w_per_m: float = 25.0
    
    # Thermal resistance method defaults
    default_insulation_thickness_mm: float = 50.0  # Standard PUR foam
    default_burial_depth_m: float = 1.0
    soil_conductivity_w_mk: float = 1.5  # Typical soil
    supply_return_interaction: bool = True  # Enable TwinPipe correction
    
    # Reference temperatures
    soil_temp_k: float = 285.15  # 12°C
```

### 5. Temperature Drop Calculation (Optional)

**For profile generation**:
```python
def compute_temperature_drop_along_pipe(
    q_loss_w: float,
    mdot_kg_per_s: float,
    cp_j_per_kgk: float = 4180.0
) -> float:
    """
    Compute temperature drop ΔT [K] along a pipe segment.
    
    ΔT ≈ Q_loss / (m_dot × cp)
    """
```

**For distributed loss (exponential decay)**:
```python
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
    
    T_out = T_soil + (T_in - T_soil) * exp(-(U*A_o)/(m_dot*cp) * L)
    """
```

## Implementation Steps

1. **Create `heat_loss.py` module** with both methods and helper functions
2. **Add unit tests** for:
   - Linear heat loss lookup (DN → W/m)
   - Thermal resistance calculation (U-value from layers)
   - Temperature drop conversion
   - TwinPipe interaction correction
3. **Extend `sizing_catalog.py`** to load heat loss specs from Technikkatalog Excel (if available)
4. **Update `network_builder_trunk_spur.py`** to:
   - Pass DN/role/circuit per pipe to `_apply_pipe_thermal_losses()`
   - Call new heat loss calculator per pipe
   - Handle supply/return pairing for TwinPipe correction
5. **Update `config.py`** with heat loss configuration options
6. **Update `kpi_extractor.py`** to report per-pipe and total heat losses (already reads `qext_w`)
7. **Document** in `docs/cha_pipeline_flow.md` or `docs/architecture.md`

## Data Sources

- **Aquatherm blog**: 30 W/m typical for insulated DH pipes (90/70°C, buried)
- **Technikkatalog Excel**: May contain DN-specific `q_linear_w_per_m` or insulation specs
- **EN 13941**: Wallentén model for TwinPipe thermal interaction
- **Energies 13, 4505 (2020)**: Thermal resistance formulation with soil shape factor

## Validation

- Compare computed `q'` with Aquatherm blog example (30 W/m over 1000 m → 30 kW → ~263 MWh/a at 8760 h)
- Check that temperature drops along long trunk pipes are realistic (<5°C for typical lengths)
- Verify that total annual heat loss matches expected ranges (5-15% of annual heat delivered)

## Notes

- **Pandapipes compatibility**: Uses `u_w_per_m2k` and `text_k` columns (already supported in v0.12+)
- **Default behavior**: Use "linear" method with catalog or conservative defaults if catalog missing
- **TwinPipe**: Can be approximated with correction factor initially; full EN 13941 model is optional enhancement
