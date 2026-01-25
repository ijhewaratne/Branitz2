import geopandas as gpd
import pandas as pd


def test_estimate_envelope_uses_sanierungszustand_and_uwerte3_if_available():
    from branitz_heat_decision.data.typology import estimate_envelope

    # Minimal GeoDataFrame; geometry not needed for this test.
    df = gpd.GeoDataFrame(
        {
            "building_id": ["B1"],
            "building_code": ["1010"],  # Wohnhaus exists in uwerte3.json (legacy)
            "building_function": ["Wohnhaus"],
            "sanierungszustand": ["vollsaniert"],
            "footprint_m2": [100.0],
            "wall_area_m2": [250.0],
            "volume_m3": [600.0],
            "floor_area_m2": [160.0],
            "annual_heat_demand_kwh_a": [20000.0],
        },
        geometry=[None],
    )

    out = estimate_envelope(df)
    assert out.loc[0, "renovation_state"] == "full"
    # Should have TABULA/U-value-derived fields populated (either from uwerte3 or fallback)
    assert "t_indoor_c" in out.columns
    assert "air_change_1_h" in out.columns
    assert "h_total_w_per_k" in out.columns
    assert pd.notna(out.loc[0, "t_indoor_c"])
    # With geometry present, heat-loss coefficient should be computable
    assert out.loc[0, "h_total_w_per_k"] > 0

