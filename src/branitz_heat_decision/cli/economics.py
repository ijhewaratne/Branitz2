from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd

# ---------------------------------------------------------------------
# Imports with fallback (repo is not installed as a package by default)
# ---------------------------------------------------------------------
try:
    from ..economics.params import EconomicParameters, load_params_from_yaml
    from ..economics.monte_carlo import run_monte_carlo_for_cluster, compute_mc_summary
    from ..config import BUILDING_CLUSTER_MAP_PATH, HOURLY_PROFILES_PATH, DESIGN_TOPN_PATH
except Exception:
    # Fallback for direct execution when src/ isn't on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from branitz_heat_decision.economics.params import EconomicParameters, load_params_from_yaml
    from branitz_heat_decision.economics.monte_carlo import run_monte_carlo_for_cluster, compute_mc_summary
    from branitz_heat_decision.config import BUILDING_CLUSTER_MAP_PATH, HOURLY_PROFILES_PATH, DESIGN_TOPN_PATH


logger = logging.getLogger(__name__)


def _compute_cluster_summary_fallback(cluster_id: str) -> Dict[str, float]:
    """
    Fallback when cluster_load_summary.parquet doesn't contain the cluster_id.
    Computes:
    - annual_heat_mwh from hourly profiles for buildings in building_cluster_map
    - design_load_kw from design hour in cluster_design_topn.json
    """
    bcm = pd.read_parquet(BUILDING_CLUSTER_MAP_PATH)
    bcm["cluster_id"] = bcm["cluster_id"].astype(str).str.strip()
    b = bcm[bcm["cluster_id"] == str(cluster_id).strip()]
    if len(b) == 0:
        raise ValueError(f"Cluster {cluster_id} not found in building_cluster_map: {BUILDING_CLUSTER_MAP_PATH}")

    building_ids = set(b["building_id"].astype(str).tolist())
    prof = pd.read_parquet(HOURLY_PROFILES_PATH)
    cols = [c for c in prof.columns if str(c) in building_ids]
    if not cols:
        raise ValueError(f"No hourly heat profile columns match cluster buildings for {cluster_id}.")

    # annual heat: sum(kW over hours)=kWh, then /1000 => MWh
    annual_heat_mwh = float(prof[cols].sum(axis=1).sum()) / 1000.0

    topn = json.loads(Path(DESIGN_TOPN_PATH).read_text(encoding="utf-8"))
    design_hour = int(topn["clusters"][cluster_id]["design_hour"])
    design_load_kw = float(prof.loc[design_hour, cols].sum())

    return {"annual_heat_mwh": annual_heat_mwh, "design_load_kw": design_load_kw}


def run_economics_for_cluster(
    cluster_id: str,
    cha_kpis_path: Path,
    dha_kpis_path: Path,
    cluster_summary_path: Path,
    output_dir: Path,
    n_samples: int = 500,
    seed: int = 42,
    scenario_file: Optional[Path] = None,
    randomness_config_file: Optional[Path] = None,
    quiet: bool = False,
    n_jobs: int = 1,
) -> dict:
    """
    Run full economics pipeline for a cluster:
    - load parameters (default or YAML scenario)
    - load CHA/DHA KPIs
    - load cluster summary row
    - run Monte Carlo
    - compute summary stats
    - save samples + summary
    """
    log_level = logging.WARNING if quiet else logging.INFO
    logger.setLevel(log_level)

    logger.info("=== Economics Pipeline for %s ===", cluster_id)
    logger.info("Parameters: n_samples=%d, seed=%d", int(n_samples), int(seed))

    # 1) Output dir
    output_dir.mkdir(parents=True, exist_ok=True)

    # 2) Params
    if scenario_file:
        if not scenario_file.exists():
            raise FileNotFoundError(f"Scenario file not found: {scenario_file}")
        params = load_params_from_yaml(str(scenario_file))
        logger.info("✓ Loaded scenario from %s", scenario_file.name)
    else:
        params = EconomicParameters()
        logger.info("✓ Using default economic parameters")

    # 3) randomness config
    if randomness_config_file:
        if not randomness_config_file.exists():
            raise FileNotFoundError(f"Randomness config file not found: {randomness_config_file}")
        randomness_config = json.loads(randomness_config_file.read_text(encoding="utf-8"))
        logger.info("✓ Loaded randomness config from %s", randomness_config_file.name)
    else:
        randomness_config = None
        logger.info("✓ Using default randomness configuration")

    # 4) Load inputs
    if not cha_kpis_path.exists():
        raise FileNotFoundError(f"CHA KPI file not found: {cha_kpis_path}")
    if not dha_kpis_path.exists():
        raise FileNotFoundError(f"DHA KPI file not found: {dha_kpis_path}")
    if not cluster_summary_path.exists():
        raise FileNotFoundError(f"Cluster summary file not found: {cluster_summary_path}")

    cha_kpis = json.loads(cha_kpis_path.read_text(encoding="utf-8"))
    dha_kpis = json.loads(dha_kpis_path.read_text(encoding="utf-8"))

    summary_df = pd.read_parquet(cluster_summary_path)
    if "cluster_id" not in summary_df.columns:
        raise ValueError("Invalid cluster summary format: missing 'cluster_id' column")
    summary_df["cluster_id"] = summary_df["cluster_id"].astype(str).str.strip()
    rows = summary_df[summary_df["cluster_id"] == str(cluster_id).strip()]

    if len(rows) == 0:
        logger.warning(
            "Cluster %s not found in %s; falling back to computing annual_heat_mwh/design_load_kw from processed profiles.",
            cluster_id,
            cluster_summary_path,
        )
        row = _compute_cluster_summary_fallback(cluster_id)
        row["cluster_id"] = cluster_id
        row["_cluster_summary_source"] = "fallback_from_profiles"
    else:
        row = rows.iloc[0].to_dict()
        row["_cluster_summary_source"] = "cluster_load_summary_parquet"

        # Our current schema uses annual_heat_kwh_a; convert to annual_heat_mwh for economics engine.
        if "annual_heat_mwh" not in row:
            if "annual_heat_kwh_a" in row:
                row["annual_heat_mwh"] = float(row["annual_heat_kwh_a"]) / 1000.0
            else:
                raise ValueError("Cluster summary must contain annual_heat_mwh or annual_heat_kwh_a")

    logger.info("✓ Cluster data: %.2f MWh/year", float(row["annual_heat_mwh"]))

    # 5) Monte Carlo
    logger.info("Running Monte Carlo simulation (%d samples)...", int(n_samples))
    mc_results = run_monte_carlo_for_cluster(
        cluster_id=cluster_id,
        cha_kpis=cha_kpis,
        dha_kpis=dha_kpis,
        cluster_summary=row,
        n_samples=int(n_samples),
        randomness_config=randomness_config,
        base_params=params,
        seed=int(seed),
        n_jobs=int(n_jobs),
    )
    logger.info("✓ Monte Carlo completed: %d samples", len(mc_results))

    # 6) Save raw samples
    samples_path = output_dir / "monte_carlo_samples.parquet"
    mc_results.to_parquet(samples_path, compression="snappy", index=False)
    logger.info("✓ Saved samples to %s", samples_path.name)

    # 7) Summary stats
    summary = compute_mc_summary(mc_results)

    # 8) Save summary JSON with metadata
    summary_path = output_dir / "monte_carlo_summary.json"
    summary = dict(summary)  # ensure mutable
    summary["metadata"] = {
        "cluster_id": cluster_id,
        "timestamp": pd.Timestamp.now().isoformat(),
        "seed": int(seed),
        "n_samples": int(n_samples),
        "n_valid": int(summary["monte_carlo"]["n_valid"]),
        "input_files": {
            "cha_kpis": str(cha_kpis_path),
            "dha_kpis": str(dha_kpis_path),
            "cluster_summary": str(cluster_summary_path),
        },
        "parameters": {
            "discount_rate": float(params.discount_rate),
            "lifetime_years": int(params.lifetime_years),
            "dh_generation_type": str(params.dh_generation_type),
            "electricity_price_eur_per_mwh": float(params.electricity_price_eur_per_mwh),
            "gas_price_eur_per_mwh": float(params.gas_price_eur_per_mwh),
            "biomass_price_eur_per_mwh": float(params.biomass_price_eur_per_mwh),
            "hp_cost_eur_per_kw_th": float(params.hp_cost_eur_per_kw_th),
            "cop_default": float(params.cop_default),
        },
    }
    summary_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    logger.info("✓ Saved summary to %s", summary_path.name)

    # 9) Decision insight
    dh_win_frac = float(summary["monte_carlo"]["dh_wins_fraction"])
    hp_win_frac = float(summary["monte_carlo"]["hp_wins_fraction"])
    if dh_win_frac > 0.70:
        insight = "robust_dh"
    elif hp_win_frac > 0.70:
        insight = "robust_hp"
    elif dh_win_frac > 0.55 or hp_win_frac > 0.55:
        insight = "sensitive"
    else:
        insight = "inconclusive"
    summary["metadata"]["decision_insight"] = insight
    summary_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")

    if not quiet:
        _print_summary(cluster_id, summary)

    return summary


def _print_summary(cluster_id: str, summary: dict) -> None:
    print("\n" + "=" * 70)
    print(f"Economics Summary: {cluster_id}")
    print("=" * 70)

    print("\nLevelized Cost of Heat (EUR/MWh):")
    print(
        f"  DH: {summary['lcoh']['dh']['p50']:.2f} "
        f"(95% CI: {summary['lcoh']['dh']['p05']:.2f} - {summary['lcoh']['dh']['p95']:.2f})"
    )
    print(
        f"  HP: {summary['lcoh']['hp']['p50']:.2f} "
        f"(95% CI: {summary['lcoh']['hp']['p05']:.2f} - {summary['lcoh']['hp']['p95']:.2f})"
    )

    print("\nCO2 Emissions (kg/MWh):")
    print(
        f"  DH: {summary['co2']['dh']['p50']:.2f} "
        f"(95% CI: {summary['co2']['dh']['p05']:.2f} - {summary['co2']['dh']['p95']:.2f})"
    )
    print(
        f"  HP: {summary['co2']['hp']['p50']:.2f} "
        f"(95% CI: {summary['co2']['hp']['p05']:.2f} - {summary['co2']['hp']['p95']:.2f})"
    )

    print("\nMonte Carlo Robustness:")
    print(f"  DH wins (cost): {summary['monte_carlo']['dh_wins_fraction']:.1%}")
    print(f"  HP wins (cost): {summary['monte_carlo']['hp_wins_fraction']:.1%}")
    print(f"  DH wins (CO2):  {summary['monte_carlo']['dh_wins_co2_fraction']:.1%}")
    print(f"  HP wins (CO2):  {summary['monte_carlo']['hp_wins_co2_fraction']:.1%}")

    n_valid = summary["monte_carlo"]["n_valid"]
    n_total = summary["monte_carlo"]["n_samples"]
    print(f"\nValid samples: {n_valid}/{n_total} ({n_valid/n_total:.1%})")
    print("=" * 70)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run economics analysis (LCOH, CO2) with Monte Carlo uncertainty quantification",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument("--cluster-id", required=True, help="Cluster identifier (e.g., ST010_HEINRICH_ZILLE_STRASSE)")
    parser.add_argument("--cha-kpis", required=True, type=Path, help="Path to cha_kpis.json")
    parser.add_argument("--dha-kpis", required=True, type=Path, help="Path to dha_kpis.json")
    parser.add_argument("--cluster-summary", required=True, type=Path, help="Path to cluster_load_summary.parquet")
    parser.add_argument("--out", required=True, type=Path, help="Output directory for results")

    parser.add_argument("--n-samples", type=int, default=500, help="Number of Monte Carlo samples")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility")
    parser.add_argument("--n-jobs", type=int, default=1, help="Parallel jobs (-1=all cores)")

    parser.add_argument("--scenario", type=Path, help="YAML file with economic scenario parameters")
    parser.add_argument("--randomness-config", type=Path, help="JSON file with parameter distribution specifications")

    parser.add_argument("--quiet", action="store_true", help="Suppress detailed logging and summary output")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    args = parser.parse_args()

    if args.debug:
        log_level = logging.DEBUG
    elif args.quiet:
        log_level = logging.WARNING
    else:
        log_level = logging.INFO

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    missing_files = [p for p in [args.cha_kpis, args.dha_kpis, args.cluster_summary] if not p.exists()]
    if missing_files:
        for f in missing_files:
            logger.error("Missing input file: %s", f)
        raise SystemExit(2)

    run_economics_for_cluster(
        cluster_id=args.cluster_id,
        cha_kpis_path=args.cha_kpis,
        dha_kpis_path=args.dha_kpis,
        cluster_summary_path=args.cluster_summary,
        output_dir=args.out,
        n_samples=args.n_samples,
        seed=args.seed,
        scenario_file=args.scenario,
        randomness_config_file=args.randomness_config,
        quiet=args.quiet,
        n_jobs=args.n_jobs,
    )


if __name__ == "__main__":
    main()

