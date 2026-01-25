import math

import pytest


@pytest.mark.economics
def test_compute_co2_dh_gas_acceptance():
    from branitz_heat_decision.economics.params import EconomicParameters
    from branitz_heat_decision.economics.co2 import compute_co2_dh

    params = EconomicParameters(dh_generation_type="gas")
    co2_kg_per_mwh, br = compute_co2_dh(annual_heat_mwh=1000.0, params=params, generation_type="gas")
    assert abs(co2_kg_per_mwh - (200.0 / 0.90)) < 1e-9
    assert abs(br["annual_co2_kg"] - (1000.0 / 0.90) * 200.0) < 1e-6


@pytest.mark.economics
def test_compute_co2_dh_biomass_acceptance():
    from branitz_heat_decision.economics.params import EconomicParameters
    from branitz_heat_decision.economics.co2 import compute_co2_dh

    params = EconomicParameters(dh_generation_type="biomass")
    co2_kg_per_mwh, _ = compute_co2_dh(annual_heat_mwh=1000.0, params=params, generation_type="biomass")
    assert abs(co2_kg_per_mwh - (25.0 / 0.85)) < 1e-9


@pytest.mark.economics
def test_compute_co2_hp_acceptance():
    from branitz_heat_decision.economics.params import EconomicParameters
    from branitz_heat_decision.economics.co2 import compute_co2_hp

    params = EconomicParameters(ef_electricity_kg_per_mwh=350.0)
    co2_kg_per_mwh, br = compute_co2_hp(annual_heat_mwh=1000.0, cop_annual_average=2.8, params=params)
    assert abs(co2_kg_per_mwh - 125.0) < 1e-9
    assert math.isfinite(br["annual_co2_kg"])


@pytest.mark.economics
def test_compute_co2_zero_heat_raises():
    from branitz_heat_decision.economics.params import EconomicParameters
    from branitz_heat_decision.economics.co2 import compute_co2_dh

    params = EconomicParameters()
    with pytest.raises(ValueError):
        compute_co2_dh(annual_heat_mwh=0.0, params=params)

