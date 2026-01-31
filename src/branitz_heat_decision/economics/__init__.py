"""
Economics module (Phase 4):
- LCOH via CRF method
- CO2 emissions
- Monte Carlo uncertainty propagation
"""

from .integration import (
    build_pipe_network_results_for_cluster,
    get_trunk_connection_length_m,
)
from .params import (
    EconomicParameters,
    EconomicsParams,
    MonteCarloParams,
    get_default_economics_params,
    get_default_monte_carlo_params,
    load_default_params,
    load_params_from_yaml,
)
from .lcoh import (
    DHInputs,
    HPInputs,
    PlantContext,
    build_plant_context_from_params,
    compute_lcoh_dh,
    compute_lcoh_dh_for_cluster,
    compute_lcoh_district_aggregate,
    compute_lcoh_hp,
    lcoh_dh_crf,
    lcoh_hp_crf,
)
from .co2 import compute_co2_dh, compute_co2_hp, co2_dh, co2_hp
from .monte_carlo import compute_mc_summary, run_monte_carlo, run_monte_carlo_for_cluster

__all__ = [
    "build_pipe_network_results_for_cluster",
    "get_trunk_connection_length_m",
    "EconomicParameters",
    "EconomicsParams",
    "MonteCarloParams",
    "PlantContext",
    "build_plant_context_from_params",
    "compute_lcoh_dh_for_cluster",
    "compute_lcoh_district_aggregate",
    "get_default_economics_params",
    "get_default_monte_carlo_params",
    "load_default_params",
    "load_params_from_yaml",
    "DHInputs",
    "HPInputs",
    "compute_lcoh_dh",
    "compute_lcoh_hp",
    "lcoh_dh_crf",
    "lcoh_hp_crf",
    "compute_co2_dh",
    "compute_co2_hp",
    "co2_dh",
    "co2_hp",
    "run_monte_carlo",
    "run_monte_carlo_for_cluster",
    "compute_mc_summary",
]

