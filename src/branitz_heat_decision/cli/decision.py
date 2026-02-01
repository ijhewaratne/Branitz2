#!/usr/bin/env python3
"""
Decision Pipeline CLI (single-cluster or batch)

Outputs (per cluster):
- `kpi_contract_<cluster_id>.json`
- `decision_<cluster_id>.json`
- `explanation_<cluster_id>.md` (optional)
- `explanation_<cluster_id>.html` (optional)

Examples:
  # Single cluster, auto-discover inputs from results/
  PYTHONPATH=src python -m branitz_heat_decision.cli.decision --cluster-id ST010_HEINRICH_ZILLE_STRASSE

  # Single cluster with explicit inputs and HTML report
  PYTHONPATH=src python -m branitz_heat_decision.cli.decision \
    --cluster-id ST010_HEINRICH_ZILLE_STRASSE \
    --cha-kpis results/cha/ST010_HEINRICH_ZILLE_STRASSE/cha_kpis.json \
    --dha-kpis results/dha/ST010_HEINRICH_ZILLE_STRASSE/dha_kpis.json \
    --econ-summary results/economics/ST010_HEINRICH_ZILLE_STRASSE/monte_carlo_summary.json \
    --format html

  # LLM explanation (fail hard if LLM unavailable or unsafe)
  PYTHONPATH=src python -m branitz_heat_decision.cli.decision \
    --cluster-id ST010_HEINRICH_ZILLE_STRASSE --llm-explanation --no-fallback

  # Batch mode for all clusters under results/cha/
  PYTHONPATH=src python -m branitz_heat_decision.cli.decision --all-clusters --output-dir results/decision_all
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Tuple, List, cast

from branitz_heat_decision.decision.kpi_contract import build_kpi_contract
from branitz_heat_decision.decision.schemas import ContractValidator
from branitz_heat_decision.decision.rules import decide_from_contract, validate_config
from branitz_heat_decision.uhdc.explainer import (
    explain_with_llm,
    _fallback_template_explanation,
    GOOGLE_MODEL_DEFAULT,
    GOOGLE_API_KEY,
    LLM_AVAILABLE,
    LLM_READY,
    UHDC_FORCE_TEMPLATE,
)
from branitz_heat_decision.uhdc.report_builder import render_html_report, render_markdown_report


def _configure_logging_from_env() -> None:
    level = os.getenv("UHDC_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(level=getattr(logging, level, logging.INFO))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate KPI contract, decision, and explanation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python -m branitz_heat_decision.cli.decision --cluster-id ST010_HEINRICH_ZILLE_STRASSE\n"
            "  python -m branitz_heat_decision.cli.decision --cluster-id ST010_HEINRICH_ZILLE_STRASSE --llm-explanation\n"
            "  python -m branitz_heat_decision.cli.decision --all-clusters --format json\n"
        ),
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--cluster-id", help="Single cluster identifier (e.g., ST010_HEINRICH_ZILLE_STRASSE)")
    group.add_argument("--all-clusters", action="store_true", help="Process every cluster under results/cha/")

    # Backward-compatible path args (aliases)
    parser.add_argument("--cha-kpis", dest="cha_kpis", help="Path to CHA KPIs JSON (alias: --cha-kpis-path)")
    parser.add_argument("--dha-kpis", dest="dha_kpis", help="Path to DHA KPIs JSON (alias: --dha-kpis-path)")
    parser.add_argument("--econ-summary", dest="econ_summary", help="Path to economics summary JSON (alias: --econ-summary-path)")
    parser.add_argument("--out-dir", dest="out_dir", help="Output directory (alias: --output-dir)")

    # New preferred arg names
    parser.add_argument("--cha-kpis-path", dest="cha_kpis", help="Path to CHA KPIs JSON")
    parser.add_argument("--dha-kpis-path", dest="dha_kpis", help="Path to DHA KPIs JSON")
    parser.add_argument("--econ-summary-path", dest="econ_summary", help="Path to economics summary JSON")
    parser.add_argument("--output-dir", dest="out_dir", help="Output directory")

    parser.add_argument("--llm-explanation", action="store_true", help="[Deprecated] LLM is always used for executive summary")
    parser.add_argument("--template-only", action="store_true", help="Skip LLM and use template for explanation (overrides default)")
    parser.add_argument(
        "--explanation-style",
        default="executive",
        choices=["executive", "technical", "detailed"],
        help="Explanation style",
    )
    parser.add_argument("--config", help="Custom decision config JSON file")
    parser.add_argument("--no-fallback", action="store_true", help="Fail if LLM unavailable / API fails / safety fails")
    parser.add_argument(
        "--format",
        default="all",
        choices=["json", "md", "html", "all"],
        help="Output format(s) to generate (JSON is always written for contract + decision)",
    )
    
    return parser.parse_args()


def load_json(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return cast(Dict[str, Any], json.load(f))
    except Exception as e:
        print(f"Error loading {path}: {e}", file=sys.stderr)
        raise


def save_json(data: Dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"✓ Saved: {path}")

def _discover_paths_for_cluster(cluster_id: str) -> Tuple[Path, Path, Path]:
    base = Path("results")
    cha = base / "cha" / cluster_id / "cha_kpis.json"
    dha = base / "dha" / cluster_id / "dha_kpis.json"
    # Try economics_monte_carlo.json first (current format), fallback to monte_carlo_summary.json (legacy)
    econ_dir = base / "economics" / cluster_id
    econ = econ_dir / "economics_monte_carlo.json"
    if not econ.exists():
        econ = econ_dir / "monte_carlo_summary.json"  # Legacy fallback
    return cha, dha, econ

def _list_clusters() -> List[str]:
    base = Path("results") / "cha"
    if not base.exists():
        return []
    return sorted([p.name for p in base.iterdir() if p.is_dir()])

def _write_explanation_outputs(
    out_dir: Path,
    cluster_id: str,
    contract: Dict[str, Any],
    decision: Dict[str, Any],
    explanation: str,
    fmt: str,
) -> None:
    if fmt not in ("md", "html", "all"):
        return

    report_data = {
        "cluster_id": cluster_id,
        "contract": contract,
        "decision": decision,
        "explanation": explanation,
        "sources": {},
        "metadata": {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ")},
    }

    if fmt in ("md", "all"):
        md = render_markdown_report(report_data)
        p = out_dir / f"explanation_{cluster_id}.md"
        p.write_text(md, encoding="utf-8")
        print(f"✓ Saved: {p}")

    if fmt in ("html", "all"):
        html = render_html_report(report_data, map_path=None)
        p = out_dir / f"explanation_{cluster_id}.html"
        p.write_text(html, encoding="utf-8")
        print(f"✓ Saved: {p}")

def main() -> None:
    _configure_logging_from_env()
    args = parse_args()
    
    config = None
    if args.config:
        config = load_json(args.config)
        print(f"Loaded custom decision config: {args.config}")
        config = validate_config(config)

    # LLM status (always use LLM for executive summary unless --template-only)
    if args.format in ("md", "html", "all") and not args.template_only:
        if UHDC_FORCE_TEMPLATE:
            print("ℹ️  LLM disabled: UHDC_FORCE_TEMPLATE=true (template mode forced).")
        elif not LLM_AVAILABLE:
            print("⚠️  Warning: google-genai SDK not installed; LLM explanations will use fallback template.")
            print("   Install: pip install google-genai")
        elif GOOGLE_API_KEY is None:
            print("⚠️  Warning: GOOGLE_API_KEY not found in environment or .env.")
            print("   LLM explanations will use fallback template. Create .env: echo 'GOOGLE_API_KEY=your_key' > .env")
        else:
            print(f"✅ LLM enabled for executive summary: {GOOGLE_MODEL_DEFAULT}")

        if args.no_fallback and not LLM_READY:
            print("❌ Error: --no-fallback specified but LLM is unavailable/disabled.", file=sys.stderr)
            sys.exit(1)

    if args.all_clusters:
        clusters = _list_clusters()
        if not clusters:
            raise FileNotFoundError("No clusters found under results/cha/. Run CHA first.")
        base_out = Path(args.out_dir) if args.out_dir else Path("results") / "decision_all"
        base_out.mkdir(parents=True, exist_ok=True)
        print(f"Found {len(clusters)} clusters under results/cha/. Writing to: {base_out}")

        summary_rows = []
        for cid in clusters:
            try:
                out_dir = base_out / cid
                out_dir.mkdir(parents=True, exist_ok=True)

                cha_path, dha_path, econ_path = _discover_paths_for_cluster(cid)
                if args.cha_kpis:
                    cha_path = Path(args.cha_kpis)
                if args.dha_kpis:
                    dha_path = Path(args.dha_kpis)
                if args.econ_summary:
                    econ_path = Path(args.econ_summary)

                if not (cha_path.exists() and dha_path.exists() and econ_path.exists()):
                    print(f"! Skipping {cid}: missing prerequisites")
                    continue

                cha_kpis = load_json(str(cha_path))
                dha_kpis = load_json(str(dha_path))
                econ_summary = load_json(str(econ_path))

                metadata = {
                    "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "inputs": {
                        "cha_kpis_path": str(cha_path.resolve()),
                        "dha_kpis_path": str(dha_path.resolve()),
                        "econ_summary_path": str(econ_path.resolve()),
                        "decision_config": config or "defaults",
                    },
                    "notes": [],
                }

                contract = build_kpi_contract(cid, cha_kpis, dha_kpis, econ_summary, metadata)
                ContractValidator.validate(contract)

                decision_result = decide_from_contract(contract, config)
                contract_path = out_dir / f"kpi_contract_{cid}.json"
                decision_path = out_dir / f"decision_{cid}.json"
                save_json(contract, contract_path)
                save_json(decision_result.to_dict(), decision_path)

                # Explanation only if requested format requires it (always use LLM unless --template-only)
                explanation = None
                if args.format in ("md", "html", "all"):
                    if args.template_only:
                        explanation = _fallback_template_explanation(contract, decision_result.to_dict(), args.explanation_style)
                    else:
                        try:
                            explanation = explain_with_llm(
                                contract,
                                decision_result.to_dict(),
                                style=args.explanation_style,
                                no_fallback=args.no_fallback,
                            )
                        except Exception as e:
                            if args.no_fallback:
                                raise
                            explanation = _fallback_template_explanation(contract, decision_result.to_dict(), args.explanation_style)
                            print(f"! {cid}: LLM explanation failed, used template fallback ({e})")

                    _write_explanation_outputs(out_dir, cid, contract, decision_result.to_dict(), explanation, args.format)

                summary_rows.append(
                    {
                        "cluster_id": cid,
                        "choice": decision_result.choice,
                        "robust": decision_result.robust,
                        "lcoh_dh": decision_result.metrics_used.get("lcoh_dh_median"),
                        "lcoh_hp": decision_result.metrics_used.get("lcoh_hp_median"),
                    }
                )
            except Exception as e:
                print(f"✗ Failed on {cid}: {e}", file=sys.stderr)
                if args.no_fallback:
                    raise

        # Write summary CSV (no pandas dependency)
        try:
            import csv

            summary_path = base_out / "summary.csv"
            with open(summary_path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=["cluster_id", "choice", "robust", "lcoh_dh", "lcoh_hp"])
                w.writeheader()
                for row in summary_rows:
                    w.writerow(row)
            print(f"✓ Saved: {summary_path}")
        except Exception as e:
            print(f"! Failed to write summary.csv: {e}", file=sys.stderr)

        return

    # Single cluster mode
    cluster_id = args.cluster_id
    if not cluster_id:
        raise ValueError("cluster_id is required in single-cluster mode")

    if args.cha_kpis and args.dha_kpis and args.econ_summary:
        cha_path = Path(args.cha_kpis)
        dha_path = Path(args.dha_kpis)
        econ_path = Path(args.econ_summary)
    else:
        cha_path, dha_path, econ_path = _discover_paths_for_cluster(cluster_id)

    if not (cha_path.exists() and dha_path.exists() and econ_path.exists()):
        raise FileNotFoundError(
            f"Missing prerequisite artifacts for {cluster_id}. "
            f"Expected: {cha_path}, {dha_path}, {econ_path}"
        )

    out_dir = Path(args.out_dir) if args.out_dir else (Path("results") / "decision" / cluster_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading CHA KPIs: {cha_path}")
    cha_kpis = load_json(str(cha_path))

    print(f"Loading DHA KPIs: {dha_path}")
    dha_kpis = load_json(str(dha_path))

    print(f"Loading economics summary: {econ_path}")
    econ_summary = load_json(str(econ_path))

    metadata = {
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "inputs": {
            "cha_kpis_path": str(cha_path.resolve()),
            "dha_kpis_path": str(dha_path.resolve()),
            "econ_summary_path": str(econ_path.resolve()),
            "decision_config": config or "defaults",
        },
        "notes": [],
    }

    print("\nBuilding KPI contract...")
    contract = build_kpi_contract(cluster_id, cha_kpis, dha_kpis, econ_summary, metadata)
    print("✓ KPI contract built successfully")
    
    print("Validating contract schema...")
    ContractValidator.validate(contract)
    print("✓ Contract schema validation passed")
    
    save_json(contract, out_dir / f"kpi_contract_{cluster_id}.json")
    
    print("\nApplying decision rules...")
    decision_result = decide_from_contract(contract, config)
    save_json(decision_result.to_dict(), out_dir / f"decision_{cluster_id}.json")
    print(f"✓ Decision: {decision_result.choice} (robust: {decision_result.robust})")
    print(f"  Reasons: {', '.join(decision_result.reason_codes)}")
    
    # Explanation only if requested format requires it (always use LLM unless --template-only)
    if args.format in ("md", "html", "all"):
        print("\nGenerating explanation...")
        if args.template_only:
            explanation = _fallback_template_explanation(contract, decision_result.to_dict(), args.explanation_style)
            print("ℹ️  Using template (--template-only)")
        else:
            try:
                explanation = explain_with_llm(
                    contract,
                    decision_result.to_dict(),
                    style=args.explanation_style,
                    no_fallback=args.no_fallback,
                )
            except Exception as e:
                if args.no_fallback:
                    raise
                explanation = _fallback_template_explanation(contract, decision_result.to_dict(), args.explanation_style)
                print(f"! LLM explanation failed, used template fallback ({e})")

        # NEW: Validate explanation using TNLI Logic Auditor
        try:
            from branitz_heat_decision.validation import LogicAuditor
            
            print("\nValidating explanation with TNLI Logic Auditor...")
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
            
            # Log results
            print(f"✓ Validation Status: {validation_report.validation_status}")
            print(f"  Verified: {validation_report.verified_count}/{validation_report.statements_validated}")
            
            if validation_report.has_contradictions:
                print(f"  ⚠️  {len(validation_report.contradictions)} contradictions detected:")
                for contra in validation_report.contradictions:
                    print(f"     - {contra.statement[:80]}...")
            
            # Save validation report
            validation_path = out_dir / f"validation_{cluster_id}.json"
            save_json(validation_report.to_dict(), validation_path)
            
            # Add full validation report to decision output (includes sentence_results)
            decision_with_validation = decision_result.to_dict()
            decision_with_validation["validation"] = validation_report.to_dict()
            save_json(decision_with_validation, out_dir / f"decision_{cluster_id}.json")
            
        except ImportError:
            print("ℹ️  TNLI validation skipped (validation module not available)")
        except Exception as e:
            print(f"⚠️  Validation failed: {e}")

        _write_explanation_outputs(out_dir, cluster_id, contract, decision_result.to_dict(), explanation, args.format)
    
    print("\nDecision pipeline complete!")

    print(f"Outputs saved to: {out_dir}")


if __name__ == "__main__":
    main()