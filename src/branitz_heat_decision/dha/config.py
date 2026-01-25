from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DHAConfig:
    """
    Configuration for DHA (LV grid hosting analysis for heat pumps).
    """

    # Electrical boundary (Option 2)
    mv_vn_kv: float = 20.0
    lv_vn_kv: float = 0.4
    ext_grid_vm_pu: float = 1.02

    # Transformer defaults (MV/LV)
    trafo_sn_mva: float = 0.63
    trafo_vk_percent: float = 6.0
    trafo_vkr_percent: float = 0.5
    trafo_pfe_kw: float = 1.0
    trafo_i0_percent: float = 0.1
    trafo_vector_group: str = "Dyn"
    trafo_tap_min: int = -2
    trafo_tap_max: int = 2
    trafo_tap_step_percent: float = 2.5
    trafo_tap_pos: int = 0
    trafo_tap_side: str = "hv"

    # Line defaults (fallback when no better metadata exists)
    # These are generic LV cable-like parameters and should be replaced with DSO std-types for real studies.
    line_r_ohm_per_km: float = 0.206
    line_x_ohm_per_km: float = 0.080
    line_c_nf_per_km: float = 210.0
    line_max_i_ka: float = 0.27

    # Mapping
    max_mapping_dist_m: float = 1000.0

    # KPI thresholds
    v_min_pu: float = 0.90
    v_max_pu: float = 1.10
    line_loading_limit_pct: float = 100.0
    trafo_loading_limit_pct: float = 100.0  # Transformer loading limit
    planning_warning_pct: float = 80.0

    # Feeder analysis thresholds
    long_feeder_km_threshold: float = 0.8  # km - threshold for "long feeder" classification

    # Operational control feasibility thresholds
    operational_control_max_fraction: float = 0.2  # 20% of hours - max violation fraction for operational mitigation

    # Severity classification thresholds
    voltage_severe_threshold: float = 0.88  # pu - below this is "severe" undervoltage
    loading_severe_threshold: float = 120.0  # % - above this is "severe" overload


def get_default_config() -> DHAConfig:
    return DHAConfig()
