"""
Main DH network design validation engine.

Coordinates all validation checks and generates comprehensive report.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional
from pathlib import Path
import json

import geopandas as gpd
import pandas as pd
import pandapipes as pp

from branitz_heat_decision.config.validation_standards import ValidationConfig, get_default_validation_config
from branitz_heat_decision.cha.geospatial_checks import GeospatialValidator
from branitz_heat_decision.cha.hydraulic_checks import HydraulicValidator
from branitz_heat_decision.cha.thermal_checks import ThermalValidator
from branitz_heat_decision.cha.robustness_checks import RobustnessValidator

logger = logging.getLogger(__name__)


@dataclass
class ValidationReport:
    """Complete validation report"""
    
    cluster_id: str
    timestamp: datetime
    
    # Overall status
    passed: bool
    validation_level: str  # "PASS", "PASS_WITH_WARNINGS", "FAIL"
    
    # Individual check results
    geospatial_passed: bool
    hydraulic_passed: bool
    thermal_passed: bool
    robustness_passed: bool
    
    # All issues and warnings
    all_issues: List[str] = field(default_factory=list)
    all_warnings: List[str] = field(default_factory=list)
    
    # Metrics from all checks
    metrics: Dict[str, any] = field(default_factory=dict)
    
    # Raw results from each validator (optional to store)
    # geospatial_result: Optional[any] = None
    # hydraulic_result: Optional[any] = None
    # thermal_result: Optional[any] = None
    # robustness_result: Optional[any] = None
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization"""
        return {
            "cluster_id": self.cluster_id,
            "timestamp": self.timestamp.isoformat(),
            "validation_summary": {
                "passed": self.passed,
                "level": self.validation_level,
                "total_issues": len(self.all_issues),
                "total_warnings": len(self.all_warnings)
            },
            "check_results": {
                "geospatial": self.geospatial_passed,
                "hydraulic": self.hydraulic_passed,
                "thermal": self.thermal_passed,
                "robustness": self.robustness_passed
            },
            "issues": self.all_issues,
            "warnings": self.all_warnings,
            "metrics": self.metrics
        }
    
    def generate_summary(self) -> str:
        """Generate human-readable summary"""
        
        lines = []
        lines.append("=" * 60)
        lines.append(f"DH Network Design Validation Report")
        lines.append(f"Cluster: {self.cluster_id}")
        lines.append(f"Time: {self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("=" * 60)
        lines.append("")
        
        # Overall status
        status_icon = "✅" if self.passed else "❌"
        lines.append(f"{status_icon} Overall Status: {self.validation_level}")
        lines.append("")
        
        # Individual checks
        lines.append("Individual Checks:")
        checks = [
            ("Geospatial", self.geospatial_passed),
            ("Hydraulic (EN 13941-1)", self.hydraulic_passed),
            ("Thermal", self.thermal_passed),
            ("Robustness", self.robustness_passed)
        ]
        
        for name, passed in checks:
            icon = "✅" if passed else "❌"
            lines.append(f"  {icon} {name}")
        
        lines.append("")
        
        # Issues
        if self.all_issues:
            lines.append(f"❌ Issues ({len(self.all_issues)}):")
            for i, issue in enumerate(self.all_issues, 1):
                lines.append(f"  {i}. {issue}")
            lines.append("")
        
        # Warnings
        if self.all_warnings:
            lines.append(f"⚠️  Warnings ({len(self.all_warnings)}):")
            for i, warning in enumerate(self.all_warnings, 1):
                lines.append(f"  {i}. {warning}")
            lines.append("")
        
        # Key metrics
        lines.append("Key Metrics:")
        key_metrics = [
            ("Building Connectivity", "building_connectivity_pct", "%"),
            ("Max Velocity", "max_velocity_m_per_s", "m/s"),
            ("Max Pressure Drop", "max_pressure_drop_bar", "bar"),
            ("Heat Losses", "heat_loss_pct", "%"),
            ("Robustness", "robustness_success_rate", "%")
        ]
        
        for name, key, unit in key_metrics:
            if key in self.metrics:
                value = self.metrics[key]
                if "pct" in key or "rate" in key:
                    lines.append(f"  - {name}: {value:.1f}{unit}")
                else:
                    lines.append(f"  - {name}: {value:.2f} {unit}")
        
        lines.append("")
        lines.append("=" * 60)
        
        return "\n".join(lines)


class DHNetworkDesignValidator:
    """
    Complete DH network design validator.
    
    Coordinates all validation checks according to Document 24 methodology.
    """
    
    def __init__(self, config: Optional[ValidationConfig] = None):
        """
        Initialize validator.
        
        Args:
            config: Validation configuration (uses defaults if None)
        """
        self.config = config or get_default_validation_config()
        
        # Initialize individual validators
        self.geospatial = GeospatialValidator(self.config)
        self.hydraulic = HydraulicValidator(self.config)
        self.thermal = ThermalValidator(self.config)
        self.robustness = RobustnessValidator(self.config)
        
        logger.info("DHNetworkDesignValidator initialized")
    
    def validate_design(
        self,
        net: pp.pandapipesNet,
        cluster_id: str,
        streets_gdf: Optional[gpd.GeoDataFrame] = None,
        buildings_gdf: Optional[gpd.GeoDataFrame] = None,
        run_robustness: bool = True
    ) -> ValidationReport:
        """
        Complete design validation.
        
        Args:
            net: Pandapipes network (must have converged pipeflow results)
            cluster_id: Cluster identifier
            streets_gdf: Street network (required for geospatial checks)
            buildings_gdf: Buildings with demand (required for geospatial checks)
            run_robustness: Whether to run Monte Carlo robustness check
        
        Returns:
            ValidationReport with complete results
        """
        
        logger.info(f"Starting design validation for cluster {cluster_id}")
        
        timestamp = datetime.now()
        
        all_issues = []
        all_warnings = []
        metrics = {}
        
        # 1. GEOSPATIAL VALIDATION
        # geospatial_result = None
        geospatial_passed = True
        
        if streets_gdf is not None and buildings_gdf is not None:
            logger.info("Running geospatial validation...")
            geospatial_result = self.geospatial.validate(net, streets_gdf, buildings_gdf)
            
            geospatial_passed = geospatial_result.passed
            all_issues.extend([f"[Geospatial] {issue}" for issue in geospatial_result.issues])
            all_warnings.extend([f"[Geospatial] {warn}" for warn in geospatial_result.warnings])
            metrics.update(geospatial_result.metrics)
        else:
            logger.warning("Skipping geospatial validation (no street/building data provided)")
        
        # 2. HYDRAULIC VALIDATION
        logger.info("Running hydraulic validation (EN 13941-1)...")
        hydraulic_result = self.hydraulic.validate(net)
        
        hydraulic_passed = hydraulic_result.passed
        all_issues.extend([f"[Hydraulic] {issue}" for issue in hydraulic_result.issues])
        all_warnings.extend([f"[Hydraulic] {warn}" for warn in hydraulic_result.warnings])
        metrics.update(hydraulic_result.metrics)
        
        # 3. THERMAL VALIDATION
        logger.info("Running thermal validation...")
        thermal_result = self.thermal.validate(net)
        
        thermal_passed = thermal_result.passed
        all_issues.extend([f"[Thermal] {issue}" for issue in thermal_result.issues])
        all_warnings.extend([f"[Thermal] {warn}" for warn in thermal_result.warnings])
        metrics.update(thermal_result.metrics)
        
        # 4. ROBUSTNESS VALIDATION (optional, can be slow)
        # robustness_result = None
        robustness_passed = True
        
        if run_robustness:
            logger.info("Running robustness validation (Monte Carlo)...")
            robustness_result = self.robustness.validate(net)
            
            robustness_passed = robustness_result.passed
            all_issues.extend([f"[Robustness] {issue}" for issue in robustness_result.issues])
            all_warnings.extend([f"[Robustness] {warn}" for warn in robustness_result.warnings])
            metrics.update(robustness_result.metrics)
        else:
            logger.info("Skipping robustness validation (disabled)")
        
        # DETERMINE OVERALL STATUS
        passed = (
            geospatial_passed and
            hydraulic_passed and
            thermal_passed and
            robustness_passed
        )
        
        if passed:
            if all_warnings:
                validation_level = "PASS_WITH_WARNINGS"
            else:
                validation_level = "PASS"
        else:
            validation_level = "FAIL"
        
        # CREATE REPORT
        report = ValidationReport(
            cluster_id=cluster_id,
            timestamp=timestamp,
            passed=passed,
            validation_level=validation_level,
            geospatial_passed=geospatial_passed,
            hydraulic_passed=hydraulic_passed,
            thermal_passed=thermal_passed,
            robustness_passed=robustness_passed,
            all_issues=all_issues,
            all_warnings=all_warnings,
            metrics=metrics,
            # geospatial_result=geospatial_result,
            # hydraulic_result=hydraulic_result,
            # thermal_result=thermal_result,
            # robustness_result=robustness_result
        )
        
        logger.info(f"Validation complete: {validation_level}")
        logger.info(f"  Issues: {len(all_issues)}, Warnings: {len(all_warnings)}")
        
        return report
    
    def save_report(
        self,
        report: ValidationReport,
        output_dir: Path
    ):
        """
        Save validation report to disk.
        
        Args:
            report: Validation report
            output_dir: Directory to save report
        """
        
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Save JSON report
        json_path = output_dir / "design_validation.json"
        with open(json_path, 'w') as f:
            json.dump(report.to_dict(), f, indent=2)
        
        logger.info(f"Validation report saved: {json_path}")
        
        # Save human-readable summary
        summary_path = output_dir / "design_validation_summary.txt"
        with open(summary_path, 'w') as f:
            f.write(report.generate_summary())
        
        logger.info(f"Validation summary saved: {summary_path}")
        
        # Save detailed metrics CSV
        if report.metrics:
            # Flatten any nested dictionaries in metrics
            flat_metrics = {}
            for k, v in report.metrics.items():
                if isinstance(v, dict):
                    flat_metrics[k] = json.dumps(v)
                else:
                    flat_metrics[k] = v
                    
            metrics_df = pd.DataFrame([flat_metrics])
            metrics_path = output_dir / "design_validation_metrics.csv"
            metrics_df.to_csv(metrics_path, index=False)
            
            logger.info(f"Validation metrics saved: {metrics_path}")
