from __future__ import annotations

from branitz_heat_decision.decision.rules import decide_from_contract


def _base_contract() -> dict:
    return {
        "district_heating": {"feasible": True, "lcoh": {"median": 70.0}, "co2": {"median": 100.0}},
        "heat_pumps": {"feasible": True, "lcoh": {"median": 80.0}, "co2": {"median": 120.0}},
        "monte_carlo": {"dh_wins_fraction": 0.6, "hp_wins_fraction": 0.4},
    }


def test_only_dh_feasible():
    c = _base_contract()
    c["heat_pumps"]["feasible"] = False
    r = decide_from_contract(c)
    assert r.choice == "DH"
    assert "ONLY_DH_FEASIBLE" in r.reason_codes


def test_only_hp_feasible():
    c = _base_contract()
    c["district_heating"]["feasible"] = False
    r = decide_from_contract(c)
    assert r.choice == "HP"
    assert "ONLY_HP_FEASIBLE" in r.reason_codes


def test_neither_feasible():
    c = _base_contract()
    c["district_heating"]["feasible"] = False
    c["heat_pumps"]["feasible"] = False
    r = decide_from_contract(c)
    assert r.choice == "UNDECIDED"
    assert "NONE_FEASIBLE" in r.reason_codes


def test_cost_dominant_dh():
    c = _base_contract()
    c["district_heating"]["lcoh"]["median"] = 60.0
    c["heat_pumps"]["lcoh"]["median"] = 80.0
    r = decide_from_contract(c)
    assert r.choice == "DH"
    assert "COST_DOMINANT_DH" in r.reason_codes


def test_cost_close_use_co2_tiebreaker():
    c = _base_contract()
    c["district_heating"]["lcoh"]["median"] = 70.0
    c["heat_pumps"]["lcoh"]["median"] = 71.0  # close
    c["district_heating"]["co2"]["median"] = 90.0
    c["heat_pumps"]["co2"]["median"] = 120.0
    r = decide_from_contract(c)
    assert "COST_CLOSE_USE_CO2" in r.reason_codes
    assert r.choice == "DH"

def test_robust_threshold_70():
    c = _base_contract()
    c["district_heating"]["lcoh"]["median"] = 60.0
    c["heat_pumps"]["lcoh"]["median"] = 80.0
    c["monte_carlo"]["dh_wins_fraction"] = 0.75
    r = decide_from_contract(c)
    assert r.choice == "DH"
    assert r.robust is True
    assert "ROBUST_DECISION" in r.reason_codes


def test_sensitive_threshold_55_to_70():
    c = _base_contract()
    c["district_heating"]["lcoh"]["median"] = 60.0
    c["heat_pumps"]["lcoh"]["median"] = 80.0
    c["monte_carlo"]["dh_wins_fraction"] = 0.60
    r = decide_from_contract(c)
    assert r.choice == "DH"
    assert r.robust is False
    assert "SENSITIVE_DECISION" in r.reason_codes


def test_co2_equal_defaults_to_dh():
    c = _base_contract()
    c["district_heating"]["lcoh"]["median"] = 70.0
    c["heat_pumps"]["lcoh"]["median"] = 71.0  # close
    c["district_heating"]["co2"]["median"] = 100.0
    c["heat_pumps"]["co2"]["median"] = 100.0
    r = decide_from_contract(c)
    assert r.choice == "DH"


def test_robustness_handles_mc_none():
    c = _base_contract()
    c["monte_carlo"] = None
    r = decide_from_contract(c)
    assert "MC_MISSING" in r.reason_codes


# Exhaustive-ish coverage of critical decision paths
DECISION_PATH_TEST_CASES = [
    # --- 1) Feasibility-only paths ---
    ("only_dh_feasible_mc_missing", True, False, 70.0, 80.0, 100.0, 120.0, {}, "DH", ["ONLY_DH_FEASIBLE", "MC_MISSING"]),
    ("only_hp_feasible_mc_missing", False, True, 70.0, 80.0, 100.0, 120.0, {}, "HP", ["ONLY_HP_FEASIBLE", "MC_MISSING"]),
    ("neither_feasible_mc_missing", False, False, 70.0, 80.0, 100.0, 120.0, {}, "UNDECIDED", ["NONE_FEASIBLE", "MC_MISSING"]),

    # --- 2) Cost-dominant paths ---
    ("cost_dominant_dh_robust", True, True, 80.0, 100.0, 100.0, 120.0, {"dh_wins_fraction": 0.80}, "DH", ["COST_DOMINANT_DH", "ROBUST_DECISION"]),
    ("cost_dominant_hp_robust", True, True, 100.0, 80.0, 100.0, 120.0, {"hp_wins_fraction": 0.80}, "HP", ["COST_DOMINANT_HP", "ROBUST_DECISION"]),

    # --- 3) CO₂ tie-breaker paths (costs close) ---
    ("cost_close_co2_dh_robust", True, True, 100.0, 104.0, 90.0, 110.0, {"dh_wins_fraction": 0.80}, "DH", ["COST_CLOSE_USE_CO2", "CO2_TIEBREAKER_DH", "ROBUST_DECISION"]),
    ("cost_close_co2_hp_robust", True, True, 100.0, 104.0, 110.0, 90.0, {"hp_wins_fraction": 0.80}, "HP", ["COST_CLOSE_USE_CO2", "CO2_TIEBREAKER_HP", "ROBUST_DECISION"]),
    ("cost_close_co2_equal_defaults_dh_mc_missing", True, True, 100.0, 104.0, 100.0, 100.0, {}, "DH", ["COST_CLOSE_USE_CO2", "CO2_TIEBREAKER_DH", "MC_MISSING"]),

    # --- 4) Monte Carlo sensitivity paths ---
    ("cost_dominant_dh_sensitive", True, True, 80.0, 100.0, 100.0, 120.0, {"dh_wins_fraction": 0.60}, "DH", ["COST_DOMINANT_DH", "SENSITIVE_DECISION"]),
    ("cost_dominant_hp_sensitive", True, True, 100.0, 80.0, 100.0, 120.0, {"hp_wins_fraction": 0.60}, "HP", ["COST_DOMINANT_HP", "SENSITIVE_DECISION"]),
    ("cost_close_co2_dh_sensitive", True, True, 100.0, 104.0, 90.0, 110.0, {"dh_wins_fraction": 0.60}, "DH", ["COST_CLOSE_USE_CO2", "CO2_TIEBREAKER_DH", "SENSITIVE_DECISION"]),
    ("cost_close_co2_hp_sensitive", True, True, 100.0, 104.0, 110.0, 90.0, {"hp_wins_fraction": 0.60}, "HP", ["COST_CLOSE_USE_CO2", "CO2_TIEBREAKER_HP", "SENSITIVE_DECISION"]),

    # --- 5) MC missing after a non-feasibility decision (still a critical path) ---
    ("cost_dominant_dh_mc_missing", True, True, 80.0, 100.0, 100.0, 120.0, {}, "DH", ["COST_DOMINANT_DH", "MC_MISSING"]),
    ("cost_dominant_hp_mc_missing", True, True, 100.0, 80.0, 100.0, 120.0, {}, "HP", ["COST_DOMINANT_HP", "MC_MISSING"]),
    ("cost_close_co2_dh_mc_missing", True, True, 100.0, 104.0, 90.0, 110.0, {}, "DH", ["COST_CLOSE_USE_CO2", "CO2_TIEBREAKER_DH", "MC_MISSING"]),
    ("cost_close_co2_hp_mc_missing", True, True, 100.0, 104.0, 110.0, 90.0, {}, "HP", ["COST_CLOSE_USE_CO2", "CO2_TIEBREAKER_HP", "MC_MISSING"]),
]


def _contract_for_paths(
    dh_feasible: bool,
    hp_feasible: bool,
    lcoh_dh: float,
    lcoh_hp: float,
    co2_dh: float,
    co2_hp: float,
    mc: dict | None,
) -> dict:
    return {
        "district_heating": {"feasible": dh_feasible, "lcoh": {"median": lcoh_dh}, "co2": {"median": co2_dh}},
        "heat_pumps": {"feasible": hp_feasible, "lcoh": {"median": lcoh_hp}, "co2": {"median": co2_hp}},
        "monte_carlo": mc,
    }


def test_decide_all_paths():
    """
    Covers the critical feasibility/cost/CO₂/robustness/MC-missing branches in one table.
    (We assert expected reasons are present; other reasons may appear depending on the MC block.)
    """
    for (
        name,
        dh_feasible,
        hp_feasible,
        lcoh_dh,
        lcoh_hp,
        co2_dh,
        co2_hp,
        mc,
        expected_choice,
        expected_reasons,
    ) in DECISION_PATH_TEST_CASES:
        c = _contract_for_paths(dh_feasible, hp_feasible, lcoh_dh, lcoh_hp, co2_dh, co2_hp, mc)
        r = decide_from_contract(c)
        assert r.choice == expected_choice, f"{name}: expected {expected_choice}, got {r.choice}"
        for reason in expected_reasons:
            assert reason in r.reason_codes, f"{name}: missing reason {reason} in {r.reason_codes}"

