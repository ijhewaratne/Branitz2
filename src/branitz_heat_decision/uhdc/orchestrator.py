"""
UHDC Orchestrator
- Discovers artifacts in nested results structures
- Handles missing files gracefully
- Returns complete report payload
"""

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Dict, Any, Optional

from .io import load_kpi_contract, load_cha_kpis, load_dha_kpis, load_econ_summary
from .explainer import explain_with_llm, _fallback_template_explanation
from .report_builder import save_reports
from ..decision.kpi_contract import build_kpi_contract
from ..decision.rules import decide_from_contract
from ..config_paths import SEARCH_PATTERNS

logger = logging.getLogger(__name__)

# Optional logging control from environment (used by orchestrator CLI).
def _configure_logging_from_env() -> None:
    level = os.getenv("UHDC_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(level=getattr(logging, level, logging.INFO))

# Cache for discovery results to avoid repeated filesystem checks.
# Key: (resolved_base_dir, cluster_id)
_discovered_paths_cache: Dict[tuple[str, str], Dict[str, Optional[Path]]] = {}


def clear_discovery_cache() -> None:
    """Clear the in-memory artifact discovery cache (useful for tests)."""
    _discovered_paths_cache.clear()


def discover_artifact_paths(
    cluster_id: str,
    base_dir: Path,
) -> Dict[str, Optional[Path]]:
    """
    Discover all artifact paths using intelligent search.
    
    Searches multiple patterns in order, returns first match.
    
    Args:
        cluster_id: Cluster identifier
        base_dir: Base results directory
    
    Returns:
        Dict mapping artifact type to discovered Path or None
    """
    
    cache_key = (str(base_dir.resolve()), str(cluster_id))
    if cache_key in _discovered_paths_cache:
        logger.debug(f"[PathDiscovery] cache hit for cluster={cluster_id} base_dir={base_dir}")
        return _discovered_paths_cache[cache_key]

    discovered: Dict[str, Optional[Path]] = {}
    
    for artifact_type, patterns in SEARCH_PATTERNS.items():
        found = None
        attempted_paths: list[str] = []

        logger.info(f"[PathDiscovery] Searching for {artifact_type} (cluster: {cluster_id})")
        
        for idx, pattern in enumerate(patterns, 1):
            path = base_dir / pattern.format(cluster_id=cluster_id)
            attempted_paths.append(str(path))

            # Log attempt regardless of existence
            logger.debug(f"[PathDiscovery] [{idx}/{len(patterns)}] Trying: {path}")
            
            if path.exists():
                found = path
                logger.info(f"[PathDiscovery] ✓ Found {artifact_type}: {path} (pattern {idx})")
                if idx < len(patterns):
                    logger.debug(f"[PathDiscovery] Skipping remaining {len(patterns) - idx} patterns")
                break
        
        if found is None:
            logger.error(
                f"[PathDiscovery] ✗ Not found: {artifact_type}. Attempted paths:\n"
                + "\n".join(f"  - {p}" for p in attempted_paths)
            )
        
        discovered[artifact_type] = found
    
    _discovered_paths_cache[cache_key] = discovered
    return discovered

def build_uhdc_report(
    cluster_id: str,
    run_dir: Path,
    kpi_contract_path: Optional[Path] = None,
    use_llm: bool = False,
    explanation_style: str = "executive",
) -> Dict[str, Any]:
    """
    Build complete UHDC report from artifacts.
    
    Args:
        cluster_id: Target cluster
        run_dir: Directory containing results (e.g., Path('results'))
        kpi_contract_path: Optional explicit path to contract (fast path)
        use_llm: Generate LLM explanation (requires API key)
        explanation_style: Style for LLM explanation
    
    Returns:
        Complete report dictionary:
        {
            'cluster_id': str,
            'contract': KPIContract,
            'decision': DecisionResult,
            'explanation': str,
            'sources': Dict[str, Path],
            'metadata': {timestamp, version},
        }
    
    Raises:
        FileNotFoundError: If run directory does not exist
        ValueError: If required artifacts are missing
    """
    
    logger.info(f"Building UHDC report for {cluster_id}")
    
    # Step 1: Try to load KPI contract directly (fast path)
    if kpi_contract_path and kpi_contract_path.exists():
        logger.info("Loading provided KPI contract")
        contract = load_kpi_contract(kpi_contract_path)
        sources: Dict[str, Optional[Path]] = {'kpi_contract': kpi_contract_path}
    
    else:
        # Step 2: Discover individual artifacts and build contract
        logger.info("Discovering artifacts")
        sources = discover_artifact_paths(cluster_id, run_dir)
        
        if not any(sources.values()):
            raise FileNotFoundError(
                f"No artifacts found for {cluster_id} in {run_dir}. "
                f"Have you run CHA/DHA/Economics pipelines?"
            )
        
        # Load individual components
        cha_kpis = None
        if sources['cha_kpis']:
            cha_kpis = load_cha_kpis(sources['cha_kpis'])
        
        dha_kpis = None
        if sources['dha_kpis']:
            dha_kpis = load_dha_kpis(sources['dha_kpis'])
        
        econ_summary = None
        if sources['econ_summary']:
            econ_summary = load_econ_summary(sources['econ_summary'])
        
        # Build metadata
        metadata = {
            'created_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'sources': {k: str(v) if v else None for k, v in sources.items()},
            'notes': [],
        }
        
        # Build contract
        logger.info("Composing KPI contract from artifacts")
        contract = build_kpi_contract(
            cluster_id=cluster_id,
            cha_kpis=cha_kpis or {},
            dha_kpis=dha_kpis or {},
            econ_summary=econ_summary or {},
            metadata=metadata,
        )
    
    # Step 3: Make decision
    logger.info("Applying decision rules")
    decision_result = decide_from_contract(contract)
    
    # Step 4: Generate explanation
    explanation = None
    if use_llm:
        logger.info("Generating LLM explanation")
        try:
            explanation = explain_with_llm(
                contract,
                decision_result.to_dict(),
                style=explanation_style,
            )
        except Exception as e:
            logger.error(f"LLM explanation failed: {e}")
            explanation = _fallback_template_explanation(
                contract,
                decision_result.to_dict(),
                explanation_style,
            )
    else:
        # Use template explanation
        explanation = _fallback_template_explanation(
            contract,
            decision_result.to_dict(),
            explanation_style,
        )
    
    # Step 4.5: Validate explanation using TNLI Logic Auditor
    validation_report = None
    try:
        from ..validation import LogicAuditor
        
        logger.info("Validating explanation with TNLI Logic Auditor")
        auditor = LogicAuditor()
        
        # Build decision data for validation
        decision_data = {
            "choice": decision_result.choice,
            "reason_codes": decision_result.reason_codes,
            "kpis": decision_result.metrics_used,
            "cluster_id": cluster_id,
            "robust": decision_result.robust,
            "explanation": explanation,
        }
        
        validation_report = auditor.validate_decision_explanation(decision_data)
        
        logger.info(
            f"Validation complete: {validation_report.validation_status} "
            f"({validation_report.verified_count}/{validation_report.statements_validated} verified)"
        )
        
        if validation_report.has_contradictions:
            logger.warning(f"{len(validation_report.contradictions)} contradictions detected")
            
    except ImportError:
        logger.debug("TNLI validation skipped (validation module not available)")
    except Exception as e:
        logger.warning(f"Validation failed: {e}")
    
    # Step 5: Compile report
    report = {
        'cluster_id': cluster_id,
        'contract': contract,
        'decision': decision_result.to_dict(),
        'explanation': explanation,
        'sources': {k: str(v) if v else None for k, v in sources.items()},
        'metadata': {
            'uhdc_version': '1.0',
            'generated_by': 'uhdc.orchestrator',
            'timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ'),
        },
    }
    
    # Add validation to report if available
    if validation_report:
        report['validation'] = validation_report.to_dict()
        report['decision']['validation_status'] = validation_report.validation_status
    
    logger.info("UHDC report complete")

    return report

# CLI wrapper
def main() -> None:
    """Entry point for UHDC orchestrator."""
    _configure_logging_from_env()
    
    import argparse
    
    parser = argparse.ArgumentParser(description="Generate UHDC report")
    parser.add_argument('--cluster-id', required=True)
    parser.add_argument('--run-dir', default='results', type=Path)
    parser.add_argument('--out-dir', required=True, type=Path)
    parser.add_argument('--llm', action='store_true')
    parser.add_argument('--style', default='executive', choices=['executive', 'technical', 'detailed'])
    parser.add_argument('--contract-path', type=Path, help='Use specific contract file')
    parser.add_argument('--html', action='store_true', help='Write HTML report')
    parser.add_argument('--md', action='store_true', help='Write Markdown report')
    
    args = parser.parse_args()
    
    if not args.run_dir.exists():
        print(f"Error: run directory does not exist: {args.run_dir}", file=sys.stderr)
        sys.exit(1)
    
    try:
        report = build_uhdc_report(
            cluster_id=args.cluster_id,
            run_dir=args.run_dir,
            kpi_contract_path=args.contract_path,
            use_llm=args.llm,
            explanation_style=args.style,
        )
    except Exception as e:
        print(f"Error building report: {e}", file=sys.stderr)
        sys.exit(1)
    
    # Save report
    args.out_dir.mkdir(parents=True, exist_ok=True)
    
    # Always save canonical JSON (payload)
    json_path = args.out_dir / f"uhdc_report_{args.cluster_id}.json"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"✓ Saved JSON report: {json_path}")

    # Save reports (HTML/MD) if requested; default to HTML+MD if neither flag is provided.
    include_html = bool(args.html or (not args.html and not args.md))
    include_md = bool(args.md or (not args.html and not args.md))

    # Discover available interactive maps (CHA: velocity/temp/pressure; DHA: hp_lv_map).
    # Use paths relative to out_dir so the HTML can be opened from disk anywhere.
    map_specs: list[Dict[str, Any]] = []

    cha_dir = args.run_dir / "cha" / args.cluster_id
    cha_candidates = [
        ("cha-velocity", "CHA — Velocity", cha_dir / "interactive_map.html", "bi-wind", "text-primary"),
        ("cha-temperature", "CHA — Temperature", cha_dir / "interactive_map_temperature.html", "bi-thermometer-sun", "text-danger"),
        ("cha-pressure", "CHA — Pressure", cha_dir / "interactive_map_pressure.html", "bi-speedometer2", "text-primary"),
    ]
    for key, label, p, icon, spin in cha_candidates:
        if p.exists():
            map_specs.append({"key": key, "label": label, "path": str(p), "icon": icon, "spinner_class": spin})

    dha_map = args.run_dir / "dha" / args.cluster_id / "hp_lv_map.html"
    if dha_map.exists():
        map_specs.append({"key": "dha-grid", "label": "DHA — LV Grid", "path": str(dha_map), "icon": "bi-lightning-charge", "spinner_class": "text-warning"})

    save_reports(
        report_data=report,
        out_dir=args.out_dir,
        include_html=include_html,
        include_markdown=include_md,
        include_json=False,  # already saved above
        map_specs=map_specs if map_specs else None,
    )
    
    print("UHDC orchestrator complete!")

if __name__ == '__main__':
    main()