"""
Feedback loop for re-generating LLM rationales when contradictions are detected.

Implements iterative refinement with context enrichment.
"""

from __future__ import annotations

import logging
from typing import Dict, Any, Optional, Callable

from .logic_auditor import LogicAuditor, ValidationReport, Contradiction
from .config import ValidationConfig

logger = logging.getLogger(__name__)


class FeedbackLoop:
    """
    Manages feedback loop for LLM rationale re-generation.
    
    When contradictions are detected, enriches context and triggers
    LLM to regenerate the rationale.
    """
    
    def __init__(self, auditor: LogicAuditor, config: Optional[ValidationConfig] = None):
        """
        Initialize feedback loop.
        
        Args:
            auditor: LogicAuditor instance
            config: Validation configuration
        """
        self.auditor = auditor
        self.config = config or ValidationConfig()
    
    def validate_with_feedback(
        self,
        kpis: Dict[str, Any],
        initial_rationale: str,
        regenerate_fn: Callable[[Dict[str, Any], str], str],
        cluster_id: str = "unknown"
    ) -> tuple[str, ValidationReport]:
        """
        Validate rationale with automatic feedback loop.
        
        Args:
            kpis: KPI data table
            initial_rationale: Initial LLM-generated rationale
            regenerate_fn: Function to regenerate rationale
                           Signature: (kpis: dict, additional_context: str) -> str
            cluster_id: Cluster identifier
            
        Returns:
            Tuple of (final_rationale, validation_report)
        """
        if not self.config.enable_feedback:
            # Just validate once without feedback
            report = self.auditor.validate_rationale(kpis, initial_rationale, cluster_id)
            return initial_rationale, report
        
        rationale = initial_rationale
        iteration = 0
        
        while iteration < self.config.max_iterations:
            iteration += 1
            logger.info(f"Validation iteration {iteration}/{self.config.max_iterations}")
            
            # Validate current rationale
            report = self.auditor.validate_rationale(kpis, rationale, cluster_id)
            report.feedback_iterations = iteration
            
            # Check if validation passed
            if not report.has_contradictions:
                logger.info(f"Validation passed on iteration {iteration}")
                return rationale, report
            
            # Check if max iterations reached
            if iteration >= self.config.max_iterations:
                logger.warning(f"Max iterations ({self.config.max_iterations}) reached")
                break
            
            # Build context for re-generation
            context = self._build_enriched_context(kpis, report.contradictions)
            logger.info(f"Re-generating rationale with enriched context (iteration {iteration})")
            
            try:
                # Re-generate rationale
                new_rationale = regenerate_fn(kpis, context)
                
                # Check if rationale actually changed
                if new_rationale.strip() == rationale.strip():
                    logger.warning("Re-generated rationale unchanged, stopping iteration")
                    break
                
                rationale = new_rationale
                
            except Exception as e:
                logger.error(f"Failed to regenerate rationale: {e}")
                break
        
        # Return best attempt
        final_report = self.auditor.validate_rationale(kpis, rationale, cluster_id)
        final_report.feedback_iterations = iteration
        
        return rationale, final_report
    
    def _build_enriched_context(
        self,
        kpis: Dict[str, Any],
        contradictions: list[Contradiction]
    ) -> str:
        """
        Build enriched context for LLM re-generation.
        
        Args:
            kpis: KPI data
            contradictions: List of detected contradictions
            
        Returns:
            Formatted context string with correction guidance
        """
        context_parts = []
        
        context_parts.append("IMPORTANT: Previous explanation contained contradictions with the data.")
        context_parts.append("Please regenerate ensuring all statements are consistent with these KPIs:")
        context_parts.append("")
        
        # Add relevant KPIs
        context_parts.append("**Verified KPI Values:**")
        for key, value in kpis.items():
            context_parts.append(f"- {key}: {value}")
        context_parts.append("")
        
        # Add contradiction details
        if contradictions:
            context_parts.append("**Detected Contradictions:**")
            for i, contra in enumerate(contradictions, 1):
                context_parts.append(f"{i}. \"{contra.statement}\"")
                context_parts.append(f"   Context: {contra.context}")
                if contra.evidence:
                    context_parts.append(f"   Evidence: {contra.evidence}")
            context_parts.append("")
        
        # Add guidance
        context_parts.append("**Guidelines:**")
        context_parts.append("- Only make statements that can be directly verified from the KPIs")
        context_parts.append("- Use exact values from the KPI table")
        context_parts.append("- Avoid speculation or unsupported conclusions")
        context_parts.append("- Be precise with numbers and comparisons")
        
        return "\n".join(context_parts)


def create_feedback_loop(
    config: Optional[ValidationConfig] = None
) -> FeedbackLoop:
    """
    Factory function to create a FeedbackLoop instance.
    
    Args:
        config: Optional validation configuration
        
    Returns:
        Configured FeedbackLoop instance
    """
    auditor = LogicAuditor(config)
    return FeedbackLoop(auditor, config)
