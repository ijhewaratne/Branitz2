"""
Deterministic mitigation recommendation engine for DHA violations.
Maps violation patterns to structured, auditable mitigation strategies.
"""

from dataclasses import dataclass, asdict
from typing import List, Dict, Any

from .config import DHAConfig


@dataclass
class MitigationRecommendation:
    """Structured mitigation recommendation"""
    code: str  # e.g., "MIT_UNDERVOLTAGE_LONG_FEEDER"
    severity: str  # "low" | "moderate" | "high"
    category: str  # "operational" | "reinforcement" | "expansion"
    title: str
    actions: List[str]
    evidence: Dict[str, Any]
    estimated_cost_class: str  # "low" | "medium" | "high" | "very_high"


def recommend_mitigations(net, kpis: Dict[str, Any], violations_df, cfg: DHAConfig) -> Dict[str, Any]:
    """
    Generate mitigation recommendations based on violation patterns.
    
    Args:
        net: pandapower network (unused currently, for future enhancements)
        kpis: DHA KPIs dictionary
        violations_df: Violations DataFrame
        cfg: DHA configuration
    
    Returns:
        {
            "mitigation_class": "operational" | "reinforcement" | "expansion" | "none",
            "recommendations": [MitigationRecommendation, ...],
            "feasible_with_mitigation": bool,
            "summary": str
        }
    """
    
    recommendations = []
    
    # Early exit if no violations
    if kpis.get("critical_hours_count", 0) == 0:
        return {
            "mitigation_class": "none",
            "recommendations": [],
            "feasible_with_mitigation": True,
            "summary": "No violations detected - grid can host heat pumps without modifications"
        }
    
    # Analyze violation patterns
    has_voltage_vio = kpis.get("voltage_violated_hours", 0) > 0
    has_line_vio = kpis.get("line_overload_hours", 0) > 0
    has_trafo_vio = kpis.get("trafo_overload_hours", 0) > 0
    
    feeder_metrics = kpis.get("feeder_metrics", {})
    long_feeder = feeder_metrics.get("long_feeder", False)
    feeder_distance = feeder_metrics.get("distance_km")
    
    critical_hours = kpis.get("critical_hours_count", 0)
    hours_simulated = kpis.get("hours_total", 1)
    violation_fraction = critical_hours / hours_simulated if hours_simulated > 0 else 0.0
    
    # Severity assessment
    worst_vmin = kpis.get("worst_vmin_pu")
    max_trafo_loading = kpis.get("max_trafo_loading_pct")
    max_line_loading = kpis.get("max_feeder_loading_pct")
    
    severe_voltage = worst_vmin is not None and worst_vmin < cfg.voltage_severe_threshold
    severe_trafo = max_trafo_loading is not None and max_trafo_loading > cfg.loading_severe_threshold
    severe_line = max_line_loading is not None and max_line_loading > cfg.loading_severe_threshold
    
    # Rule 1: Undervoltage + Long Feeder → Infrastructure upgrade
    if has_voltage_vio and long_feeder and feeder_distance is not None:
        recommendations.append(MitigationRecommendation(
            code="MIT_UNDERVOLTAGE_LONG_FEEDER",
            severity="high" if severe_voltage else "moderate",
            category="reinforcement",
            title="Undervoltage on long feeder - infrastructure upgrade needed",
            actions=[
                f"Feeder reinforcement: upgrade cable to larger cross-section (current distance: {feeder_distance:.2f} km)",
                "Feeder splitting: divide load across multiple parallel feeders",
                "New substation: install transformer closer to load center"
            ],
            evidence={
                "worst_bus_id": kpis.get("worst_vmin_bus"),
                "worst_vmin_pu": worst_vmin,
                "feeder_distance_km": feeder_distance,
                "threshold_km": cfg.long_feeder_km_threshold,
                "severity": "severe" if severe_voltage else "moderate"
            },
            estimated_cost_class="high" if feeder_distance > 1.0 else "medium"
        ))
    
    # Rule 2: Line overload → Parallel cable or upgrade
    if has_line_vio:
        recommendations.append(MitigationRecommendation(
            code="MIT_LINE_OVERLOAD",
            severity="high" if severe_line else "moderate",
            category="reinforcement",
            title="Line overload - cable capacity insufficient",
            actions=[
                "Install parallel cable on overloaded segments",
                "Upgrade to higher-capacity cable",
                "Implement feeder meshing (connect multiple feeders)"
            ],
            evidence={
                "max_loading_line": kpis.get("max_loading_line"),
                "max_loading_pct": max_line_loading,
                "limit_pct": cfg.line_loading_limit_pct,
                "affected_hours": kpis.get("line_overload_hours")
            },
            estimated_cost_class="medium"
        ))
    
    # Rule 3: Transformer overload → Critical expansion needed
    if has_trafo_vio:
        recommendations.append(MitigationRecommendation(
            code="MIT_TRAFO_OVERLOAD",
            severity="high" if severe_trafo else "moderate",
            category="expansion",
            title="Transformer capacity exceeded",
            actions=[
                "Upgrade to higher-capacity transformer",
                "Install additional transformer in parallel",
                "Redistribute load to adjacent transformers (if available)"
            ],
            evidence={
                "max_loading_trafo": kpis.get("max_loading_trafo"),
                "max_loading_pct": max_trafo_loading,
                "limit_pct": cfg.trafo_loading_limit_pct,
                "affected_hours": kpis.get("trafo_overload_hours")
            },
            estimated_cost_class="very_high"
        ))
    
    # Rule 4: Infrequent violations → Operational control sufficient
    if violation_fraction <= cfg.operational_control_max_fraction and not (severe_voltage or severe_trafo or severe_line):
        recommendations.append(MitigationRecommendation(
            code="MIT_OPERATIONAL_CONTROL",
            severity="low",
            category="operational",
            title="Violations limited to peak hours - operational measures feasible",
            actions=[
                "Smart charging control: shift heat pump load outside peak hours",
                "Thermal storage: buffer tanks to time-shift heating demand",
                "Demand response: coordinate heat pump operation across cluster",
                "Load curtailment: temporary power reduction during extreme peaks"
            ],
            evidence={
                "critical_hours": critical_hours,
                "total_hours_simulated": hours_simulated,
                "violation_fraction": round(violation_fraction, 3),
                "threshold_fraction": cfg.operational_control_max_fraction,
                "worst_vmin_pu": worst_vmin,
                "max_loading_pct": max(max_line_loading or 0, max_trafo_loading or 0)
            },
            estimated_cost_class="low"
        ))
    
    # Determine overall classification
    categories = [r.category for r in recommendations]
    
    if "expansion" in categories:
        mitigation_class = "expansion"
        feasible_with_mitigation = not (severe_voltage or severe_trafo or violation_fraction > 0.5)
    elif "reinforcement" in categories:
        mitigation_class = "reinforcement"
        feasible_with_mitigation = True
    elif "operational" in categories:
        mitigation_class = "operational"
        feasible_with_mitigation = True
    else:
        mitigation_class = "none"
        feasible_with_mitigation = True
    
    # Generate summary
    if mitigation_class == "operational":
        summary = f"Grid hosting possible with operational controls (violations in {critical_hours}/{hours_simulated} hours)"
    elif mitigation_class == "reinforcement":
        summary = f"Grid reinforcement needed for {len([r for r in recommendations if r.category == 'reinforcement'])} components"
    elif mitigation_class == "expansion":
        summary = "Major grid expansion required - transformer and/or feeder capacity insufficient"
    else:
        summary = "No mitigations needed"
    
    return {
        "mitigation_class": mitigation_class,
        "recommendations": [asdict(r) for r in recommendations],
        "feasible_with_mitigation": feasible_with_mitigation,
        "summary": summary
    }
