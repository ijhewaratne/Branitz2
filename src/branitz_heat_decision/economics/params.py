from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from typing import Dict


@dataclass(frozen=True)
class EconomicParameters:
    """
    Economic parameters for LCOH and CO2 calculations.
    All monetary values in EUR, energy in MWh, emissions in kg CO2.
    """

    # Time value
    lifetime_years: int = 20
    discount_rate: float = 0.04  # 4%

    # Energy prices (EUR/MWh)
    electricity_price_eur_per_mwh: float = 250.0
    gas_price_eur_per_mwh: float = 80.0
    biomass_price_eur_per_mwh: float = 110.0

    # Emission factors (kg CO2/MWh)
    ef_electricity_kg_per_mwh: float = 350.0  # German grid mix (reference)
    ef_gas_kg_per_mwh: float = 200.0
    ef_biomass_kg_per_mwh: float = 25.0

    # CAPEX parameters
    pipe_cost_eur_per_m: Dict[str, float] = field(
        default_factory=lambda: {
            "DN20": 50.0,
            "DN25": 60.0,
            "DN32": 75.0,
            "DN40": 90.0,
            "DN50": 110.0,
            "DN65": 140.0,
            "DN80": 170.0,
            "DN100": 220.0,
            "DN125": 280.0,
            "DN150": 350.0,
            "DN200": 500.0,
        }
    )
    plant_cost_base_eur: float = 1500000.0
    pump_cost_per_kw: float = 500.0

    # HP parameters
    hp_cost_eur_per_kw_th: float = 900.0
    cop_default: float = 2.8

    # LV upgrade cost (optional hook)
    lv_upgrade_cost_eur_per_kw_el: float = 200.0

    # Planning limit used for LV upgrade heuristic in HP economics (fraction, e.g. 0.8 = 80%)
    feeder_loading_planning_limit: float = 0.8

    # O&M fractions
    dh_om_frac_per_year: float = 0.02
    hp_om_frac_per_year: float = 0.02

    # DH generation type
    dh_generation_type: str = "biomass"  # 'gas' | 'biomass' | 'electric'

    def __post_init__(self) -> None:
        if not 0.0 < float(self.discount_rate) < 1.0:
            raise ValueError(f"Discount rate must be in (0,1), got {self.discount_rate}")
        if int(self.lifetime_years) <= 0:
            raise ValueError(f"Lifetime must be positive, got {self.lifetime_years}")
        if self.dh_generation_type not in ["gas", "biomass", "electric"]:
            raise ValueError(f"Unknown generation type: {self.dh_generation_type}")
        if not 0.0 < float(self.feeder_loading_planning_limit) <= 1.0:
            raise ValueError(
                f"feeder_loading_planning_limit must be in (0,1], got {self.feeder_loading_planning_limit}"
            )
        logging.info("EconomicParameters initialized: %s", self)

    def dh_energy_price_eur_per_mwh(self) -> float:
        if self.dh_generation_type == "gas":
            return float(self.gas_price_eur_per_mwh)
        if self.dh_generation_type == "biomass":
            return float(self.biomass_price_eur_per_mwh)
        return float(self.electricity_price_eur_per_mwh)

    def dh_emission_factor_kg_per_mwh(self) -> float:
        if self.dh_generation_type == "gas":
            return float(self.ef_gas_kg_per_mwh)
        if self.dh_generation_type == "biomass":
            return float(self.ef_biomass_kg_per_mwh)
        return float(self.ef_electricity_kg_per_mwh)


def load_default_params() -> EconomicParameters:
    return EconomicParameters()


def load_params_from_yaml(path: str) -> EconomicParameters:
    import yaml

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return EconomicParameters(**data)


# Backwards-compat aliases (so existing code keeps working while we align with Phase 4 plan)
EconomicsParams = EconomicParameters


@dataclass(frozen=True)
class MonteCarloParams:
    n: int = 500
    seed: int = 42

    # bounded multipliers / ranges (MVP)
    capex_mult_min: float = 0.8
    capex_mult_max: float = 1.2
    elec_price_mult_min: float = 0.7
    elec_price_mult_max: float = 1.3
    fuel_price_mult_min: float = 0.7
    fuel_price_mult_max: float = 1.3
    grid_co2_mult_min: float = 0.7
    grid_co2_mult_max: float = 1.3
    hp_cop_min: float = 2.0
    hp_cop_max: float = 3.5
    discount_rate_min: float = 0.02
    discount_rate_max: float = 0.08


def get_default_economics_params() -> EconomicsParams:
    return load_default_params()


def get_default_monte_carlo_params() -> MonteCarloParams:
    return MonteCarloParams()


def apply_multipliers(
    base: EconomicsParams,
    *,
    capex_mult: float,
    elec_price_mult: float,
    fuel_price_mult: float,
    grid_co2_mult: float,
    hp_cop: float,
    discount_rate: float,
) -> EconomicsParams:
    """
    Apply simple multipliers for Monte Carlo (MVP).
    - CAPEX multiplier applies to pipe + plant + hp CAPEX and pump cost
    - Electricity & grid CO2 multipliers apply to electricity price / EF
    - Fuel price multiplier applies to gas+biomass (DH generation energy price)
    """
    p = base
    # Apply CAPEX mult to pipe costs + plant base + pump and HP capex.
    pipe_cost = {k: float(v) * float(capex_mult) for k, v in p.pipe_cost_eur_per_m.items()}

    # Apply fuel multiplier to gas+biomass prices.
    gas_price = float(p.gas_price_eur_per_mwh) * float(fuel_price_mult)
    biomass_price = float(p.biomass_price_eur_per_mwh) * float(fuel_price_mult)

    return replace(
        p,
        discount_rate=float(discount_rate),
        pipe_cost_eur_per_m=pipe_cost,
        plant_cost_base_eur=float(p.plant_cost_base_eur) * float(capex_mult),
        pump_cost_per_kw=float(p.pump_cost_per_kw) * float(capex_mult),
        hp_cost_eur_per_kw_th=float(p.hp_cost_eur_per_kw_th) * float(capex_mult),
        electricity_price_eur_per_mwh=float(p.electricity_price_eur_per_mwh) * float(elec_price_mult),
        ef_electricity_kg_per_mwh=float(p.ef_electricity_kg_per_mwh) * float(grid_co2_mult),
        gas_price_eur_per_mwh=gas_price,
        biomass_price_eur_per_mwh=biomass_price,
        cop_default=float(hp_cop),
    )

