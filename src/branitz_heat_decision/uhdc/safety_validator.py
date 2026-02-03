"""
TNLI Logic Auditor for LLM Explanation Validation
Implements claim-type validation as described in Thesis Section 3.9.6
"""
import re
import logging
from typing import List, Dict, Union, Tuple, Optional
from enum import Enum

logger = logging.getLogger(__name__)


class ClaimType(Enum):
    NUMERICAL = "numerical"
    COMPARISON = "comparison"
    THRESHOLD = "threshold"
    CATEGORICAL = "categorical"


class Claim:
    def __init__(
        self,
        claim_type: ClaimType,
        subject: str,
        value: Union[float, str],
        relation: Optional[str] = None,
        reference: Optional[str] = None,
    ):
        self.claim_type = claim_type
        self.subject = subject
        self.value = value
        self.relation = relation  # for comparisons: ">", "<", "=="
        self.reference = reference


class LogicAuditor:
    """
    Textual Natural Language Inference validator for LLM explanations.
    Parses explanations into atomic claims and validates against KPI contract.
    """

    TOLERANCE = 0.01  # 1% tolerance for numerical claims

    def __init__(self, kpi_contract: Optional[dict] = None):
        self.contract = kpi_contract or {}
        self.extracted_claims: List[Claim] = []
        self.violations: List[str] = []

    def parse_claims(self, explanation: str) -> List[Claim]:
        """
        Parse explanation text into typed claims.
        Supports: numerical, comparison, threshold, categorical
        """
        claims = []

        # Numerical claims: "DH LCOH is 145.2 EUR/MWh" or "HP LCOH is 80.0 EUR/MWh"
        # Pattern 1: System-specific LCOH (DH/HP)
        dh_hp_pattern = r"(DH|HP|district heating|heat pump).*?LCOH.*?is\s+(\d+\.?\d*)\s*(EUR\/MWh)"
        matches = re.finditer(dh_hp_pattern, explanation, re.IGNORECASE)
        for match in matches:
            system = match.group(1).lower()
            value = float(match.group(2))
            unit = match.group(3)
            system_key = "dh" if "dh" in system or "district" in system else "hp"
            claims.append(Claim(ClaimType.NUMERICAL, f"lcoh_{system_key}_{unit}", value))
        
        # Pattern 2: Generic metrics (velocity, pressure, loading)
        generic_pattern = r"(velocity|pressure|loading).*?is\s+(\d+\.?\d*)\s*(m\/s|Pa|%|p\.u\.)"
        matches = re.finditer(generic_pattern, explanation, re.IGNORECASE)
        for match in matches:
            subject = match.group(1).lower()
            value = float(match.group(2))
            unit = match.group(3)
            claims.append(Claim(ClaimType.NUMERICAL, f"{subject}_{unit}", value))

        # Comparison claims: "DH is cheaper than HP", "velocity exceeds 1.5 m/s"
        comp_pattern = r"(DH|HP|district heating|heat pump).*?(is|are)\s+(cheaper|more expensive|lower|higher|better|worse).*?(than|DH|HP)"
        if re.search(comp_pattern, explanation, re.IGNORECASE):
            claims.append(Claim(ClaimType.COMPARISON, "lcoh_comparison", None, relation="<"))

        # Threshold claims: "within limits", "exceeds threshold"
        thresh_pattern = r"(velocity|pressure|loading).*?(within|exceeds|below|above).*?(limits|threshold|1\.5|0\.95|100)"
        matches = re.finditer(thresh_pattern, explanation, re.IGNORECASE)
        for match in matches:
            subject = match.group(1)
            relation = match.group(2)  # within, exceeds
            limit = match.group(3)
            claims.append(Claim(ClaimType.THRESHOLD, subject, limit, relation=relation))

        # Categorical claims: "feasible", "infeasible", "robust", "marginal"
        cat_pattern = r"(feasible|infeasible|robust|marginal|uncertain)"
        matches = re.finditer(cat_pattern, explanation, re.IGNORECASE)
        for match in matches:
            claims.append(Claim(ClaimType.CATEGORICAL, "decision_status", match.group(1).lower()))

        self.extracted_claims = claims
        return claims

    def validate_claim(self, claim: Claim) -> bool:
        """
        Validate individual claim against KPI contract.
        Returns True if valid, False if contradiction detected.
        """
        if claim.claim_type == ClaimType.NUMERICAL:
            return self._validate_numerical(claim)
        elif claim.claim_type == ClaimType.COMPARISON:
            return self._validate_comparison(claim)
        elif claim.claim_type == ClaimType.THRESHOLD:
            return self._validate_threshold(claim)
        elif claim.claim_type == ClaimType.CATEGORICAL:
            return self._validate_categorical(claim)
        return False

    def _validate_numerical(self, claim: Claim) -> bool:
        """Validate numerical claim within ±1% tolerance"""
        # Extract contract values based on subject
        contract_value = self._get_contract_value(claim.subject)
        if contract_value is None:
            self.violations.append(f"Subject {claim.subject} not found in contract")
            return False

        # Check tolerance
        diff = abs(claim.value - contract_value) / max(abs(contract_value), 1e-9)
        if diff > self.TOLERANCE:
            self.violations.append(
                f"Numerical mismatch: claimed {claim.value}, contract has {contract_value} "
                f"(diff: {diff:.2%}, tol: {self.TOLERANCE:.0%})"
            )
            return False
        return True

    def _validate_comparison(self, claim: Claim) -> bool:
        """Validate ordering claims (e.g., DH cheaper than HP)"""
        dh_lcoh = self.contract.get("district_heating", {}).get("lcoh", {}).get("median")
        hp_lcoh = self.contract.get("heat_pumps", {}).get("lcoh", {}).get("median")

        if dh_lcoh is None or hp_lcoh is None:
            return False

        if "cheaper" in claim.subject or claim.relation == "<":
            if dh_lcoh >= hp_lcoh:
                self.violations.append(
                    f"Claimed DH cheaper, but DH LCOH ({dh_lcoh}) >= HP ({hp_lcoh})"
                )
                return False
        return True

    def _validate_threshold(self, claim: Claim) -> bool:
        """Validate threshold claims (within limits, exceeds, etc.)"""
        if "velocity" in claim.subject:
            v_share = (
                self.contract.get("district_heating", {})
                .get("hydraulics", {})
                .get("v_share_within_limits", 0)
            )
            if claim.relation == "within" and v_share < 0.95:
                self.violations.append(
                    f"Claimed velocity within limits, but v_share={v_share:.2f} < 0.95"
                )
                return False
        return True

    def _validate_categorical(self, claim: Claim) -> bool:
        """Validate categorical claims (feasible, robust, etc.)"""
        contract_status = self.contract.get("district_heating", {}).get("feasible")
        if claim.value in ["feasible", "infeasible"]:
            claimed_bool = claim.value == "feasible"
            if claimed_bool != contract_status:
                self.violations.append(
                    f"Claimed {claim.value}, but contract has feasible={contract_status}"
                )
                return False
        return True

    def _get_contract_value(self, subject: str) -> Union[float, None]:
        """Extract relevant value from KPI contract based on subject string"""
        subject_lower = subject.lower()
        
        # System-specific LCOH (DH or HP)
        if "lcoh_dh_eur/mwh" in subject_lower:
            value = self.contract.get("district_heating", {}).get("lcoh", {}).get("median")
            return float(value) if isinstance(value, (int, float)) else None
        elif "lcoh_hp_eur/mwh" in subject_lower:
            value = self.contract.get("heat_pumps", {}).get("lcoh", {}).get("median")
            return float(value) if isinstance(value, (int, float)) else None
        
        # Generic metrics
        mapping = {
            "velocity_m/s": ["district_heating", "hydraulics", "v_max_ms"],
            "loading_%": ["heat_pumps", "lv_grid", "max_feeder_loading_pct"],
        }

        for key, path in mapping.items():
            if key in subject_lower:
                value = self.contract
                for p in path:
                    value = value.get(p, {})
                return float(value) if isinstance(value, (int, float)) else None
        return None

    def validate_explanation(self, explanation: str) -> Tuple[bool, List[str]]:
        """
        Main entry point: validate full explanation.
        Returns: (is_valid, violations_list)
        """
        claims = self.parse_claims(explanation)

        if not claims:
            # No verifiable claims found - risky but not necessarily invalid
            return True, ["WARNING: No verifiable claims extracted"]

        all_valid = True
        for claim in claims:
            if not self.validate_claim(claim):
                all_valid = False

        return all_valid, self.violations


def generate_safe_explanation(
    contract: dict, decision: dict, style: str = "executive"
) -> str:
    """
    Generate explanation with TNLI validation and template fallback.
    Integrates with existing explainer module.
    """
    from .explainer import explain_with_llm, _fallback_template_explanation

    # Try LLM explanation first
    try:
        llm_explanation = explain_with_llm(contract, decision, style=style, no_fallback=True)
    except Exception as e:
        logger.warning(f"LLM explanation failed: {e}, using template")
        return _fallback_template_explanation(contract, decision, style)

    # Validate with Logic Auditor
    auditor = LogicAuditor(contract)
    is_valid, violations = auditor.validate_explanation(llm_explanation)

    if not is_valid:
        # Hallucination detected - fallback to template
        logger.warning(f"LLM explanation failed validation: {violations}")
        return _fallback_template_explanation(contract, decision, style)

    return llm_explanation


def generate_template_explanation(
    contract: dict, decision: dict, violations: Optional[List[str]] = None
) -> str:
    """Deterministic fallback template when LLM fails validation."""
    from .explainer import _fallback_template_explanation

    explanation = _fallback_template_explanation(contract, decision, style="executive")

    if violations:
        explanation += f"\n\n[Note: Automated validation detected {len(violations)} inconsistencies]"

    return explanation
