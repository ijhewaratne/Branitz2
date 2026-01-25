from __future__ import annotations

import pytest

from branitz_heat_decision.uhdc.explainer import _validate_explanation_safety, _fallback_template_explanation


def _contract_and_decision():
    contract = {
        "cluster_id": "ST_TEST",
        "district_heating": {
            "feasible": True,
            "lcoh": {"median": 70.0, "p05": 60.0, "p95": 90.0},
            "co2": {"median": 80.0, "p05": 60.0, "p95": 120.0},
            "hydraulics": {"v_max_ms": 1.2},
            "losses": {"pump_power_kw": 10.0},
        },
        "heat_pumps": {
            "feasible": True,
            "lcoh": {"median": 75.0, "p05": 65.0, "p95": 110.0},
            "co2": {"median": 120.0, "p05": 90.0, "p95": 200.0},
            "lv_grid": {"max_feeder_loading_pct": 80.0, "voltage_violations_total": 0},
        },
        "monte_carlo": {"dh_wins_fraction": 0.6, "hp_wins_fraction": 0.4},
    }
    decision = {"choice": "DH", "robust": False, "reason_codes": ["COST_DOMINANT_DH"]}
    return contract, decision


def test_fallback_template_is_safe_and_validates():
    contract, decision = _contract_and_decision()
    explanation = _fallback_template_explanation(contract, decision, style="executive")
    _validate_explanation_safety(explanation, contract, decision)


def test_validate_explanation_safety_rejects_hallucinated_number():
    contract, decision = _contract_and_decision()
    explanation = "District heating is recommended. LCOH is 999 €/MWh. EN 13941-1."
    with pytest.raises(ValueError, match="hallucination"):
        _validate_explanation_safety(explanation, contract, decision)


def test_llm_safety_allows_rounding():
    """
    The LLM (or templates) may round values (e.g., 85.5 → 86).
    Our safety validator should allow this within the configured tolerance / rounding policy.
    """
    contract = {
        "cluster_id": "ST_TEST",
        "district_heating": {
            "feasible": True,
            "lcoh": {"median": 85.5},
            "co2": {"median": 98.3},
            "hydraulics": {},
            "losses": {},
        },
        "heat_pumps": {
            "feasible": True,
            "lcoh": {"median": 92.3},
            "co2": {"median": 126.0},
            "lv_grid": {},
        },
        "monte_carlo": {},
    }
    decision = {"choice": "DH", "robust": True, "reason_codes": ["COST_DOMINANT_DH"]}

    # Rounded/pretty-printed numbers (should still validate)
    explanation = (
        "District heating (DH) is recommended. "
        "DH LCOH is 86 €/MWh and CO₂ is 98 kg/MWh, while HP LCOH is 92 €/MWh and CO₂ is 126 kg/MWh. "
        "This aligns with EN 13941-1."
    )
    _validate_explanation_safety(explanation, contract, decision)

