from __future__ import annotations

import pytest

from branitz_heat_decision.decision.schemas import ContractValidator


def _valid_contract() -> dict:
    return {
        "version": "1.0",
        "cluster_id": "ST_TEST",
        "metadata": {"created_utc": "2026-01-01T00:00:00Z"},
        "district_heating": {
            "feasible": True,
            "reasons": ["DH_OK"],
            "lcoh": {"median": 70.0, "p05": 60.0, "p95": 90.0},
            "co2": {"median": 80.0, "p05": 60.0, "p95": 120.0},
            "hydraulics": {
                "velocity_ok": True,
                "dp_ok": True,
                "v_max_ms": 1.2,
                "v_min_ms": 0.01,
                "v_share_within_limits": 0.98,
                "dp_per_100m_max": 0.2,
                "hard_violations": [],
            },
            "losses": {
                "total_length_m": 1000.0,
                "trunk_length_m": 800.0,
                "service_length_m": 200.0,
                "loss_share_pct": 3.0,
                "pump_power_kw": 10.0,
            },
        },
        "heat_pumps": {
            "feasible": True,
            "reasons": ["HP_OK"],
            "lcoh": {"median": 75.0, "p05": 65.0, "p95": 110.0},
            "co2": {"median": 120.0, "p05": 90.0, "p95": 200.0},
            "lv_grid": {
                "planning_warning": False,
                "max_feeder_loading_pct": 80.0,
                "voltage_violations_total": 0,
                "line_violations_total": 0,
                "worst_bus_id": None,
                "worst_line_id": None,
            },
            "hp_system": {"hp_total_kw_design": 100.0, "hp_total_kw_topn_max": 120.0},
        },
        "monte_carlo": {"dh_wins_fraction": 0.6, "hp_wins_fraction": 0.4, "n_samples": 500, "seed": 42},
    }


def test_schema_validates_correct_contract():
    ContractValidator.validate(_valid_contract())


def test_schema_rejects_missing_keys():
    c = _valid_contract()
    del c["cluster_id"]
    with pytest.raises(ValueError, match="missing top-level keys"):
        ContractValidator.validate(c)


def test_schema_rejects_invalid_reason_code():
    c = _valid_contract()
    c["district_heating"]["reasons"] = ["NOT_A_CODE"]
    with pytest.raises(ValueError, match="Unknown reason code"):
        ContractValidator.validate(c)


def test_schema_allows_missing_mc_block():
    c = _valid_contract()
    c["monte_carlo"] = None
    ContractValidator.validate(c)

