"""
Centralized artifact discovery patterns.

Why this module exists:
- The project already has `branitz_heat_decision/config.py` as a module, so we cannot
  safely introduce a `branitz_heat_decision/config/` package without import conflicts.
- `uhdc.orchestrator.discover_artifact_paths()` relies on these patterns to locate
  artifacts across evolving folder layouts (nested/flat/legacy).

Patterns are evaluated in-order: first match wins.
Patterns are *relative* to the `base_dir` passed to discovery (typically `results/`),
but we also include `results/...` prefixed variants for callers that pass the repo
root as base_dir.
"""

from __future__ import annotations

from typing import Dict, List

SEARCH_PATTERNS: Dict[str, List[str]] = {
    "kpi_contract": [
        # Newer / nested under decision/<cluster_id>/
        "decision/{cluster_id}/kpi_contract_{cluster_id}.json",
        "decision/{cluster_id}/kpi_contract.json",
        # Flat under decision/
        "decision/kpi_contract_{cluster_id}.json",
        "decision/kpi_contract.json",
        # Legacy-ish / flat in base_dir root
        "kpi_contract_{cluster_id}.json",
        # Cluster folder fallbacks
        "{cluster_id}/kpi_contract.json",
        # Minimal single-file fallback
        "kpi_contract.json",
        # If base_dir is repo root instead of results/
        "results/decision/{cluster_id}/kpi_contract_{cluster_id}.json",
        "results/decision/kpi_contract_{cluster_id}.json",
        "results/kpi_contract_{cluster_id}.json",
    ],
    "cha_kpis": [
        # Standard nested under results/
        "cha/{cluster_id}/cha_kpis.json",
        # Alternate nested layouts
        "{cluster_id}/cha_kpis.json",
        # Flat (debugging / single run)
        "cha_kpis.json",
        # If base_dir is repo root instead of results/
        "results/cha/{cluster_id}/cha_kpis.json",
        "results/{cluster_id}/cha_kpis.json",
        "results/cha_kpis.json",
    ],
    "dha_kpis": [
        "dha/{cluster_id}/dha_kpis.json",
        "{cluster_id}/dha_kpis.json",
        "dha_kpis.json",
        "results/dha/{cluster_id}/dha_kpis.json",
        "results/{cluster_id}/dha_kpis.json",
        "results/dha_kpis.json",
    ],
    "econ_summary": [
        "economics/{cluster_id}/monte_carlo_summary.json",
        "economics/{cluster_id}/cli_run/monte_carlo_summary.json",
        # legacy / alternate naming
        "economics/{cluster_id}/economics_monte_carlo.json",
        "econ/{cluster_id}/monte_carlo_summary.json",
        "{cluster_id}/monte_carlo_summary.json",
        "monte_carlo_summary.json",
        # If base_dir is repo root instead of results/
        "results/economics/{cluster_id}/monte_carlo_summary.json",
        "results/econ/{cluster_id}/monte_carlo_summary.json",
        "results/monte_carlo_summary.json",
    ],
}

