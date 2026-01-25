"""
Logic Auditor - validates LLM-generated rationales using TNLI.

Edit C: Fixed scoring semantics (verified/unverified/contradiction)
Edit D: Wired feedback loop for automatic regeneration

Checks if natural language explanations are consistent with KPI data tables.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Any, Optional, Callable

from .tnli_model import TNLIModel, LightweightResult as EntailmentResult, EntailmentLabel
from .config import ValidationConfig
from .claims import StructuredExplanation, ClaimValidator, ClaimResult

logger = logging.getLogger(__name__)


@dataclass
class Contradiction:
    """A detected contradiction between statement and table."""
    statement: str
    context: str  # Which KPI/metric it contradicts
    confidence: float
    evidence: Optional[Dict[str, Any]] = None


@dataclass
class ValidationReport:
    """
    Report of validation results.
    
    Edit C: Proper scoring semantics:
    - verified_rate: fraction of statements that are ENTAILED
    - unverified_rate: fraction that are NEUTRAL (not provable)
    - contradiction_rate: fraction that CONTRADICT the data
    """
    
    cluster_id: str
    timestamp: datetime
    validation_status: str  # "pass", "warning", "fail"
    overall_confidence: float
    
    statements_validated: int = 0
    contradictions: List[Contradiction] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    feedback_iterations: int = 0
    
    entailment_results: List[EntailmentResult] = field(default_factory=list)
    evidence: Dict[str, Any] = field(default_factory=dict)
    
    # Edit C: Proper scoring metrics
    verified_count: int = 0
    unverified_count: int = 0
    contradiction_count: int = 0
    
    @property
    def has_contradictions(self) -> bool:
        """Check if any contradictions were found."""
        return len(self.contradictions) > 0
    
    @property
    def verified_rate(self) -> float:
        """Percentage of statements that were verified (ENTAILED)."""
        if self.statements_validated == 0:
            return 0.0
        return self.verified_count / self.statements_validated
    
    @property
    def unverified_rate(self) -> float:
        """Percentage of statements that could not be verified (NEUTRAL)."""
        if self.statements_validated == 0:
            return 0.0
        return self.unverified_count / self.statements_validated
    
    @property
    def contradiction_rate(self) -> float:
        """Percentage of statements that contradict the data."""
        if self.statements_validated == 0:
            return 0.0
        return self.contradiction_count / self.statements_validated
    
    @property
    def pass_rate(self) -> float:
        """Alias for verified_rate for backward compatibility."""
        return self.verified_rate
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert report to dictionary for JSON serialization."""
        return {
            "cluster_id": self.cluster_id,
            "timestamp": self.timestamp.isoformat(),
            "validation_status": self.validation_status,
            "overall_confidence": self.overall_confidence,
            "statements_validated": self.statements_validated,
            # Include sentence-by-sentence results
            "sentence_results": [
                {
                    "statement": result.statement,
                    "status": "ENTAILMENT" if result.is_valid else 
                             "CONTRADICTION" if result.is_contradiction else 
                             "NEUTRAL",
                    "confidence": result.confidence,
                    "evidence": result.reason,
                    "label": result.label.value
                }
                for result in self.entailment_results
            ],
            "contradictions": [
                {
                    "statement": c.statement,
                    "context": c.context,
                    "confidence": c.confidence,
                    "evidence": c.evidence
                }
                for c in self.contradictions
            ],
            "warnings": self.warnings,
            "feedback_iterations": self.feedback_iterations,
            # Edit C: Include proper scoring
            "verified_count": self.verified_count,
            "unverified_count": self.unverified_count,
            "contradiction_count": self.contradiction_count,
            "verified_rate": self.verified_rate,
            "unverified_rate": self.unverified_rate,
            "contradiction_rate": self.contradiction_rate,
            "pass_rate": self.pass_rate,
            "evidence": self.evidence
        }


class LogicAuditor:
    """
    Validates LLM-generated decision rationales against KPI tables.
    
    Edit D: Includes optional feedback loop for automatic regeneration.
    """
    
    def __init__(self, config: Optional[ValidationConfig] = None):
        """Initialize Logic Auditor with TNLI model."""
        self.config = config or ValidationConfig()
        self.model = TNLIModel(self.config)
        self.claim_validator = ClaimValidator()
        logger.info("LogicAuditor initialized")
    
    def validate_rationale(
        self,
        kpis: Dict[str, Any],
        rationale: str,
        cluster_id: str = "unknown",
        regenerate_fn: Optional[Callable[[Dict[str, Any], str], str]] = None
    ) -> ValidationReport:
        """
        Validate a decision rationale against KPI table.
        
        Edit D: If regenerate_fn is provided and feedback is enabled,
        will attempt to regenerate on contradictions.
        
        Args:
            kpis: Dictionary of KPIs (metrics and values)
            rationale: Natural language explanation to validate
            cluster_id: Identifier for the cluster
            regenerate_fn: Optional function to regenerate rationale
            
        Returns:
            ValidationReport with validation results
        """
        current_rationale = rationale
        iteration = 0
        
        while iteration < self.config.max_iterations:
            iteration += 1
            
            # Perform validation
            report = self._validate_once(kpis, current_rationale, cluster_id)
            report.feedback_iterations = iteration
            
            # Check if we should stop
            if not report.has_contradictions:
                logger.info(f"Validation passed on iteration {iteration}")
                return report
            
            # Edit D: Attempt regeneration if enabled and function provided
            if not self.config.enable_feedback or regenerate_fn is None:
                return report
            
            if iteration >= self.config.max_iterations:
                logger.warning(f"Max iterations ({self.config.max_iterations}) reached")
                return report
            
            # Build enriched context for regeneration
            context = self._build_feedback_context(kpis, report.contradictions)
            
            logger.info(f"Regenerating rationale (iteration {iteration})")
            try:
                new_rationale = regenerate_fn(kpis, context)
                
                if new_rationale.strip() == current_rationale.strip():
                    logger.warning("Regenerated rationale unchanged, stopping")
                    return report
                
                current_rationale = new_rationale
            except Exception as e:
                logger.error(f"Regeneration failed: {e}")
                return report
        
        return report
    
    def _validate_once(
        self,
        kpis: Dict[str, Any],
        rationale: str,
        cluster_id: str
    ) -> ValidationReport:
        """Single validation pass (no feedback loop)."""
        # Parse rationale into individual statements
        statements = self._parse_statements(rationale)
        
        logger.info(f"Validating {len(statements)} statements for cluster {cluster_id}")
        
        # Validate each statement
        results = self.model.batch_validate(kpis, statements)
        
        # Edit C: Proper scoring semantics
        contradictions = []
        warnings = []
        verified_count = 0
        unverified_count = 0
        contradiction_count = 0
        total_confidence = 0.0
        
        for result in results:
            total_confidence += result.confidence
            
            if result.is_valid:  # ENTAILED
                verified_count += 1
            elif result.is_contradiction:  # CONTRADICTION
                contradiction_count += 1
                context = self._identify_contradiction_context(result.statement, kpis)
                contradictions.append(Contradiction(
                    statement=result.statement,
                    context=context,
                    confidence=result.confidence,
                    evidence={
                        "kpis_checked": list(kpis.keys()),
                        "reason": result.reason
                    }
                ))
            else:  # NEUTRAL
                unverified_count += 1
                if result.confidence < self.config.min_confidence:
                    warnings.append(f"Could not verify: {result.statement[:100]}")
        
        # Edit C: Proper status determination
        # FAIL only if contradictions exist
        # WARNING if too many unverified (neutral) or low confidence
        # PASS if verified is high and contradictions are zero
        if contradictions:
            status = "fail"
        elif unverified_count > len(statements) * 0.5:  # >50% unverified
            status = "warning"
        elif warnings:
            status = "warning"
        else:
            status = "pass"
        
        avg_confidence = total_confidence / len(results) if results else 0.0
        
        report = ValidationReport(
            cluster_id=cluster_id,
            timestamp=datetime.now(),
            validation_status=status,
            overall_confidence=avg_confidence,
            statements_validated=len(statements),
            contradictions=contradictions,
            warnings=warnings,
            entailment_results=results,
            verified_count=verified_count,
            unverified_count=unverified_count,
            contradiction_count=contradiction_count,
            evidence={"kpis": {k: str(v) for k, v in kpis.items()}}
        )
        
        logger.info(
            f"Validation: {status} | Verified: {verified_count}, "
            f"Unverified: {unverified_count}, Contradictions: {contradiction_count}"
        )
        
        return report
    
    def validate_structured_claims(
        self,
        kpis: Dict[str, Any],
        explanation: StructuredExplanation,
        cluster_id: str = "unknown"
    ) -> ValidationReport:
        """
        Validate structured claims (Edit A format).
        
        Deterministic validation - no LLM needed.
        """
        results = self.claim_validator.validate_all(explanation, kpis)
        
        contradictions = []
        verified_count = 0
        
        for result in results:
            if result.is_valid:
                verified_count += 1
            else:
                contradictions.append(Contradiction(
                    statement=result.claim.description or str(result.claim.lhs),
                    context=result.reason,
                    confidence=1.0,  # Deterministic
                    evidence={
                        "lhs": result.actual_lhs,
                        "rhs": result.actual_rhs,
                        "operator": result.claim.op.value
                    }
                ))
        
        status = "fail" if contradictions else "pass"
        
        # Convert ClaimResults to EntailmentResults for UI display
        entailment_results = []
        for result in results:
            label = EntailmentLabel.ENTAILMENT if result.is_valid else EntailmentLabel.CONTRADICTION
            statement = result.claim.description or f"{result.claim.lhs} {result.claim.op} {result.claim.rhs}"
            
            entailment_results.append(EntailmentResult(
                statement=statement,
                label=label,
                confidence=1.0,
                reason=result.reason
            ))

        return ValidationReport(
            cluster_id=cluster_id,
            timestamp=datetime.now(),
            validation_status=status,
            overall_confidence=1.0,  # Deterministic
            statements_validated=len(results),
            contradictions=contradictions,
            verified_count=verified_count,
            unverified_count=0,
            contradiction_count=len(contradictions),
            evidence={"kpis": {k: str(v) for k, v in kpis.items()}},
            entailment_results=entailment_results
        )
    
    def validate_decision_explanation(
        self,
        decision_data: Dict[str, Any]
    ) -> ValidationReport:
        """
        Validate a complete decision explanation.
        
        Issue A Fix: Injects choice/reason_codes into KPIs for deterministic validation.
        Correctness Fix: Uses structured claims for reason_codes to validate each individually.
        """
        kpis = decision_data.get("kpis", decision_data.get("metrics_used", {})).copy()
        cluster_id = decision_data.get("cluster_id", "unknown")
        reason_codes = decision_data.get("reason_codes", [])
        
        # Issue A: Inject decision fields into KPIs for rule-based validation
        if "choice" in decision_data:
            kpis["choice"] = decision_data["choice"]
        if "recommendation" in decision_data:
            kpis["recommendation"] = decision_data["recommendation"]
        if "robust" in decision_data:
            kpis["robust"] = decision_data["robust"]
        if reason_codes:
            kpis["reason_codes"] = reason_codes
            
            # Infer feasibility from reason_codes if not already set
            if "ONLY_DH_FEASIBLE" in reason_codes:
                if "dh_feasible" not in kpis and "cha_feasible" not in kpis:
                    kpis["dh_feasible"] = True
                if "hp_feasible" not in kpis and "dha_feasible" not in kpis:
                    kpis["hp_feasible"] = False
            elif "ONLY_HP_FEASIBLE" in reason_codes:
                if "hp_feasible" not in kpis and "dha_feasible" not in kpis:
                    kpis["hp_feasible"] = True
                if "dh_feasible" not in kpis and "cha_feasible" not in kpis:
                    kpis["dh_feasible"] = False
                    
            # Infer robustness from ROBUST_DECISION reason code
            if "ROBUST_DECISION" in reason_codes and "robust" not in kpis:
                kpis["robust"] = True
        
        # Check for structured claims first (best path - fully deterministic)
        if "claims" in decision_data:
            explanation = StructuredExplanation.from_dict(decision_data)
            return self.validate_structured_claims(kpis, explanation, cluster_id)
        
        # Correctness Fix: If reason_codes exist, use structured claims path
        # This ensures each reason code is validated individually
        if reason_codes:
            structured = StructuredExplanation.from_decision_result(decision_data)

            return self.validate_structured_claims(kpis, structured, cluster_id)
        
        # Fall back to free-text validation only if no structured data available
        explanation = decision_data.get("explanation", "")
        return self.validate_rationale(kpis, explanation, cluster_id)
    
    def _parse_statements(self, rationale: str) -> List[str]:
        """Parse rationale into individual statements for validation."""
        import re
        
        # Split on sentence boundaries
        sentences = re.split(r'[.!?]+', rationale)
        
        # Clean and filter
        statements = []
        for sentence in sentences:
            cleaned = sentence.strip()
            if len(cleaned) > 15 and any(char.isalpha() for char in cleaned):
                statements.append(cleaned)
        
        return statements
    
    def _identify_contradiction_context(self, statement: str, kpis: Dict[str, Any]) -> str:
        """Identify which KPI(s) a contradictory statement relates to."""
        statement_lower = statement.lower()
        
        relevant_kpis = []
        for key in kpis.keys():
            if key.lower().replace("_", " ") in statement_lower:
                relevant_kpis.append(key)
        
        if relevant_kpis:
            return f"KPIs: {', '.join(relevant_kpis)}"
        else:
            return "Unknown KPI context"
    
    def _build_feedback_context(
        self,
        kpis: Dict[str, Any],
        contradictions: List[Contradiction]
    ) -> str:
        """Build enriched context for LLM regeneration."""
        context_parts = [
            "IMPORTANT: Previous explanation contained contradictions.",
            "",
            "**Verified KPI Values:**"
        ]
        
        for key, value in kpis.items():
            context_parts.append(f"- {key}: {value}")
        
        context_parts.append("")
        context_parts.append("**Detected Contradictions:**")
        
        for i, contra in enumerate(contradictions, 1):
            context_parts.append(f"{i}. \"{contra.statement}\"")
            context_parts.append(f"   Problem: {contra.context}")
        
        context_parts.extend([
            "",
            "**Guidelines:**",
            "- Only make statements verifiable from KPIs",
            "- Use exact values from the table",
            "- Avoid speculation"
        ])
        
        return "\n".join(context_parts)
