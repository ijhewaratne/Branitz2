"""
Dynamic Plant Context — Singleton Cottbus CHP shared across all streets.

The same plant serves the entire district; marginal cost allocation
ensures each street pays only for capacity expansion (if any), not the sunk plant cost.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CottbusCHPContext:
    """
    Singleton context for Cottbus CHP plant.
    Shared across ALL streets — same plant serves entire district.
    """

    # Plant specifications from GEM data
    total_capacity_kw_th: float = 220_000  # 220 MW thermal (54+48.9 MW elec * ~2 CHP ratio)
    utilized_capacity_kw_th: float = 180_000  # Current baseline load (city minus spare)
    total_cost_eur: float = 150_000_000  # Historical sunk cost (~150M€)
    is_built: bool = True  # EXISTS since 1999/2022
    marginal_cost_per_kw: float = 150.0  # Expansion cost if needed
    fuel_type: str = "natural_gas"  # Changed from coal (retired 2022)

    @property
    def available_capacity_kw(self) -> float:
        """Spare capacity available for new street connections."""
        return self.total_capacity_kw_th - self.utilized_capacity_kw_th

    def can_accommodate(self, street_peak_kw: float, safety_factor: float = 1.2) -> bool:
        """Check if street can be served without plant expansion."""
        required = street_peak_kw * safety_factor
        return required <= self.available_capacity_kw


# Singleton instance — used across entire application
COTTBUS_CHP = CottbusCHPContext()


def get_plant_context_for_street(
    street_peak_load_kw: float,
) -> Dict[str, Any]:
    """
    Get plant allocation for ANY street dynamically.

    Returns marginal allocation (0€) if capacity available,
    or expansion cost if constrained.
    """
    from .lcoh import PlantContext

    # Always use the same Cottbus CHP context
    plant_ctx = PlantContext(
        total_capacity_kw=COTTBUS_CHP.total_capacity_kw_th,
        total_cost_eur=COTTBUS_CHP.total_cost_eur,
        utilized_capacity_kw=COTTBUS_CHP.utilized_capacity_kw_th,
        is_built=COTTBUS_CHP.is_built,
        marginal_cost_per_kw=COTTBUS_CHP.marginal_cost_per_kw,
    )

    # Check if this specific street triggers expansion
    allocation = plant_ctx.get_marginal_allocation(street_peak_load_kw)

    logger.info(
        "Street %.1f kW: %s (Spare: %.0f kW)",
        street_peak_load_kw,
        allocation.get("rationale", ""),
        COTTBUS_CHP.available_capacity_kw,
    )

    return {
        "context": plant_ctx,
        "allocation": allocation,
        "is_within_capacity": COTTBUS_CHP.can_accommodate(street_peak_load_kw),
    }
