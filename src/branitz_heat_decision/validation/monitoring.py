"""
Monitoring and metrics for validation system.

Tracks validation performance, logs results, and generates alerts.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional

from .logic_auditor import ValidationReport
from .config import ValidationConfig

logger = logging.getLogger(__name__)


@dataclass
class ValidationMetrics:
    """Aggregated metrics across multiple validations."""
    
    total_validations: int = 0
    pass_count: int = 0
    warning_count: int = 0
    fail_count: int = 0
    
    total_statements: int = 0
    total_contradictions: int = 0
    
    avg_confidence: float = 0.0
    avg_pass_rate: float = 0.0
    
    feedback_loop_triggers: int = 0
    avg_iterations_to_success: float = 0.0
    
    @property
    def overall_pass_rate(self) -> float:
        """Overall validation

 pass rate."""
        if self.total_validations == 0:
            return 0.0
        return self.pass_count / self.total_validations
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


class ValidationMonitor:
    """
    Monitors validation performance and logs results.
    
    Tracks metrics, generates reports, and triggers alerts for issues.
    """
    
    def __init__(self, config: Optional[ValidationConfig] = None):
        """
        Initialize monitor.
        
        Args:
            config: Validation configuration
        """
        self.config = config or ValidationConfig()
        self.metrics = ValidationMetrics()
        self.validation_history: List[ValidationReport] = []
        
        # Setup logging
        logging.basicConfig(
            level=getattr(logging, self.config.log_level),
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
    
    def record_validation(self, report: ValidationReport):
        """
        Record a validation result and update metrics.
        
        Args:
            report: Validation report to record
        """
        self.validation_history.append(report)
        
        # Update counters
        self.metrics.total_validations += 1
        if report.validation_status == "pass":
            self.metrics.pass_count += 1
        elif report.validation_status == "warning":
            self.metrics.warning_count += 1
        else:
            self.metrics.fail_count += 1
        
        self.metrics.total_statements += report.statements_validated
        self.metrics.total_contradictions += len(report.contradictions)
        
        # Update running averages
        n = self.metrics.total_validations
        old_avg_conf = self.metrics.avg_confidence
        old_avg_pass = self.metrics.avg_pass_rate
        
        self.metrics.avg_confidence = (old_avg_conf * (n - 1) + report.overall_confidence) / n
        self.metrics.avg_pass_rate = (old_avg_pass * (n - 1) + report.pass_rate) / n
        
        # Track feedback iterations
        if report.feedback_iterations > 0:
            self.metrics.feedback_loop_triggers += 1
            k = self.metrics.feedback_loop_triggers
            old_avg_iter = self.metrics.avg_iterations_to_success
            self.metrics.avg_iterations_to_success = (
                (old_avg_iter * (k - 1) + report.feedback_iterations) / k
            )
        
        # Log result
        logger.info(
            f"Validation recorded: {report.cluster_id} - "
            f"Status: {report.validation_status}, "
            f"Confidence: {report.overall_confidence:.2f}, "
            f"Contradictions: {len(report.contradictions)}"
        )
        
        # Check for alerts
        self._check_alerts(report)
        
        # Save report if configured
        if self.config.save_reports:
            self._save_report(report)
    
    def _check_alerts(self, report: ValidationReport):
        """Check if validation result triggers any alerts."""
        # Alert on contradictions
        if report.has_contradictions:
            logger.warning(
                f"⚠️  ALERT: {len(report.contradictions)} contradictions detected "
                f"for cluster {report.cluster_id}"
            )
            for contra in report.contradictions:
                logger.warning(f"  - {contra.statement[:100]}... (Confidence: {contra.confidence:.2f})")
        
        # Alert on low confidence
        if report.overall_confidence < self.config.min_confidence:
            logger.warning(
                f"⚠️  ALERT: Low validation confidence ({report.overall_confidence:.2f}) "
                f"for cluster {report.cluster_id}"
            )
        
        # Alert on excessive feedback iterations
        if report.feedback_iterations >= self.config.max_iterations:
            logger.warning(
                f"⚠️  ALERT: Max feedback iterations reached ({report.feedback_iterations}) "
                f"for cluster {report.cluster_id}"
            )
    
    def _save_report(self, report: ValidationReport):
        """Save validation report to disk."""
        try:
            # Create cluster-specific directory
            report_dir = self.config.report_dir / report.cluster_id
            report_dir.mkdir(parents=True, exist_ok=True)
            
            # Save as JSON
            report_path = report_dir / f"validation_{report.timestamp.strftime('%Y%m%d_%H%M%S')}.json"
            with open(report_path, 'w') as f:
                json.dump(report.to_dict(), f, indent=2)
            
            logger.debug(f"Validation report saved: {report_path}")
            
        except Exception as e:
            logger.error(f"Failed to save validation report: {e}")
    
    def get_metrics(self) -> ValidationMetrics:
        """Get current aggregated metrics."""
        return self.metrics
    
    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of monitoring status."""
        return {
            "metrics": self.metrics.to_dict(),
            "recent_validations": len(self.validation_history),
            "last_validation": (
                self.validation_history[-1].timestamp.isoformat()
                if self.validation_history else None
            )
        }
    
    def export_metrics(self, output_path: Path):
        """Export metrics to JSON file."""
        with open(output_path, 'w') as f:
            json.dump(self.get_summary(), f, indent=2)
        logger.info(f"Metrics exported to {output_path}")
