"""
Example integration of TNLI Logic Auditor into decision pipeline.

This demonstrates how to validate LLM-generated explanations against KPI data.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional

from branitz_heat_decision.decision import kpi_contract, rules
from branitz_heat_decision.validation import LogicAuditor, ValidationConfig, FeedbackLoop

logger = logging.getLogger(__name__)


def validate_decision_explanation(
    cluster_id: str,
    kpis: Dict[str, Any],
    explanation: str,
    validation_config: Optional[ValidationConfig] = None,
    enable_feedback: bool = True
) -> tuple[str, Dict[str, Any]]:
    """
    Validate and potentially refine an LLM-generated decision explanation.
    
    Args:
        cluster_id: Cluster identifier
        kpis: KPI contract data
        explanation: LLM-generated explanation text
        validation_config: Optional validation configuration
        enable_feedback: Whether to use feedback loop for refinement
        
    Returns:
        Tuple of (final_explanation, validation_report_dict)
    """
    config = validation_config or ValidationConfig()
    
    if not enable_feedback:
        # Simple validation without feedback
        auditor = LogicAuditor(config)
        report = auditor.validate_rationale(kpis, explanation, cluster_id)
        
        logger.info(
            f"Validation complete: {report.validation_status} "
            f"({len(report.contradictions)} contradictions)"
        )
        
        return explanation, report.to_dict()
    
    else:
        # Validation with automatic feedback loop
        from branitz_heat_decision.validation.feedback_loop import create_feedback_loop
        
        feedback_loop = create_feedback_loop(config)
        
        # Define regeneration function (placeholder - would call actual LLM)
        def regenerate_fn(kpis_data: Dict[str, Any], additional_context: str) -> str:
            """
            Regenerate explanation with additional context.
            
            In real implementation, this would call the LLM with enriched context.
            For now, returns a refined version with disclaimer.
            """
            logger.warning("Regeneration function not implemented - returning original with disclaimer")
            return f"{explanation}\n\n[Note: Validation detected issues. Manual review recommended.]"
        
        final_explanation, report = feedback_loop.validate_with_feedback(
            kpis=kpis,
            initial_rationale=explanation,
            regenerate_fn=regenerate_fn,
            cluster_id=cluster_id
        )
        
        logger.info(
            f"Validation with feedback complete: {report.validation_status} "
            f"(iterations: {report.feedback_iterations})"
        )
        
        return final_explanation, report.to_dict()


def make_decision_with_validation(
    cluster_id: str,
    results_dir: Path = Path("results"),
    validate_explanation: bool = True
) -> Dict[str, Any]:
    """
    Run decision pipeline with optional TNLI validation.
    
    Args:
        cluster_id: Cluster to analyze
        results_dir: Results directory
        validate_explanation: Whether to validate LLM explanations
        
    Returns:
        Decision result dictionary with validation report if enabled
    """
    logger.info(f"Making decision for cluster: {cluster_id}")
    
    # Build KPI contract
    contract_data = kpi_contract.build_kpi_contract(
        cluster_id=cluster_id,
        results_dir=results_dir
    )
    
    # Make deterministic decision
    decision_result = rules.decide_from_contract(contract_data)
    
    # Prepare decision output
    decision_output = {
        "cluster_id": cluster_id,
        "choice": decision_result.choice,
        "robust": decision_result.robust,
        "reason_codes": decision_result.reason_codes,
        "metrics": decision_result.metrics_used,
        "kpis": contract_data,  # Include full KPI data
    }
    
    # If LLM explanation exists and validation is enabled
    if validate_explanation and "explanation" in decision_output:
        logger.info("Validating LLM-generated explanation...")
        
        validated_explanation, validation_report = validate_decision_explanation(
            cluster_id=cluster_id,
            kpis=contract_data,
            explanation=decision_output["explanation"],
            enable_feedback=True
        )
        
        # Update decision output with validated explanation and report
        decision_output["explanation"] = validated_explanation
        decision_output["validation_report"] = validation_report
        
        # Log validation status
        if validation_report["validation_status"] == "fail":
            logger.warning(
                f"⚠️ Validation failed: {len(validation_report['contradictions'])} contradictions detected"
            )
        elif validation_report["validation_status"] == "warning":
            logger.warning(f"⚠️ Validation warnings: {len(validation_report['warnings'])}")
        else:
            logger.info("✅ Validation passed")
    
    # Save decision with validation
    decision_dir = results_dir / "decision" / cluster_id
    decision_dir.mkdir(parents=True, exist_ok=True)
    
    decision_path = decision_dir / "decision.json"
    with open(decision_path, 'w') as f:
        json.dump(decision_output, f, indent=2)
    
    logger.info(f"Decision saved: {decision_path}")
    
    return decision_output


# Example CLI usage
if __name__ == "__main__":
    import argparse
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    parser = argparse.ArgumentParser(description="Make decision with TNLI validation")
    parser.add_argument("--cluster-id", required=True, help="Cluster ID")
    parser.add_argument("--results-dir", default="results", help="Results directory")
    parser.add_argument("--no-validation", action="store_true", help="Disable TNLI validation")
    
    args = parser.parse_args()
    
    result = make_decision_with_validation(
        cluster_id=args.cluster_id,
        results_dir=Path(args.results_dir),
        validate_explanation=not args.no_validation
    )
    
    print(f"\nDecision: {result['choice']}")
    print(f"Robust: {result['robust']}")
    
    if "validation_report" in result:
        report = result["validation_report"]
        print(f"\nValidation Status: {report['validation_status']}")
        print(f"Confidence: {report['overall_confidence']:.2%}")
        if report["contradictions"]:
            print(f"Contradictions: {len(report['contradictions'])}")
