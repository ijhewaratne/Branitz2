import math

import pytest


@pytest.mark.economics
def test_compute_lcoh_dh_gas_matches_formula():
    from branitz_heat_decision.economics.params import EconomicParameters
    from branitz_heat_decision.economics.lcoh import compute_lcoh_dh
    from branitz_heat_decision.economics.utils import calculate_crf

    params = EconomicParameters(discount_rate=0.04, lifetime_years=20, dh_generation_type="gas")

    annual_heat_mwh = 1000.0
    pipe_lengths_by_dn = {"DN50": 1000.0}  # 1 km DN50
    total_pipe_length_m = 1000.0
    pump_power_kw = 10.0

    lcoh, br = compute_lcoh_dh(
        annual_heat_mwh=annual_heat_mwh,
        pipe_lengths_by_dn=pipe_lengths_by_dn,
        total_pipe_length_m=total_pipe_length_m,
        pump_power_kw=pump_power_kw,
        params=params,
    )

    capex_pipes = 1000.0 * params.pipe_cost_eur_per_m["DN50"]
    capex_pump = pump_power_kw * params.pump_cost_per_kw
    capex_plant = params.plant_cost_base_eur
    capex_total = capex_pipes + capex_pump + capex_plant

    opex_om = capex_total * params.dh_om_frac_per_year
    efficiency = 0.90
    opex_energy = (annual_heat_mwh / efficiency) * params.gas_price_eur_per_mwh
    crf = calculate_crf(params.discount_rate, params.lifetime_years)

    expected = (capex_total * crf + (opex_om + opex_energy)) / annual_heat_mwh
    assert math.isfinite(lcoh)
    assert abs(lcoh - expected) < 1e-6
    assert br["generation_type"] == "gas"


@pytest.mark.economics
def test_compute_lcoh_hp_lv_upgrade_triggers():
    from branitz_heat_decision.economics.params import EconomicParameters
    from branitz_heat_decision.economics.lcoh import compute_lcoh_hp

    params = EconomicParameters(feeder_loading_planning_limit=0.8)

    annual_heat_mwh = 1000.0
    hp_total_capacity_kw_th = 300.0
    cop = 2.8
    max_loading_pct = 120.0  # > 80% => upgrade

    lcoh, br = compute_lcoh_hp(
        annual_heat_mwh=annual_heat_mwh,
        hp_total_capacity_kw_th=hp_total_capacity_kw_th,
        cop_annual_average=cop,
        max_feeder_loading_pct=max_loading_pct,
        params=params,
    )
    assert lcoh > 0
    assert br["capex_lv_upgrade"] > 0

