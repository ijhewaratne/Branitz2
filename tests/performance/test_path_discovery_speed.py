from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from branitz_heat_decision.uhdc.orchestrator import discover_artifact_paths, clear_discovery_cache

pytestmark = pytest.mark.performance


def test_path_discovery_handles_1000_clusters(tmp_path: Path):
    """
    Path discovery should not degrade with many clusters present.

    This test is skipped by default unless RUN_PERFORMANCE_TESTS=1 is set,
    because timing thresholds are environment-dependent.
    """
    if os.environ.get("RUN_PERFORMANCE_TESTS") != "1":
        pytest.skip("Set RUN_PERFORMANCE_TESTS=1 to enable performance benchmarks")

    run_dir = tmp_path / "results"
    # Create 1000 cluster directories with a CHA KPI artifact
    for i in range(1000):
        cid = f"ST{i:03d}"
        p = run_dir / "cha" / cid
        p.mkdir(parents=True, exist_ok=True)
        (p / "cha_kpis.json").write_text("{}", encoding="utf-8")

    # Time discovery for the last cluster (should be near-constant time)
    t0 = time.perf_counter()
    found = discover_artifact_paths(cluster_id="ST999", base_dir=run_dir)
    elapsed = time.perf_counter() - t0

    assert found["cha_kpis"] is not None
    assert elapsed < 0.25, f"Path discovery too slow: {elapsed:.3f}s for 1000 clusters"


def test_path_discovery_cache_avoids_exists_calls(monkeypatch, tmp_path: Path):
    """
    Ensure cache prevents repeated Path.exists filesystem checks on subsequent calls.
    """
    if os.environ.get("RUN_PERFORMANCE_TESTS") != "1":
        pytest.skip("Set RUN_PERFORMANCE_TESTS=1 to enable performance benchmarks")

    clear_discovery_cache()

    run_dir = tmp_path / "results"
    cid = "ST001"
    p = run_dir / "cha" / cid
    p.mkdir(parents=True, exist_ok=True)
    (p / "cha_kpis.json").write_text("{}", encoding="utf-8")

    # First call populates cache
    discover_artifact_paths(cluster_id=cid, base_dir=run_dir)

    # Second call should not call Path.exists at all
    calls = {"n": 0}
    orig_exists = Path.exists

    def _counting_exists(self: Path) -> bool:  # type: ignore[override]
        calls["n"] += 1
        return orig_exists(self)

    monkeypatch.setattr(Path, "exists", _counting_exists, raising=True)
    discover_artifact_paths(cluster_id=cid, base_dir=run_dir)
    assert calls["n"] == 0, f"Cache did not work; Path.exists called {calls['n']} times"

