from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .co2 import compute_co2_dh, compute_co2_hp
from .lcoh import DHInputs, HPInputs, lcoh_dh_crf, lcoh_hp_crf
from .lcoh import compute_lcoh_dh, compute_lcoh_hp
from .params import EconomicParameters, EconomicsParams, MonteCarloParams, apply_multipliers
from .utils import percentile


@dataclass(frozen=True)
class MonteCarloResult:
    samples: List[Dict[str, float]]
    summary: Dict[str, float]


def sample_param(spec: Dict[str, Any], rng: np.random.Generator) -> float:
    """
    Sample a single parameter from a distribution specification.

    Supported distributions:
    - normal: {'dist': 'normal', 'mean': float, 'std': float, 'clip': [min, max]}
    - lognormal: {'dist': 'lognormal', 'mean': float, 'std': float, 'clip': [min, max]}
    - triangular: {'dist': 'triangular', 'low': float, 'mode': float, 'high': float}
    - uniform: {'dist': 'uniform', 'low': float, 'high': float}
    """
    dist_type = spec["dist"]

    if dist_type == "normal":
        value = rng.normal(loc=float(spec["mean"]), scale=float(spec["std"]))
    elif dist_type == "lognormal":
        # Spec follows the user-provided MVP: treat mean/std as for X and approximate sigma for log(X).
        mean = float(spec["mean"])
        std = float(spec["std"])
        mu = float(np.log(mean))
        sigma = float(std / mean) if mean != 0 else 0.0
        value = rng.lognormal(mean=mu, sigma=sigma)
    elif dist_type == "triangular":
        value = rng.triangular(left=float(spec["low"]), mode=float(spec["mode"]), right=float(spec["high"]))
    elif dist_type == "uniform":
        value = rng.uniform(low=float(spec["low"]), high=float(spec["high"]))
    else:
        raise ValueError(f"Unknown distribution type: {dist_type}")

    if "clip" in spec and spec["clip"] is not None:
        min_val, max_val = spec["clip"]
        value = float(np.clip(value, float(min_val), float(max_val)))

    return float(value)


def run_monte_carlo(
    *,
    dh_inputs: DHInputs,
    hp_inputs: HPInputs,
    base_params: EconomicsParams,
    mc: MonteCarloParams,
) -> MonteCarloResult:
    """
    Monte Carlo simulation (MVP): bounded ranges on a small set of parameters.
    Note: `sample_param` enables spec-driven sampling; we keep the current bounded sampling
    via `MonteCarloParams` for backwards-compat and migrate progressively.
    Returns both per-sample values and a compact summary (median + P10/P90 + robustness).
    """
    logger = logging.getLogger(__name__)
    rng = np.random.default_rng(int(mc.seed))
    samples: List[Dict[str, float]] = []

    for _ in range(int(mc.n)):
        capex_mult = float(rng.uniform(mc.capex_mult_min, mc.capex_mult_max))
        elec_price_mult = float(rng.uniform(mc.elec_price_mult_min, mc.elec_price_mult_max))
        fuel_price_mult = float(rng.uniform(mc.fuel_price_mult_min, mc.fuel_price_mult_max))
        grid_co2_mult = float(rng.uniform(mc.grid_co2_mult_min, mc.grid_co2_mult_max))
        hp_cop = float(rng.uniform(mc.hp_cop_min, mc.hp_cop_max))
        discount_rate = float(rng.uniform(mc.discount_rate_min, mc.discount_rate_max))

        p = apply_multipliers(
            base_params,
            capex_mult=capex_mult,
            elec_price_mult=elec_price_mult,
            fuel_price_mult=fuel_price_mult,
            grid_co2_mult=grid_co2_mult,
            hp_cop=hp_cop,
            discount_rate=discount_rate,
        )

        l_dh = lcoh_dh_crf(dh_inputs, p)
        l_hp = lcoh_hp_crf(hp_inputs, p)
        # Annual totals in t/a derived from specific kg/MWh and annual MWh.
        c_dh_kg_per_mwh, c_dh_br = compute_co2_dh(dh_inputs.heat_mwh_per_year, params=p)
        c_hp_kg_per_mwh, c_hp_br = compute_co2_hp(hp_inputs.heat_mwh_per_year, cop_annual_average=p.cop_default, params=p)
        c_dh = float(c_dh_br["annual_co2_kg"]) / 1000.0
        c_hp = float(c_hp_br["annual_co2_kg"]) / 1000.0

        samples.append(
            {
                "lcoh_dh_eur_per_mwh": float(l_dh),
                "lcoh_hp_eur_per_mwh": float(l_hp),
                "co2_dh_t_per_a": float(c_dh),
                "co2_hp_t_per_a": float(c_hp),
                "co2_dh_kg_per_mwh": float(c_dh_kg_per_mwh),
                "co2_hp_kg_per_mwh": float(c_hp_kg_per_mwh),
                "capex_mult": float(capex_mult),
                "elec_price_mult": float(elec_price_mult),
                "fuel_price_mult": float(fuel_price_mult),
                "grid_co2_mult": float(grid_co2_mult),
                "hp_cop": float(hp_cop),
                "discount_rate": float(discount_rate),
            }
        )

    l_dh_vals = [s["lcoh_dh_eur_per_mwh"] for s in samples]
    l_hp_vals = [s["lcoh_hp_eur_per_mwh"] for s in samples]
    c_dh_vals = [s["co2_dh_t_per_a"] for s in samples]
    c_hp_vals = [s["co2_hp_t_per_a"] for s in samples]

    prob_dh_cheaper = sum(1 for s in samples if s["lcoh_dh_eur_per_mwh"] < s["lcoh_hp_eur_per_mwh"]) / max(
        1, len(samples)
    )
    prob_dh_lower_co2 = sum(1 for s in samples if s["co2_dh_t_per_a"] < s["co2_hp_t_per_a"]) / max(1, len(samples))

    summary = {
        "n": float(len(samples)),
        "prob_dh_cheaper": float(prob_dh_cheaper),
        "prob_dh_lower_co2": float(prob_dh_lower_co2),
        "lcoh_dh_p10": percentile(l_dh_vals, 0.10),
        "lcoh_dh_p50": percentile(l_dh_vals, 0.50),
        "lcoh_dh_p90": percentile(l_dh_vals, 0.90),
        "lcoh_hp_p10": percentile(l_hp_vals, 0.10),
        "lcoh_hp_p50": percentile(l_hp_vals, 0.50),
        "lcoh_hp_p90": percentile(l_hp_vals, 0.90),
        "co2_dh_p10": percentile(c_dh_vals, 0.10),
        "co2_dh_p50": percentile(c_dh_vals, 0.50),
        "co2_dh_p90": percentile(c_dh_vals, 0.90),
        "co2_hp_p10": percentile(c_hp_vals, 0.10),
        "co2_hp_p50": percentile(c_hp_vals, 0.50),
        "co2_hp_p90": percentile(c_hp_vals, 0.90),
    }

    return MonteCarloResult(samples=samples, summary=summary)


def _tqdm(iterable, **kwargs):
    """Optional tqdm wrapper (tqdm may not be installed)."""
    try:
        from tqdm import tqdm  # type: ignore

        return tqdm(iterable, **kwargs)
    except Exception:
        return iterable


def _extract_mc_inputs_from_kpis(
    *,
    cha_kpis: Dict[str, Any],
    dha_kpis: Dict[str, Any],
    cluster_summary: Dict[str, float],
) -> Tuple[float, float, Optional[Dict[str, float]], float, float, float]:
    """
    Returns:
      total_length_m, pump_power_kw, pipe_dn_lengths_or_none, hp_capacity_kw, max_loading_pct, annual_heat_mwh
    """
    # Annual heat
    if "annual_heat_mwh" not in cluster_summary:
        raise KeyError("cluster_summary['annual_heat_mwh']")
    annual_heat_mwh = float(cluster_summary["annual_heat_mwh"])

    # DH (CHA) - support both the user-proposed schema and our current output schema.
    # Preferred user schema:
    #   cha_kpis['network']['total_length_m'], cha_kpis['network']['pump_power_kw'], cha_kpis['network'].get('pipe_dn_lengths')
    # Our current schema:
    #   cha_kpis['losses']['length_total_m'] (or aggregate.length_total_m)
    #   cha_kpis['pump']['pump_power_kw']
    if "network" in cha_kpis:
        total_length_m = float(cha_kpis["network"]["total_length_m"])
        pump_power_kw = float(cha_kpis["network"]["pump_power_kw"])
        pipe_dn_lengths = cha_kpis["network"].get("pipe_dn_lengths")
        pipe_dn_lengths = {str(k): float(v) for k, v in (pipe_dn_lengths or {}).items()} or None
    else:
        blk = cha_kpis.get("losses") or cha_kpis.get("aggregate") or {}
        total_length_m = float(blk.get("length_total_m", 0.0))
        pump_power_kw = float((cha_kpis.get("pump") or {}).get("pump_power_kw", 0.0))
        pipe_dn_lengths = None

    # HP (DHA) - support both schemas.
    # Preferred user schema:
    #   dha_kpis['hp_system']['hp_total_kw_design'], dha_kpis['lv_grid']['max_feeder_loading_pct']
    # Our current schema:
    #   dha_kpis['kpis']['max_feeder_loading_pct'] and design load from cluster_summary['design_load_kw']
    if "hp_system" in dha_kpis and "lv_grid" in dha_kpis:
        hp_capacity_kw = float(dha_kpis["hp_system"]["hp_total_kw_design"])
        max_loading_pct = float(dha_kpis["lv_grid"]["max_feeder_loading_pct"])
    else:
        max_loading_pct = float((dha_kpis.get("kpis") or {}).get("max_feeder_loading_pct", 0.0))
        if "design_load_kw" in cluster_summary:
            hp_capacity_kw = float(cluster_summary["design_load_kw"])
        else:
            # fallback: not ideal, but keeps function usable
            hp_capacity_kw = 0.0

    return total_length_m, pump_power_kw, pipe_dn_lengths, hp_capacity_kw, max_loading_pct, annual_heat_mwh


def _run_one_sample_for_cluster(
    *,
    sample_id: int,
    seed_i: int,
    randomness_config: Dict[str, Any],
    base_params: EconomicParameters,
    annual_heat_mwh: float,
    total_length_m: float,
    pump_power_kw: float,
    pipe_dn_lengths: Optional[Dict[str, float]],
    hp_capacity_kw: float,
    max_loading_pct: float,
) -> Dict[str, Any]:
    logger = logging.getLogger(__name__)
    rng_i = np.random.default_rng(int(seed_i))

    sampled_params: Dict[str, float] = {}
    for param_name, spec in randomness_config.items():
        sampled_params[param_name] = sample_param(spec, rng_i)

    p = base_params
    sample_params = EconomicParameters(
        # Override base params with sampled values
        discount_rate=float(sampled_params.get("discount_rate", p.discount_rate)),
        electricity_price_eur_per_mwh=float(sampled_params.get("electricity_price", p.electricity_price_eur_per_mwh)),
        gas_price_eur_per_mwh=float(sampled_params.get("gas_price", p.gas_price_eur_per_mwh)),
        ef_electricity_kg_per_mwh=float(sampled_params.get("ef_electricity", p.ef_electricity_kg_per_mwh)),
        cop_default=float(sampled_params.get("cop", p.cop_default)),
        # Keep base for everything else
        lifetime_years=p.lifetime_years,
        biomass_price_eur_per_mwh=p.biomass_price_eur_per_mwh,
        ef_gas_kg_per_mwh=p.ef_gas_kg_per_mwh,
        ef_biomass_kg_per_mwh=p.ef_biomass_kg_per_mwh,
        dh_generation_type=p.dh_generation_type,
        pipe_cost_eur_per_m=dict(p.pipe_cost_eur_per_m),
        plant_cost_base_eur=p.plant_cost_base_eur,
        pump_cost_per_kw=p.pump_cost_per_kw,
        hp_cost_eur_per_kw_th=p.hp_cost_eur_per_kw_th,
        lv_upgrade_cost_eur_per_kw_el=p.lv_upgrade_cost_eur_per_kw_el,
        dh_om_frac_per_year=p.dh_om_frac_per_year,
        hp_om_frac_per_year=p.hp_om_frac_per_year,
        feeder_loading_planning_limit=p.feeder_loading_planning_limit,
    )

    pipe_cost_adj = float(sampled_params.get("pipe_cost_multiplier", 1.0))
    if abs(pipe_cost_adj - 1.0) > 1e-12:
        sample_params = EconomicParameters(
            **{
                **sample_params.__dict__,
                "pipe_cost_eur_per_m": {dn: float(cost) * pipe_cost_adj for dn, cost in p.pipe_cost_eur_per_m.items()},
            }
        )

    try:
        lcoh_dh, _ = compute_lcoh_dh(
            annual_heat_mwh=annual_heat_mwh,
            pipe_lengths_by_dn=pipe_dn_lengths,
            total_pipe_length_m=total_length_m,
            pump_power_kw=pump_power_kw,
            params=sample_params,
        )
    except Exception as e:
        logger.debug("Sample %d: DH LCOH failed: %s", sample_id, e)
        lcoh_dh = float("nan")

    try:
        lcoh_hp, _ = compute_lcoh_hp(
            annual_heat_mwh=annual_heat_mwh,
            hp_total_capacity_kw_th=hp_capacity_kw,
            cop_annual_average=sample_params.cop_default,
            max_feeder_loading_pct=max_loading_pct,
            params=sample_params,
        )
    except Exception as e:
        logger.debug("Sample %d: HP LCOH failed: %s", sample_id, e)
        lcoh_hp = float("nan")

    try:
        co2_dh, _ = compute_co2_dh(annual_heat_mwh=annual_heat_mwh, params=sample_params)
    except Exception as e:
        logger.debug("Sample %d: DH CO2 failed: %s", sample_id, e)
        co2_dh = float("nan")

    try:
        co2_hp, _ = compute_co2_hp(annual_heat_mwh=annual_heat_mwh, cop_annual_average=sample_params.cop_default, params=sample_params)
    except Exception as e:
        logger.debug("Sample %d: HP CO2 failed: %s", sample_id, e)
        co2_hp = float("nan")

    dh_cheaper = bool(np.isfinite(lcoh_dh) and np.isfinite(lcoh_hp) and (lcoh_dh < lcoh_hp))
    dh_lower_co2 = bool(np.isfinite(co2_dh) and np.isfinite(co2_hp) and (co2_dh < co2_hp))

    result: Dict[str, Any] = {
        "sample_id": int(sample_id),
        "lcoh_dh": float(lcoh_dh),
        "lcoh_hp": float(lcoh_hp),
        "co2_dh": float(co2_dh),
        "co2_hp": float(co2_hp),
        "dh_cheaper": dh_cheaper,
        "dh_lower_co2": dh_lower_co2,
    }
    for k, v in sampled_params.items():
        result[f"param_{k}"] = float(v)
    return result


def run_monte_carlo_for_cluster(
    cluster_id: str,
    cha_kpis: Dict[str, Any],
    dha_kpis: Dict[str, Any],
    cluster_summary: Dict[str, float],
    n_samples: int = 500,
    randomness_config: Optional[Dict[str, Any]] = None,
    base_params: Optional[EconomicParameters] = None,
    seed: int = 42,
    n_jobs: int = 1,
):
    """
    Run Monte Carlo simulation for a single cluster.

    Returns a pandas DataFrame with columns:
    - sample_id, lcoh_dh, lcoh_hp, co2_dh, co2_hp
    - dh_cheaper, dh_lower_co2
    - param_* for sampled parameters
    """
    import pandas as pd

    logger = logging.getLogger(__name__)
    logger.info("Starting Monte Carlo for %s: %d samples, seed=%d", cluster_id, int(n_samples), int(seed))

    params = base_params if base_params is not None else EconomicParameters()
    rng = np.random.default_rng(int(seed))

    if randomness_config is None:
        randomness_config = {
            "discount_rate": {"dist": "normal", "mean": 0.04, "std": 0.01, "clip": [0.01, 0.08]},
            "electricity_price": {"dist": "normal", "mean": 250.0, "std": 50.0, "clip": [150, 400]},
            "gas_price": {"dist": "triangular", "low": 40, "mode": 80, "high": 140},
            "pipe_cost_multiplier": {"dist": "triangular", "low": 0.8, "mode": 1.0, "high": 1.2},
            "cop": {"dist": "normal", "mean": 2.8, "std": 0.3, "clip": [2.0, 4.0]},
            "ef_electricity": {"dist": "normal", "mean": 350.0, "std": 80.0, "clip": [200, 500]},
        }

    total_length_m, pump_power_kw, pipe_dn_lengths, hp_capacity_kw, max_loading_pct, annual_heat_mwh = (
        _extract_mc_inputs_from_kpis(cha_kpis=cha_kpis, dha_kpis=dha_kpis, cluster_summary=cluster_summary)
    )

    # Deterministic per-sample seeds (so parallel mode stays reproducible)
    seeds = rng.integers(low=0, high=2**31 - 1, size=int(n_samples), dtype=np.int64).tolist()

    results: List[Dict[str, Any]] = []
    if int(n_jobs) == 1:
        for sample_id in _tqdm(range(int(n_samples)), desc=f"MC: {cluster_id}", unit="sample"):
            results.append(
                _run_one_sample_for_cluster(
                    sample_id=sample_id,
                    seed_i=int(seeds[sample_id]),
                    randomness_config=randomness_config,
                    base_params=params,
                    annual_heat_mwh=annual_heat_mwh,
                    total_length_m=total_length_m,
                    pump_power_kw=pump_power_kw,
                    pipe_dn_lengths=pipe_dn_lengths,
                    hp_capacity_kw=hp_capacity_kw,
                    max_loading_pct=max_loading_pct,
                )
            )
    else:
        # Parallel processing (simple; progress bar may be less informative)
        import os
        import multiprocessing as mp
        from concurrent.futures import ProcessPoolExecutor, as_completed

        max_workers = None if int(n_jobs) == -1 else int(n_jobs)
        if max_workers is None:
            max_workers = os.cpu_count() or 1
        # macOS spawn + <stdin> breaks; prefer fork context when available.
        try:
            ctx = mp.get_context("fork")
            ex_kwargs = {"mp_context": ctx}
        except Exception:
            ex_kwargs = {}

        with ProcessPoolExecutor(max_workers=max_workers, **ex_kwargs) as ex:
            futs = [
                ex.submit(
                    _run_one_sample_for_cluster,
                    sample_id=i,
                    seed_i=int(seeds[i]),
                    randomness_config=randomness_config,
                    base_params=params,
                    annual_heat_mwh=annual_heat_mwh,
                    total_length_m=total_length_m,
                    pump_power_kw=pump_power_kw,
                    pipe_dn_lengths=pipe_dn_lengths,
                    hp_capacity_kw=hp_capacity_kw,
                    max_loading_pct=max_loading_pct,
                )
                for i in range(int(n_samples))
            ]
            for fut in _tqdm(as_completed(futs), total=int(n_samples), desc=f"MC: {cluster_id}", unit="sample"):
                results.append(fut.result())

        # restore ordering
        results.sort(key=lambda d: d["sample_id"])

    df = pd.DataFrame(results)
    return df


def compute_mc_summary(mc_results) -> Dict[str, Any]:
    """
    Compute summary statistics from Monte Carlo results DataFrame.

    Returns a dict with:
    - lcoh/co2 p05/p50/p95/mean/std for dh and hp
    - win fractions
    - n_samples, n_valid
    """
    import pandas as pd

    logger = logging.getLogger(__name__)
    logger.info("Computing MC summary statistics")

    if not isinstance(mc_results, pd.DataFrame):
        raise TypeError("mc_results must be a pandas DataFrame")

    valid = mc_results.dropna(subset=["lcoh_dh", "lcoh_hp", "co2_dh", "co2_hp"])
    n_valid = int(len(valid))
    n_total = int(len(mc_results))

    if n_valid == 0:
        logger.error("No valid samples for summary statistics")
        raise ValueError("Monte Carlo produced no valid results")

    if n_valid < n_total:
        logger.warning("Only %d/%d samples were valid", n_valid, n_total)

    lcoh_stats: Dict[str, Dict[str, float]] = {}
    for system in ["dh", "hp"]:
        col = f"lcoh_{system}"
        if col in valid.columns:
            lcoh_stats[system] = {
                "p05": float(valid[col].quantile(0.05)),
                "p50": float(valid[col].median()),
                "p95": float(valid[col].quantile(0.95)),
                "mean": float(valid[col].mean()),
                "std": float(valid[col].std()),
            }
        else:
            lcoh_stats[system] = {k: float("nan") for k in ["p05", "p50", "p95", "mean", "std"]}

    co2_stats: Dict[str, Dict[str, float]] = {}
    for system in ["dh", "hp"]:
        col = f"co2_{system}"
        if col in valid.columns:
            co2_stats[system] = {
                "p05": float(valid[col].quantile(0.05)),
                "p50": float(valid[col].median()),
                "p95": float(valid[col].quantile(0.95)),
                "mean": float(valid[col].mean()),
                "std": float(valid[col].std()),
            }
        else:
            co2_stats[system] = {k: float("nan") for k in ["p05", "p50", "p95", "mean", "std"]}

    dh_cheaper_fraction = float(valid["dh_cheaper"].mean()) if "dh_cheaper" in valid.columns else float("nan")
    dh_lower_co2_fraction = float(valid["dh_lower_co2"].mean()) if "dh_lower_co2" in valid.columns else float("nan")

    summary: Dict[str, Any] = {
        "lcoh": {"dh": lcoh_stats["dh"], "hp": lcoh_stats["hp"]},
        "co2": {"dh": co2_stats["dh"], "hp": co2_stats["hp"]},
        "monte_carlo": {
            "dh_wins_fraction": float(dh_cheaper_fraction),
            "hp_wins_fraction": float(1.0 - dh_cheaper_fraction) if np.isfinite(dh_cheaper_fraction) else float("nan"),
            "dh_wins_co2_fraction": float(dh_lower_co2_fraction),
            "hp_wins_co2_fraction": float(1.0 - dh_lower_co2_fraction)
            if np.isfinite(dh_lower_co2_fraction)
            else float("nan"),
            "n_samples": n_total,
            "n_valid": n_valid,
        },
    }

    logger.info("MC Summary: DH wins %.1f%% (cost), %.1f%% (CO2)", dh_cheaper_fraction * 100.0, dh_lower_co2_fraction * 100.0)
    return summary

