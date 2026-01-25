from __future__ import annotations

import pytest

from branitz_heat_decision.decision.rules import validate_config


def test_valid_config_passes():
    cfg = {"robust_win_fraction": 0.8, "sensitive_win_fraction": 0.6}
    validated = validate_config(cfg)
    assert validated["robust_win_fraction"] == 0.8
    assert validated["sensitive_win_fraction"] == 0.6


def test_robust_out_of_range():
    with pytest.raises(ValueError, match="robust_win_fraction must be in"):
        validate_config({"robust_win_fraction": 1.5})


def test_sensitive_greater_than_robust():
    with pytest.raises(ValueError, match="sensitive_win_fraction"):
        validate_config({"robust_win_fraction": 0.6, "sensitive_win_fraction": 0.7})


def test_negative_abs_threshold():
    with pytest.raises(ValueError, match="close_cost_abs_threshold must be positive"):
        validate_config({"close_cost_abs_threshold": -5.0})


def test_non_dict_config():
    with pytest.raises(TypeError, match="Config must be a dict"):
        validate_config([1, 2, 3])  # type: ignore[arg-type]

