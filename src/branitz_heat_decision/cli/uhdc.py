from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional, List

from branitz_heat_decision.uhdc.orchestrator import build_uhdc_report
from branitz_heat_decision.uhdc.report_builder import save_reports


def _configure_logging_from_env() -> None:
    level = os.getenv("UHDC_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(level=getattr(logging, level, logging.INFO))


def main() -> None:
    _configure_logging_from_env()
    ap = argparse.ArgumentParser(
        description="Generate UHDC HTML/MD/JSON report from results artifacts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python -m branitz_heat_decision.cli.uhdc --cluster-id ST010_HEINRICH_ZILLE_STRASSE --out-dir results/decision/ST010/report\n"
            "  python -m branitz_heat_decision.cli.uhdc --all-clusters --out-dir results/decision_all/reports --format html\n"
        ),
    )
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--cluster-id")
    group.add_argument("--all-clusters", action="store_true", help="Generate reports for all clusters under results/cha/")
    ap.add_argument("--run-dir", default="results", type=Path, help="Base results directory")
    ap.add_argument("--out-dir", required=True, type=Path, help="Output directory for the report files")
    ap.add_argument("--llm", action="store_true", help="Use LLM explanation (if available); else template fallback")
    ap.add_argument("--style", default="executive", choices=["executive", "technical", "detailed"])
    ap.add_argument("--format", default="all", choices=["html", "md", "json", "all"], help="Which outputs to write")
    args = ap.parse_args()

    def _discover_map_specs(cluster_id: str, out_dir: Path) -> List[Dict[str, Any]]:
        """
        Discover CHA (3) + DHA (1) interactive maps for a cluster, if they exist.
        - CHA: results/cha/<cluster>/{interactive_map.html, interactive_map_temperature.html, interactive_map_pressure.html}
        - DHA: results/dha/<cluster>/hp_lv_map.html
        Returns a list of specs: {key,label,src,icon,spinner_class}
        """
        specs: List[Dict[str, Any]] = []

        cha_dir = args.run_dir / "cha" / cluster_id
        cha_maps = [
            ("cha-velocity", "CHA — Velocity", cha_dir / "interactive_map.html", "bi-wind", "text-primary"),
            ("cha-temperature", "CHA — Temperature", cha_dir / "interactive_map_temperature.html", "bi-thermometer-sun", "text-danger"),
            ("cha-pressure", "CHA — Pressure", cha_dir / "interactive_map_pressure.html", "bi-speedometer2", "text-primary"),
        ]
        for key, label, path, icon, spin in cha_maps:
            if path.exists():
                specs.append({"key": key, "label": label, "path": str(path), "icon": icon, "spinner_class": spin})

        dha_map = args.run_dir / "dha" / cluster_id / "hp_lv_map.html"
        if dha_map.exists():
            specs.append({"key": "dha-grid", "label": "DHA — LV Grid", "path": str(dha_map), "icon": "bi-lightning-charge", "spinner_class": "text-warning"})

        return specs

    def _discover_violations_csv(cluster_id: str) -> Optional[Path]:
        """Discover violations.csv in DHA results directory."""
        violations_path = args.run_dir / "dha" / cluster_id / "violations.csv"
        return violations_path if violations_path.exists() else None

    def _save(report: Dict[str, Any], out_dir: Path) -> None:
        include_html = args.format in ("html", "all")
        include_md = args.format in ("md", "all")
        include_json = args.format in ("json", "all")
        map_specs = _discover_map_specs(report["cluster_id"], out_dir=out_dir)
        violations_csv = _discover_violations_csv(report["cluster_id"])
        save_reports(
            report_data=report,
            out_dir=out_dir,
            include_html=include_html,
            include_markdown=include_md,
            include_json=include_json,
            map_specs=map_specs if map_specs else None,
            violations_csv_path=violations_csv,
        )

    if args.all_clusters:
        cha_dir = args.run_dir / "cha"
        if not cha_dir.exists():
            raise FileNotFoundError(f"No clusters found: {cha_dir} does not exist")
        cluster_ids = sorted([p.name for p in cha_dir.iterdir() if p.is_dir()])
        args.out_dir.mkdir(parents=True, exist_ok=True)
        for cid in cluster_ids:
            report = build_uhdc_report(
                cluster_id=cid,
                run_dir=args.run_dir,
                use_llm=args.llm,
                explanation_style=args.style,
            )
            _save(report, args.out_dir / cid)
    else:
        report = build_uhdc_report(
            cluster_id=args.cluster_id,
            run_dir=args.run_dir,
            use_llm=args.llm,
            explanation_style=args.style,
        )
        args.out_dir.mkdir(parents=True, exist_ok=True)
        _save(report, args.out_dir)


if __name__ == "__main__":
    main()

