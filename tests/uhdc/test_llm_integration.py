import importlib

import pytest


def test_llm_ready_reflects_key_and_force_template(monkeypatch):
    """
    This is a *local* integration sanity check for env wiring.
    It does NOT call the external Gemini API.
    """
    # Ensure a clean import state
    import branitz_heat_decision.uhdc.explainer as explainer

    # If the SDK isn't installed in this environment, we can't assert "ready"
    if not getattr(explainer, "LLM_AVAILABLE", False):
        pytest.skip("google-genai SDK not installed in this environment")

    # Case 1: key present, not forced -> ready
    monkeypatch.setenv("GOOGLE_API_KEY", "fake_key_for_test")
    monkeypatch.setenv("UHDC_FORCE_TEMPLATE", "false")
    explainer = importlib.reload(explainer)
    assert explainer.GOOGLE_API_KEY == "fake_key_for_test"
    assert explainer.UHDC_FORCE_TEMPLATE is False
    assert explainer.LLM_READY is True

    # Case 2: forced template -> not ready
    monkeypatch.setenv("UHDC_FORCE_TEMPLATE", "true")
    explainer = importlib.reload(explainer)
    assert explainer.UHDC_FORCE_TEMPLATE is True
    assert explainer.LLM_READY is False

    # Case 3: "missing" key -> not ready
    #
    # Important: this repo may have a real `.env` present on disk, and the explainer
    # loads it on import (override=False). To make this test deterministic and avoid
    # relying on local files, we set the placeholder value explicitly, which the
    # explainer treats as "missing".
    monkeypatch.setenv("GOOGLE_API_KEY", "YOUR_ACTUAL_API_KEY_HERE")
    monkeypatch.setenv("UHDC_FORCE_TEMPLATE", "false")
    explainer = importlib.reload(explainer)
    assert explainer.GOOGLE_API_KEY is None
    assert explainer.LLM_READY is False

