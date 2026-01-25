"""
ADK Evaluations Module

Trajectory validation and artifact checks for ADK agents.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def validate_trajectory(
    trajectory: List[Dict[str, Any]],
    cluster_id: str,
    expected_phases: Optional[List[str]] = None,
) -> Tuple[bool, List[str]]:
    """
    Validate agent trajectory (sequence of actions).
    
    Args:
        trajectory: List of actions with their results
        cluster_id: Cluster identifier
        expected_phases: Expected phases (e.g., ["data", "cha", "dha", "economics", "decision", "uhdc"])
    
    Returns:
        Tuple of (valid, issues) where issues is a list of validation errors
    """
    if expected_phases is None:
        expected_phases = ["data", "cha", "dha", "economics", "decision", "uhdc"]
    
    issues = []
    
    # Check trajectory structure
    if not trajectory:
        issues.append("Trajectory is empty")
        return False, issues
    
    # Check for required phases
    executed_phases = [action.get("phase") for action in trajectory if "phase" in action]
    
    for phase in expected_phases:
        if phase not in executed_phases:
            issues.append(f"Required phase '{phase}' not found in trajectory")
    
    # Check phase order (data → cha → dha → economics → decision → uhdc)
    phase_order = {
        "data": 0,
        "cha": 1,
        "dha": 2,
        "economics": 3,
        "decision": 4,
        "uhdc": 5,
    }
    
    for i, action in enumerate(trajectory):
        phase = action.get("phase")
        if phase and phase in phase_order:
            # Check that previous phases were executed
            required_prev_phases = [
                p for p, order in phase_order.items()
                if order < phase_order[phase]
            ]
            executed_prev_phases = [
                action.get("phase") for action in trajectory[:i]
                if "phase" in action
            ]
            for prev_phase in required_prev_phases:
                if prev_phase not in executed_prev_phases:
                    issues.append(
                        f"Phase '{phase}' executed before required phase '{prev_phase}'"
                    )
    
    # Check action success
    failed_actions = [
        action for action in trajectory
        if action.get("status") == "error"
    ]
    
    if failed_actions:
        for action in failed_actions:
            issues.append(
                f"Action '{action.get('name')}' failed: {action.get('error', 'Unknown error')}"
            )
    
    return len(issues) == 0, issues


def validate_artifacts(
    cluster_id: str,
    phases: Optional[List[str]] = None,
) -> Tuple[bool, Dict[str, List[str]]]:
    """
    Validate artifacts exist and are valid for a cluster.
    
    Args:
        cluster_id: Cluster identifier
        phases: List of phases to check (None = check all)
    
    Returns:
        Tuple of (all_valid, issues_by_phase) where issues_by_phase is a dict mapping phase to list of issues
    """
    from branitz_heat_decision.config import resolve_cluster_path
    
    if phases is None:
        phases = ["cha", "dha", "economics", "decision"]
    
    issues_by_phase: Dict[str, List[str]] = {}
    
    for phase in phases:
        phase_dir = resolve_cluster_path(cluster_id, phase)
        issues = []
        
        if phase == "cha":
            if not (phase_dir / "cha_kpis.json").exists():
                issues.append("cha_kpis.json missing")
            else:
                # Validate KPI structure
                try:
                    with open(phase_dir / "cha_kpis.json", "r") as f:
                        kpis = json.load(f)
                        if "en13941_compliance" not in kpis:
                            issues.append("cha_kpis.json missing 'en13941_compliance' block")
                        if "aggregate" not in kpis:
                            issues.append("cha_kpis.json missing 'aggregate' block")
                except Exception as e:
                    issues.append(f"cha_kpis.json invalid: {e}")
            
            if not (phase_dir / "network.pickle").exists():
                issues.append("network.pickle missing")
            
            if not (phase_dir / "interactive_map.html").exists():
                issues.append("interactive_map.html missing")
        
        elif phase == "dha":
            if not (phase_dir / "dha_kpis.json").exists():
                issues.append("dha_kpis.json missing")
            else:
                # Validate KPI structure
                try:
                    with open(phase_dir / "dha_kpis.json", "r") as f:
                        kpis = json.load(f)
                        if "kpis" not in kpis:
                            issues.append("dha_kpis.json missing 'kpis' block")
                except Exception as e:
                    issues.append(f"dha_kpis.json invalid: {e}")
            
            if not (phase_dir / "violations.csv").exists():
                issues.append("violations.csv missing")
            
            if not (phase_dir / "hp_lv_map.html").exists():
                issues.append("hp_lv_map.html missing")
        
        elif phase == "economics":
            if not (phase_dir / "economics_deterministic.json").exists():
                issues.append("economics_deterministic.json missing")
            
            if not (phase_dir / "monte_carlo_summary.json").exists():
                issues.append("monte_carlo_summary.json missing")
            else:
                # Validate Monte Carlo summary structure
                try:
                    with open(phase_dir / "monte_carlo_summary.json", "r") as f:
                        summary = json.load(f)
                        if "monte_carlo" not in summary:
                            issues.append("monte_carlo_summary.json missing 'monte_carlo' block")
                        else:
                            mc = summary["monte_carlo"]
                            if "dh_wins_fraction" not in mc or "hp_wins_fraction" not in mc:
                                issues.append("monte_carlo summary missing win fractions")
                except Exception as e:
                    issues.append(f"monte_carlo_summary.json invalid: {e}")
            
            if not (phase_dir / "monte_carlo_samples.parquet").exists():
                issues.append("monte_carlo_samples.parquet missing")
        
        elif phase == "decision":
            if not (phase_dir / f"kpi_contract_{cluster_id}.json").exists():
                issues.append(f"kpi_contract_{cluster_id}.json missing")
            else:
                # Validate contract schema
                try:
                    from branitz_heat_decision.decision.schemas import ContractValidator
                    with open(phase_dir / f"kpi_contract_{cluster_id}.json", "r") as f:
                        contract = json.load(f)
                        ContractValidator.validate(contract)
                except Exception as e:
                    issues.append(f"kpi_contract_{cluster_id}.json invalid: {e}")
            
            if not (phase_dir / f"decision_{cluster_id}.json").exists():
                issues.append(f"decision_{cluster_id}.json missing")
            else:
                # Validate decision structure
                try:
                    with open(phase_dir / f"decision_{cluster_id}.json", "r") as f:
                        decision = json.load(f)
                        if "choice" not in decision:
                            issues.append("decision.json missing 'choice' field")
                        elif decision["choice"] not in ["DH", "HP", "UNDECIDED"]:
                            issues.append(f"decision.json invalid 'choice': {decision['choice']}")
                        if "reason_codes" not in decision:
                            issues.append("decision.json missing 'reason_codes' field")
                except Exception as e:
                    issues.append(f"decision_{cluster_id}.json invalid: {e}")
        
        if issues:
            issues_by_phase[phase] = issues
    
    all_valid = len(issues_by_phase) == 0
    return all_valid, issues_by_phase


def check_artifact_completeness(
    cluster_id: str,
    phase: str,
) -> Tuple[bool, List[str]]:
    """
    Check artifact completeness for a specific phase.
    
    Args:
        cluster_id: Cluster identifier
        phase: Phase to check (cha, dha, economics, decision, uhdc)
    
    Returns:
        Tuple of (complete, missing_artifacts)
    """
    from branitz_heat_decision.config import resolve_cluster_path
    
    phase_dir = resolve_cluster_path(cluster_id, phase)
    missing = []
    
    expected_artifacts = {
        "cha": [
            "cha_kpis.json",
            "network.pickle",
            "interactive_map.html",
            "interactive_map_temperature.html",
            "interactive_map_pressure.html",
        ],
        "dha": [
            "dha_kpis.json",
            "buses_results.geojson",
            "lines_results.geojson",
            "violations.csv",
            "hp_lv_map.html",
        ],
        "economics": [
            "economics_deterministic.json",
            "monte_carlo_summary.json",
            "monte_carlo_samples.parquet",
        ],
        "decision": [
            f"kpi_contract_{cluster_id}.json",
            f"decision_{cluster_id}.json",
        ],
        "uhdc": [
            f"uhdc_report_{cluster_id}.html",
            f"uhdc_explanation_{cluster_id}.md",
            f"uhdc_report_{cluster_id}.json",
        ],
    }
    
    if phase not in expected_artifacts:
        return False, [f"Unknown phase: {phase}"]
    
    for artifact in expected_artifacts[phase]:
        if not (phase_dir / artifact).exists():
            missing.append(artifact)
    
    return len(missing) == 0, missing
