from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Literal, Optional, Tuple

import numpy as np

from .params import EconomicParameters, EconomicsParams
from .utils import crf

logger = logging.getLogger(__name__)

# --- Marginal Cost vs. Sunk Cost: Plant Context ---

PlantCostAllocation = Literal["full", "marginal", "proportional", "none"]


@dataclass
class PlantContext:
    """Shared plant asset context for marginal cost calculations."""

    total_capacity_kw: float = 0.0  # Total plant thermal capacity (kW)
    total_cost_eur: float = 0.0  # Total plant CAPEX (sunk cost)
    utilized_capacity_kw: float = 0.0  # Already allocated/utilized capacity (kW)
    is_built: bool = False  # Whether plant exists (sunk) or is new
    marginal_cost_per_kw: float = 150.0  # €/kW for capacity expansion

    def get_marginal_allocation(
        self, street_peak_load_kw: float, safety_factor: float = 1.2
    ) -> Dict[str, Any]:
        """
        TRUE marginal cost: Only pay for capacity expansion, not full plant.

        Args:
            street_peak_load_kw: Design peak load for the street (kW)
            safety_factor: Safety margin multiplier (default 1.2)

        Returns:
            Dict with allocated_eur, is_marginal, marginal_capacity_kw, rationale, method
        """
        required_capacity = street_peak_load_kw * safety_factor
        spare_capacity = self.total_capacity_kw - self.utilized_capacity_kw

        if spare_capacity >= required_capacity:
            # Spare capacity available - NO COST (sunk cost principle)
            return {
                "allocated_eur": 0.0,
                "allocated_cost": 0.0,  # backward compat
                "is_marginal": False,
                "marginal_capacity_kw": 0.0,
                "rationale": f"Utilizes existing spare capacity ({spare_capacity:.0f}kW available, {required_capacity:.0f}kW needed)",
                "method": "marginal",
            }
        else:
            # Need expansion - pay only for the ADDITIONAL capacity
            marginal_kw = required_capacity - spare_capacity
            cost = marginal_kw * self.marginal_cost_per_kw

            return {
                "allocated_eur": cost,
                "allocated_cost": cost,  # backward compat
                "is_marginal": True,
                "marginal_capacity_kw": marginal_kw,
                "rationale": f"Marginal capacity expansion: {marginal_kw:.0f}kW @ {self.marginal_cost_per_kw}€/kW",
                "method": "marginal",
            }

    # Backward compatibility alias
    def calculate_marginal_allocation(
        self, street_peak_load_kw: float
    ) -> Dict[str, Any]:
        """Backward-compat wrapper for get_marginal_allocation."""
        return self.get_marginal_allocation(street_peak_load_kw)


def build_plant_context_from_params(params: EconomicParameters) -> Optional[PlantContext]:
    """Build PlantContext from EconomicParameters when plant context fields are set."""
    if params.plant_total_capacity_kw <= 0:
        return None
    return PlantContext(
        total_capacity_kw=float(params.plant_total_capacity_kw),
        total_cost_eur=float(params.plant_cost_base_eur),
        utilized_capacity_kw=float(params.plant_utilized_capacity_kw),
        is_built=bool(params.plant_is_built),
        marginal_cost_per_kw=float(params.plant_marginal_cost_per_kw_eur),
    )


def get_plant_context_for_marginal(
    params: EconomicParameters,
    street_peak_load_kw: float,
) -> Optional[PlantContext]:
    """
    Get PlantContext for marginal cost allocation.
    Creates one from params if configured, or a sensible default when plant_total_capacity_kw=0.
    Default: assumes district plant with spare capacity (total=2x street peak, utilized=40%).
    """
    if params.plant_total_capacity_kw > 0:
        return build_plant_context_from_params(params)
    # Default: spare capacity exists so marginal allocation = 0
    total = max(2000.0, 2.0 * float(street_peak_load_kw))
    utilized = total * 0.4  # 40% utilized, 60% spare
    return PlantContext(
        total_capacity_kw=total,
        total_cost_eur=float(params.plant_cost_base_eur),
        utilized_capacity_kw=utilized,
        is_built=True,
        marginal_cost_per_kw=float(params.plant_marginal_cost_per_kw_eur),
    )


# --- Helper Functions for Network Cost Extraction ---


def _extract_pipe_lengths(network_results: Dict[str, Any]) -> Dict[str, float]:
    """
    Extract pipe lengths from pandapipes network results.
    Fixes the 'capex_pipes: 0' issue by properly parsing network output.
    """
    pipes = network_results.get("pipes", {})
    lengths: Dict[str, float] = {}
    for pipe_id, pipe_data in pipes.items():
        if isinstance(pipe_data, dict):
            dn = pipe_data.get("dn", "DN100")
            length = pipe_data.get("length_m", 0)
            lengths[dn] = lengths.get(dn, 0) + float(length)
    return lengths


def _calculate_lv_upgrade_cost(lv_results: Dict[str, Any]) -> float:
    """
    Calculate LV grid upgrade costs from pandapower/DHA analysis.

    Accepts:
    - total_reinforcement_cost_eur: direct cost from DHA reinforcement plan (preferred)
    - transformer_upgrade_needed, cable_length_to_replace_m, new_connection_length_m:
      granular fields for heuristic cost calculation
    """
    if not lv_results:
        return 0.0

    # Prefer direct DHA reinforcement total when available
    direct_cost = lv_results.get("total_reinforcement_cost_eur", 0.0)
    if direct_cost > 0:
        return float(direct_cost)

    # Fallback: heuristic from granular fields
    costs = {
        "transformer_upgrade": 15000.0,  # € per transformer
        "cable_replacement": 50.0,  # € per meter
        "new_connection": 200.0,  # € per meter
    }

    total = 0.0
    if lv_results.get("transformer_upgrade_needed"):
        total += costs["transformer_upgrade"]

    total += lv_results.get("cable_length_to_replace_m", 0) * costs["cable_replacement"]
    total += lv_results.get("new_connection_length_m", 0) * costs["new_connection"]

    return total


def _calculate_crf_local(rate: float, years: int) -> float:
    """Local CRF calculator (fallback)."""
    if rate == 0:
        return 1.0 / years
    return (rate * (1 + rate) ** years) / ((1 + rate) ** years - 1)


# --- New Cluster-Level LCOH Function with Proper Marginal Cost ---


def compute_lcoh_dh_for_cluster(
    annual_heat_demand_mwh: float,
    pipe_network_results: Dict[str, Any],
    connection_length_m: float,
    street_peak_load_kw: float,
    plant_context: Optional[PlantContext] = None,
    pump_cost_eur: float = 5000.0,
    params: Optional[EconomicParameters] = None,
    cost_allocation_method: Literal["marginal", "proportional", "none"] = "marginal",
) -> Dict[str, Any]:
    """
    Compute LCOH for a street cluster with proper marginal cost accounting.

    This function implements the Marginal Cost vs. Sunk Cost principle:
    - Network costs are always included (street-specific)
    - Plant costs only included if capacity expansion is triggered (marginal)
    - LV upgrade costs extracted from power simulation results

    Args:
        annual_heat_demand_mwh: Annual heat demand for the cluster (MWh)
        pipe_network_results: Dict from pandapipes simulation with 'pipes' and 'lv_results'
        connection_length_m: Trunk connection length from plant to street (m)
        street_peak_load_kw: Design peak load for the street (kW)
        plant_context: Shared plant context (for marginal allocation)
        pump_cost_eur: Street-specific pump cost (€)
        params: Economic parameters (uses defaults if None)
        cost_allocation_method: 'marginal', 'proportional', or 'none'

    Returns:
        Dict with lcoh_eur_per_mwh, capex breakdown, plant allocation details
    """
    if params is None:
        from .params import get_default_economics_params

        params = get_default_economics_params()

    if annual_heat_demand_mwh <= 0:
        return {
            "lcoh_eur_per_mwh": float("inf"),
            "capex_total": 0.0,
            "error": "Annual heat demand must be positive",
        }

    # --- 1. EXTRACT PIPE COSTS from network results ---
    pipe_lengths_m = _extract_pipe_lengths(pipe_network_results)

    capex_network = 0.0
    if pipe_lengths_m:
        for dn, length in pipe_lengths_m.items():
            cost_per_m = params.pipe_cost_eur_per_m.get(str(dn), 300.0)
            capex_network += length * cost_per_m
    else:
        # Fallback: use total pipe length if available
        total_length = pipe_network_results.get("total_pipe_length_m", 0.0)
        avg_cost = float(np.mean(list(params.pipe_cost_eur_per_m.values())))
        capex_network = total_length * avg_cost

    # --- 2. Connection cost ---
    default_pipe_cost = params.pipe_cost_eur_per_m.get("DN100", 300.0)
    capex_connection = connection_length_m * default_pipe_cost

    # --- 3. PLANT COST - MARGINAL LOGIC ---
    capex_plant = 0.0
    plant_info: Dict[str, Any] = {
        "method": cost_allocation_method,
        "allocated_eur": 0.0,
        "rationale": "No allocation",
    }

    if plant_context and cost_allocation_method == "marginal":
        # TRUE marginal cost - only expansion costs
        allocation = plant_context.get_marginal_allocation(street_peak_load_kw)
        capex_plant = allocation["allocated_eur"]
        plant_info = allocation

    elif plant_context and cost_allocation_method == "proportional":
        # Proportional - for comparison only (not recommended for street-level)
        share = (
            street_peak_load_kw / plant_context.total_capacity_kw
            if plant_context.total_capacity_kw > 0
            else 0
        )
        capex_plant = share * plant_context.total_cost_eur
        plant_info = {
            "allocated_eur": capex_plant,
            "method": "proportional",
            "capacity_share_frac": share,
            "rationale": f"Proportional: {share*100:.1f}% of total plant cost",
        }

    # --- 4. LV GRID UPGRADE COSTS ---
    lv_upgrade_cost = _calculate_lv_upgrade_cost(
        pipe_network_results.get("lv_results", {})
    )

    # --- 5. Total CAPEX ---
    total_capex = (
        capex_network + capex_connection + capex_plant + pump_cost_eur + lv_upgrade_cost
    )

    # --- 6. OPEX: Only network O&M (2%), NOT plant O&M ---
    opex_om_network = capex_network * params.dh_om_frac_per_year
    # Heat purchase cost (simplified)
    heat_price_eur_per_mwh = 50.0  # Default heat purchase price
    opex_energy = annual_heat_demand_mwh * heat_price_eur_per_mwh
    total_opex = opex_om_network + opex_energy

    # --- 7. LCOH ---
    crf_val = crf(float(params.discount_rate), int(params.lifetime_years))
    annualized = total_capex * crf_val + total_opex
    lcoh = annualized / annual_heat_demand_mwh

    return {
        "lcoh_eur_per_mwh": round(lcoh, 2),
        "capex_total": round(total_capex, 2),
        "capex_breakdown": {
            "network_pipes": round(capex_network, 2),
            "connection": round(capex_connection, 2),
            "plant_allocated": round(capex_plant, 2),
            "pump": round(pump_cost_eur, 2),
            "lv_upgrade": round(lv_upgrade_cost, 2),
        },
        "opex_annual": round(total_opex, 2),
        "opex_breakdown": {
            "network_om": round(opex_om_network, 2),
            "energy": round(opex_energy, 2),
        },
        "plant_allocation": plant_info,
        "crf": round(crf_val, 6),
        "annual_heat_mwh": annual_heat_demand_mwh,
        "methodology": "Marginal cost: Only incremental network/capacity costs included",
    }


@dataclass(frozen=True)
class DHInputs:
    heat_mwh_per_year: float
    pipe_lengths_by_dn: Optional[Dict[str, float]]
    total_pipe_length_m: float
    pump_power_kw: float


@dataclass(frozen=True)
class HPInputs:
    heat_mwh_per_year: float
    hp_total_capacity_kw_th: float
    cop_annual_average: float
    max_feeder_loading_pct: float


def compute_lcoh_dh(
    annual_heat_mwh: float,
    pipe_lengths_by_dn: Optional[Dict[str, float]],
    total_pipe_length_m: float,
    pump_power_kw: float,
    params: EconomicParameters,
    plant_cost_override: Optional[float] = None,
    *,
    plant_cost_allocation: PlantCostAllocation = "full",
    plant_context: Optional[PlantContext] = None,
    street_peak_load_kw: Optional[float] = None,
    district_total_design_capacity_kw: Optional[float] = None,
) -> Tuple[float, Dict]:
    """
    Compute LCOH for District Heating using CRF method.

    Economic Principle: Marginal Cost vs. Sunk Cost
    - full: Include full plant cost (default, backward compatible)
    - none: Exclude plant cost (street-level network extension only)
    - marginal: Only allocate cost if street triggers capacity expansion (requires plant_context)
    - proportional: Allocate plant cost by capacity share (requires plant_context or district_total_design_capacity_kw)

    Returns (lcoh_eur_per_mwh, breakdown_dict).
    """
    logger.info("Computing LCOH_DH for %.2f MWh/year", float(annual_heat_mwh))

    if float(annual_heat_mwh) <= 0:
        raise ValueError(f"Annual heat demand must be positive, got {annual_heat_mwh}")

    # 1) CAPEX - Network (always included)
    capex_pipes = 0.0
    if pipe_lengths_by_dn:
        for dn, length_m in pipe_lengths_by_dn.items():
            cost_per_m = params.pipe_cost_eur_per_m.get(str(dn), params.pipe_cost_eur_per_m["DN100"])
            capex_pipes += float(length_m) * float(cost_per_m)
        logger.debug("Pipe CAPEX (detailed): %.2f EUR", capex_pipes)
    else:
        avg_cost = float(np.mean(list(params.pipe_cost_eur_per_m.values())))
        capex_pipes = float(total_pipe_length_m) * avg_cost
        logger.debug("Using fallback pipe costing: %.2f EUR", capex_pipes)

    capex_pump = float(pump_power_kw) * float(params.pump_cost_per_kw)

    # 2) Plant CAPEX - Marginal Cost vs. Sunk Cost
    capex_plant = 0.0
    plant_allocation_info: Dict[str, object] = {
        "method": plant_cost_allocation,
        "rationale": "Full plant cost (default)",
    }

    if plant_cost_override is not None:
        # Explicit override takes precedence
        capex_plant = float(plant_cost_override)
        plant_allocation_info["rationale"] = "Explicit plant_cost_override"
    elif plant_cost_allocation == "none":
        capex_plant = 0.0
        plant_allocation_info["rationale"] = "No plant cost (street-level marginal cost)"
    elif plant_cost_allocation == "marginal":
        if plant_context is not None and street_peak_load_kw is not None:
            allocation = plant_context.calculate_marginal_allocation(float(street_peak_load_kw))
            capex_plant = float(allocation.get("allocated_cost", allocation.get("allocated_eur", 0)))
            plant_allocation_info.update(allocation)
        else:
            # No plant context or peak load: 0 allocation (cost at district level)
            capex_plant = 0.0
            plant_allocation_info["rationale"] = (
                "Marginal requested but no plant context - 0€ allocation (cost at district level)"
            )
    elif plant_cost_allocation == "proportional":
        peak_kw = street_peak_load_kw if street_peak_load_kw is not None else 0.0
        district_kw = (
            district_total_design_capacity_kw
            if district_total_design_capacity_kw is not None
            else (plant_context.total_capacity_kw if plant_context else 0.0)
        )
        if district_kw > 0 and peak_kw > 0:
            share = peak_kw / district_kw
            capex_plant = share * (
                plant_context.total_cost_eur if plant_context else float(params.plant_cost_base_eur)
            )
            plant_allocation_info.update(
                {"allocated_eur": capex_plant, "capacity_share_frac": share}
            )
            plant_allocation_info["rationale"] = f"Proportional allocation: {share*100:.1f}% of plant capacity"
        else:
            capex_plant = float(params.plant_cost_base_eur)
            plant_allocation_info["rationale"] = "Proportional fallback: no district capacity, using full"
    else:
        # full (default)
        capex_plant = float(params.plant_cost_base_eur)
        plant_allocation_info["rationale"] = "Full plant cost allocated to cluster"

    total_capex = capex_pipes + capex_pump + capex_plant

    # 2) OPEX
    opex_om = total_capex * float(params.dh_om_frac_per_year)

    if params.dh_generation_type == "gas":
        efficiency = 0.90
        opex_energy = (float(annual_heat_mwh) / efficiency) * float(params.gas_price_eur_per_mwh)
    elif params.dh_generation_type == "biomass":
        efficiency = 0.85
        opex_energy = (float(annual_heat_mwh) / efficiency) * float(params.biomass_price_eur_per_mwh)
    elif params.dh_generation_type == "electric":
        cop = 3.0
        opex_energy = (float(annual_heat_mwh) / cop) * float(params.electricity_price_eur_per_mwh)
    else:
        raise ValueError(f"Unknown generation type: {params.dh_generation_type}")

    total_opex_annual = opex_om + opex_energy

    # 3) CRF
    crf_val = crf(float(params.discount_rate), int(params.lifetime_years))

    # 4) LCOH
    lcoh = (total_capex * crf_val + total_opex_annual) / float(annual_heat_mwh)

    breakdown = {
        "capex_total": total_capex,
        "capex_pipes": capex_pipes,
        "capex_pump": capex_pump,
        "capex_plant": capex_plant,
        "opex_annual": total_opex_annual,
        "opex_om": opex_om,
        "opex_energy": opex_energy,
        "crf": crf_val,
        "annual_heat_mwh": float(annual_heat_mwh),
        "generation_type": params.dh_generation_type,
        "plant_allocation": plant_allocation_info,
        "plant_cost_allocation_method": plant_cost_allocation,
    }
    return float(lcoh), breakdown


def compute_lcoh_hp(
    annual_heat_mwh: float,
    hp_total_capacity_kw_th: float,
    cop_annual_average: float,
    max_feeder_loading_pct: float,
    params: EconomicParameters,
) -> Tuple[float, Dict]:
    """
    Compute LCOH for Heat Pump system using CRF method.
    Returns (lcoh_eur_per_mwh, breakdown_dict).
    """
    logger = logging.getLogger(__name__)
    logger.info("Computing LCOH_HP for %.2f MWh/year, COP=%.3f", float(annual_heat_mwh), float(cop_annual_average))

    if float(annual_heat_mwh) <= 0:
        raise ValueError(f"Annual heat demand must be positive, got {annual_heat_mwh}")
    if float(cop_annual_average) <= 0:
        raise ValueError(f"COP must be positive, got {cop_annual_average}")

    capex_hp = float(hp_total_capacity_kw_th) * float(params.hp_cost_eur_per_kw_th)

    loading_threshold = float(params.feeder_loading_planning_limit) * 100.0
    if float(max_feeder_loading_pct) > loading_threshold:
        overload_factor = (float(max_feeder_loading_pct) - loading_threshold) / 100.0
        hp_el_capacity_kw = float(hp_total_capacity_kw_th) / float(cop_annual_average)
        upgrade_kw_el = overload_factor * hp_el_capacity_kw * 1.5
        capex_lv_upgrade = float(upgrade_kw_el) * float(params.lv_upgrade_cost_eur_per_kw_el)
        # Avoid spamming warnings during Monte Carlo; breakdown captures the value for audit.
        logger.debug("LV upgrade needed: %.1f kW_el, cost: %.2f EUR", upgrade_kw_el, capex_lv_upgrade)
    else:
        capex_lv_upgrade = 0.0

    total_capex = capex_hp + capex_lv_upgrade

    opex_om = capex_hp * float(params.hp_om_frac_per_year)
    annual_el_mwh = float(annual_heat_mwh) / float(cop_annual_average)
    opex_energy = annual_el_mwh * float(params.electricity_price_eur_per_mwh)
    total_opex_annual = opex_om + opex_energy

    crf_val = crf(float(params.discount_rate), int(params.lifetime_years))
    lcoh = (total_capex * crf_val + total_opex_annual) / float(annual_heat_mwh)

    breakdown = {
        "capex_total": total_capex,
        "capex_hp": capex_hp,
        "capex_lv_upgrade": capex_lv_upgrade,
        "opex_annual": total_opex_annual,
        "opex_om": opex_om,
        "opex_energy": opex_energy,
        "crf": crf_val,
        "annual_heat_mwh": float(annual_heat_mwh),
        "annual_el_mwh": float(annual_el_mwh),
        "cop_used": float(cop_annual_average),
        "max_feeder_loading_pct": float(max_feeder_loading_pct),
        "loading_threshold_pct": float(loading_threshold),
    }
    return float(lcoh), breakdown


def lcoh_dh_crf(
    inputs: DHInputs,
    params: EconomicsParams,
    *,
    street_peak_load_kw: Optional[float] = None,
) -> float:
    """Back-compat: return only LCOH. Pass street_peak_load_kw for marginal/proportional allocation."""
    plant_ctx = build_plant_context_from_params(params) if hasattr(params, "plant_total_capacity_kw") else None
    v, _ = compute_lcoh_dh(
        annual_heat_mwh=inputs.heat_mwh_per_year,
        pipe_lengths_by_dn=inputs.pipe_lengths_by_dn,
        total_pipe_length_m=inputs.total_pipe_length_m,
        pump_power_kw=inputs.pump_power_kw,
        params=params,
        plant_cost_allocation=getattr(params, "plant_cost_allocation", "full"),
        plant_context=plant_ctx,
        street_peak_load_kw=street_peak_load_kw,
        district_total_design_capacity_kw=getattr(params, "district_total_design_capacity_kw", None) or None,
    )
    return float(v)


def compute_lcoh_district_aggregate(
    cluster_results: Dict[str, Dict],
    shared_plant_cost_eur: float,
    total_demand_mwh: float,
    plant_opex_frac: float = 0.03,
    discount_rate: float = 0.04,
    lifetime_years: int = 20,
) -> Dict[str, object]:
    """
    Aggregate LCOH across multiple clusters with shared plant costs.
    Called after individual street calculations to add plant costs at district level.
    """
    if total_demand_mwh <= 0:
        return {
            "district_lcoh_eur_per_mwh": 0.0,
            "street_lcoh_component": 0.0,
            "plant_lcoh_component": 0.0,
            "total_clusters": len(cluster_results),
            "total_demand_mwh": 0.0,
            "methodology": "Two-stage: Marginal at street level, sunk costs at district level",
        }

    # Weighted average street-level LCOH (before plant)
    weighted_sum = sum(
        r.get("lcoh_eur_per_mwh", 0.0) * r.get("annual_heat_mwh", 0.0)
        for r in cluster_results.values()
    )
    avg_lcoh_before_plant = weighted_sum / total_demand_mwh

    crf_val = crf(float(discount_rate), int(lifetime_years))
    annualized_plant = shared_plant_cost_eur * crf_val
    annual_plant_opex = shared_plant_cost_eur * plant_opex_frac
    plant_cost_per_mwh = (annualized_plant + annual_plant_opex) / total_demand_mwh

    return {
        "district_lcoh_eur_per_mwh": avg_lcoh_before_plant + plant_cost_per_mwh,
        "street_lcoh_component": avg_lcoh_before_plant,
        "plant_lcoh_component": plant_cost_per_mwh,
        "total_clusters": len(cluster_results),
        "total_demand_mwh": total_demand_mwh,
        "shared_plant_annualized_eur": annualized_plant + annual_plant_opex,
        "methodology": "Two-stage: Marginal at street level, sunk costs at district level",
    }


def lcoh_hp_crf(inputs: HPInputs, params: EconomicsParams) -> float:
    """Back-compat: return only LCOH."""
    v, _ = compute_lcoh_hp(
        annual_heat_mwh=inputs.heat_mwh_per_year,
        hp_total_capacity_kw_th=inputs.hp_total_capacity_kw_th,
        cop_annual_average=inputs.cop_annual_average,
        max_feeder_loading_pct=inputs.max_feeder_loading_pct,
        params=params,
    )
    return float(v)

