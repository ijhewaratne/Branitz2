"""
ADK Policies Module

Guardrails and policies for ADK agents.
Critical policy: "LLM cannot decide" - decision must come from deterministic rules.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class PolicyViolation(Exception):
    """Exception raised when an agent action violates a policy."""
    
    policy_name: str
    violation_message: str
    action: Optional[str] = None
    context: Optional[Dict[str, Any]] = None
    
    def __str__(self) -> str:
        msg = f"Policy violation [{self.policy_name}]: {self.violation_message}"
        if self.action:
            msg += f" (action: {self.action})"
        return msg


# Policy registry
_POLICIES: Dict[str, callable] = {}


def register_policy(name: str, validator: callable) -> None:
    """
    Register a policy validator function.
    
    Args:
        name: Policy name
        validator: Function that takes (action, context) and returns (allowed, reason)
    """
    _POLICIES[name] = validator
    logger.debug(f"[ADK Policies] Registered policy: {name}")


def validate_agent_action(
    action: str,
    context: Optional[Dict[str, Any]] = None,
    policies: Optional[List[str]] = None,
) -> tuple[bool, Optional[str]]:
    """
    Validate an agent action against registered policies.
    
    Args:
        action: Agent action (e.g., "run_decision", "modify_kpi_contract")
        context: Action context (e.g., {"cluster_id": "...", "parameters": {...}})
        policies: List of policy names to check (None = check all)
    
    Returns:
        Tuple of (allowed, reason) where reason is None if allowed
    """
    if context is None:
        context = {}
    
    policies_to_check = policies if policies is not None else list(_POLICIES.keys())
    
    for policy_name in policies_to_check:
        if policy_name not in _POLICIES:
            logger.warning(f"[ADK Policies] Policy '{policy_name}' not found")
            continue
        
        validator = _POLICIES[policy_name]
        try:
            allowed, reason = validator(action, context)
            if not allowed:
                logger.warning(f"[ADK Policies] Policy '{policy_name}' blocked action '{action}': {reason}")
                return False, f"[{policy_name}] {reason}"
        except Exception as e:
            logger.error(f"[ADK Policies] Policy '{policy_name}' validation error: {e}")
            return False, f"[{policy_name}] Validation error: {e}"
    
    return True, None


def enforce_guardrails(
    action: str,
    context: Optional[Dict[str, Any]] = None,
    policies: Optional[List[str]] = None,
) -> None:
    """
    Enforce guardrails by raising PolicyViolation if action is not allowed.
    
    Args:
        action: Agent action
        context: Action context
        policies: List of policy names to check (None = check all)
    
    Raises:
        PolicyViolation: If action violates any policy
    """
    allowed, reason = validate_agent_action(action, context, policies)
    if not allowed:
        raise PolicyViolation(
            policy_name=policies[0] if policies else "unknown",
            violation_message=reason or "Action not allowed",
            action=action,
            context=context,
        )


# ============================================================================
# Core Policies
# ============================================================================

def _policy_llm_cannot_decide(action: str, context: Dict[str, Any]) -> tuple[bool, Optional[str]]:
    """
    Policy: LLM cannot make decisions. Decision must come from deterministic rules.
    
    Allowed actions:
    - run_decision: OK (uses deterministic rules, not LLM)
    - run_uhdc: OK (LLM only for explanation, not decision)
    - modify_kpi_contract: BLOCKED (would change decision input)
    - override_decision: BLOCKED (LLM cannot override)
    - manual_decision: BLOCKED (no manual overrides)
    """
    blocked_actions = [
        "modify_kpi_contract",
        "override_decision",
        "manual_decision",
        "set_decision",
        "change_decision",
    ]
    
    if action in blocked_actions:
        return False, f"LLM cannot make decisions. Action '{action}' is blocked."
    
    # Check for LLM in decision context
    if action == "run_decision":
        # Decision tool uses deterministic rules, not LLM
        # LLM is only for explanation (optional)
        return True, None
    
    if action == "run_uhdc":
        # UHDC uses LLM only for explanation, not decision
        # Decision comes from deterministic rules
        return True, None
    
    return True, None


def _policy_readonly_artifacts(action: str, context: Dict[str, Any]) -> tuple[bool, Optional[str]]:
    """
    Policy: Artifacts from previous phases are read-only.
    
    Allowed actions:
    - read_kpis: OK (read-only)
    - load_contract: OK (read-only)
    - modify_kpis: BLOCKED (artifacts are immutable)
    - delete_artifacts: BLOCKED (artifacts must be preserved)
    """
    readonly_actions = [
        "read_kpis",
        "load_contract",
        "load_kpis",
        "discover_artifacts",
    ]
    
    mutable_actions = [
        "modify_kpis",
        "delete_artifacts",
        "delete_kpis",
        "edit_kpis",
        "update_kpis",
        "change_kpis",
    ]
    
    if action in readonly_actions:
        return True, None
    
    if action in mutable_actions:
        return False, f"Artifacts are read-only. Action '{action}' is blocked."
    
    return True, None


def _policy_required_phases(action: str, context: Dict[str, Any]) -> tuple[bool, Optional[str]]:
    """
    Policy: Enforce phase dependencies (e.g., Decision requires CHA/DHA/Economics).
    
    Checks if required artifacts exist before allowing actions.
    """
    # Phase dependencies
    phase_dependencies = {
        "run_decision": ["cha", "dha", "economics"],
        "run_uhdc": ["decision"],  # UHDC requires decision (or builds it)
        "run_economics": ["cha", "dha"],
        "run_dha": [],  # DHA only needs data preparation
        "run_cha": [],  # CHA only needs data preparation
    }
    
    if action not in phase_dependencies:
        return True, None  # No dependency check for this action
    
    required_phases = phase_dependencies[action]
    cluster_id = context.get("cluster_id")
    
    if not cluster_id:
        return True, None  # Cannot validate without cluster_id
    
    # Check if required artifacts exist
    from branitz_heat_decision.config import resolve_cluster_path
    
    missing_phases = []
    for phase in required_phases:
        phase_dir = resolve_cluster_path(cluster_id, phase)
        if phase == "cha" and not (phase_dir / "cha_kpis.json").exists():
            missing_phases.append(phase)
        elif phase == "dha" and not (phase_dir / "dha_kpis.json").exists():
            missing_phases.append(phase)
        elif phase == "economics" and not (phase_dir / "monte_carlo_summary.json").exists():
            missing_phases.append(phase)
        elif phase == "decision" and not (phase_dir / f"decision_{cluster_id}.json").exists():
            missing_phases.append(phase)
    
    if missing_phases:
        return False, f"Required phases not complete: {', '.join(missing_phases)}. Run missing phases first."
    
    return True, None


def _policy_deterministic_outputs(action: str, context: Dict[str, Any]) -> tuple[bool, Optional[str]]:
    """
    Policy: All outputs must be deterministic (no randomness in decision paths).
    
    Allowed:
    - Monte Carlo randomness is OK (controlled via seed)
    - LLM explanation randomness is OK (optional, doesn't affect decision)
    
    Blocked:
    - Random decision choices
    - Non-deterministic parameter modifications
    """
    # Monte Carlo and LLM are OK (controlled randomness)
    if action in ["run_economics", "run_uhdc"]:
        return True, None
    
    # Check for random parameters in context
    if context.get("random") or context.get("non_deterministic"):
        return False, "Non-deterministic parameters are not allowed in decision pipeline."
    
    return True, None


# Register default policies
register_policy("llm_cannot_decide", _policy_llm_cannot_decide)
register_policy("readonly_artifacts", _policy_readonly_artifacts)
register_policy("required_phases", _policy_required_phases)
register_policy("deterministic_outputs", _policy_deterministic_outputs)
