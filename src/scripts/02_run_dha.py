#!/usr/bin/env python3
"""
DHA pipeline: LV grid hosting analysis for heat pumps.
"""
import sys
import argparse
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

import pandas as pd
import geopandas as gpd

from branitz_heat_decision.config import (
    DATA_PROCESSED,
    HOURLY_PROFILES_PATH,
    resolve_cluster_path,
)
from branitz_heat_decision.dha.config import DHAConfig, get_default_config
from branitz_heat_decision.dha import grid_builder, mapping, loadflow, kpi_extractor
from branitz_heat_decision.dha.export import export_dha_outputs
from branitz_heat_decision.dha.base_loads import load_base_loads_from_gebaeude_lastphasen
from branitz_heat_decision.dha.bdew_base_loads import (
    compute_bdew_base_loads_for_hours_and_assumptions,
    BDEWPaths,
    _default_bdew_paths,
)
from branitz_heat_decision.dha.hosting_capacity import run_monte_carlo_hosting_capacity
from branitz_heat_decision.dha.smart_grid_strategies import simulate_smart_grid_strategies
from branitz_heat_decision.dha.reinforcement_optimizer import plan_grid_reinforcement
from dataclasses import asdict

def main():
    parser = argparse.ArgumentParser(description="Run DHA (LV grid hosting) for a cluster")
    parser.add_argument("--cluster-id", required=True, type=str, help="Cluster ID (e.g., ST010_HEINRICH_ZILLE_STRASSE)")
    parser.add_argument("--cop", type=float, default=2.8, help="Heat pump COP (P_el = Q_th / COP)")
    parser.add_argument("--pf", type=float, default=0.95, help="Power factor for reactive power: Q = P*tan(arccos(pf))")
    parser.add_argument("--hp-three-phase", action="store_true", help="Model HP loads as balanced 3-phase (default)")
    parser.add_argument("--single-phase", action="store_true", help="Model HP loads as single-phase imbalance (uses runpp_3ph if available)")
    parser.add_argument("--topn", type=int, default=10, help="Number of top hours to include (default 10)")
    parser.add_argument("--max-mapping-dist-m", type=float, default=None, help="Max building->bus mapping distance (m)")
    parser.add_argument("--grid-buffer-m", type=float, default=1500.0, help="Buffer around cluster buildings to subset the LV grid geodata")
    parser.add_argument(
        "--base-load-json",
        type=str,
        default="data/raw/gebaeude_lastphasenV2.json",
        help="Base electrical load JSON (scenario-based) path (default: data/raw/gebaeude_lastphasenV2.json)",
    )
    parser.add_argument(
        "--base-load-source",
        type=str,
        default="scenario_json",
        choices=["scenario_json", "bdew_timeseries"],
        help="Base load source: scenario_json (scalar per building) or bdew_timeseries (hourly via BDEW SLP)",
    )
    parser.add_argument(
        "--bdew-profiles-csv",
        type=str,
        default=None,
        help="Optional path to bdew_profiles.csv (else auto-discovered from data/raw or Legacy/fromDifferentThesis)",
    )
    parser.add_argument(
        "--bdew-mapping-json",
        type=str,
        default=None,
        help="Optional path to bdew_slp_gebaeudefunktionen.json (else auto-discovered if present)",
    )
    parser.add_argument(
        "--bdew-population-json",
        type=str,
        default=None,
        help="REQUIRED for bdew_timeseries: Path to building_population_resultsV6.json (deterministic H0 scaling)",
    )
    parser.add_argument(
        "--base-scenario",
        type=str,
        default="winter_werktag_abendspitze",
        help="Scenario key inside gebaeude_lastphasenV2.json to use as P_base (default: winter_werktag_abendspitze)",
    )
    parser.add_argument(
        "--base-unit",
        type=str,
        default="AUTO",
        choices=["AUTO", "MW", "kW", "KW"],
        help="Unit of gebaeude_lastphasenV2.json values (default AUTO; converted to kW internally)",
    )
    parser.add_argument(
        "--disable-base-load",
        action="store_true",
        help="If set, ignore gebaeude_lastphasenV2.json (HP-only loads).",
    )
    parser.add_argument(
        "--use-pf-split",
        action="store_true",
        help="If set, compute Q_total as Q_base(pf_base)+Q_hp(pf_hp) instead of one pf_total for total P.",
    )
    parser.add_argument("--pf-base", type=float, default=0.95, help="Power factor for base load (pf_base)")
    parser.add_argument("--pf-hp", type=float, default=0.95, help="Power factor for HP incremental load (pf_hp)")
    parser.add_argument(
        "--grid-source",
        type=str,
        default="legacy_json",
        choices=["legacy_json", "geodata"],
        help="Grid source to build LV network: legacy_json (Legacy/DHA nodes/ways) or geodata (data/processed/power_lines/substations).",
    )
    parser.add_argument(
        "--legacy-nodes-ways-json",
        type=str,
        default=None,
        help="Path to legacy nodes/ways JSON (default: Legacy/DHA/HP New /Data/branitzer_siedlung_ns_v3_ohne_UW.json).",
    )
    parser.add_argument("--output-dir", type=str, default=None, help="Output dir (default results/dha/<cluster_id>/)")
    parser.add_argument("--monte-carlo", type=int, default=0, help="Run Monte Carlo hosting capacity analysis with N scenarios (default: 0 = off)")
    parser.add_argument("--monte-carlo-range", type=str, default="0.1,1.0", help="Penetration range 'min,max' for Monte Carlo (default: 0.1,1.0)")
    parser.add_argument("--simulate-strategies", action="store_true", help="Run Smart Grid Strategy simulation (curtailment, Q-control, OLTC)")
    parser.add_argument("--plan-reinforcement", action="store_true", help="Run Automated Reinforcement Planning if violations exist")
    args = parser.parse_args()

    cluster_id = args.cluster_id
    cfg: DHAConfig = get_default_config()
    if args.max_mapping_dist_m is not None:
        cfg.max_mapping_dist_m = float(args.max_mapping_dist_m)

    hp_three_phase = True
    if args.single_phase:
        hp_three_phase = False
    if args.hp_three_phase:
        hp_three_phase = True

    out_dir = Path(args.output_dir) if args.output_dir else resolve_cluster_path(cluster_id, "dha")
    out_dir.mkdir(parents=True, exist_ok=True)

    # --- Load cluster buildings ---
    buildings_path = DATA_PROCESSED / "buildings.parquet"
    bcm_path = DATA_PROCESSED / "building_cluster_map.parquet"
    if not buildings_path.exists() or not bcm_path.exists():
        raise FileNotFoundError("Missing processed data: buildings.parquet or building_cluster_map.parquet")

    buildings = gpd.read_parquet(buildings_path)
    bcm = pd.read_parquet(bcm_path)
    bids = bcm.loc[bcm["cluster_id"] == cluster_id, "building_id"].astype(str).tolist()
    if not bids:
        raise ValueError(f"No buildings found for cluster {cluster_id} in building_cluster_map.parquet")
    buildings = buildings[buildings["building_id"].astype(str).isin(bids)].copy()
    if buildings.empty:
        raise ValueError(f"Cluster {cluster_id} resolved to 0 buildings after filtering.")

    # --- Load design hour + TopN hours ---
    topn_path = DATA_PROCESSED / "cluster_design_topn.json"
    if not topn_path.exists():
        raise FileNotFoundError(f"Missing cluster design/topN file: {topn_path}")
    topn_obj = json.loads(topn_path.read_text(encoding="utf-8"))
    clusters = topn_obj.get("clusters", {})
    if cluster_id not in clusters:
        raise KeyError(f"Cluster {cluster_id} not present in {topn_path}")
    design_hour = int(clusters[cluster_id]["design_hour"])
    topn_hours = [int(h) for h in clusters[cluster_id].get("topn_hours", [])][: int(args.topn)]
    if design_hour not in topn_hours:
        topn_hours = [design_hour] + topn_hours

    # --- Load hourly heat profiles (kW_th) ---
    if not Path(HOURLY_PROFILES_PATH).exists():
        raise FileNotFoundError(f"Missing hourly profiles parquet: {HOURLY_PROFILES_PATH}")
    hourly = pd.read_parquet(HOURLY_PROFILES_PATH)
    # Filter to cluster buildings (columns are building_ids)
    cols = [c for c in bids if c in hourly.columns]
    if not cols:
        raise ValueError(f"No cluster building IDs found in hourly profiles columns for {cluster_id}")
    hourly = hourly[cols].copy()

    # IMPORTANT: only consider the buildings that have hourly heat profiles (proxy: residential w/ heat demand)
    # so the simulation + map are based on the residential buildings in the selected street cluster.
    buildings = buildings[buildings["building_id"].astype(str).isin(cols)].copy()
    if buildings.empty:
        raise ValueError(
            f"After restricting to buildings with hourly heat profiles, cluster {cluster_id} has 0 buildings."
        )

    # --- Load base electrical demand (scenario-based) ---
    base_kw = None
    if not args.disable_base_load:
        if str(args.base_load_source) == "bdew_timeseries":
            if not args.bdew_population_json:
                raise ValueError(
                    "For --base-load-source bdew_timeseries you must pass --bdew-population-json "
                    "(building_population_resultsV6.json) so H0 scaling is deterministic."
                )
            # Build a time-varying base profile for the same hours we simulate.
            hours_needed = [design_hour] + topn_hours
            hours_needed = list(dict.fromkeys([int(h) for h in hours_needed]))
            paths = _default_bdew_paths()
            if args.bdew_profiles_csv:
                paths = BDEWPaths(
                    bdew_profiles_csv=Path(args.bdew_profiles_csv),
                    building_function_mapping_json=paths.building_function_mapping_json,
                    building_population_json=paths.building_population_json,
                )
            if args.bdew_mapping_json:
                paths = BDEWPaths(
                    bdew_profiles_csv=paths.bdew_profiles_csv,
                    building_function_mapping_json=Path(args.bdew_mapping_json),
                    building_population_json=paths.building_population_json,
                )
            if args.bdew_population_json:
                paths = BDEWPaths(
                    bdew_profiles_csv=paths.bdew_profiles_csv,
                    building_function_mapping_json=paths.building_function_mapping_json,
                    building_population_json=Path(args.bdew_population_json),
                )
            base_df, bdew_assumptions_df = compute_bdew_base_loads_for_hours_and_assumptions(
                buildings_df=buildings,
                hours=hours_needed,
                year=2023,
                paths=paths,
                require_population=True,
            )
            # Keep only modeled buildings (those with heat profiles)
            base_kw = base_df.reindex(columns=cols).fillna(0.0)

            # Audit: write per-building assumptions to output dir
            assumptions_path = out_dir / "bdew_base_load_assumptions.csv"
            try:
                bdew_assumptions_df.to_csv(assumptions_path, index=False)
            except Exception:
                assumptions_path.write_text(bdew_assumptions_df.to_csv(index=False), encoding="utf-8")
        else:
            base_series = load_base_loads_from_gebaeude_lastphasen(
                Path(args.base_load_json),
                scenario=str(args.base_scenario),
                unit=str(args.base_unit),
            )
            # Filter to cluster buildings only; missing defaults to 0 later
            base_kw = base_series.reindex(cols).fillna(0.0)

    # --- Build grid (Option 2 boundary) ---
    lines_gdf = None
    if args.grid_source == "geodata":
        # Build from processed power grid geodata (must overlap the buildings CRS/area)
        lines_gdf = gpd.read_file(DATA_PROCESSED / "power_lines.geojson")
        subs_gdf = gpd.read_file(DATA_PROCESSED / "power_substations.geojson")
        if lines_gdf.empty or subs_gdf.empty:
            raise ValueError("power_lines.geojson or power_substations.geojson is empty; cannot build LV grid.")

        # Subset grid to cluster area for performance (keep enough buffer to remain connected)
        bbox = buildings.total_bounds  # (minx,miny,maxx,maxy) in EPSG:25833
        from shapely.geometry import box

        area = box(*bbox).buffer(float(args.grid_buffer_m))
        lines_gdf = lines_gdf[lines_gdf.geometry.intersects(area)].copy()
        subs_gdf = subs_gdf[subs_gdf.geometry.intersects(area)].copy()

        if subs_gdf.empty:
            subs_gdf = gpd.read_file(DATA_PROCESSED / "power_substations.geojson")

        net = grid_builder.build_lv_grid_option2(lines_gdf, subs_gdf, cfg)
    else:
        # Default/recommended for Branitz continuity: legacy nodes/ways JSON
        legacy_path = args.legacy_nodes_ways_json
        if legacy_path is None:
            legacy_path = str(
                Path("Legacy/DHA/HP New /Data/branitzer_siedlung_ns_v3_ohne_UW.json")
            )
        net = grid_builder.build_lv_grid_from_nodes_ways_json(Path(legacy_path), cfg)

    # --- Map buildings -> LV buses ---
    bmap = mapping.map_buildings_to_lv_buses(
        buildings_gdf=buildings,
        net=net,
        max_dist_m=float(cfg.max_mapping_dist_m),
        bus_crs=(str(lines_gdf.crs) if (lines_gdf is not None and getattr(lines_gdf, "crs", None) is not None) else "EPSG:4326"),
        lv_vn_kv=float(cfg.lv_vn_kv),
    )

    # --- Build hourly electrical loads and run loadflows ---
    loads_by_hour = loadflow.assign_hp_loads(
        hourly_heat_profiles_df=hourly,
        building_bus_map=bmap,
        design_hour=design_hour,
        topn_hours=topn_hours,
        cop=float(args.cop),
        pf=float(args.pf),
        hp_three_phase=hp_three_phase,
        base_profiles_kw=base_kw,
        pf_base=float(args.pf_base),
        pf_hp=float(args.pf_hp),
        use_pf_split=bool(args.use_pf_split),
    )

    # Per-hour load summary (auditable): bus-aggregated and system totals
    load_summary_rows = []
    for h, dfh in loads_by_hour.items():
        load_summary_rows.append(
            {
                "hour": int(h),
                "p_base_kw_total": float(dfh["p_base_kw"].sum()) if "p_base_kw" in dfh.columns else 0.0,
                "p_hp_kw_total": float(dfh["p_hp_kw"].sum()) if "p_hp_kw" in dfh.columns else 0.0,
                "p_total_kw_total": float(dfh["p_total_kw"].sum()) if "p_total_kw" in dfh.columns else float(dfh["p_mw"].sum() * 1000.0),
                "q_total_kvar_total": float(dfh["q_total_kvar"].sum()) if "q_total_kvar" in dfh.columns else float(dfh["q_mvar"].sum() * 1000.0),
            }
        )
    load_summary_df = pd.DataFrame(load_summary_rows).sort_values("hour")

    results_by_hour = loadflow.run_loadflow(
        net=net,
        loads_by_hour=loads_by_hour,
        hp_three_phase=hp_three_phase,
        run_3ph_if_available=True,
    )

    # --- KPIs + violations ---
    kpis, violations_df = kpi_extractor.extract_dha_kpis(results_by_hour, cfg, net=net)  # Pass net for feeder distance

    # Add auditable peak contributions (base vs HP) to KPIs
    if not load_summary_df.empty:
        kpis["peak_p_base_kw_total"] = float(load_summary_df["p_base_kw_total"].max())
        kpis["peak_p_hp_kw_total"] = float(load_summary_df["p_hp_kw_total"].max())
        kpis["peak_p_total_kw_total"] = float(load_summary_df["p_total_kw_total"].max())
        # hour of peak total P
        try:
            kpis["peak_p_total_hour"] = int(load_summary_df.loc[load_summary_df["p_total_kw_total"].idxmax(), "hour"])
        except Exception:
            pass
    
    # --- Mitigation Analysis (NEW) ---
    from branitz_heat_decision.dha.mitigations import recommend_mitigations
    
    mitigation_analysis = recommend_mitigations(net, kpis, violations_df, cfg)
    kpis["mitigations"] = mitigation_analysis
    
    print(f"\nMitigation Analysis:")
    print(f"  Class: {mitigation_analysis['mitigation_class']}")
    print(f"  Feasible with mitigation: {mitigation_analysis['feasible_with_mitigation']}")
    print(f"  Summary: {mitigation_analysis['summary']}")
    if mitigation_analysis["recommendations"]:
        print(f"  Recommendations: {len(mitigation_analysis['recommendations'])}")

    # --- Export ---
    exported = export_dha_outputs(
        net=net,
        results_by_hour=results_by_hour,
        kpis=kpis,
        violations_df=violations_df,
        output_dir=out_dir,
        title=f"HP LV Grid Hosting — {cluster_id}",
        geodata_crs=(str(lines_gdf.crs) if (lines_gdf is not None and getattr(lines_gdf, "crs", None) is not None) else "EPSG:4326"),
        focus_bus_ids=set(bmap.loc[bmap["mapped"] == True, "bus_id"].dropna().astype(int).tolist()),  # noqa: E712
    )

    # --- Monte Carlo Hosting Capacity (NEW) ---
    if args.monte_carlo > 0:
        print(f"\nRunning Monte Carlo Hosting Capacity Analysis (N={args.monte_carlo})...")
        try:
            min_p, max_p = map(float, args.monte_carlo_range.split(","))
            mc_results = run_monte_carlo_hosting_capacity(
                net=net,
                building_bus_map=bmap,
                hourly_heat_profiles=hourly,
                base_load_profiles=base_kw,
                cfg=cfg,
                n_scenarios=args.monte_carlo,
                penetration_range=(min_p, max_p),
                design_cop=float(args.cop),
                design_hour_idx=design_hour,
                top_n_hours=topn_hours # Already sliced by args.topn
            )
            
            mc_path = out_dir / "dha_hosting_capacity.json"
            mc_dict = asdict(mc_results)
            mc_path.write_text(json.dumps(mc_dict, indent=2), encoding="utf-8")
            exported["dha_hosting_capacity"] = mc_path
            
            # Print Summary
            print(f"  Scenarios safe: {mc_results.safe_scenarios}/{mc_results.scenarios_analyzed} ({mc_results.safety_score:.1%})")
            print(f"  Hosting Capacity (Median): {mc_results.safe_capacity_median_kw:.1f} kW")
            print(f"  Safe Penetration (Median): {mc_results.safe_penetration_median_pct:.1%}")
            
            # Add basic MC stats to main KPIs for UI quick view
            kpis["hosting_capacity"] = {
                "median_kw": mc_results.safe_capacity_median_kw,
                "safety_score": mc_results.safety_score,
                "safe_scenarios": mc_results.safe_scenarios,
                "total_scenarios": mc_results.scenarios_analyzed
            }
            # Re-export kpis to include MC data
            (out_dir / "dha_kpis.json").write_text(json.dumps(kpis, indent=2), encoding="utf-8")

        except Exception as e:
            print(f"⚠️ Monte Carlo analysis failed: {e}")
            import traceback
            traceback.print_exc()

    # --- Smart Grid Strategies (NEW) ---
    if args.simulate_strategies:
        print(f"\nRunning Smart Grid Strategy Simulation...")
        try:
            strat_results = simulate_smart_grid_strategies(net, loads_by_hour, kpis, cfg)
            
            strat_path = out_dir / "dha_strategies.json"
            # StrategyResult is dataclass
            strat_dict = {k: asdict(v) for k, v in strat_results.items()}
            strat_path.write_text(json.dumps(strat_dict, indent=2), encoding="utf-8")
            exported["dha_strategies"] = strat_path
            
            print(f"  Simulated {len(strat_results)} strategies.")
            for name, res in strat_results.items():
                print(f"  - {name}: Feasible={res.is_feasible}, V_worst={res.worst_voltage_pu:.3f}, Cost=€{res.cost_estimate_eur:,.0f}")
                
        except Exception as e:
            print(f"⚠️ Strategy simulation failed: {e}")
            import traceback
            traceback.print_exc()

    # --- Reinforcement Planning (NEW) ---
    if args.plan_reinforcement:
        if kpis.get("feasible", False):
             print("\nSkipping Reinforcement Planning (Grid is already feasible).")
        else:
            print(f"\nRunning Automated Reinforcement Planning...")
            try:
                plan = plan_grid_reinforcement(net, loads_by_hour, cfg)
                
                plan_path = out_dir / "dha_reinforcement.json"
                plan_dict = asdict(plan)
                plan_path.write_text(json.dumps(plan_dict, indent=2), encoding="utf-8")
                exported["dha_reinforcement"] = plan_path
                
                print(f"  Plan sufficient: {plan.is_sufficient}")
                print(f"  Total Cost: €{plan.total_cost_eur:,.2f}")
                print(f"  Measures: {len(plan.measures)}")
                
            except Exception as e:
                print(f"⚠️ Reinforcement planning failed: {e}")    
                import traceback
                traceback.print_exc()

    # Save per-hour load summary CSV
    load_summary_path = out_dir / "load_summary_by_hour.csv"
    load_summary_df.to_csv(load_summary_path, index=False)
    exported["load_summary_by_hour"] = load_summary_path
    if (not args.disable_base_load) and str(args.base_load_source) == "bdew_timeseries":
        # If created above, attach it for discovery/audit
        ap = out_dir / "bdew_base_load_assumptions.csv"
        if ap.exists():
            exported["bdew_base_load_assumptions"] = ap

    print("\nDHA complete")
    print(f"Cluster: {cluster_id}")
    print(f"Design hour: {design_hour} | TopN hours: {topn_hours[:int(args.topn)]}")
    print(f"Feasible: {kpis.get('feasible')}")
    print("Outputs:")
    for k, p in exported.items():
        print(f"  {k}: {p}")

if __name__ == "__main__":
    main()

