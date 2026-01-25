import pytest


@pytest.mark.economics
def test_economic_parameters_validation_discount_rate():
    from branitz_heat_decision.economics.params import EconomicParameters

    with pytest.raises(ValueError):
        EconomicParameters(discount_rate=-0.1)
    with pytest.raises(ValueError):
        EconomicParameters(discount_rate=1.5)


@pytest.mark.economics
def test_economic_parameters_validation_generation_type():
    from branitz_heat_decision.economics.params import EconomicParameters

    with pytest.raises(ValueError):
        EconomicParameters(dh_generation_type="coal")


@pytest.mark.economics
def test_economic_parameters_validation_feeder_loading_limit():
    from branitz_heat_decision.economics.params import EconomicParameters

    with pytest.raises(ValueError):
        EconomicParameters(feeder_loading_planning_limit=0.0)
    with pytest.raises(ValueError):
        EconomicParameters(feeder_loading_planning_limit=1.5)


@pytest.mark.economics
def test_load_params_from_yaml(tmp_path):
    from branitz_heat_decision.economics.params import load_params_from_yaml

    y = tmp_path / "scenario.yaml"
    y.write_text(
        "\n".join(
            [
                "discount_rate: 0.05",
                "lifetime_years: 25",
                "electricity_price_eur_per_mwh: 300",
                "dh_generation_type: gas",
            ]
        ),
        encoding="utf-8",
    )
    p = load_params_from_yaml(str(y))
    assert p.discount_rate == 0.05
    assert p.lifetime_years == 25
    assert p.electricity_price_eur_per_mwh == 300.0
    assert p.dh_generation_type == "gas"

