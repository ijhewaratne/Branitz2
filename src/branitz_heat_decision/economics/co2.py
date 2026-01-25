from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from .params import EconomicParameters, EconomicsParams
from .utils import safe_div


@dataclass(frozen=True)
class DHCO2Inputs:
    heat_mwh_per_year: float


@dataclass(frozen=True)
class HPCO2Inputs:
    heat_mwh_per_year: float


def compute_co2_dh(
    annual_heat_mwh: float,
    params: EconomicParameters,
    generation_type: Optional[str] = None,
) -> Tuple[float, Dict]:
    """
    Compute specific CO2 emissions for District Heating.

    Returns:
      (co2_kg_per_mwh_th, breakdown)
    """
    logger = logging.getLogger(__name__)
    if float(annual_heat_mwh) <= 0:
        raise ValueError(f"Annual heat demand must be positive, got {annual_heat_mwh}")

    gen_type = str(generation_type) if generation_type else params.dh_generation_type

    if gen_type == "gas":
        efficiency = 0.90
        emission_factor = float(params.ef_gas_kg_per_mwh)
        logger.debug("Using gas generation: ef=%.1f kg/MWh, eff=%.2f", emission_factor, efficiency)
        co2_per_mwh = emission_factor / efficiency
        annual_co2 = (float(annual_heat_mwh) / efficiency) * emission_factor
    elif gen_type == "biomass":
        efficiency = 0.85
        emission_factor = float(params.ef_biomass_kg_per_mwh)
        logger.debug("Using biomass generation: ef=%.1f kg/MWh, eff=%.2f", emission_factor, efficiency)
        co2_per_mwh = emission_factor / efficiency
        annual_co2 = (float(annual_heat_mwh) / efficiency) * emission_factor
    elif gen_type == "electric":
        cop_central = 3.0
        efficiency = None
        emission_factor = float(params.ef_electricity_kg_per_mwh)
        co2_per_mwh = emission_factor / cop_central
        annual_co2 = float(annual_heat_mwh) * co2_per_mwh
        logger.debug("Using central HP: COP=%.2f, ef=%.1f kg/MWh_el", cop_central, emission_factor)
    else:
        raise ValueError(f"Unknown generation type: {gen_type}")

    logger.info("CO2_DH: %.2f kg/MWh (total: %.2f kg/year)", co2_per_mwh, annual_co2)
    breakdown = {
        "co2_kg_per_mwh": float(co2_per_mwh),
        "annual_co2_kg": float(annual_co2),
        "generation_type": gen_type,
        "efficiency": float(efficiency) if gen_type in ["gas", "biomass"] else None,
        "emission_factor_kg_per_mwh": float(emission_factor),
    }
    return float(co2_per_mwh), breakdown


def compute_co2_hp(
    annual_heat_mwh: float,
    cop_annual_average: float,
    params: EconomicParameters,
) -> Tuple[float, Dict]:
    """
    Compute specific CO2 emissions for Heat Pump system.

    Returns:
      (co2_kg_per_mwh_th, breakdown)
    """
    logger = logging.getLogger(__name__)
    if float(annual_heat_mwh) <= 0:
        raise ValueError(f"Annual heat demand must be positive, got {annual_heat_mwh}")
    if float(cop_annual_average) <= 0:
        raise ValueError(f"COP must be positive, got {cop_annual_average}")

    annual_el_mwh = float(annual_heat_mwh) / float(cop_annual_average)
    annual_co2 = annual_el_mwh * float(params.ef_electricity_kg_per_mwh)
    co2_per_mwh = annual_co2 / float(annual_heat_mwh)

    logger.info("CO2_HP: %.2f kg/MWh (total: %.2f kg/year)", co2_per_mwh, annual_co2)
    breakdown = {
        "co2_kg_per_mwh": float(co2_per_mwh),
        "annual_co2_kg": float(annual_co2),
        "annual_el_mwh": float(annual_el_mwh),
        "cop_used": float(cop_annual_average),
        "ef_electricity_kg_per_mwh": float(params.ef_electricity_kg_per_mwh),
    }
    return float(co2_per_mwh), breakdown


def co2_dh(inputs: DHCO2Inputs, params: EconomicsParams) -> float:
    """Back-compat: annual CO2 in t/a for DH."""
    co2_kg_per_mwh, br = compute_co2_dh(inputs.heat_mwh_per_year, params=params)
    return float(br["annual_co2_kg"]) / 1000.0


def co2_hp(inputs: HPCO2Inputs, params: EconomicsParams) -> float:
    """Back-compat: annual CO2 in t/a for HP (uses params.cop_default)."""
    _, br = compute_co2_hp(inputs.heat_mwh_per_year, cop_annual_average=float(params.cop_default), params=params)
    return float(br["annual_co2_kg"]) / 1000.0

