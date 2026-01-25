"""
Decision Rules Engine
- Purely deterministic
- No LLM involvement
- Transparent, auditable logic
"""

import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

from .schemas import REASON_CODES

logger = logging.getLogger(__name__)

# Decision configuration
DEFAULT_DECISION_CONFIG = {
    'close_cost_rel_threshold': 0.05,  # 5% relative difference
    'close_cost_abs_threshold': 5.0,   # 5 EUR/MWh absolute difference
    'robust_win_fraction': 0.70,       # ≥70% MC wins → robust
    'sensitive_win_fraction': 0.55,    # ≥55% MC wins → sensitive
}

def validate_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate decision configuration parameters and fill defaults.
    
    Args:
        config: Configuration dictionary (partial allowed)
    
    Returns:
        Validated config dict with defaults filled.
    
    Raises:
        TypeError: if config is not a dict
        ValueError: if any parameter value is invalid
    """
    if not isinstance(config, dict):
        raise TypeError(f"Config must be a dict, got {type(config)}")
    
    validated: Dict[str, Any] = {}
    
    robust = config.get('robust_win_fraction', DEFAULT_DECISION_CONFIG['robust_win_fraction'])
    if not (0 < robust <= 1.0):
        raise ValueError(f"robust_win_fraction must be in (0, 1], got {robust}")
    validated['robust_win_fraction'] = float(robust)
    
    sensitive = config.get('sensitive_win_fraction', DEFAULT_DECISION_CONFIG['sensitive_win_fraction'])
    if not (0 < sensitive < robust):
        raise ValueError(f"sensitive_win_fraction must be in (0, {robust}), got {sensitive}")
    validated['sensitive_win_fraction'] = float(sensitive)
    
    rel_threshold = config.get('close_cost_rel_threshold', DEFAULT_DECISION_CONFIG['close_cost_rel_threshold'])
    if not (0 <= rel_threshold <= 1.0):
        raise ValueError(f"close_cost_rel_threshold must be in [0, 1], got {rel_threshold}")
    validated['close_cost_rel_threshold'] = float(rel_threshold)
    
    abs_threshold = config.get('close_cost_abs_threshold', DEFAULT_DECISION_CONFIG['close_cost_abs_threshold'])
    if abs_threshold <= 0:
        raise ValueError(f"close_cost_abs_threshold must be positive, got {abs_threshold}")
    validated['close_cost_abs_threshold'] = float(abs_threshold)
    
    logger.info(f"Decision config validated: {validated}")
    return validated

@dataclass
class DecisionResult:
    """Structured decision output."""
    choice: str                # "DH", "HP", or "UNDECIDED"
    robust: bool
    reason_codes: List[str]
    metrics_used: Dict[str, float]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'choice': self.choice,
            'robust': self.robust,
            'reason_codes': self.reason_codes,
            'metrics_used': self.metrics_used,
        }

def decide_from_contract(
    contract: Dict[str, Any],
    config: Optional[Dict[str, Any]] = None,
) -> DecisionResult:
    """
    Make deterministic decision from KPI contract.
    
    Decision Logic (in order):
    1. Feasibility gate: If only one option feasible → choose it
    2. Cost comparison: If costs differ >5% → choose cheaper
    3. CO₂ tie-breaker: If costs close → choose lower CO₂
    4. Robustness check: Evaluate Monte Carlo win fractions
    
    Args:
        contract: Validated KPI contract (from build_kpi_contract)
        config: Decision thresholds (uses defaults if None)
    
    Returns:
        DecisionResult with choice, robustness, and reasons
    """
    
    if config is None:
        config = DEFAULT_DECISION_CONFIG
    else:
        config = validate_config(config)
    
    dh = contract['district_heating']
    hp = contract['heat_pumps']
    mc = contract.get('monte_carlo') or {}
    
    # Extract core metrics
    lcoh_dh = dh['lcoh']['median']
    lcoh_hp = hp['lcoh']['median']
    co2_dh = dh['co2']['median']
    co2_hp = hp['co2']['median']
    
    # Initialize decision tracking
    choice = None
    reasons = []
    
    # --- STEP 1: FEASIBILITY GATE ---
    logger.info("Step 1: Evaluating feasibility")
    
    if dh['feasible'] and not hp['feasible']:
        choice = "DH"
        reasons.append("ONLY_DH_FEASIBLE")
        logger.info("→ Only DH feasible")
    
    elif not dh['feasible'] and hp['feasible']:
        choice = "HP"
        reasons.append("ONLY_HP_FEASIBLE")
        logger.info("→ Only HP feasible")
    
    elif not dh['feasible'] and not hp['feasible']:
        choice = "UNDECIDED"
        reasons.append("NONE_FEASIBLE")
        logger.warning("→ Neither option feasible")
    
    else:
        # --- STEP 2: COST COMPARISON ---
        logger.info("Step 2: Comparing costs")
        
        # Handle zero or very small LCOH values to avoid division by zero
        min_lcoh = min(lcoh_dh, lcoh_hp)
        if min_lcoh <= 0 or not (lcoh_dh > 0 and lcoh_hp > 0):
            # Invalid LCOH values - cannot compare costs
            logger.error(f"Invalid LCOH values: DH={lcoh_dh}, HP={lcoh_hp}. Cannot compare costs.")
            choice = "UNDECIDED"
            reasons.append("INVALID_LCOH_VALUES")
        else:
            rel_diff = abs(lcoh_dh - lcoh_hp) / min_lcoh
            abs_diff = abs(lcoh_dh - lcoh_hp)
            
            is_close = (rel_diff <= config['close_cost_rel_threshold'] or 
                       abs_diff <= config['close_cost_abs_threshold'])
            
            if not is_close:
                # Clear cost winner
                if lcoh_dh < lcoh_hp:
                    choice = "DH"
                    reasons.append("COST_DOMINANT_DH")
                    logger.info(f"→ DH cheaper by {rel_diff:.1%}")
                else:
                    choice = "HP"
                    reasons.append("COST_DOMINANT_HP")
                    logger.info(f"→ HP cheaper by {rel_diff:.1%}")
            else:
                # --- STEP 3: CO₂ TIE-BREAKER ---
                logger.info("Step 3: Costs close → using CO₂ tie-breaker")
                reasons.append("COST_CLOSE_USE_CO2")
                
                if co2_dh <= co2_hp:
                    choice = "DH"
                    reasons.append("CO2_TIEBREAKER_DH")
                    if co2_dh == co2_hp:
                        logger.info("→ CO₂ equal → defaulting to DH for determinism")
                    else:
                        logger.info(f"→ DH lower CO₂ by {co2_hp - co2_dh:.1f} kg/MWh")
                else:
                    choice = "HP"
                    reasons.append("CO2_TIEBREAKER_HP")
                    logger.info(f"→ HP lower CO₂ by {co2_dh - co2_hp:.1f} kg/MWh")
    
    # --- STEP 4: ROBUSTNESS CHECK ---
    logger.info("Step 4: Evaluating robustness")
    
    robust = False
    win_fraction_threshold = config['robust_win_fraction']
    
    if choice == "DH" and mc.get('dh_wins_fraction'):
        win_fraction = mc['dh_wins_fraction']
        if win_fraction >= win_fraction_threshold:
            robust = True
            reasons.append("ROBUST_DECISION")
        elif win_fraction >= config['sensitive_win_fraction']:
            reasons.append("SENSITIVE_DECISION")
        logger.info(f"→ DH win fraction: {win_fraction:.1%} (robust: {robust})")
    
    elif choice == "HP" and mc.get('hp_wins_fraction'):
        win_fraction = mc['hp_wins_fraction']
        if win_fraction >= win_fraction_threshold:
            robust = True
            reasons.append("ROBUST_DECISION")
        elif win_fraction >= config['sensitive_win_fraction']:
            reasons.append("SENSITIVE_DECISION")
        logger.info(f"→ HP win fraction: {win_fraction:.1%} (robust: {robust})")
    
    else:
        reasons.append("MC_MISSING")
        logger.warning("→ Monte Carlo data missing, robustness unknown")
    
    # Compile metrics used
    metrics_used = {
        'lcoh_dh_median': lcoh_dh,
        'lcoh_hp_median': lcoh_hp,
        'co2_dh_median': co2_dh,
        'co2_hp_median': co2_hp,
    }
    
    # Add MC win fractions if available
    if 'dh_wins_fraction' in mc:
        metrics_used['dh_wins_fraction'] = mc['dh_wins_fraction']
    if 'hp_wins_fraction' in mc:
        metrics_used['hp_wins_fraction'] = mc['hp_wins_fraction']
    
    # Validate choice
    if choice not in ["DH", "HP", "UNDECIDED"]:
        raise RuntimeError(f"Invalid choice generated: {choice}")
    
    logger.info(f"Final decision: {choice} (robust: {robust})")
    
    return DecisionResult(
        choice=choice,
        robust=robust,
        reason_codes=reasons,
        metrics_used=metrics_used,
    )

def _extract_metric(contract: Dict[str, Any], path: str, default: Any = None) -> Any:
    """Safely extract nested metric using dot-notation path."""
    keys = path.split('.')
    value = contract
    try:
        for key in keys:
            value = value[key]
        return value
    except (KeyError, TypeError):
        return default

# Legacy wrapper for backward compatibility
def decide_cluster(
    contract: Dict[str, Any],
    strategy: str = "cost_first",
) -> Dict[str, Any]:
    """
    Legacy interface (kept for compatibility).
    Strategy parameter is ignored - all decisions use cost_first.CO2_tiebreaker.
    """
    
    result = decide_from_contract(contract)
    
    # Map to legacy format
    legacy_choice_map = {
        "DH": "district_heating",
        "HP": "heat_pumps",
        "UNDECIDED": "infeasible",
    }
    
    confidence = "medium"
    if result.robust:
        confidence = "high"
    elif result.choice == "UNDECIDED":
        confidence = "low"
    
    return {
        'decision': legacy_choice_map[result.choice],
        'rationale': result.reason_codes,
        'confidence': confidence,
        'metrics_used': result.metrics_used,
    }

# Export
__all__ = ['decide_from_contract', 'decide_cluster', 'DecisionResult', 'DEFAULT_DECISION_CONFIG']