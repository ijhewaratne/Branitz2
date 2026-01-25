from __future__ import annotations

import pytest

from branitz_heat_decision.decision.kpi_contract import build_kpi_contract
from branitz_heat_decision.decision.schemas import ContractValidator


def test_build_contract_minimal_inputs_validates():
    # Minimal-ish CHA/DHA/Econ structures that match our current builders.
    cha_kpis = {
        "en13941_compliance": {"feasible": True, "reasons": ["DH_OK"]},
        "aggregate": {"v_share_within_limits": 0.98, "dp_max_bar_per_100m": 0.2, "v_max_ms": 1.2, "v_min_ms": 0.01},
        "losses": {"length_total_m": 1000.0, "length_supply_m": 400.0, "length_return_m": 400.0, "length_service_m": 200.0, "loss_share_percent": 3.0},
        "pump": {"pump_power_kw": 10.0},
    }
    dha_kpis = {
        "kpis": {
            "feasible": True,
            "reasons": ["HP_OK"],
            "planning_warnings_total": 0,
            "max_feeder_loading_pct": 80.0,
            "voltage_violations_total": 0,
            "line_violations_total": 0,
        }
    }
    econ_summary = {
        "lcoh": {"dh": {"p05": 60.0, "p50": 70.0, "p95": 90.0}, "hp": {"p05": 65.0, "p50": 75.0, "p95": 110.0}},
        "co2": {"dh": {"p05": 60.0, "p50": 80.0, "p95": 120.0}, "hp": {"p05": 90.0, "p50": 120.0, "p95": 200.0}},
        "monte_carlo": {"dh_wins_fraction": 0.6, "hp_wins_fraction": 0.4, "n_samples": 500},
        "metadata": {"seed": 42},
    }
    metadata = {"created_utc": "2026-01-01T00:00:00Z"}

    contract = build_kpi_contract("ST_TEST", cha_kpis, dha_kpis, econ_summary, metadata)
    ContractValidator.validate(contract)


def test_missing_violation_counts_marks_hp_infeasible_and_reason_missing():
    cha_kpis = {"aggregate": {"v_share_within_limits": 1.0}, "en13941_compliance": {"feasible": True, "reasons": ["DH_OK"]}}
    dha_kpis = {"kpis": {"planning_warnings_total": 0, "max_feeder_loading_pct": 10.0}}  # missing voltage/line counts
    econ_summary = {
        "lcoh": {"dh": {"p05": 60.0, "p50": 70.0, "p95": 90.0}, "hp": {"p05": 65.0, "p50": 75.0, "p95": 110.0}},
        "co2": {"dh": {"p05": 60.0, "p50": 80.0, "p95": 120.0}, "hp": {"p05": 90.0, "p50": 120.0, "p95": 200.0}},
    }
    metadata = {"created_utc": "2026-01-01T00:00:00Z"}

    contract = build_kpi_contract("ST_TEST", cha_kpis, dha_kpis, econ_summary, metadata)
    assert contract["heat_pumps"]["feasible"] is False
    assert "DHA_MISSING_KPIS" in contract["heat_pumps"]["reasons"]

    # Contract still validates (because lv_grid fields are allowed to be None for violation counts)
    ContractValidator.validate(contract)


def test_missing_dh_kpis_marks_dh_infeasible_and_reason_missing():
    cha_kpis = {}  # nothing to infer from
    dha_kpis = {"kpis": {"voltage_violations_total": 0, "line_violations_total": 0, "max_feeder_loading_pct": 10.0}}
    econ_summary = {
        "lcoh": {"dh": {"p05": 60.0, "p50": 70.0, "p95": 90.0}, "hp": {"p05": 65.0, "p50": 75.0, "p95": 110.0}},
        "co2": {"dh": {"p05": 60.0, "p50": 80.0, "p95": 120.0}, "hp": {"p05": 90.0, "p50": 120.0, "p95": 200.0}},
    }
    metadata = {"created_utc": "2026-01-01T00:00:00Z"}

    contract = build_kpi_contract("ST_TEST", cha_kpis, dha_kpis, econ_summary, metadata)
    assert contract["district_heating"]["feasible"] is False
    assert "CHA_MISSING_KPIS" in contract["district_heating"]["reasons"]

