from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from branitz_heat_decision.decision.rules import decide_from_contract

pytestmark = pytest.mark.performance


def _load_contract_or_synthetic() -> dict:
    # Prefer a real contract if present.
    candidate = Path("results") / "decision" / "ST001_HEINRICH_ZILLE_STRASSE" / "kpi_contract_ST001_HEINRICH_ZILLE_STRASSE.json"
    if candidate.exists():
        return json.loads(candidate.read_text(encoding="utf-8"))

    # Otherwise use a synthetic minimal contract.
    return {
        "district_heating": {"feasible": True, "lcoh": {"median": 70.0}, "co2": {"median": 100.0}},
        "heat_pumps": {"feasible": True, "lcoh": {"median": 80.0}, "co2": {"median": 120.0}},
        "monte_carlo": {"dh_wins_fraction": 0.6, "hp_wins_fraction": 0.4},
    }


def test_decision_speed():
    """
    Decision logic must be <10ms per cluster (average), measured over 1000 iterations.
    
    This test is skipped by default unless RUN_PERFORMANCE_TESTS=1 is set,
    because performance assertions are environment-dependent.
    """
    if os.environ.get("RUN_PERFORMANCE_TESTS") != "1":
        pytest.skip("Set RUN_PERFORMANCE_TESTS=1 to enable performance benchmarks")

    contract = _load_contract_or_synthetic()

    n = 1000
    t0 = time.perf_counter()
    for _ in range(n):
        decide_from_contract(contract)
    elapsed = time.perf_counter() - t0

    avg_s = elapsed / n
    assert avg_s < 0.01, f"Decision too slow: {avg_s*1000:.2f}ms avg"


def test_batch_processing_overhead():
    """
    Placeholder: batch overhead depends on IO and cluster count.
    Keep as a manual benchmark for now.
    """
    pytest.skip("Manual benchmark (depends on disk IO and number of clusters)")

