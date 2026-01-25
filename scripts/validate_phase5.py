#!/usr/bin/env python3
"""
Phase 5 validation script.

This script runs:
- Reason code count check
- Key unit tests (decision + UHDC)
- Integration tests (if artifacts exist)
- Determinism check (decision only; no LLM)
- CLI help flag checks

Usage:
  conda activate branitz_env
  PYTHONPATH=src python scripts/validate_phase5.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def run_cmd(name: str, cmd: list[str]) -> None:
    print("\n" + "=" * 70)
    print(f"Running: {name}")
    print("=" * 70)
    r = subprocess.run(cmd)
    if r.returncode != 0:
        print(f"❌ FAILED: {name}")
        sys.exit(r.returncode)
    print(f"✅ PASSED: {name}")


def pick_cluster_id() -> str:
    cid = os.environ.get("BRANITZ_INTEGRATION_CLUSTER_ID")
    if cid:
        return cid
    # prefer ST001 if present, else ST010
    for candidate in ("ST001_HEINRICH_ZILLE_STRASSE", "ST010_HEINRICH_ZILLE_STRASSE"):
        if (Path("results") / "cha" / candidate / "cha_kpis.json").exists():
            return candidate
    return "ST001_HEINRICH_ZILLE_STRASSE"


def main() -> None:
    # 1) Reason codes count
    print("\nChecking reason codes count...")
    from branitz_heat_decision.decision.schemas import REASON_CODES  # type: ignore

    n = len(REASON_CODES)
    if n < 30:
        print(f"❌ Only {n} reason codes, need >=30")
        sys.exit(1)
    print(f"✅ {n} reason codes")

    # 2) Unit tests (config validation)
    run_cmd(
        "Config Validation Tests",
        ["pytest", "-q", "tests/decision/test_config_validation.py"],
    )

    # 3) Fallback tests
    run_cmd(
        "Fallback Tests (LLM failure/hallucination → fallback)",
        ["pytest", "-q", "tests/uhdc/test_explainer_fallback.py"],
    )

    # 4) All Phase 5 unit tests (decision + UHDC)
    run_cmd(
        "All Phase 5 Unit Tests (decision + UHDC)",
        ["pytest", "-q", "tests/decision", "tests/uhdc"],
    )

    # 5) Integration tests (auto-skip if artifacts missing)
    run_cmd(
        "Integration Tests (-m integration)",
        ["pytest", "-q", "-m", "integration", "tests/integration"],
    )

    # 6) Determinism check (no LLM)
    print("\nChecking determinism (decision only, no LLM)...")
    cluster_id = pick_cluster_id()
    required = [
        Path("results") / "cha" / cluster_id / "cha_kpis.json",
        Path("results") / "dha" / cluster_id / "dha_kpis.json",
        Path("results") / "economics" / cluster_id / "monte_carlo_summary.json",
    ]
    missing = [p for p in required if not p.exists()]
    if missing:
        print("⚠️ Skipping determinism check (missing prerequisites):")
        for p in missing:
            print(f"  - {p}")
    else:
        out_dir = Path("results") / "decision_validation" / cluster_id
        out_dir.mkdir(parents=True, exist_ok=True)
        prev = None
        for i in range(3):
            cmd = [
                "python",
                "-m",
                "branitz_heat_decision.cli.decision",
                "--cluster-id",
                cluster_id,
                "--cha-kpis",
                str(required[0]),
                "--dha-kpis",
                str(required[1]),
                "--econ-summary",
                str(required[2]),
                "--out-dir",
                str(out_dir),
                "--format",
                "json",
            ]
            r = subprocess.run(cmd, env={**os.environ, "PYTHONPATH": "src"}, check=True)
            _ = r

            decision_path = out_dir / f"decision_{cluster_id}.json"
            d = json.loads(decision_path.read_text(encoding="utf-8"))
            print(f"Run {i+1}: choice={d['choice']}, robust={d['robust']}")
            if prev is not None:
                if d["choice"] != prev["choice"] or d["robust"] != prev["robust"] or d["reason_codes"] != prev["reason_codes"]:
                    print("❌ Decision not deterministic!")
                    sys.exit(1)
            prev = d
        print("✅ Determinism verified")

    # 7) CLI help flag checks
    print("\nChecking CLI help flags...")
    r = subprocess.run(
        ["python", "-m", "branitz_heat_decision.cli.decision", "--help"],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": "src"},
    )
    if r.returncode != 0:
        print("❌ Decision CLI --help failed")
        sys.exit(1)
    help_text = r.stdout
    for flag in ("--no-fallback", "--all-clusters", "--format"):
        if flag not in help_text:
            print(f"❌ Decision CLI missing required flag in --help output: {flag}")
            sys.exit(1)
    print("✅ CLI flags complete")

    print("\n" + "=" * 70)
    print("🎉 PHASE 5 VALIDATION COMPLETE - READY FOR PHASE 6")
    print("=" * 70)


if __name__ == "__main__":
    main()

