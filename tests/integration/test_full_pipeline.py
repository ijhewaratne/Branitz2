from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def _pick_cluster_id() -> str:
    # Prefer explicit override, else try common clusters we used in this repo.
    cid = os.environ.get("BRANITZ_INTEGRATION_CLUSTER_ID")
    if cid:
        return cid
    for candidate in ("ST001_HEINRICH_ZILLE_STRASSE", "ST010_HEINRICH_ZILLE_STRASSE"):
        if (Path("results") / "cha" / candidate / "cha_kpis.json").exists():
            return candidate
    return "ST001_HEINRICH_ZILLE_STRASSE"


def _require_paths_or_skip(cluster_id: str) -> None:
    required = [
        Path("results") / "cha" / cluster_id / "cha_kpis.json",
        Path("results") / "dha" / cluster_id / "dha_kpis.json",
        Path("results") / "economics" / cluster_id / "monte_carlo_summary.json",
    ]
    missing = [p for p in required if not p.exists()]
    if missing:
        pytest.skip(
            "Integration prerequisites missing. Run pipelines first. Missing: "
            + ", ".join(str(p) for p in missing)
        )


def test_decision_cli_on_real_cluster(tmp_path: Path):
    """
    End-to-end Phase 5: run decision CLI on real (precomputed) CHA/DHA/Economics artifacts.
    This test does NOT run CHA/DHA/Economics; it validates Phase 5 integration only.
    """
    cluster_id = _pick_cluster_id()
    _require_paths_or_skip(cluster_id)

    out_dir = tmp_path / "decision_out"

    cmd = [
        "python",
        "-m",
        "branitz_heat_decision.cli.decision",
        "--cluster-id",
        cluster_id,
        "--cha-kpis",
        f"results/cha/{cluster_id}/cha_kpis.json",
        "--dha-kpis",
        f"results/dha/{cluster_id}/dha_kpis.json",
        "--econ-summary",
        f"results/economics/{cluster_id}/monte_carlo_summary.json",
        "--out-dir",
        str(out_dir),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, env={**os.environ, "PYTHONPATH": "src"})
    assert r.returncode == 0, f"Decision CLI failed:\nSTDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}"
    assert "Contract schema validation passed" in r.stdout

    contract_path = out_dir / f"kpi_contract_{cluster_id}.json"
    decision_path = out_dir / f"decision_{cluster_id}.json"
    assert contract_path.exists()
    assert decision_path.exists()

    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    decision = json.loads(decision_path.read_text(encoding="utf-8"))

    assert contract["cluster_id"] == cluster_id
    assert decision["choice"] in ["DH", "HP", "UNDECIDED"]
    assert isinstance(decision["robust"], bool)
    assert len(decision["reason_codes"]) > 0

    # Schema validation should pass (no raise)
    from branitz_heat_decision.decision.schemas import ContractValidator

    ContractValidator.validate(contract)


def test_decision_is_deterministic_on_real_cluster(tmp_path: Path):
    """
    Run decision twice with identical inputs and verify stable output (no LLM).
    """
    cluster_id = _pick_cluster_id()
    _require_paths_or_skip(cluster_id)

    out_dir = tmp_path / "decision_out"

    def _run_and_load():
        cmd = [
            "python",
            "-m",
            "branitz_heat_decision.cli.decision",
            "--cluster-id",
            cluster_id,
            "--cha-kpis",
            f"results/cha/{cluster_id}/cha_kpis.json",
            "--dha-kpis",
            f"results/dha/{cluster_id}/dha_kpis.json",
            "--econ-summary",
            f"results/economics/{cluster_id}/monte_carlo_summary.json",
            "--out-dir",
            str(out_dir),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, env={**os.environ, "PYTHONPATH": "src"})
        assert r.returncode == 0, f"Decision CLI failed:\n{r.stderr}"
        decision_path = out_dir / f"decision_{cluster_id}.json"
        return json.loads(decision_path.read_text(encoding="utf-8"))

    d1 = _run_and_load()
    d2 = _run_and_load()

    assert d1["choice"] == d2["choice"]
    assert d1["reason_codes"] == d2["reason_codes"]
    assert d1["metrics_used"] == d2["metrics_used"]


def test_uhdc_cli_generates_reports_from_real_cluster(tmp_path: Path):
    """
    End-to-end UHDC report generation on real artifacts.
    """
    cluster_id = _pick_cluster_id()
    _require_paths_or_skip(cluster_id)

    out_dir = tmp_path / "uhdc_report"

    cmd = [
        "python",
        "-m",
        "branitz_heat_decision.cli.uhdc",
        "--cluster-id",
        cluster_id,
        "--run-dir",
        "results",
        "--out-dir",
        str(out_dir),
        "--style",
        "executive",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, env={**os.environ, "PYTHONPATH": "src"})
    assert r.returncode == 0, f"UHDC CLI failed:\nSTDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}"

    assert (out_dir / f"uhdc_report_{cluster_id}.html").exists()
    assert (out_dir / f"uhdc_explanation_{cluster_id}.md").exists()
    assert (out_dir / f"uhdc_report_{cluster_id}.json").exists()

