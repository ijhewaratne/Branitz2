"""
Enhanced Network Builder with Trunk-Spur Architecture.
Implements strict street-following trunks and exclusive per-building spurs.
"""

import geopandas as gpd
import pandas as pd
import numpy as np
import networkx as nx
import pandapipes as pp
import re
from shapely.geometry import Point, LineString, box
from shapely.strtree import STRtree
from typing import Tuple, List, Dict, Any, Optional
import logging
from pathlib import Path

from .config import CHAConfig, get_default_config
from .sizing_catalog import size_trunk_and_spurs
from .sizing import load_pipe_catalog
from .heat_loss import compute_heat_loss, HeatLossInputs
from ..config import resolve_cluster_path
from ..data.cluster import normalize_street_name

logger = logging.getLogger(__name__)

def build_trunk_spur_network(
    cluster_id: str,
    buildings: gpd.GeoDataFrame,
    streets: gpd.GeoDataFrame,
    plant_coords: Tuple[float, float],
    selected_street_name: Optional[str],
    design_loads_kw: Dict[str, float],
    pipe_catalog: pd.DataFrame,
    config: Optional[CHAConfig] = None,
    street_buffer_m: float = 15.0,
    max_spur_length_m: float = 50.0,
    attach_mode: str = 'split_edge_per_building',
    disable_auto_plant_siting: bool = False,
) -> Tuple[pp.pandapipesNet, Dict[str, Any]]:
    """
    Build complete trunk-spur network with closed loops via buildings.
    
    Args:
        cluster_id: Street cluster identifier
        buildings: GeoDataFrame with building data (must include geometry, building_id)
        streets: GeoDataFrame with street centerlines
        plant_coords: (x, y) tuple for plant location
        design_loads_kw: Dict mapping building_id to peak load (kW)
        pipe_catalog: DataFrame with DN specifications
        config: CHAConfig instance
        street_buffer_m: Buffer around building cluster for street selection
        max_spur_length_m: Maximum allowed spur length
        attach_mode: How buildings attach ('split_edge_per_building' recommended)
    
    Returns:
        Tuple of (converged pandapipesNet, topology_info_dict)
    """
    if config is None:
        config = get_default_config()
    
    logger.info(f"Building trunk-spur network for {cluster_id} ({len(buildings)} buildings)")
    
    # Step 0: Choose plant location (optional: re-site to nearby *different* street)
    plant_coords_input = plant_coords
    if selected_street_name and not disable_auto_plant_siting:
        try:
            alt = _choose_plant_coords_on_nearby_other_street(
                streets=streets,
                buildings=buildings,
                selected_street_name=selected_street_name,
                buffer_m=max(75.0, street_buffer_m * 6.0),
            )
            if alt is not None:
                plant_coords = alt
                logger.info(
                    f"Plant sited on nearby other street (not '{selected_street_name}'): "
                    f"{plant_coords_input} -> {plant_coords}"
                )
            else:
                logger.warning(
                    f"Could not place plant on a different nearby street for '{selected_street_name}'. "
                    f"Using provided plant_coords={plant_coords_input}."
                )
        except Exception as e:
            logger.warning(
                f"Plant siting on nearby other street failed ({e}). Using provided plant_coords={plant_coords_input}."
            )

    # Step 1: Filter streets to cluster area (must include plant vicinity too)
    # We also validate that all building attach points are connected to the plant connection node.
    # If not, we progressively expand the street buffer.
    street_subgraph = None
    plant_attach_node = None
    attach_info = None
    trunk_edges = None
    trunk_nodes = None

    for factor in (1.0, 2.0, 4.0, 8.0):
        edges_all, G = _filter_streets_to_cluster(
            streets, buildings, buffer_m=street_buffer_m * factor, plant_coords=plant_coords
        )
        if G.number_of_nodes() == 0:
            continue

        # Plant connection node is where the trunk begins (on the street graph)
        plant_attach_node = _nearest_graph_node_to_point(G, plant_coords)

        # Building attach points (projections on nearest edges)
        attach_info = _compute_building_attach_nodes(buildings, G)
        target_nodes = _building_attach_targets(G, attach_info)

        # Connectivity check: all target nodes must be reachable from plant_attach_node
        unreachable = [n for n in target_nodes if not nx.has_path(G, plant_attach_node, n)]
        if unreachable:
            # Last chance: the street data sometimes has tiny gaps / snapping issues that split the graph.
            # If buffer expansion didn't help, bridge disconnected components with minimal virtual edges.
            if factor >= 8.0:
                bridged = _bridge_disconnected_target_components(
                    G=G,
                    plant_node=plant_attach_node,
                    target_nodes=target_nodes,
                )
                if bridged > 0:
                    unreachable = [n for n in target_nodes if not nx.has_path(G, plant_attach_node, n)]
                    if not unreachable:
                        logger.info(
                            f"Bridged {bridged} disconnected street components; all attach targets are now reachable."
                        )
                    else:
                        logger.warning(
                            f"After bridging {bridged} components, still {len(unreachable)}/{len(target_nodes)} "
                            f"targets disconnected. Expanding buffer..."
                        )
                        continue
                else:
                    logger.warning(
                        f"Street graph buffer factor={factor} leaves {len(unreachable)}/{len(target_nodes)} "
                        f"building attach targets disconnected from plant and no components could be bridged."
                    )
                    continue
            else:
                logger.warning(
                    f"Street graph buffer factor={factor} still leaves {len(unreachable)}/{len(target_nodes)} "
                    f"building attach targets disconnected from plant. Expanding buffer..."
                )
                continue

        # Build a radial (acyclic) trunk: subtree of the single-source shortest-path tree (SPT)
        trunk_edges = _build_radial_trunk_edges(G, plant_attach_node, target_nodes, weight="length_m")
        trunk_nodes = sorted({n for e in trunk_edges for n in e} | {plant_attach_node})
        street_subgraph = G
        break

    if street_subgraph is None or trunk_edges is None or plant_attach_node is None:
        raise ValueError("Could not build a connected street graph for trunk creation.")

    logger.info(
        f"Built RADIAL trunk: nodes={len(trunk_nodes)}, edges={len(trunk_edges)} "
        f"(connected={nx.is_connected(nx.Graph(trunk_edges)) if trunk_edges else False})"
    )

    # Step 2: Map buildings to exclusive spur attachment points (service connections)
    spur_assignments = _assign_exclusive_spur_points(
        buildings, trunk_edges, street_subgraph, max_spur_length_m
    )

    # Step 2.5: Implement "tee on main" by splitting trunk edges at attach points (recommended)
    if attach_mode == "split_edge_per_building":
        trunk_edges, attach_node_for_building = _split_trunk_edges_at_attach_points(trunk_edges, spur_assignments)
        # Update trunk nodes to include the new tee nodes
        trunk_nodes = sorted({n for e in trunk_edges for n in e} | {plant_attach_node})
        # Persist the chosen attach trunk node for each building
        for bid, n in attach_node_for_building.items():
            if bid in spur_assignments:
                spur_assignments[bid]["trunk_attach_node"] = n
        logger.info(
            f"Applied tee-on-main splitting: trunk nodes={len(trunk_nodes)}, edges={len(trunk_edges)} "
            f"(tee nodes={len(attach_node_for_building)})"
        )

    # Step 2.75: Prune dead-end trunk stubs that do not lead to any service tee (design hygiene).
    # This avoids zero-flow trunk segments (which often produce NaN thermal values on those pipes).
    if getattr(config, "prune_trunk_to_service_subtree", False):
        tee_nodes = {
            a.get("trunk_attach_node")
            for a in spur_assignments.values()
            if a.get("trunk_attach_node") is not None
        }
        if tee_nodes:
            old_edge_count = len(trunk_edges)
            trunk_edges_pruned = _prune_trunk_to_service_subtree(
                trunk_edges=trunk_edges,
                trunk_root=plant_attach_node,
                tee_nodes=tee_nodes,
            )
            if trunk_edges_pruned and len(trunk_edges_pruned) < len(trunk_edges):
                trunk_edges = trunk_edges_pruned
                trunk_nodes = sorted({n for e in trunk_edges for n in e} | {plant_attach_node})
                logger.info(
                    f"Pruned trunk to minimal service subtree: nodes={len(trunk_nodes)}, "
                    f"edges={len(trunk_edges)} (removed {old_edge_count - len(trunk_edges)})"
                )

    # Step 3: Create pandapipes network structure (dual pipes supply+return)
    net = _create_trunk_spur_pandapipes(
        plant_attach_node=plant_attach_node,
        plant_coords=plant_coords,
        trunk_nodes=trunk_nodes,
        trunk_edges=trunk_edges,
        spur_assignments=spur_assignments,
        buildings=buildings,
        design_loads_kw=design_loads_kw,
        config=config,
    )
    
    # Step 5: Size pipes using technical catalog
    # Apply design margin (25%) for robustness to handle demand/temperature variations
    # This ensures pipes can handle ±20% demand variation in Monte Carlo scenarios
    design_margin = 1.25  # 25% margin for robustness
    design_loads_kw_sized = {bid: load * design_margin for bid, load in design_loads_kw.items()}
    logger.info(f"Applied {design_margin*100:.0f}% design margin for robustness (sizing loads: {sum(design_loads_kw_sized.values()):.1f} kW vs base: {sum(design_loads_kw.values()):.1f} kW)")
    
    pipe_sizes = size_trunk_and_spurs(
        net,
        design_loads_kw_sized,  # Use margin-adjusted loads for sizing
        trunk_edges,
        list(spur_assignments.keys()),
        pipe_catalog,
        spur_assignments=spur_assignments,
        trunk_root=plant_attach_node,
        delta_t_k=float(config.supply_temp_k - config.return_temp_k),
        # role-based sizing limits (optionally eco-mode)
        # Use more conservative velocity limits for robustness
        v_limit_trunk_ms=float(config.v_eco_mode_ms if config.sizing_eco_mode else min(config.v_limit_trunk_ms, 1.2)),  # Cap at 1.2 m/s for robustness
        v_limit_service_ms=float(config.v_eco_mode_ms if config.sizing_eco_mode else min(config.v_limit_service_ms, 1.2)),  # Cap at 1.2 m/s for robustness
        v_abs_max_ms=float(config.v_abs_max_ms),
        dp_per_m_max_pa=float(config.dp_per_m_max_pa),
    )
    _apply_pipe_sizes(net, pipe_sizes, trunk_edges)

    # Persist sizing rationale CSV (map-only; does not affect simulation)
    try:
        rationale_rows = pipe_sizes.get("rationale", [])
        if isinstance(rationale_rows, list) and len(rationale_rows) > 0:
            out_dir = resolve_cluster_path(cluster_id, "cha")
            out_dir.mkdir(parents=True, exist_ok=True)
            out_csv = out_dir / "pipe_sizing_rationale.csv"
            pd.DataFrame(rationale_rows).to_csv(out_csv, index=False)
            logger.info(f"Saved pipe sizing rationale to {out_csv}")
    except Exception as e:
        logger.warning(f"Could not write pipe sizing rationale CSV: {e}")

    # Step 5.5: Enable pipe heat losses (thermal)
    # Without u_w_per_m2k + text_k, temperatures tend to stay flat (no distributed losses).
    _apply_pipe_thermal_losses(net, config)
    
    # Step 6: Run pipeflow to get converged pressures/velocities/temperatures.
    # If heat consumers exist, run in thermal mode ("sequential") so temperatures are computed.
    # Otherwise run hydraulics only.
    #
    # With the dual ext_grid boundary conditions (plant supply+return) this should converge without
    # the spur optimizer; we keep the optimizer as a fallback.
    opt_summary: Dict[str, Any] = {"method": "direct_pipeflow_hydraulics"}
    try:
        has_hc = hasattr(net, "heat_consumer") and net.heat_consumer is not None and (not net.heat_consumer.empty)
        if has_hc:
            opt_summary["method"] = "direct_pipeflow_sequential"
            pp.pipeflow(net, mode="sequential", max_iter_hyd=80, max_iter_therm=80)
        else:
            pp.pipeflow(net, mode="hydraulics", max_iter_hyd=80)
        converged = True
        opt_summary["converged"] = True

        # Sanity gate: negative/too-low absolute pressures are physically invalid for DH water networks.
        # If this happens, increase plant pressure level and pump lift and retry a few times.
        try:
            p_min_allowed = float(getattr(config, "p_min_bar_allowed", 1.5))
            if hasattr(net, "res_junction") and net.res_junction is not None and not net.res_junction.empty and "p_bar" in net.res_junction.columns:
                pmin = float(pd.to_numeric(net.res_junction["p_bar"], errors="coerce").min())
                opt_summary["min_pressure_bar"] = pmin
                if np.isfinite(pmin) and pmin < p_min_allowed:
                    opt_summary["pressure_sanity_retry"] = {
                        "p_min_allowed": p_min_allowed,
                        "attempts": [],
                    }
                    for attempt in range(3):
                        # Increase both the absolute level and Δp to compensate for friction losses
                        config.system_pressure_bar = float(config.system_pressure_bar) * 1.5
                        config.pump_plift_bar = float(getattr(config, "pump_plift_bar", 3.0)) * 1.5
                        opt_summary["pressure_sanity_retry"]["attempts"].append(
                            {
                                "attempt": attempt + 1,
                                "system_pressure_bar": float(config.system_pressure_bar),
                                "pump_plift_bar": float(config.pump_plift_bar),
                            }
                        )

                        # Update boundary elements in-place
                        if hasattr(net, "ext_grid") and net.ext_grid is not None and not net.ext_grid.empty:
                            net.ext_grid.loc[:, "p_bar"] = float(config.system_pressure_bar)
                            if "t_k" in net.ext_grid.columns:
                                net.ext_grid.loc[:, "t_k"] = float(config.supply_temp_k)
                        if hasattr(net, "circ_pump_const_pressure") and net.circ_pump_const_pressure is not None and not net.circ_pump_const_pressure.empty:
                            net.circ_pump_const_pressure.loc[:, "p_flow_bar"] = float(config.system_pressure_bar)
                            net.circ_pump_const_pressure.loc[:, "plift_bar"] = float(config.pump_plift_bar)
                            if "t_flow_k" in net.circ_pump_const_pressure.columns:
                                net.circ_pump_const_pressure.loc[:, "t_flow_k"] = float(config.supply_temp_k)

                        # Re-run pipeflow
                        if has_hc:
                            pp.pipeflow(net, mode="sequential", max_iter_hyd=80, max_iter_therm=80)
                        else:
                            pp.pipeflow(net, mode="hydraulics", max_iter_hyd=80)

                        pmin = float(pd.to_numeric(net.res_junction["p_bar"], errors="coerce").min())
                        opt_summary["pressure_sanity_retry"]["attempts"][-1]["min_pressure_bar"] = pmin
                        if np.isfinite(pmin) and pmin >= p_min_allowed:
                            opt_summary["min_pressure_bar"] = pmin
                            break
        except Exception as _e:
            opt_summary["pressure_sanity_retry_error"] = f"{type(_e).__name__}: {_e}"
    except Exception as e:
        converged = False
        opt_summary["converged"] = False
        opt_summary["error"] = f"{type(e).__name__}: {e}"
        logger.warning(f"Direct pipeflow failed ({type(e).__name__}: {e}). Falling back to spur optimizer...")
        from .convergence_optimizer_spur import optimize_network_for_convergence
        converged, net, opt2 = optimize_network_for_convergence(net, config, max_iterations=3)
        opt_summary["fallback_optimizer"] = opt2
    
    # Step 8: Cleanup isolated junctions
    # Remove junctions not connected to any element (trunks nodes pruned away, etc.)
    # This prevents geospatial checks from reporting them as disconnected components.
    connected_juncs = set()
    # Pipes
    if hasattr(net, "pipe") and not net.pipe.empty:
        connected_juncs.update(net.pipe.from_junction.values)
        connected_juncs.update(net.pipe.to_junction.values)
    # Valves/Pumps/Controls
    for tbl in ["valve", "pump", "flow_control", "heat_exchanger", "circ_pump_const_pressure", "ext_grid", "heat_consumer", "sink", "source"]:
        if hasattr(net, tbl):
            df = getattr(net, tbl)
            if df is not None and not df.empty:
                for col in ["from_junction", "to_junction", "junction", "flow_junction", "return_junction"]:
                    if col in df.columns:
                        connected_juncs.update(df[col].dropna().values)
    
    # Drop isolated
    isolated = net.junction.index.difference(connected_juncs)
    if len(isolated) > 0:
        net.junction.drop(isolated, inplace=True)
        if hasattr(net, "junction_geodata"):
            net.junction_geodata = net.junction_geodata.loc[net.junction_geodata.index.isin(net.junction.index)]
        if hasattr(net, "res_junction"):
             net.res_junction = net.res_junction.loc[net.res_junction.index.isin(net.junction.index)]
        logger.info(f"Dropped {len(isolated)} isolated junctions to ensure clean topology.")
    topology_info = {
        'plant_node': plant_attach_node,
        'plant_coords_input': plant_coords_input,
        'plant_coords_used': plant_coords,
        'selected_street_name': selected_street_name,
        'trunk_nodes': trunk_nodes,
        'trunk_edges': trunk_edges,
        'spur_assignments': spur_assignments,
        'street_subgraph': street_subgraph,
        'converged': converged,
        'optimization_log': opt_summary
    }
    
    return net, topology_info


def _apply_pipe_thermal_losses(
    net: pp.pandapipesNet,
    config: CHAConfig,
    catalog: Optional[Dict[str, Any]] = None
) -> None:
    """
    Apply per-pipe heat loss parameters using DN, role, and circuit-aware calculation.

    Uses the heat_loss module to compute u_w_per_m2k and text_k per pipe based on:
    - DN (from diameter_m or std_type)
    - Role (trunk vs service)
    - Circuit (supply vs return)
    - Mean fluid temperature: T_mean = (T_sup + T_ret) / 2

    pandapipes v0.12 uses:
      - net.pipe.u_w_per_m2k: overall heat transfer coefficient (W/m²K)
      - net.pipe.text_k: external temperature (soil/ambient) in Kelvin
      - net.pipe.qext_w: additional external heat input (W) (default 0)
    """
    if not hasattr(net, "pipe") or net.pipe is None or net.pipe.empty:
        return

    t_soil = float(getattr(config, "soil_temp_k", 285.15))
    
    # Mean fluid temperature: (T_sup + T_ret) / 2
    # For steady-state design runs, use config defaults
    t_mean_k = (config.supply_temp_k + config.return_temp_k) / 2.0

    # Ensure columns exist (pandapipes creates them, but be defensive)
    if "u_w_per_m2k" not in net.pipe.columns:
        net.pipe["u_w_per_m2k"] = 0.0
    if "text_k" not in net.pipe.columns:
        net.pipe["text_k"] = t_soil
    if "qext_w" not in net.pipe.columns:
        net.pipe["qext_w"] = 0.0

    # Apply per-pipe heat loss calculation
    u_values = []
    text_values = []
    
    for idx, pipe in net.pipe.iterrows():
        # Extract DN from diameter_m or std_type
        dn_mm = None
        if pd.notna(pipe.get("diameter_m")):
            dn_mm = float(pipe["diameter_m"]) * 1000.0  # Convert m to mm
        elif pd.notna(pipe.get("std_type")):
            std_type_str = str(pipe["std_type"])
            # Try to extract DN from std_type like "DN50" or "DN50_trunk"
            match = re.search(r"DN(\d+)", std_type_str)
            if match:
                dn_mm = float(match.group(1))
        
        if dn_mm is None:
            # Fallback: estimate from default diameter
            dn_mm = getattr(config, "default_diameter_m", 0.05) * 1000.0
            logger.warning(f"Pipe {pipe.get('name', idx)}: could not extract DN, using {dn_mm}mm")
        
        # Determine role (trunk vs service) and circuit (supply vs return) from name
        pipe_name = str(pipe.get("name", ""))
        if "pipe_" in pipe_name or pipe_name.startswith("pipe_"):
            role = "trunk"
        elif "service_" in pipe_name or pipe_name.startswith("service_"):
            role = "service"
        else:
            # Fallback: infer from diameter (larger = trunk)
            role = "trunk" if dn_mm >= 50 else "service"
        
        if "_S_" in pipe_name or pipe_name.endswith("_S") or "supply" in pipe_name.lower():
            circuit = "supply"
        elif "_R_" in pipe_name or pipe_name.endswith("_R") or "return" in pipe_name.lower():
            circuit = "return"
        else:
            # Fallback: infer from flow direction or use supply as default
            circuit = "supply"
        
        # Extract pipe length
        length_m = float(pipe.get("length_km", 0.0)) * 1000.0
        if length_m <= 0:
            length_m = 0.01  # Minimum length
        
        # Extract outer diameter if available (for thermal resistance method)
        outer_diameter_m = None
        if pd.notna(pipe.get("diameter_m")):
            # For insulated pipes, add insulation thickness estimate
            # Typical: DN + ~100mm total (insulation + casing)
            d_inner_m = float(pipe["diameter_m"])
            outer_diameter_m = d_inner_m + 0.1  # Rough estimate
        
        # Extract velocity if available (for thermal resistance method h_i calculation)
        velocity_m_s = None
        if hasattr(net, "res_pipe") and net.res_pipe is not None and not net.res_pipe.empty:
            if idx in net.res_pipe.index:
                v_mean = net.res_pipe.loc[idx].get("v_mean_m_per_s")
                if pd.notna(v_mean):
                    velocity_m_s = float(v_mean)
        
        # Extract pair_id if available (for TwinPipe correction)
        pair_id = None
        if "pair_id" in net.pipe.columns and pd.notna(pipe.get("pair_id")):
            pair_id_val = pipe.get("pair_id")
            # Keep pair_id as-is (can be string like "trunk_seg_0" or int)
            # For heat_loss module, we need hashable value, but pair_id in HeatLossInputs
            # accepts int | None, so convert string to int if numeric suffix exists
            if isinstance(pair_id_val, str) and "_" in pair_id_val:
                try:
                    # Extract numeric suffix (e.g., "trunk_seg_0" -> 0)
                    pair_id = int(pair_id_val.split("_")[-1])
                except (ValueError, AttributeError):
                    pair_id = None  # Use None if conversion fails
            elif isinstance(pair_id_val, (int, float)):
                pair_id = int(pair_id_val)
            else:
                pair_id = None
        
        # Build heat loss inputs
        heat_loss_inputs = HeatLossInputs(
            dn_mm=dn_mm,
            length_m=length_m,
            t_fluid_k=t_mean_k,  # Use mean fluid temperature
            t_soil_k=t_soil,
            role=role,
            circuit=circuit,
            std_type=pipe.get("std_type"),
            outer_diameter_m=outer_diameter_m,
            insulation_thickness_m=None,  # Use defaults from method (meters, not mm)
            burial_depth_m=getattr(config, "default_burial_depth_m", 1.0),
            soil_k_w_mk=getattr(config, "soil_k_w_mk", 1.5),
            velocity_m_s=velocity_m_s,
            pair_id=pair_id,  # From pipe.pair_id column (assigned during network creation)
        )
        
        # Compute heat loss parameters
        result = compute_heat_loss(heat_loss_inputs, config, catalog)
        
        u_values.append(result.u_w_per_m2k)
        text_values.append(result.text_k)
        
        # Store diagnostics in net.pipe for auditability
        if result.diagnostics:
            for diag_key, diag_value in result.diagnostics.items():
                diag_col = f"diag_{diag_key}"
                if diag_col not in net.pipe.columns:
                    # Initialize column with NaN for all pipes
                    net.pipe[diag_col] = None
                net.pipe.at[idx, diag_col] = diag_value
        
        # Optional: log diagnostics for first few pipes
        if idx < 3 and result.diagnostics:
            logger.debug(
                f"Pipe {pipe_name}: role={role}, circuit={circuit}, DN={dn_mm}mm, "
                f"q'={result.q_loss_w_per_m:.2f} W/m, U={result.u_w_per_m2k:.3f} W/m²K"
            )
    
    net.pipe["u_w_per_m2k"] = u_values
    net.pipe["text_k"] = text_values
    # No external heat gains by default; pipe heat losses come from U*(Tfluid-Text)
    net.pipe["qext_w"] = 0.0
    
    mean_u = float(np.mean(u_values)) if u_values else 0.0
    logger.info(
        f"Applied per-pipe heat loss parameters: mean U={mean_u:.3f} W/m²K, "
        f"method={getattr(config, 'heat_loss_method', 'linear')}, "
        f"n_pipes={len(u_values)}"
    )

def _prune_trunk_to_service_subtree(
    trunk_edges: List[Tuple[Tuple[float, float], Tuple[float, float]]],
    trunk_root: Tuple[float, float],
    tee_nodes: set,
) -> List[Tuple[Tuple[float, float], Tuple[float, float]]]:
    """
    Prune trunk edges to the minimal subtree connecting the plant root to all service tee nodes.

    Assumptions:
    - trunk_edges form an acyclic connected trunk (tree) rooted at trunk_root.
    - each building attaches via a tee node (after split-edge attachment).

    Returns:
        A subset of trunk_edges, preserving original edge order, that connects trunk_root
        to every tee node. Any dead-end trunk stubs not required for service are removed.
    """
    T = nx.Graph()
    T.add_edges_from(trunk_edges)
    if trunk_root not in T:
        return trunk_edges

    # BFS parent pointers (tree-walk). In a tree, this defines unique root->node paths.
    parent: Dict[Tuple[float, float], Optional[Tuple[float, float]]] = {trunk_root: None}
    from collections import deque
    q = deque([trunk_root])
    while q:
        u = q.popleft()
        for v in T.neighbors(u):
            if v in parent:
                continue
            parent[v] = u
            q.append(v)

    keep_undirected = set()
    for tee in tee_nodes:
        if tee not in parent:
            continue
        cur = tee
        steps = 0
        while cur != trunk_root and cur in parent and parent[cur] is not None:
            pred = parent[cur]
            keep_undirected.add(tuple(sorted((pred, cur))))
            cur = pred
            steps += 1
            if steps > len(parent) + 5:
                break

    # Preserve original order, but drop edges not required.
    pruned = []
    for u, v in trunk_edges:
        if tuple(sorted((u, v))) in keep_undirected:
            pruned.append((u, v))

    # Ensure trunk_root stays (even if tee_nodes empty) - callers handle tee_nodes empty.
    return pruned if pruned else trunk_edges

def _nearest_graph_node_to_point(G: nx.Graph, point_xy: Tuple[float, float]) -> Tuple[float, float]:
    """Return the graph node closest to a given (x, y) point."""
    p = Point(point_xy)
    return min(G.nodes(), key=lambda n: p.distance(Point(n)))


def _building_attach_targets(
    G: nx.Graph,
    attach_info: List[Tuple[Tuple, Tuple[float, float]]],
) -> List[Tuple[float, float]]:
    """
    Convert building attach projections into target graph nodes.

    We use the closest endpoint of the nearest edge for each building attach point.
    """
    targets = []
    for edge, ap in attach_info:
        a, b = edge
        ap_pt = Point(ap)
        targets.append(a if ap_pt.distance(Point(a)) <= ap_pt.distance(Point(b)) else b)
    # Deduplicate while preserving order
    seen = set()
    out = []
    for t in targets:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _build_radial_trunk_edges(
    G: nx.Graph,
    root: Tuple[float, float],
    targets: List[Tuple[float, float]],
    weight: str = "length_m",
) -> List[Tuple[Tuple[float, float], Tuple[float, float]]]:
    """
    Build a radial trunk (tree) by taking the union of root->target paths from a
    single-source shortest-path tree (SPT). This guarantees:
      - one connected component (for all reachable targets)
      - no loops (acyclic)
    """
    if root not in G:
        raise ValueError("Root not in street graph")

    # Single-source shortest distances
    dist = nx.single_source_dijkstra_path_length(G, root, weight=weight)

    # Parent selection: for each node, pick one predecessor with strictly smaller dist
    parent: Dict[Tuple[float, float], Tuple[float, float]] = {}
    for node in dist.keys():
        if node == root:
            continue
        best_pred = None
        best_val = float("inf")
        for nbr in G.neighbors(node):
            if nbr not in dist:
                continue
            w = G[nbr][node].get(weight, Point(nbr).distance(Point(node)))
            val = dist[nbr] + w
            # within tolerance of shortest distance
            if abs(val - dist[node]) <= 1e-6:
                if dist[nbr] < best_val:
                    best_val = dist[nbr]
                    best_pred = nbr
        if best_pred is not None:
            parent[node] = best_pred

    # Collect edges by walking parents from each target up to root
    edges = set()
    for t in targets:
        if t == root:
            continue
        if t not in dist:
            continue
        cur = t
        steps = 0
        while cur != root and cur in parent:
            pred = parent[cur]
            edges.add((pred, cur))
            cur = pred
            steps += 1
            if steps > len(dist) + 5:
                break

    # Ensure connectedness of the resulting trunk (within the selected targets)
    if edges:
        T = nx.Graph()
        T.add_edges_from(edges)
        T.add_node(root)
        # It's ok if some targets were duplicates; but trunk must be connected
        if not nx.is_connected(T):
            logger.warning("Radial trunk edges are not fully connected; this indicates unreachable targets or parent assignment issues.")

    return list(edges)


def _choose_plant_coords_on_nearby_other_street(
    streets: gpd.GeoDataFrame,
    buildings: gpd.GeoDataFrame,
    selected_street_name: str,
    buffer_m: float,
) -> Optional[Tuple[float, float]]:
    """
    Choose a plant location on a nearby street that is NOT the selected street.

    Strategy:
    - Take the buildings centroid.
    - Consider street segments intersecting a buffer around buildings.
    - Exclude segments whose street name matches the selected street (normalized).
    - Pick the street segment closest to the centroid.
    - Place plant at the nearest point on that segment to the centroid.
    """
    if streets is None or streets.empty:
        return None
    if buildings is None or buildings.empty:
        return None

    # Determine street name column
    street_name_col = None
    for col in ("street_name", "name", "strasse", "str"):
        if col in streets.columns:
            street_name_col = col
            break

    selected_norm = normalize_street_name(selected_street_name)

    centroid = buildings.geometry.union_all().centroid
    area = buildings.geometry.union_all().buffer(buffer_m)

    candidates = streets[streets.geometry.intersects(area)].copy()
    if candidates.empty:
        return None

    if street_name_col:
        names_norm = candidates[street_name_col].astype(str).apply(normalize_street_name)
        candidates = candidates[names_norm != selected_norm].copy()

    if candidates.empty:
        return None

    # Pick closest candidate to centroid
    candidates["__dist"] = candidates.geometry.distance(centroid)
    best = candidates.sort_values("__dist").iloc[0]
    geom = best.geometry
    if geom is None or geom.is_empty:
        return None

    # Nearest point on line/multiline
    try:
        p = geom.interpolate(geom.project(centroid))
    except Exception:
        # MultiLineString fallback: choose closest sub-geom
        try:
            parts = list(getattr(geom, "geoms", []))
            if not parts:
                return None
            parts = sorted(parts, key=lambda g: g.distance(centroid))
            g0 = parts[0]
            p = g0.interpolate(g0.project(centroid))
        except Exception:
            return None

    return (float(p.x), float(p.y))

def _filter_streets_to_cluster(
    streets: gpd.GeoDataFrame,
    buildings: gpd.GeoDataFrame,
    buffer_m: float,
    plant_coords: Optional[Tuple[float, float]] = None,
) -> Tuple[List[Tuple], nx.Graph]:
    """
    Filter streets to those within or intersecting the building cluster.
    
    If streets are already filtered by name (e.g., in load_cluster_data),
    this function will use them as-is, only applying minimal bounding box
    filtering as a safety check. This ensures the trunk only uses streets
    where buildings actually attach.
    """
    # Check if streets are already filtered (e.g., by name)
    # If all streets have the same name, they're likely already filtered
    street_name_col = None
    for col in ['street_name', 'name', 'strasse', 'str']:
        if col in streets.columns:
            street_name_col = col
            break
    
    # Build a bounding geometry that covers BOTH the building cluster and the plant location.
    # This is crucial when the plant is far from the cluster (e.g., fixed CHP coordinates),
    # otherwise the street graph can be disconnected from plant -> buildings.
    building_bounds = buildings.total_bounds
    bbox = box(*building_bounds).buffer(buffer_m)
    if plant_coords is not None:
        try:
            # Expand to include the plant point, and also include the corridor between plant and cluster bbox
            p = Point(plant_coords)
            bbox = bbox.union(p).buffer(buffer_m)
            # Add a corridor to encourage connectivity (buffered line from plant to cluster centroid)
            c = buildings.geometry.union_all().centroid
            corridor = LineString([(p.x, p.y), (c.x, c.y)]).buffer(max(buffer_m, 200.0))
            bbox = bbox.union(corridor)
        except Exception:
            # Fallback: just include a local plant buffer
            try:
                plant_buf = Point(plant_coords).buffer(max(200.0, buffer_m))
                bbox = bbox.union(plant_buf)
            except Exception:
                pass

    if street_name_col and len(streets) > 0:
        unique_names = streets[street_name_col].dropna().unique()
        if len(unique_names) == 1:
            # Streets are already filtered by name, use as-is with minimal buffer
            logger.info(f"Streets already filtered to single street '{unique_names[0]}', using as-is")
            streets_in_cluster = streets.copy()
        else:
            # Multiple street names, apply bounding box filtering
            streets_in_cluster = streets[streets.geometry.apply(lambda g: g.intersects(bbox))]
            logger.info(f"Multiple street names detected, filtering by bounding box: {len(streets_in_cluster)} segments")
    else:
        # No street name column or empty, apply bounding box filtering
        streets_in_cluster = streets[streets.geometry.apply(lambda g: g.intersects(bbox))]
        logger.info(f"Filtering streets by bounding box: {len(streets_in_cluster)} segments")
    
    if len(streets_in_cluster) == 0:
        raise ValueError("No streets found within cluster area")
    
    # Build NetworkX graph
    G = _build_street_graph(streets_in_cluster)
    
    # Get edge list
    edges = list(G.edges())
    
    logger.info(f"Using {len(streets_in_cluster)} street segments, {len(edges)} graph edges for trunk topology")
    
    return edges, G

def _build_street_graph(streets: gpd.GeoDataFrame) -> nx.Graph:
    """Convert streets GeoDataFrame to NetworkX graph."""
    G = nx.Graph()

    # Snap near-identical street endpoints to improve connectivity (street data often has tiny gaps).
    snap_tol_m = 1.0
    buckets: Dict[Tuple[int, int], List[Tuple[float, float]]] = {}
    snapped_count = 0

    def _snap_node(x: float, y: float) -> Tuple[float, float]:
        nonlocal snapped_count
        cand = (round(float(x), 2), round(float(y), 2))
        if snap_tol_m <= 0:
            return cand
        bx = int(np.floor(cand[0] / snap_tol_m))
        by = int(np.floor(cand[1] / snap_tol_m))
        best = None
        best_d = float("inf")
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for n in buckets.get((bx + dx, by + dy), []):
                    d = Point(cand).distance(Point(n))
                    if d <= snap_tol_m and d < best_d:
                        best = n
                        best_d = d
        if best is not None:
            snapped_count += 1
            return best
        buckets.setdefault((bx, by), []).append(cand)
        return cand
    
    for idx, row in streets.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        
        # Handle MultiLineString
        if geom.geom_type == 'MultiLineString':
            lines = list(geom.geoms)
        else:
            lines = [geom]
        
        for line in lines:
            coords = list(line.coords)
            for i in range(len(coords) - 1):
                start = _snap_node(coords[i][0], coords[i][1])
                end = _snap_node(coords[i + 1][0], coords[i + 1][1])
                
                length_m = Point(start).distance(Point(end))
                # Skip zero-length segments (duplicate coordinates) to avoid zero-length pipes later
                if length_m < 0.01:
                    continue
                
                G.add_edge(start, end, 
                          length_m=length_m,
                          geometry=LineString([start, end]),
                          street_name=row.get('street_name', ''),
                          edge_id=f"{idx}_{i}")
    
    if snapped_count > 0:
        logger.info(f"Snapped {snapped_count} street endpoints within {snap_tol_m} m to improve graph connectivity")
    
    return G


def _bridge_disconnected_target_components(
    G: nx.Graph,
    plant_node: Tuple[float, float],
    target_nodes: List[Tuple[float, float]],
) -> int:
    """
    If the street graph is disconnected (typically due to tiny topology gaps),
    add minimal "virtual bridge" edges so all target_nodes become reachable
    from plant_node.
    """
    if G.number_of_nodes() == 0 or plant_node not in G:
        return 0

    comps = list(nx.connected_components(G))
    if len(comps) <= 1:
        return 0

    comp_idx: Dict[Tuple[float, float], int] = {}
    for i, comp in enumerate(comps):
        for n in comp:
            comp_idx[n] = i

    plant_c = comp_idx.get(plant_node, None)
    if plant_c is None:
        return 0

    needed = sorted({comp_idx.get(t) for t in target_nodes if comp_idx.get(t) is not None and comp_idx.get(t) != plant_c})
    if not needed:
        return 0

    plant_nodes = list(comps[plant_c])
    plant_pts = [Point(n) for n in plant_nodes]
    tree = STRtree(plant_pts)
    id_to_node = {id(pt): node for pt, node in zip(plant_pts, plant_nodes)}

    bridged = 0
    for c in needed:
        comp_nodes = list(comps[c])
        best_d = float("inf")
        best_u = None
        best_v = None
        for v in comp_nodes:
            q = Point(v)
            nearest = tree.nearest(q)
            if isinstance(nearest, (int, np.integer)):
                u = plant_nodes[int(nearest)]
                u_pt = plant_pts[int(nearest)]
            else:
                u = id_to_node.get(id(nearest))
                u_pt = nearest
            if u is None:
                continue
            d = float(q.distance(u_pt))
            if d < best_d:
                best_d = d
                best_u = u
                best_v = v
        if best_u is not None and best_v is not None and not G.has_edge(best_u, best_v):
            G.add_edge(
                best_u,
                best_v,
                length_m=max(best_d, 0.01),
                geometry=LineString([best_u, best_v]),
                street_name="virtual_bridge",
                edge_id=f"virtual_bridge_{bridged}",
            )
            bridged += 1

    return bridged

def _build_main_trunk(
    G: nx.Graph,
    plant_coords: Tuple[float, float],
    all_edges: List[Tuple],
    buildings: Optional[gpd.GeoDataFrame] = None,
    loop_mode: bool = True
) -> Tuple[Tuple[float, float], List[Tuple], List[Tuple]]:
    """
    Build main arterial trunk path.
    
    If loop_mode=True: Creates closed loop topology that encompasses buildings
    If loop_mode=False: Creates linear path from plant to farthest node
    """
    
    # Find nearest graph node to plant
    plant_point = Point(plant_coords)
    plant_node = min(G.nodes(), key=lambda n: plant_point.distance(Point(n)))
    
    # This helper is legacy (the current implementation uses a radial shortest-path trunk).
    # Keep it correct + simple to avoid syntax errors, and use it only as a fallback.
    lengths = nx.single_source_dijkstra_path_length(G, plant_node, weight="length_m")
    far_node = max(lengths.keys(), key=lambda k: lengths[k]) if lengths else plant_node
    try:
        path_nodes = nx.shortest_path(G, plant_node, far_node, weight="length_m")
    except nx.NetworkXNoPath:
        mst = nx.minimum_spanning_tree(G, weight="length_m")
        path_nodes = list(nx.dfs_preorder_nodes(mst, source=plant_node))

    path_edges = [tuple(sorted([path_nodes[i], path_nodes[i + 1]])) for i in range(len(path_nodes) - 1)]

    if loop_mode:
        logger.warning("loop_mode requested, but legacy loop builder is disabled; using linear path fallback.")

    logger.info(f"Main trunk (fallback): {len(path_nodes)} nodes, {len(path_edges)} edges")
    return plant_node, path_nodes, path_edges

def _compute_building_attach_nodes(
    buildings: gpd.GeoDataFrame,
    G: nx.Graph
) -> List[Tuple[Tuple, Tuple[float, float]]]:
    """
    Compute attach nodes for buildings by projecting to nearest street edges.
    Returns list of (edge, attach_point) tuples where attach_point is the projection on the edge.
    This ensures each building has a unique attach point, even if on the same edge.
    """
    attach_info = []
    
    for idx, building in buildings.iterrows():
        building_point = building.geometry.centroid
        
        # Find nearest edge in graph
        best_edge = None
        best_proj = None
        best_dist = float('inf')
        
        for edge in G.edges():
            line = LineString([edge[0], edge[1]])
            proj = line.interpolate(line.project(building_point))
            dist = building_point.distance(proj)
            
            if dist < best_dist:
                best_edge = edge
                best_proj = (proj.x, proj.y)
                best_dist = dist
        
        if best_edge is not None and best_proj is not None:
            attach_info.append((best_edge, best_proj))
    
    logger.info(f"Computed {len(attach_info)} building attach points")
    return attach_info

def _build_trunk_through_all_buildings(
    G: nx.Graph,
    plant_node: Tuple[float, float],
    attach_info: List[Tuple[Tuple, Tuple[float, float]]]
) -> List[Tuple]:
    """
    Build trunk as a path from plant through all buildings, ordered along the street.
    The supply trunk goes: plant -> building1 -> building2 -> ... -> last building
    The return trunk goes: last building -> ... -> building2 -> building1 -> plant (reverse path)
    
    Args:
        attach_info: List of (edge, attach_point) tuples for each building
    """
    if not attach_info:
        logger.warning("No attach info, using empty trunk")
        return []
    
    # Get all unique edges that have buildings
    edges_with_buildings = list(set(edge for edge, _ in attach_info))
    
    if len(edges_with_buildings) == 1:
        # All buildings on same edge - trunk goes: plant -> start of edge -> along edge -> end of edge
        edge = edges_with_buildings[0]
        trunk_edges = set([edge])
        
        # Connect plant to nearest endpoint of edge
        edge_start, edge_end = edge[0], edge[1]
        dist_to_start = Point(plant_node).distance(Point(edge_start))
        dist_to_end = Point(plant_node).distance(Point(edge_end))
        
        # Determine which end to connect to (prefer the end that's farther from plant for longer path)
        # But also consider building order along edge
        line = LineString([edge_start, edge_end])
        attach_points = [ap for _, ap in attach_info]
        attach_points_sorted = sorted(
            attach_points,
            key=lambda p: line.project(Point(p))
        )
        
        # First building is at start, last building is at end
        first_building_point = attach_points_sorted[0]
        last_building_point = attach_points_sorted[-1]
        
        # Connect plant to start of edge (where first building is)
        # Path goes: plant -> edge_start -> edge_end (where last building is)
        target = edge_start
        
        try:
            path_to_edge = nx.shortest_path(G, plant_node, target, weight='length_m')
            for i in range(len(path_to_edge) - 1):
                e = tuple(sorted([path_to_edge[i], path_to_edge[i+1]]))
                trunk_edges.add(e)
        except nx.NetworkXNoPath:
            # Plant might already be on edge, check if plant is one of the endpoints
            if plant_node == edge_start or plant_node == edge_end:
                # Plant is on edge, trunk is just the edge
                pass
            else:
                # Try to find any path
                try:
                    # Try connecting to other end
                    path_to_edge = nx.shortest_path(G, plant_node, edge_end, weight='length_m')
                    for i in range(len(path_to_edge) - 1):
                        e = tuple(sorted([path_to_edge[i], path_to_edge[i+1]]))
                        trunk_edges.add(e)
                except:
                    pass
        
        trunk_edges_list = list(trunk_edges)
        logger.info(f"Built trunk path through {len(attach_info)} buildings on 1 edge: {len(trunk_edges_list)} edges (plant -> edge start -> edge end)")
        return trunk_edges_list
    
    # Multiple edges: build path through all edges
    # Group buildings by edge and order them along each edge
    edge_to_buildings = {}
    for edge, attach_point in attach_info:
        if edge not in edge_to_buildings:
            edge_to_buildings[edge] = []
        edge_to_buildings[edge].append(attach_point)
    
    # For each edge, order attach points by distance along edge
    ordered_edges = []
    for edge, attach_points in edge_to_buildings.items():
        line = LineString([edge[0], edge[1]])
        # Sort attach points by distance along line from start
        attach_points_sorted = sorted(
            attach_points,
            key=lambda p: line.project(Point(p))
        )
        ordered_edges.append((edge, attach_points_sorted))
    
    # Order edges by proximity to plant (greedy nearest-neighbor)
    visited_edges = set()
    trunk_edges = set()
    current = plant_node
    
    while len(visited_edges) < len(ordered_edges):
        # Find nearest unvisited edge
        best_edge = None
        best_target = None
        best_path = None
        best_dist = float('inf')
        
        for edge, attach_points in ordered_edges:
            if edge in visited_edges:
                continue
            
            edge_start, edge_end = edge[0], edge[1]
            dist_to_start = Point(current).distance(Point(edge_start))
            dist_to_end = Point(current).distance(Point(edge_end))
            
            target = edge_start if dist_to_start < dist_to_end else edge_end
            
            try:
                path = nx.shortest_path(G, current, target, weight='length_m')
                dist = sum(
                    G[path[i]][path[i+1]].get('length_m', Point(path[i]).distance(Point(path[i+1])))
                    for i in range(len(path) - 1)
                )
                
                if dist < best_dist:
                    best_dist = dist
                    best_edge = edge
                    best_target = target
                    best_path = path
            except nx.NetworkXNoPath:
                continue
        
        if best_edge is None:
            break
        
        # Add path to edge
        if best_path:
            for i in range(len(best_path) - 1):
                e = tuple(sorted([best_path[i], best_path[i+1]]))
                trunk_edges.add(e)
        
        # Add edge itself
        trunk_edges.add(best_edge)
        visited_edges.add(best_edge)
        
        # Update current to opposite end of edge
        edge_start, edge_end = best_edge[0], best_edge[1]
        current = edge_end if best_target == edge_start else edge_start
    
    trunk_edges_list = list(trunk_edges)
    logger.info(f"Built trunk path through {len(attach_info)} buildings on {len(edges_with_buildings)} edges: {len(trunk_edges_list)} edges")
    return trunk_edges_list

def _create_path_from_trunk_edges(
    G: nx.Graph,
    plant_node: Tuple[float, float],
    trunk_edges: List[Tuple]
) -> Tuple[List[Tuple], List[Tuple]]:
    """
    Create a path through trunk edges from plant to last building.
    Supply trunk: plant -> building1 -> building2 -> ... -> last building
    Return trunk: last building -> ... -> building2 -> building1 -> plant (reverse path)
    
    The trunk_edges should already form a path through all buildings from _build_trunk_from_paths_to_buildings.
    This function extracts the node sequence and ensures edges are in order.
    """
    if not trunk_edges:
        logger.warning("No trunk edges, returning empty path")
        return [plant_node], []
    
    # Build path by following edges from plant
    path_nodes = [plant_node]
    path_edges = []
    remaining_edges = list(trunk_edges)
    current = plant_node
    
    # Follow edges to build path
    while remaining_edges:
        found_next = False
        for i, edge in enumerate(remaining_edges):
            if edge[0] == current:
                path_nodes.append(edge[1])
                path_edges.append(edge)
                current = edge[1]
                remaining_edges.pop(i)
                found_next = True
                break
            elif edge[1] == current:
                # Reverse edge direction
                reversed_edge = (edge[1], edge[0])
                path_nodes.append(edge[0])
                path_edges.append(edge)  # Keep original edge tuple
                current = edge[0]
                remaining_edges.pop(i)
                found_next = True
                break
        
        if not found_next:
            # No more connected edges from current node
            # Try to find any edge that connects to a node already in path
            for i, edge in enumerate(remaining_edges):
                if edge[0] in path_nodes:
                    # Connect from existing node
                    idx = path_nodes.index(edge[0])
                    if idx < len(path_nodes) - 1:
                        # Insert after this node
                        path_nodes.insert(idx + 1, edge[1])
                        path_edges.insert(idx, edge)
                        remaining_edges.pop(i)
                        found_next = True
                        break
                elif edge[1] in path_nodes:
                    # Connect from existing node (reverse)
                    idx = path_nodes.index(edge[1])
                    if idx < len(path_nodes) - 1:
                        path_nodes.insert(idx + 1, edge[0])
                        path_edges.insert(idx, edge)
                        remaining_edges.pop(i)
                        found_next = True
                        break
            
            if not found_next:
                # Add remaining edges as disconnected segments
                for edge in remaining_edges:
                    if edge[0] not in path_nodes:
                        path_nodes.append(edge[0])
                    if edge[1] not in path_nodes:
                        path_nodes.append(edge[1])
                    if edge not in path_edges:
                        path_edges.append(edge)
                break
    
    logger.info(f"Created path through trunk: {len(path_nodes)} nodes, {len(path_edges)} edges")
    logger.info(f"Path starts at plant: {path_nodes[0]}, ends at: {path_nodes[-1]}")
    return path_nodes, path_edges

def _assign_exclusive_spur_points(
    buildings: gpd.GeoDataFrame,
    trunk_edges: List[Tuple],
    G: nx.Graph,
    max_length_m: float
) -> Dict[str, Dict[str, Any]]:
    """
    Assign each building to an EXCLUSIVE spur attachment point.
    No trunk point is shared by multiple buildings.
    """
    assignments = {}
    used_attach_points = set()
    
    for idx, building in buildings.iterrows():
        building_id = building['building_id']
        building_point = building.geometry.centroid
        
        # Find nearest trunk edge
        best_edge, best_point, best_dist = None, None, float('inf')
        
        for edge in trunk_edges:
            line = LineString([edge[0], edge[1]])
            proj = line.interpolate(line.project(building_point))
            dist = building_point.distance(proj)
            
            if dist < best_dist and dist <= max_length_m:
                # Check if projection point is too close to used points
                # Use the same rounding as street graph nodes (2 decimals) so attach points can be
                # promoted to true trunk nodes during "split_edge_per_building".
                attach_key = (round(proj.x, 2), round(proj.y, 2))
                if attach_key in used_attach_points:
                    continue  # Already taken, try next best
                
                best_edge = edge
                best_point = proj
                best_dist = dist
        
        if best_edge is None:
            logger.warning(f"Building {building_id} has no valid spur attachment")
            continue
        
        # Mark this point as used
        attach_key = (round(best_point.x, 2), round(best_point.y, 2))
        used_attach_points.add(attach_key)
        
        assignments[building_id] = {
            'edge': best_edge,
            'attach_point': attach_key,
            'building_point': (building_point.x, building_point.y),
            'distance_m': best_dist,
            'exclusive': True
        }
    
    logger.info(f"Assigned {len(assignments)} buildings to exclusive spur points")
    return assignments


def _split_trunk_edges_at_attach_points(
    trunk_edges: List[Tuple[Tuple[float, float], Tuple[float, float]]],
    spur_assignments: Dict[str, Dict[str, Any]],
) -> Tuple[List[Tuple[Tuple[float, float], Tuple[float, float]]], Dict[str, Tuple[float, float]]]:
    """
    Implement "tee on main": split trunk edges at building attach points.

    For each trunk edge (u, v) that has >=1 attach point:
      - sort attach points along the edge geometry
      - replace (u, v) with chain u -> a1 -> a2 -> ... -> v
      - return attach_node_for_building so service spurs can connect directly at ai

    After splitting, we no longer need intermediate trunk service junctions (S_T_*/R_T_*)
    nor trunk_conn_* pipes. The attach nodes are true trunk nodes.
    """
    # Group attach points by undirected edge key
    edge_to_pts: Dict[Tuple[Tuple[float, float], Tuple[float, float]], List[Tuple[str, Tuple[float, float]]]] = {}
    for bid, a in spur_assignments.items():
        uv = a.get("edge")
        ap = a.get("attach_point")
        if uv is None or ap is None:
            continue
        key = tuple(sorted((uv[0], uv[1])))
        edge_to_pts.setdefault(key, []).append((bid, ap))

    new_edges: List[Tuple[Tuple[float, float], Tuple[float, float]]] = []
    attach_node_for_building: Dict[str, Tuple[float, float]] = {}

    for (u, v) in trunk_edges:
        key = tuple(sorted((u, v)))
        pts = edge_to_pts.get(key, [])
        if not pts:
            new_edges.append((u, v))
            continue

        ls = LineString([u, v])
        pts_sorted = sorted(pts, key=lambda t: ls.project(Point(t[1])))

        chain_nodes: List[Tuple[float, float]] = [u]
        for bid, ap in pts_sorted:
            # attach_point is already rounded consistently (2 decimals)
            n = (float(ap[0]), float(ap[1]))
            chain_nodes.append(n)
            attach_node_for_building[bid] = n
        chain_nodes.append(v)

        for a, b in zip(chain_nodes[:-1], chain_nodes[1:]):
            if a == b:
                continue
            new_edges.append((a, b))

    # Deduplicate edges (undirected) while preserving order
    seen = set()
    dedup: List[Tuple[Tuple[float, float], Tuple[float, float]]] = []
    for u, v in new_edges:
        k = tuple(sorted((u, v)))
        if k in seen:
            continue
        seen.add(k)
        dedup.append((u, v))

    return dedup, attach_node_for_building

def _create_trunk_spur_pandapipes(
    plant_attach_node: Tuple[float, float],
    plant_coords: Tuple[float, float],
    trunk_nodes: List[Tuple],
    trunk_edges: List[Tuple],
    spur_assignments: Dict[str, Dict],
    buildings: gpd.GeoDataFrame,
    design_loads_kw: Dict[str, float],
    config: CHAConfig
) -> pp.pandapipesNet:
    """
    Create complete pandapipes network with proper dual-network structure.
    
    Implements proper district heating network with:
    - Separate supply and return junctions for trunk nodes
    - Separate supply and return pipes for trunk edges
    - Building junctions (supply + return)
    - Heat consumers connecting building supply to return (models heat extraction)
    - Service pipes (supply + return) connecting buildings to trunk
    - Proper pump placement (plant return → plant supply)
    - Distance-based pressure initialization
    """
    
    net = pp.create_empty_network(f"dh_trunk_spur", fluid="water")
    net.junction_geodata = pd.DataFrame(columns=["x", "y"])
    
    # Step 1: Calculate distances from plant connection node for pressure initialization
    trunk_graph = nx.Graph()
    for edge in trunk_edges:
        u, v = edge
        length_m = Point(u).distance(Point(v))
        trunk_graph.add_edge(u, v, weight=length_m)
    
    node_distances = {}
    if plant_attach_node in trunk_nodes and nx.has_path(trunk_graph, plant_attach_node, plant_attach_node):
        try:
            distances = nx.single_source_dijkstra_path_length(trunk_graph, plant_attach_node, weight='weight')
            node_distances = distances
        except Exception as e:
            logger.warning(f"Could not calculate shortest paths: {e}")
            for node in trunk_nodes:
                node_distances[node] = np.sqrt((node[0] - plant_attach_node[0])**2 + (node[1] - plant_attach_node[1])**2)
    else:
        for node in trunk_nodes:
            node_distances[node] = np.sqrt((node[0] - plant_attach_node[0])**2 + (node[1] - plant_attach_node[1])**2)
    
    max_distance = max(node_distances.values()) if node_distances else 1.0
    
    # Step 2: Create trunk junctions with dual-network structure (supply + return)
    trunk_junction_map = {}  # node -> {'supply': junc_idx, 'return': junc_idx}
    
    for node in trunk_nodes:
        distance_m = node_distances.get(node, 0.0)
        
        # Calculate pressure drop: 0.001 bar/m = 0.1 bar per 100m
        pressure_drop_per_m = 0.001  # bar/m
        pressure_drop = distance_m * pressure_drop_per_m
        
        # Supply pressure: system pressure minus drop, minimum 1.0 bar
        supply_pressure = max(1.0, config.system_pressure_bar - pressure_drop)
        # Return pressure: slightly lower (0.1 bar additional drop)
        return_pressure = max(0.9, supply_pressure - 0.1)
        
        # Supply junction
        junc_s = pp.create_junction(
            net,
            pn_bar=supply_pressure,
            tfluid_k=config.supply_temp_k,
            name=f"S_{node[0]:.1f}_{node[1]:.1f}"
        )
        
        # Return junction (slightly offset for visualization)
        junc_r = pp.create_junction(
            net,
            pn_bar=return_pressure,
            tfluid_k=config.return_temp_k,
            name=f"R_{node[0]:.1f}_{node[1]:.1f}"
        )
        
        trunk_junction_map[node] = {'supply': junc_s, 'return': junc_r}
        
        # Store junction coordinates
        net.junction_geodata.loc[junc_s, ["x", "y"]] = [node[0], node[1]]
        net.junction_geodata.loc[junc_r, ["x", "y"]] = [node[0], node[1]]
    
    # Step 3: Create plant junctions (supply + return) ALWAYS separate from trunk.
    # Plant is located at plant_coords (typically on a nearby different street).
    plant_distance = 0.0
    plant_supply_pressure = config.system_pressure_bar
    plant_return_pressure = max(0.9, plant_supply_pressure - 0.1)
    
    plant_supply_junc = pp.create_junction(
        net,
        pn_bar=plant_supply_pressure,
        tfluid_k=config.supply_temp_k,
        name="plant_supply"
    )
    plant_return_junc = pp.create_junction(
        net,
        pn_bar=plant_return_pressure,
        tfluid_k=config.return_temp_k,
        name="plant_return"
    )
    net.junction_geodata.loc[plant_supply_junc, ["x", "y"]] = [plant_coords[0], plant_coords[1]]
    net.junction_geodata.loc[plant_return_junc, ["x", "y"]] = [plant_coords[0], plant_coords[1]]
    logger.info("Created separate plant junctions (off-trunk)")
    
    # Step 4: Determine pipe directions (from plant to buildings)
    trunk_tree = nx.DiGraph()
    for edge in trunk_edges:
        u, v = edge
        trunk_tree.add_edge(u, v)
        trunk_tree.add_edge(v, u)
    
    if trunk_tree.has_node(plant_attach_node):
        distances = nx.single_source_shortest_path_length(trunk_tree, plant_attach_node)
    else:
        distances = {}
    
    # Step 5: Create trunk pipes (supply + return)
    for edge in trunk_edges:
        u, v = edge
        length_m = float(Point(u).distance(Point(v)))
        # Pipe lengths must reflect geometry. Only protect against *near-zero* length segments.
        length_m = max(0.01, length_m)
        length_km = length_m / 1000.0
        
        # Determine direction: from node closer to plant TO node farther from plant
        if plant_attach_node in distances:
            dist_u = distances.get(u, float('inf'))
            dist_v = distances.get(v, float('inf'))
            if dist_u <= dist_v:
                from_node, to_node = u, v
            else:
                from_node, to_node = v, u
        else:
            from_node, to_node = u, v
        
        # Get junctions
        u_supply = trunk_junction_map[u]['supply']
        u_return = trunk_junction_map[u]['return']
        v_supply = trunk_junction_map[v]['supply']
        v_return = trunk_junction_map[v]['return']
        
        # Supply pipe (from_node → to_node)
        pp.create_pipe_from_parameters(
            net,
            from_junction=trunk_junction_map[from_node]['supply'],
            to_junction=trunk_junction_map[to_node]['supply'],
            length_km=length_km,
            diameter_m=0.15,  # Initial DN150 (safe default)
            k_mm=0.01,
            name=f"pipe_S_{from_node[0]:.1f}_{from_node[1]:.1f}_to_{to_node[0]:.1f}_{to_node[1]:.1f}",
            sections=3
        )
    
        # Return pipe (to_node → from_node, reversed)
        pp.create_pipe_from_parameters(
            net,
            from_junction=trunk_junction_map[to_node]['return'],
            to_junction=trunk_junction_map[from_node]['return'],
            length_km=length_km,
            diameter_m=0.15,  # Initial DN150 (safe default)
            k_mm=0.01,
            name=f"pipe_R_{to_node[0]:.1f}_{to_node[1]:.1f}_to_{from_node[0]:.1f}_{from_node[1]:.1f}",
            sections=3
        )
    
    # Step 5.25: Assign pair_id to geometrically adjacent supply/return pipes (TwinPipe)
    # This enables TwinPipe heat loss correction in the heat_loss module
    if getattr(config, "supply_return_interaction", True):
        # Create pair_id column if it doesn't exist
        if "pair_id" not in net.pipe.columns:
            net.pipe["pair_id"] = None
        
        for edge_idx, edge in enumerate(trunk_edges):
            u, v = edge
            # Format strings match pipe naming convention
            u_str = f"{u[0]:.1f}_{u[1]:.1f}"
            v_str = f"{v[0]:.1f}_{v[1]:.1f}"
            
            # Create unique pair_id for this trunk segment
            pair_id = f"trunk_seg_{edge_idx}"
            
            # Find supply and return pipes for this edge (by name pattern)
            supply_pattern = f"pipe_S_{u_str}_to_{v_str}"
            return_pattern = f"pipe_R_{v_str}_to_{u_str}"
            # Also check reversed (in case naming is different)
            supply_pattern_rev = f"pipe_S_{v_str}_to_{u_str}"
            return_pattern_rev = f"pipe_R_{u_str}_to_{v_str}"
            
            supply_mask = (
                net.pipe['name'].astype(str).str.contains(supply_pattern, regex=False, na=False) |
                net.pipe['name'].astype(str).str.contains(supply_pattern_rev, regex=False, na=False)
            )
            return_mask = (
                net.pipe['name'].astype(str).str.contains(return_pattern, regex=False, na=False) |
                net.pipe['name'].astype(str).str.contains(return_pattern_rev, regex=False, na=False)
            )
            
            # Assign pair_id to both pipes
            net.pipe.loc[supply_mask, 'pair_id'] = pair_id
            net.pipe.loc[return_mask, 'pair_id'] = pair_id
        
        # Also assign pair_id to plant connection pipes (supply and return are paired)
        plant_supply_mask = net.pipe['name'].astype(str) == "pipe_S_plant_to_trunk"
        plant_return_mask = net.pipe['name'].astype(str) == "pipe_R_plant_to_trunk"
        net.pipe.loc[plant_supply_mask, 'pair_id'] = "trunk_plant"
        net.pipe.loc[plant_return_mask, 'pair_id'] = "trunk_plant"
        
        n_paired = (net.pipe['pair_id'].notna()).sum()
        logger.debug(f"Assigned pair_id to {n_paired} trunk pipes (TwinPipe enabled)")
    
    # Step 5.5: Connect plant to the trunk via exactly ONE supply + ONE return pipe at plant_attach_node
    if plant_attach_node not in trunk_junction_map:
        raise ValueError("plant_attach_node is not part of trunk_junction_map (trunk is disconnected).")

    plant_to_trunk_dist = float(Point(plant_coords).distance(Point(plant_attach_node)))
    # Keep the true geometric length; only protect against *near-zero* if plant coincides with attach node
    plant_to_trunk_length_km = max(plant_to_trunk_dist / 1000.0, 0.01 / 1000.0)
        
    pp.create_pipe_from_parameters(
        net,
        from_junction=plant_supply_junc,
        to_junction=trunk_junction_map[plant_attach_node]['supply'],
        length_km=plant_to_trunk_length_km,
        diameter_m=0.15,  # Initial DN150 (safe default)
        k_mm=0.01,
        name="pipe_S_plant_to_trunk",
        sections=3,
    )
    pp.create_pipe_from_parameters(
        net,
        from_junction=trunk_junction_map[plant_attach_node]['return'],
        to_junction=plant_return_junc,
        length_km=plant_to_trunk_length_km,
        diameter_m=0.15,
        k_mm=0.01,
        name="pipe_R_plant_to_trunk",
            sections=3
        )
    logger.info(f"✅ Plant connected to trunk at {plant_attach_node} (distance: {plant_to_trunk_dist:.1f}m)")
    
    # Step 6: Create building connections by teeing service pipes directly off the trunk
    # (no S_T_*/R_T_* junctions and no trunk_conn_* pipes when attach_mode="split_edge_per_building")
    building_to_junctions = {}
    
    for building_id, assignment in spur_assignments.items():
        attach_point = assignment['attach_point']
        building_point = assignment['building_point']

        # Prefer the true trunk tee node (created by split-edge attach mode)
        trunk_attach_node = assignment.get("trunk_attach_node")
        if trunk_attach_node is None:
            # Fallback: nearest trunk node to the attach point
            trunk_attach_node = min(trunk_nodes, key=lambda n: Point(n).distance(Point(attach_point)))
        if trunk_attach_node not in trunk_junction_map:
            # Fallback again: nearest existing trunk junction-map node
            trunk_attach_node = min(trunk_junction_map.keys(), key=lambda n: Point(n).distance(Point(attach_point)))
        
        # Calculate attachment distance for pressure
        attach_distance_m = node_distances.get(trunk_attach_node, 0.0)
        attach_pressure_drop = attach_distance_m * 0.001
        attach_supply_pressure = max(1.0, config.system_pressure_bar - attach_pressure_drop)
        attach_return_pressure = max(0.9, attach_supply_pressure - 0.1)

        # Tee directly off the trunk at the attach node
        trunk_service_supply_junc = trunk_junction_map[trunk_attach_node]["supply"]
        trunk_service_return_junc = trunk_junction_map[trunk_attach_node]["return"]
        
        # Create building junctions
        service_pressure_drop = 0.05  # 0.05 bar drop across service connection
        building_supply_pressure = max(0.8, attach_supply_pressure - service_pressure_drop)
        building_return_pressure = max(0.8, attach_return_pressure + service_pressure_drop)
        
        building_supply_junc = pp.create_junction(
            net,
            pn_bar=building_supply_pressure,
            tfluid_k=config.supply_temp_k,
            name=f"S_B_{building_id}"
        )
        
        building_return_junc = pp.create_junction(
            net,
            pn_bar=building_return_pressure,
            tfluid_k=config.return_temp_k,
            name=f"R_B_{building_id}"
        )
        
        # IMPORTANT: keep junction geodata at the true building location so pipe lengths match geometry.
        # (Do not offset return coordinates for visualization; supply/return separation is handled in the map.)
        net.junction_geodata.loc[building_supply_junc, ["x", "y"]] = [building_point[0], building_point[1]]
        net.junction_geodata.loc[building_return_junc, ["x", "y"]] = [building_point[0], building_point[1]]
        
        building_to_junctions[building_id] = {
            'supply': building_supply_junc,
            'return': building_return_junc
        }
        
        # Service supply pipe (trunk service → building supply)
        # Pipe lengths must reflect actual geometry between junction geodata.
        # Use the tee node coordinate (trunk_attach_node) if available, otherwise attach_point.
        attach_xy = trunk_attach_node if trunk_attach_node is not None else attach_point
        service_length_m = Point(attach_xy).distance(Point(building_point))
        # Enforce a minimum only for *near-zero* distances; never clamp long connections.
        if service_length_m < 0.01:
            service_length_m = 0.01
        
        pp.create_pipe_from_parameters(
            net,
            from_junction=trunk_service_supply_junc,
            to_junction=building_supply_junc,
            length_km=service_length_m / 1000.0,
            diameter_m=0.02,  # DN20 default, will be sized later
            k_mm=0.01,
            name=f"service_S_{building_id}",
            sections=3
        )
        
        # Service return pipe (building return → trunk service)
        pp.create_pipe_from_parameters(
            net,
            from_junction=building_return_junc,
            to_junction=trunk_service_return_junc,
            length_km=service_length_m / 1000.0,
            diameter_m=0.02,  # DN20 default
            k_mm=0.01,
            name=f"service_R_{building_id}",
            sections=3
        )
        
        # --- Building consumer model (district heating) ---
        # Use pandapipes built-in heat consumer element.
        # IMPORTANT: This requires running pipeflow in a thermal mode ("sequential" or "bidirectional")
        # to compute meaningful temperatures. We therefore run pipeflow in "sequential" mode in
        # build_trunk_spur_network().
        #
        # pandapipes requires EXACTLY TWO of:
        #   controlled_mdot_kg_per_s, qext_w, deltat_k, treturn_k
        # Option B (requested): provide qext_w + controlled_mdot_kg_per_s
        # so return temperature becomes a *result* (depends on network conditions and losses).
        load_kw = float(design_loads_kw.get(building_id, 50.0))
        qext_w = load_kw * 1000.0
        # Fix mdot using the design deltaT (prevents thermal solver from trying to back-solve mdot).
        deltat_k = max(1.0, float(config.supply_temp_k - config.return_temp_k))
        cp_j_per_kgk = 4180.0
        controlled_mdot = max(1e-5, qext_w / (cp_j_per_kgk * deltat_k))

        # Use composite model: Flow Control (valve) + Heat Exchanger (coil)
        substation_junc = pp.create_junction(
            net,
            pn_bar=building_supply_pressure - 0.1,
            tfluid_k=config.supply_temp_k,
            name=f"substation_{building_id}"
        )
        net.junction_geodata.loc[substation_junc, ["x", "y"]] = [building_point[0], building_point[1]]

        pp.create_flow_control(
            net,
            from_junction=building_supply_junc,
            to_junction=substation_junc,
            controlled_mdot_kg_per_s=controlled_mdot,
            diameter_m=0.02,
            name=f"valve_{building_id}"
        )

        pp.create_heat_exchanger(
            net,
            from_junction=substation_junc,
            to_junction=building_return_junc,
            diameter_m=0.02,
            qext_w=qext_w,
            name=f"hex_{building_id}"
        )
    
    # Step 7: Plant boundary conditions (physically correct DH)
    # - Exactly ONE ext_grid (p,T) at plant supply
    # - One circulation pump from plant return -> plant supply providing Δp (plift)
    #
    # This avoids over-constraining the thermal problem and lets the return temperature be the
    # consequence of consumer heat extraction + network mixing.
    p_supply = float(config.system_pressure_bar)
    plift_bar = float(getattr(config, "pump_plift_bar", 3.0))
    pp.create_ext_grid(
        net,
        junction=plant_supply_junc,
        p_bar=p_supply,
        t_k=config.supply_temp_k,
        name="plant_supply_slack",
    )

    pp.create_circ_pump_const_pressure(
        net,
        return_junction=plant_return_junc,
        flow_junction=plant_supply_junc,
        p_flow_bar=p_supply,   # consistent with ext_grid at supply
        plift_bar=plift_bar,   # Δp only
        t_flow_k=float(config.supply_temp_k),
        name="plant_circ_pump",
    )
    
    n_hc = len(net.heat_consumer) if hasattr(net, "heat_consumer") else 0
    n_sink = len(net.sink) if hasattr(net, "sink") else 0
    n_source = len(net.source) if hasattr(net, "source") else 0
    logger.info(
        f"Created network: {len(net.junction)} junctions, {len(net.pipe)} pipes, "
        f"{n_hc} heat_consumers, {n_sink} sinks, {n_source} sources"
    )
    return net

def _apply_pipe_sizes(net: pp.pandapipesNet, pipe_sizes: Dict[str, Any], trunk_edges: List[Tuple]):
    """
    Apply calculated DN sizes to network pipes.
    
    Args:
        net: pandapipes network
        pipe_sizes: Dict with 'trunk' and 'spurs' keys from size_trunk_and_spurs
        trunk_edges: List of trunk edge tuples (u, v) in same order as sizing
    """
    # Trunk sizes: pipe_sizes['trunk'] maps "edge_0", "edge_1", etc. to DN values
    for edge_key, dn_mm in pipe_sizes.get('trunk', {}).items():
        # Extract edge index from key like "edge_0"
        try:
            edge_idx = int(edge_key.split('_')[1])
            pair_id = f"trunk_seg_{edge_idx}"
            
            # Robust matching using pair_id (assigned in build_trunk_spur_network)
            if "pair_id" in net.pipe.columns:
                mask = net.pipe['pair_id'] == pair_id
                
                if mask.any():
                    dn_m = dn_mm / 1000.0  # Convert mm to m
                    net.pipe.loc[mask, 'diameter_m'] = dn_m
                    net.pipe.loc[mask, 'std_type'] = f"DN{int(dn_mm)}"
                    logger.debug(f"Applied DN{dn_mm} to trunk segment {pair_id} ({mask.sum()} pipes)")
                    continue
            
            # Fallback to name matching if pair_id missing or not found (legacy/safeguard)
            if edge_idx < len(trunk_edges):
                edge = trunk_edges[edge_idx]
                u, v = edge
                u_str = f"{u[0]:.1f}_{u[1]:.1f}"
                v_str = f"{v[0]:.1f}_{v[1]:.1f}"
                
                # Regex for pipe name matching
                supply_pattern = f"pipe_S_{u_str}_to_{v_str}|pipe_S_{v_str}_to_{u_str}"
                return_pattern = f"pipe_R_{u_str}_to_{v_str}|pipe_R_{v_str}_to_{u_str}"
                
                supply_mask = net.pipe['name'].astype(str).str.contains(supply_pattern, regex=True, na=False)
                return_mask = net.pipe['name'].astype(str).str.contains(return_pattern, regex=True, na=False)
                
                dn_m = dn_mm / 1000.0
                net.pipe.loc[supply_mask, 'diameter_m'] = dn_m
                net.pipe.loc[return_mask, 'diameter_m'] = dn_m
                net.pipe.loc[supply_mask, 'std_type'] = f"DN{int(dn_mm)}"
                net.pipe.loc[return_mask, 'std_type'] = f"DN{int(dn_mm)}"
                
        except (ValueError, IndexError) as e:
            logger.warning(f"Could not parse or apply edge key '{edge_key}': {e}")
            continue

    # Size plant connection pipes to match the largest trunk DN to avoid an abrupt velocity jump near plant
    try:
        trunk_dns = [int(v) for v in pipe_sizes.get('trunk', {}).values() if v is not None]
        if trunk_dns:
            dn_main_m = max(trunk_dns) / 1000.0
            plant_s = net.pipe['name'].astype(str) == "pipe_S_plant_to_trunk"
            plant_r = net.pipe['name'].astype(str) == "pipe_R_plant_to_trunk"
            net.pipe.loc[plant_s | plant_r, 'diameter_m'] = dn_main_m
    except Exception:
        pass
    
    # Service pipe sizes: pipe_sizes['spurs'] maps building_id to DN values
    for building_id, dn_mm in pipe_sizes.get('spurs', {}).items():
        # Service supply and return pipes
        supply_mask = net.pipe['name'].str.contains(f"service_S_{building_id}", na=False)
        return_mask = net.pipe['name'].str.contains(f"service_R_{building_id}", na=False)
        
        dn_m = dn_mm / 1000.0  # Convert mm to m
        net.pipe.loc[supply_mask, 'diameter_m'] = dn_m
        net.pipe.loc[return_mask, 'diameter_m'] = dn_m
        net.pipe.loc[supply_mask, 'std_type'] = f"DN{int(dn_mm)}"
        net.pipe.loc[return_mask, 'std_type'] = f"DN{int(dn_mm)}"
        
        if supply_mask.any() or return_mask.any():
            logger.debug(f"Applied DN{dn_mm} to service pipes for building {building_id}")