import pandas as pd

from branitz_heat_decision.dha.bdew_base_loads import (
    compute_bdew_base_loads_for_hours_and_assumptions,
    _default_bdew_paths,
)


def test_bdew_base_loads_for_hours_shape_and_nonnegativity():
    # Minimal buildings table with required columns
    buildings = pd.DataFrame(
        [
            {"building_id": "B1", "building_code": "1000", "floor_area_m2": 120.0},  # H0 residential
            {"building_id": "B2", "building_code": "2050", "floor_area_m2": 200.0},  # G4 retail-ish
        ]
    )
    hours = [0, 1, 123]
    base_df, assumptions = compute_bdew_base_loads_for_hours_and_assumptions(
        buildings_df=buildings, hours=hours, year=2023, paths=_default_bdew_paths(), require_population=False
    )

    assert list(base_df.index) == hours
    assert set(base_df.columns) == {"B1", "B2"}
    assert (base_df.values >= 0.0).all()
    assert set(assumptions.columns) >= {
        "building_id",
        "profile_type",
        "yearly_kwh_assumed",
        "bdew_profiles_csv",
        "population_json",
    }

