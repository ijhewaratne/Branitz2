from __future__ import annotations

import json
from pathlib import Path

import pytest

from branitz_heat_decision.uhdc.orchestrator import discover_artifact_paths, build_uhdc_report


def test_discover_artifact_paths_finds_expected_layout(tmp_path: Path):
    cluster_id = "ST_TEST"
    run_dir = tmp_path / "results"
    (run_dir / "cha" / cluster_id).mkdir(parents=True, exist_ok=True)
    (run_dir / "dha" / cluster_id).mkdir(parents=True, exist_ok=True)
    (run_dir / "economics" / cluster_id).mkdir(parents=True, exist_ok=True)

    (run_dir / "cha" / cluster_id / "cha_kpis.json").write_text(json.dumps({"x": 1}))
    (run_dir / "dha" / cluster_id / "dha_kpis.json").write_text(json.dumps({"y": 2}))
    (run_dir / "economics" / cluster_id / "monte_carlo_summary.json").write_text(json.dumps({"z": 3}))

    found = discover_artifact_paths(cluster_id=cluster_id, base_dir=run_dir)
    assert found["cha_kpis"] is not None and found["cha_kpis"].name == "cha_kpis.json"
    assert found["dha_kpis"] is not None and found["dha_kpis"].name == "dha_kpis.json"
    assert found["econ_summary"] is not None and found["econ_summary"].name == "monte_carlo_summary.json"


def test_discover_flat_structure(tmp_path: Path):
    """
    Flat structure support: artifacts present directly under base_dir.
    """
    cluster_id = "ST_TEST"
    run_dir = tmp_path / "results"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "cha_kpis.json").write_text(json.dumps({"x": 1}))
    (run_dir / "dha_kpis.json").write_text(json.dumps({"y": 2}))
    (run_dir / "monte_carlo_summary.json").write_text(json.dumps({"z": 3}))

    found = discover_artifact_paths(cluster_id=cluster_id, base_dir=run_dir)
    assert found["cha_kpis"] == run_dir / "cha_kpis.json"
    assert found["dha_kpis"] == run_dir / "dha_kpis.json"
    assert found["econ_summary"] == run_dir / "monte_carlo_summary.json"


def test_discover_fallback_order_prefers_more_specific(tmp_path: Path):
    """
    Ensure the first matching pattern wins (order matters).
    """
    cluster_id = "ST_TEST"
    run_dir = tmp_path / "results"
    (run_dir / "cha" / cluster_id).mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(parents=True, exist_ok=True)

    nested = run_dir / "cha" / cluster_id / "cha_kpis.json"
    flat = run_dir / "cha_kpis.json"
    nested.write_text(json.dumps({"nested": True}))
    flat.write_text(json.dumps({"flat": True}))

    found = discover_artifact_paths(cluster_id=cluster_id, base_dir=run_dir)
    assert found["cha_kpis"] == nested


def test_no_artifacts_raises_error(tmp_path: Path):
    """
    build_uhdc_report() must raise a clear error when nothing exists.
    """
    cluster_id = "ST_TEST"
    run_dir = tmp_path / "results"
    run_dir.mkdir(parents=True, exist_ok=True)

    with pytest.raises(FileNotFoundError):
        build_uhdc_report(cluster_id=cluster_id, run_dir=run_dir)
