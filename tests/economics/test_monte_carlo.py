import pandas as pd
import pytest


@pytest.mark.economics
def test_sample_param_normal_clip():
    import numpy as np

    from branitz_heat_decision.economics.monte_carlo import sample_param

    rng = np.random.default_rng(123)
    spec = {"dist": "normal", "mean": 10.0, "std": 2.0, "clip": [5.0, 15.0]}
    xs = [sample_param(spec, rng) for _ in range(2000)]
    assert all(5.0 <= x <= 15.0 for x in xs)
    # mean should be in the right ballpark (clipping changes it slightly)
    m = sum(xs) / len(xs)
    assert 9.0 <= m <= 11.0


@pytest.mark.economics
def test_run_monte_carlo_for_cluster_reproducible_seed():
    from branitz_heat_decision.economics.monte_carlo import run_monte_carlo_for_cluster

    cluster_id = "ST001_TEST_CLUSTER"
    cha_kpis = {
        "network": {
            "total_length_m": 1000.0,
            "pump_power_kw": 10.0,
            "pipe_dn_lengths": {"DN50": 1000.0},
        }
    }
    dha_kpis = {
        "hp_system": {"hp_total_kw_design": 300.0},
        "lv_grid": {"max_feeder_loading_pct": 120.0},
    }
    cluster_summary = {"annual_heat_mwh": 1000.0, "design_load_kw": 300.0}

    df1 = run_monte_carlo_for_cluster(
        cluster_id=cluster_id,
        cha_kpis=cha_kpis,
        dha_kpis=dha_kpis,
        cluster_summary=cluster_summary,
        n_samples=25,
        seed=42,
        n_jobs=1,
    )
    df2 = run_monte_carlo_for_cluster(
        cluster_id=cluster_id,
        cha_kpis=cha_kpis,
        dha_kpis=dha_kpis,
        cluster_summary=cluster_summary,
        n_samples=25,
        seed=42,
        n_jobs=1,
    )
    pd.testing.assert_frame_equal(df1, df2, check_exact=True)


@pytest.mark.economics
def test_compute_mc_summary_basic():
    from branitz_heat_decision.economics.monte_carlo import compute_mc_summary

    df = pd.DataFrame(
        [
            {"lcoh_dh": 10.0, "lcoh_hp": 20.0, "co2_dh": 1.0, "co2_hp": 2.0, "dh_cheaper": True, "dh_lower_co2": True},
            {"lcoh_dh": 30.0, "lcoh_hp": 20.0, "co2_dh": 3.0, "co2_hp": 2.0, "dh_cheaper": False, "dh_lower_co2": False},
        ]
    )
    s = compute_mc_summary(df)
    assert s["monte_carlo"]["n_samples"] == 2
    assert s["monte_carlo"]["n_valid"] == 2
    assert abs(s["monte_carlo"]["dh_wins_fraction"] - 0.5) < 1e-12
    assert abs(s["monte_carlo"]["hp_wins_fraction"] - 0.5) < 1e-12

