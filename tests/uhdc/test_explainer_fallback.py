from __future__ import annotations

import re
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from branitz_heat_decision.uhdc import explainer as expl


def _contract_and_decision():
    contract = {
        "cluster_id": "ST_TEST",
        "district_heating": {
            "feasible": True,
            "reasons": ["DH_OK"],
            "lcoh": {"median": 72.0, "p05": 60.0, "p95": 90.0},
            "co2": {"median": 98.0, "p05": 60.0, "p95": 120.0},
            "hydraulics": {"v_max_ms": 1.2, "v_share_within_limits": 0.98, "dp_ok": True},
            "losses": {"loss_share_pct": 3.0, "pump_power_kw": 10.0},
        },
        "heat_pumps": {
            "feasible": False,
            "reasons": ["HP_UNDERVOLTAGE"],
            "lcoh": {"median": 79.0, "p05": 65.0, "p95": 110.0},
            "co2": {"median": 126.0, "p05": 90.0, "p95": 200.0},
            "lv_grid": {"max_feeder_loading_pct": 219.96, "voltage_violations_total": 3, "planning_warning": True},
        },
        "monte_carlo": {"dh_wins_fraction": 0.90, "hp_wins_fraction": 0.10, "n_samples": 500},
    }
    decision = {"choice": "DH", "robust": True, "reason_codes": ["ONLY_DH_FEASIBLE", "ROBUST_DECISION"]}
    return contract, decision


@pytest.mark.skipif(not expl.LLM_AVAILABLE, reason="google-genai SDK not installed in environment")
def test_llm_fallback_on_api_error():
    """Simulate API down → explain_with_llm() returns fallback template output."""
    contract, decision = _contract_and_decision()

    class _BoomClient:
        def __init__(self):
            self.models = self

        def generate_content(self, *args, **kwargs):
            raise Exception("API quota exceeded")

    with patch("branitz_heat_decision.uhdc.explainer.genai.Client", return_value=_BoomClient()):
        explanation = expl.explain_with_llm(contract, decision, style="executive")

    # Should be a readable template explanation (not an exception)
    assert "recommended" in explanation.lower()
    assert "lcoh" in explanation.lower()
    # Must be safe according to validator (no hallucinated numbers)
    expl._validate_explanation_safety(explanation, contract, decision)


@pytest.mark.skipif(not expl.LLM_AVAILABLE, reason="google-genai SDK not installed in environment")
def test_llm_fallback_on_hallucination():
    """Simulate LLM hallucinating a number → safety check triggers fallback."""
    contract, decision = _contract_and_decision()

    hallucinated_text = "District heating is recommended. LCOH is 999 €/MWh. EN 13941-1."

    class _OkClient:
        def __init__(self):
            self.models = self

        def generate_content(self, *args, **kwargs):
            return SimpleNamespace(text=hallucinated_text)

    with patch("branitz_heat_decision.uhdc.explainer.genai.Client", return_value=_OkClient()):
        explanation = expl.explain_with_llm(contract, decision, style="executive")

    # If fallback happened, the hallucinated value should not be present.
    assert "999" not in explanation
    expl._validate_explanation_safety(explanation, contract, decision)


def test_all_template_styles_use_only_contract_data():
    """Ensure all 3 style templates are safe (no hallucinated numbers)."""
    contract, decision = _contract_and_decision()

    # Allow contract numbers plus traceable derived values templates may mention.
    allowed = {
        # LCOH medians / quantiles
        72.0, 60.0, 90.0,
        79.0, 65.0, 110.0,
        # CO2 medians / quantiles
        98.0, 60.0, 120.0,
        126.0, 90.0, 200.0,
        # Other contract metrics
        219.96, 10.0, 1.2, 3.0,
        # Derived
        7.0,  # abs(79-72) shown as LCOH difference in executive template
        9.7,  # relative difference % (rounded) used in detailed template
    }

    for style in ["executive", "technical", "detailed"]:
        explanation = expl._fallback_template_explanation(contract, decision, style=style)
        expl._validate_explanation_safety(explanation, contract, decision)

        # Additionally: verify we didn't introduce any extra floating-point numbers.
        numbers = {float(n) for n in re.findall(r"\d+\.\d+", explanation)}
        extra = numbers - allowed
        assert not extra, f"Style {style} hallucinated numbers: {sorted(extra)}"


def test_llm_fallback_on_missing_kpis():
    """
    Pass incomplete contract → safe template without crashing.
    This covers checklist item: LLM fallback on missing KPIs.
    """
    incomplete_contract = {
        "cluster_id": "ST_MISSING",
        "district_heating": {"lcoh": {"median": 75.0}, "co2": {"median": 120.0}},
        "heat_pumps": {"lcoh": {"median": 85.0}, "co2": {"median": 100.0}},
    }
    decision = {"choice": "UNDECIDED", "robust": False, "reason_codes": ["CHA_MISSING_KPIS"]}

    # Should not raise, should return safe template
    explanation = expl.explain_with_llm(incomplete_contract, decision, style="executive", no_fallback=False)
    assert "data incomplete" in explanation.lower()
    assert "€/MWh" in explanation

