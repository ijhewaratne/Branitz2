import json
from pathlib import Path

import pandas as pd
import pytest


@pytest.mark.economics
def test_economics_cli_pipeline_end_to_end(tmp_path):
    from branitz_heat_decision.cli.economics import run_economics_for_cluster

    cluster_id = "ST001_TEST_CLUSTER"

    # Minimal KPI files in the expected "user-schema" format.
    cha_kpis = {"network": {"total_length_m": 1000.0, "pump_power_kw": 10.0, "pipe_dn_lengths": {"DN50": 1000.0}}}
    dha_kpis = {"hp_system": {"hp_total_kw_design": 300.0}, "lv_grid": {"max_feeder_loading_pct": 120.0}}

    cha_path = tmp_path / "cha_kpis.json"
    dha_path = tmp_path / "dha_kpis.json"
    cha_path.write_text(json.dumps(cha_kpis), encoding="utf-8")
    dha_path.write_text(json.dumps(dha_kpis), encoding="utf-8")

    # Cluster summary parquet with repo-like schema (annual_heat_kwh_a)
    summary_path = tmp_path / "cluster_load_summary.parquet"
    df = pd.DataFrame(
        [
            {
                "cluster_id": cluster_id,
                "annual_heat_kwh_a": 1_000_000.0,  # -> 1000 MWh
                "design_load_kw": 300.0,
            }
        ]
    )
    df.to_parquet(summary_path, index=False)

    out_dir = tmp_path / "out"
    summary = run_economics_for_cluster(
        cluster_id=cluster_id,
        cha_kpis_path=cha_path,
        dha_kpis_path=dha_path,
        cluster_summary_path=summary_path,
        output_dir=out_dir,
        n_samples=10,
        seed=1,
        quiet=True,
        n_jobs=1,
    )

    assert (out_dir / "monte_carlo_samples.parquet").exists()
    assert (out_dir / "monte_carlo_summary.json").exists()
    assert "lcoh" in summary and "co2" in summary and "monte_carlo" in summary
    assert abs(summary["monte_carlo"]["dh_wins_fraction"] + summary["monte_carlo"]["hp_wins_fraction"] - 1.0) < 1e-9

