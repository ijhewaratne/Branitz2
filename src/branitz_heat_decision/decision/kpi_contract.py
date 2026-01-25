"""
KPI Contract Builder
- Purely compositional: no new calculations
- Handles missing fields gracefully
- Returns canonical schema
"""

import json
import logging
import subprocess
import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, cast

from .schemas import KPIContract, REASON_CODES, ContractValidator

logger = logging.getLogger(__name__)

_GIT_COMMIT_CACHE: Optional[str] = None


def _get_git_commit_hash() -> str:
    """
    Best-effort git commit hash for auditability.
    Returns "unknown" if git is unavailable or the workspace is not a git repo.
    """
    global _GIT_COMMIT_CACHE
    if _GIT_COMMIT_CACHE is not None:
        return _GIT_COMMIT_CACHE

    try:
        repo_root = Path(__file__).resolve().parents[3]
        commit = (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=str(repo_root),
                stderr=subprocess.DEVNULL,
            )
            .decode("ascii", errors="ignore")
            .strip()
        )
        _GIT_COMMIT_CACHE = commit or "unknown"
    except Exception:
        _GIT_COMMIT_CACHE = "unknown"
    return _GIT_COMMIT_CACHE


def _utc_now_iso_z() -> str:
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

def _get(d: Dict[str, Any], path: str, default: Any = None) -> Any:
    """Dot-path getter for nested dicts."""
    cur: Any = d
    try:
        for k in path.split("."):
            if isinstance(cur, dict) and k in cur:
                cur = cur[k]
            else:
                return default
        return cur
    except Exception:
        return default

def build_kpi_contract(
    cluster_id: str,
    cha_kpis: Dict[str, Any],
    dha_kpis: Dict[str, Any],
    econ_summary: Dict[str, Any],
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Build canonical KPI contract from CHA, DHA, and Economics outputs.
    
    Args:
        cluster_id: Cluster identifier
        cha_kpis: CHA KPIs from kpi_extractor.py
        dha_kpis: DHA KPIs from kpi_extractor.py
        econ_summary: Economics summary from monte_carlo.py
        metadata: Optional metadata (paths, notes)
    
    Returns:
        Validated KPI contract as dictionary
    
    Raises:
        ValueError: If required fields are missing and cannot be inferred
    """
    
    # Use provided metadata or create minimal
    if metadata is None:
        metadata = {
            'created_utc': _utc_now_iso_z(),
            'inputs': {
                'cha_kpis': 'from_memory',
                'dha_kpis': 'from_memory',
                'econ_summary': 'from_memory',
            },
            'notes': [],
        }
    else:
        # Normalize + enrich metadata for auditability
        if 'created_utc' not in metadata:
            metadata['created_utc'] = _utc_now_iso_z()

    # Always record git commit hash (best-effort)
    metadata.setdefault("git_commit", _get_git_commit_hash())
    
    # Build DH block
    dh_block = _build_dh_block(cluster_id, cha_kpis, econ_summary)
    
    # Build HP block
    hp_block = _build_hp_block(cluster_id, dha_kpis, econ_summary)
    
    # Build MC block (optional)
    mc_block = _build_mc_block(econ_summary)
    
    # Assemble contract
    contract = {
        'version': '1.0',
        'cluster_id': cluster_id,
        'metadata': metadata,
        'district_heating': dh_block,
        'heat_pumps': hp_block,
        'monte_carlo': mc_block,
    }
    
    # Validate
    try:
        ContractValidator.validate(contract)
    except ValueError as e:
        logger.error(f"Contract validation failed: {e}")
        logger.error(f"Contract content: {json.dumps(contract, indent=2)}")
        raise
    
    logger.info(f"Built valid KPI contract for {cluster_id}")
    return contract

def _build_dh_block(cluster_id: str, cha_kpis: Dict[str, Any], econ_summary: Dict[str, Any]) -> Dict[str, Any]:
    """Build DistrictHeatingBlock with fallback logic."""

    # Current CHA schema (our pipeline):
    # - en13941_compliance.feasible
    # - aggregate: v_share_within_limits, dp_max_bar_per_100m, v_max_ms/v_min_ms
    # - losses: lengths
    feasible = bool(_get(cha_kpis, "en13941_compliance.feasible", _infer_dh_feasibility(cha_kpis)))

    reasons = _get(cha_kpis, "en13941_compliance.reasons", []) or cha_kpis.get("reasons", [])
    if not reasons:
        reasons = _infer_dh_reasons(cha_kpis, feasible)

    lcoh = _extract_lcoh_metrics(econ_summary, system="dh")
    co2 = _extract_co2_metrics(econ_summary, system="dh")

    v_share = _get(cha_kpis, "aggregate.v_share_within_limits", _get(cha_kpis, "hydraulics.velocity_share_within_limits"))
    dp_max_100m = _get(cha_kpis, "aggregate.dp_max_bar_per_100m", _get(cha_kpis, "aggregate.dp_per_100m_max"))
    v_max = _get(cha_kpis, "aggregate.v_max_ms", _get(cha_kpis, "hydraulics.max_velocity_ms"))
    v_min = _get(cha_kpis, "aggregate.v_min_ms", _get(cha_kpis, "hydraulics.min_velocity_ms"))

    hydraulics = {
        "velocity_ok": bool(_get(cha_kpis, "hydraulics.velocity_ok", (float(v_share or 0.0) >= 0.95))),
        "dp_ok": bool(_get(cha_kpis, "hydraulics.dp_ok", (float(dp_max_100m or 0.0) < 0.3))),
        "v_max_ms": float(v_max) if v_max is not None else 0.0,
        "v_min_ms": float(v_min) if v_min is not None else 0.0,
        "v_share_within_limits": float(v_share) if v_share is not None else 0.0,
        "dp_per_100m_max": float(dp_max_100m) if dp_max_100m is not None else 0.0,
        "hard_violations": _get(cha_kpis, "en13941_compliance.warnings", []) or cha_kpis.get("hard_violations", []),
    }

    losses = {
        "total_length_m": float(_get(cha_kpis, "losses.length_total_m", 0.0)),
        "trunk_length_m": float(_get(cha_kpis, "losses.length_supply_m", 0.0)) + float(_get(cha_kpis, "losses.length_return_m", 0.0)),
        "service_length_m": float(_get(cha_kpis, "losses.length_service_m", 0.0)),
        "loss_share_pct": float(_get(cha_kpis, "losses.loss_share_percent", 0.0)),
        "pump_power_kw": float(_get(cha_kpis, "pump.pump_power_kw", 0.0)),
    }
    
    return {
        'feasible': feasible,
        'reasons': reasons,
        'lcoh': lcoh,
        'co2': co2,
        'hydraulics': hydraulics,
        'losses': losses,
    }

def _build_hp_block(cluster_id: str, dha_kpis: Dict[str, Any], econ_summary: Dict[str, Any]) -> Dict[str, Any]:
    """Build HeatPumpsBlock with fallback logic."""

    # Current DHA schema: {"kpis": {...}, "worst_hour": ...}
    k = dha_kpis.get("kpis", dha_kpis)
    feasible = bool(k.get("feasible", _infer_hp_feasibility(k)))
    reasons = k.get("reasons", None) or _infer_hp_reasons(k, feasible)

    lcoh = _extract_lcoh_metrics(econ_summary, system="hp")
    co2 = _extract_co2_metrics(econ_summary, system="hp")

    lv_grid = {
        "planning_warning": bool(k.get("planning_warnings_total", 0) > 0) if "planning_warnings_total" in k else bool(k.get("planning_warning", False)),
        "max_feeder_loading_pct": float(k.get("max_feeder_loading_pct", 0.0)),
        "voltage_violations_total": k.get("voltage_violations_total", None),
        "line_violations_total": k.get("line_violations_total", None),
        "worst_bus_id": k.get("worst_bus_id"),
        "worst_line_id": k.get("worst_line_id"),
    }

    hp_system = {
        "hp_total_kw_design": float(k.get("peak_p_hp_kw_total", 0.0)),
        "hp_total_kw_topn_max": float(k.get("peak_p_hp_kw_total", 0.0)),
    }
    
    return {
        'feasible': feasible,
        'reasons': reasons,
        'lcoh': lcoh,
        'co2': co2,
        'lv_grid': lv_grid,
        'hp_system': hp_system,
    }

def _build_mc_block(econ_summary: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Build MonteCarloBlock if data available."""
    # Current economics summary schema: {"monte_carlo": {...}, "lcoh": {...}, "co2": {...}, "metadata": {...}}
    mc = econ_summary.get("monte_carlo") or {}
    if not mc:
        return None
    return {
        "dh_wins_fraction": float(mc.get("dh_wins_fraction", 0.0)),
        "hp_wins_fraction": float(mc.get("hp_wins_fraction", 0.0)),
        "n_samples": int(mc.get("n_samples", 0)),
        "seed": (econ_summary.get("metadata") or {}).get("seed", None),
    }

def _infer_dh_feasibility(cha_kpis: Dict[str, Any]) -> bool:
    """Infer DH feasibility from available metrics."""
    
    # If explicit flag exists, use it
    if 'feasible' in cha_kpis:
        return bool(cha_kpis['feasible'])
    
    # Fallback: check velocity share (aggregate schema)
    v_share = _get(cha_kpis, "aggregate.v_share_within_limits", cha_kpis.get("v_share_within_limits"))
    if v_share is not None:
        try:
            return float(v_share) >= 0.95
        except Exception:
            return False
    
    # If no data, assume not feasible (safe default)
    logger.warning("Cannot infer DH feasibility: missing KPIs")
    return False

def _infer_hp_feasibility(dha_kpis: Dict[str, Any]) -> bool:
    """Infer HP feasibility from violation counts."""
    
    if 'feasible' in dha_kpis:
        return bool(dha_kpis['feasible'])
    
    # Check violation counts
    volt_viol = dha_kpis.get('voltage_violations_total')
    line_viol = dha_kpis.get('line_violations_total')
    
    # CRITICAL: None means missing data, not zero violations
    if volt_viol is None or line_viol is None:
        logger.warning("Cannot infer HP feasibility: missing violation counts")
        return False
    
    return bool(volt_viol == 0 and line_viol == 0)

def _infer_dh_reasons(cha_kpis: Dict[str, Any], feasible: bool) -> List[str]:
    """Infer reason codes for DH."""
    
    reasons = []
    
    # Optional data-quality flag (set upstream in data prep / CHA run)
    # Accept either a top-level field or nested metadata.
    dq = cha_kpis.get("data_quality") or _get(cha_kpis, "metadata.data_quality", None)
    if dq == "incomplete":
        reasons.append("CHA_DATA_INCOMPLETE")

    if feasible:
        reasons.append("DH_OK")
    else:
        if float(_get(cha_kpis, "aggregate.v_share_within_limits", 1.0)) < 0.95:
            reasons.append("DH_VELOCITY_VIOLATION")
        if float(_get(cha_kpis, "aggregate.dp_max_bar_per_100m", 0.0)) >= 0.3:
            reasons.append("DH_DP_VIOLATION")
        if cha_kpis.get('hard_violations'):
            reasons.append("DH_HARD_VIOLATION")
    
    if not reasons:
        reasons.append("CHA_MISSING_KPIS")
    
    return reasons

def _infer_hp_reasons(dha_kpis: Dict[str, Any], feasible: bool) -> List[str]:
    """Infer reason codes for HP."""
    
    reasons = []
    
    # Optional grid provenance flag (set upstream in DHA run)
    grid_source = dha_kpis.get("grid_source") or _get(dha_kpis, "metadata.grid_source", None)
    if grid_source == "synthetic":
        reasons.append("DHA_SYNTHETIC_GRID_WARNING")

    if feasible:
        reasons.append("HP_OK")
        # Check for planning warning even if feasible
        if dha_kpis.get('planning_warning', False):
            reasons.append("HP_PLANNING_WARNING_80PCT")
        # If feeder loading is in the marginal 80-85% band, mark explicitly.
        try:
            loading = float(dha_kpis.get("max_feeder_loading_pct", 0.0))
            if 80.0 <= loading <= 85.0:
                reasons.append("HP_LOADING_MARGINAL_80_85")
        except Exception:
            pass
    else:
        if dha_kpis.get('voltage_violations_total', 0) > 0:
            reasons.append("HP_UNDERVOLTAGE")
        if dha_kpis.get('line_violations_total', 0) > 0:
            reasons.append("HP_OVERCURRENT_OR_OVERLOAD")
    
    if not reasons:
        reasons.append("DHA_MISSING_KPIS")
    
    return reasons

def _extract_lcoh_metrics(econ_summary: Dict[str, Any], system: str) -> Dict[str, Any]:
    """
    Extract LCOH metrics from economics summary.
    Supports multiple schemas:
    1. econ_summary['lcoh']['dh'|'hp'] with p05/p50/p95/mean/std
    2. Top-level keys: lcoh_dh_p50, lcoh_hp_p50, etc. (Monte Carlo format)
    3. Single values: lcoh_dh_eur_per_mwh, lcoh_hp_eur_per_mwh
    """
    def _to_float(x: Any, default: float = 0.0) -> float:
        try:
            if x is None:
                return default
            return float(x)
        except Exception:
            return default
    
    # Try nested structure first: econ_summary['lcoh']['dh'|'hp']
    blk = _get(econ_summary, f"lcoh.{system}", None)
    if isinstance(blk, dict) and ("p50" in blk or "p05" in blk or "p95" in blk):
        return {
            "median": _to_float(blk.get("p50", blk.get("median", 0.0)), 0.0),
            "p05": _to_float(blk.get("p05", 0.0), 0.0),
            "p95": _to_float(blk.get("p95", 0.0), 0.0),
            "mean": _to_float(blk.get("mean"), 0.0) if "mean" in blk else None,
            "std": _to_float(blk.get("std"), 0.0) if "std" in blk else None,
        }
    
    # Try Monte Carlo format: top-level keys like lcoh_dh_p50, lcoh_hp_p50
    prefix = f"lcoh_{system}"
    p50_key = f"{prefix}_p50"
    p10_key = f"{prefix}_p10"
    p90_key = f"{prefix}_p90"
    
    if p50_key in econ_summary:
        return {
            "median": _to_float(econ_summary.get(p50_key, 0.0), 0.0),
            "p05": _to_float(econ_summary.get(p10_key, econ_summary.get(f"{prefix}_p05", 0.0)), 0.0),
            "p95": _to_float(econ_summary.get(p90_key, econ_summary.get(f"{prefix}_p95", 0.0)), 0.0),
            "mean": _to_float(econ_summary.get(f"{prefix}_mean", None), None),
            "std": _to_float(econ_summary.get(f"{prefix}_std", None), None),
        }
    
    # Fallback: deterministic economics file might have single values
    if system == "dh":
        raw = econ_summary.get("lcoh_dh_eur_per_mwh", econ_summary.get("lcoh_dh", 0.0))
    else:
        raw = econ_summary.get("lcoh_hp_eur_per_mwh", econ_summary.get("lcoh_hp", 0.0))
    return {"median": float(raw), "p05": float(raw), "p95": float(raw)}

def _extract_co2_metrics(econ_summary: Dict[str, Any], system: str) -> Dict[str, Any]:
    """
    Extract CO2 metrics from economics summary.
    Supports multiple schemas:
    1. econ_summary['co2']['dh'|'hp'] with p05/p50/p95/mean/std
    2. Top-level keys: co2_dh_p50, co2_hp_p50, etc. (Monte Carlo format)
    3. Single values: co2_dh_kg_per_mwh, co2_hp_kg_per_mwh
    """
    def _to_float(x: Any, default: float = 0.0) -> float:
        try:
            if x is None:
                return default
            return float(x)
        except Exception:
            return default
    
    # Try nested structure first: econ_summary['co2']['dh'|'hp']
    blk = _get(econ_summary, f"co2.{system}", None)
    if isinstance(blk, dict) and ("p50" in blk or "p05" in blk or "p95" in blk):
        return {
            "median": _to_float(blk.get("p50", blk.get("median", 0.0)), 0.0),
            "p05": _to_float(blk.get("p05", 0.0), 0.0),
            "p95": _to_float(blk.get("p95", 0.0), 0.0),
            "mean": _to_float(blk.get("mean"), 0.0) if "mean" in blk else None,
            "std": _to_float(blk.get("std"), 0.0) if "std" in blk else None,
        }
    
    # Try Monte Carlo format: top-level keys like co2_dh_p50, co2_hp_p50
    prefix = f"co2_{system}"
    p50_key = f"{prefix}_p50"
    p10_key = f"{prefix}_p10"
    p90_key = f"{prefix}_p90"
    
    if p50_key in econ_summary:
        return {
            "median": _to_float(econ_summary.get(p50_key, 0.0), 0.0),
            "p05": _to_float(econ_summary.get(p10_key, econ_summary.get(f"{prefix}_p05", 0.0)), 0.0),
            "p95": _to_float(econ_summary.get(p90_key, econ_summary.get(f"{prefix}_p95", 0.0)), 0.0),
            "mean": _to_float(econ_summary.get(f"{prefix}_mean", None), None),
            "std": _to_float(econ_summary.get(f"{prefix}_std", None), None),
        }
    
    # Fallback: deterministic economics file might have single values
    if system == "dh":
        raw = econ_summary.get("co2_dh_kg_per_mwh", econ_summary.get("co2_dh", 0.0))
    else:
        raw = econ_summary.get("co2_hp_kg_per_mwh", econ_summary.get("co2_hp", 0.0))
    return {"median": float(raw), "p05": float(raw), "p95": float(raw)}

# Export canonical builder
__all__ = ['build_kpi_contract', 'KPIContract', 'ContractValidator', 'REASON_CODES']