from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import numpy as np

from .params import EconomicParameters, EconomicsParams
from .utils import crf


@dataclass(frozen=True)
class DHInputs:
    heat_mwh_per_year: float
    pipe_lengths_by_dn: Optional[Dict[str, float]]
    total_pipe_length_m: float
    pump_power_kw: float


@dataclass(frozen=True)
class HPInputs:
    heat_mwh_per_year: float
    hp_total_capacity_kw_th: float
    cop_annual_average: float
    max_feeder_loading_pct: float


def compute_lcoh_dh(
    annual_heat_mwh: float,
    pipe_lengths_by_dn: Optional[Dict[str, float]],
    total_pipe_length_m: float,
    pump_power_kw: float,
    params: EconomicParameters,
    plant_cost_override: Optional[float] = None,
) -> Tuple[float, Dict]:
    """
    Compute LCOH for District Heating using CRF method.
    Returns (lcoh_eur_per_mwh, breakdown_dict).
    """
    logger = logging.getLogger(__name__)
    logger.info("Computing LCOH_DH for %.2f MWh/year", float(annual_heat_mwh))

    if float(annual_heat_mwh) <= 0:
        raise ValueError(f"Annual heat demand must be positive, got {annual_heat_mwh}")

    # 1) CAPEX
    capex_pipes = 0.0
    if pipe_lengths_by_dn:
        for dn, length_m in pipe_lengths_by_dn.items():
            cost_per_m = params.pipe_cost_eur_per_m.get(str(dn), params.pipe_cost_eur_per_m["DN100"])
            capex_pipes += float(length_m) * float(cost_per_m)
        logger.debug("Pipe CAPEX (detailed): %.2f EUR", capex_pipes)
    else:
        avg_cost = float(np.mean(list(params.pipe_cost_eur_per_m.values())))
        capex_pipes = float(total_pipe_length_m) * avg_cost
        # Avoid spamming warnings during Monte Carlo; breakdown is auditable.
        logger.debug("Using fallback pipe costing: %.2f EUR", capex_pipes)

    capex_pump = float(pump_power_kw) * float(params.pump_cost_per_kw)
    capex_plant = float(plant_cost_override) if plant_cost_override is not None else float(params.plant_cost_base_eur)
    total_capex = capex_pipes + capex_pump + capex_plant

    # 2) OPEX
    opex_om = total_capex * float(params.dh_om_frac_per_year)

    if params.dh_generation_type == "gas":
        efficiency = 0.90
        opex_energy = (float(annual_heat_mwh) / efficiency) * float(params.gas_price_eur_per_mwh)
    elif params.dh_generation_type == "biomass":
        efficiency = 0.85
        opex_energy = (float(annual_heat_mwh) / efficiency) * float(params.biomass_price_eur_per_mwh)
    elif params.dh_generation_type == "electric":
        cop = 3.0
        opex_energy = (float(annual_heat_mwh) / cop) * float(params.electricity_price_eur_per_mwh)
    else:
        raise ValueError(f"Unknown generation type: {params.dh_generation_type}")

    total_opex_annual = opex_om + opex_energy

    # 3) CRF
    crf_val = crf(float(params.discount_rate), int(params.lifetime_years))

    # 4) LCOH
    lcoh = (total_capex * crf_val + total_opex_annual) / float(annual_heat_mwh)

    breakdown = {
        "capex_total": total_capex,
        "capex_pipes": capex_pipes,
        "capex_pump": capex_pump,
        "capex_plant": capex_plant,
        "opex_annual": total_opex_annual,
        "opex_om": opex_om,
        "opex_energy": opex_energy,
        "crf": crf_val,
        "annual_heat_mwh": float(annual_heat_mwh),
        "generation_type": params.dh_generation_type,
    }
    return float(lcoh), breakdown


def compute_lcoh_hp(
    annual_heat_mwh: float,
    hp_total_capacity_kw_th: float,
    cop_annual_average: float,
    max_feeder_loading_pct: float,
    params: EconomicParameters,
) -> Tuple[float, Dict]:
    """
    Compute LCOH for Heat Pump system using CRF method.
    Returns (lcoh_eur_per_mwh, breakdown_dict).
    """
    logger = logging.getLogger(__name__)
    logger.info("Computing LCOH_HP for %.2f MWh/year, COP=%.3f", float(annual_heat_mwh), float(cop_annual_average))

    if float(annual_heat_mwh) <= 0:
        raise ValueError(f"Annual heat demand must be positive, got {annual_heat_mwh}")
    if float(cop_annual_average) <= 0:
        raise ValueError(f"COP must be positive, got {cop_annual_average}")

    capex_hp = float(hp_total_capacity_kw_th) * float(params.hp_cost_eur_per_kw_th)

    loading_threshold = float(params.feeder_loading_planning_limit) * 100.0
    if float(max_feeder_loading_pct) > loading_threshold:
        overload_factor = (float(max_feeder_loading_pct) - loading_threshold) / 100.0
        hp_el_capacity_kw = float(hp_total_capacity_kw_th) / float(cop_annual_average)
        upgrade_kw_el = overload_factor * hp_el_capacity_kw * 1.5
        capex_lv_upgrade = float(upgrade_kw_el) * float(params.lv_upgrade_cost_eur_per_kw_el)
        # Avoid spamming warnings during Monte Carlo; breakdown captures the value for audit.
        logger.debug("LV upgrade needed: %.1f kW_el, cost: %.2f EUR", upgrade_kw_el, capex_lv_upgrade)
    else:
        capex_lv_upgrade = 0.0

    total_capex = capex_hp + capex_lv_upgrade

    opex_om = capex_hp * float(params.hp_om_frac_per_year)
    annual_el_mwh = float(annual_heat_mwh) / float(cop_annual_average)
    opex_energy = annual_el_mwh * float(params.electricity_price_eur_per_mwh)
    total_opex_annual = opex_om + opex_energy

    crf_val = crf(float(params.discount_rate), int(params.lifetime_years))
    lcoh = (total_capex * crf_val + total_opex_annual) / float(annual_heat_mwh)

    breakdown = {
        "capex_total": total_capex,
        "capex_hp": capex_hp,
        "capex_lv_upgrade": capex_lv_upgrade,
        "opex_annual": total_opex_annual,
        "opex_om": opex_om,
        "opex_energy": opex_energy,
        "crf": crf_val,
        "annual_heat_mwh": float(annual_heat_mwh),
        "annual_el_mwh": float(annual_el_mwh),
        "cop_used": float(cop_annual_average),
        "max_feeder_loading_pct": float(max_feeder_loading_pct),
        "loading_threshold_pct": float(loading_threshold),
    }
    return float(lcoh), breakdown


def lcoh_dh_crf(inputs: DHInputs, params: EconomicsParams) -> float:
    """Back-compat: return only LCOH."""
    v, _ = compute_lcoh_dh(
        annual_heat_mwh=inputs.heat_mwh_per_year,
        pipe_lengths_by_dn=inputs.pipe_lengths_by_dn,
        total_pipe_length_m=inputs.total_pipe_length_m,
        pump_power_kw=inputs.pump_power_kw,
        params=params,
    )
    return float(v)


def lcoh_hp_crf(inputs: HPInputs, params: EconomicsParams) -> float:
    """Back-compat: return only LCOH."""
    v, _ = compute_lcoh_hp(
        annual_heat_mwh=inputs.heat_mwh_per_year,
        hp_total_capacity_kw_th=inputs.hp_total_capacity_kw_th,
        cop_annual_average=inputs.cop_annual_average,
        max_feeder_loading_pct=inputs.max_feeder_loading_pct,
        params=params,
    )
    return float(v)

