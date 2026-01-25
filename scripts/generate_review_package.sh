#!/usr/bin/env bash
set -euo pipefail

# Phase 5 Review Package Generator
#
# Usage:
#   ./scripts/generate_review_package.sh ST010_HEINRICH_ZILLE_STRASSE /tmp/review_package_ST010
#
# Notes:
# - Expects results artifacts under ./results/ for the given cluster.
# - Uses the current Python environment; recommended: conda activate branitz_env

CLUSTER_ID="${1:-ST010_HEINRICH_ZILLE_STRASSE}"
RUN_DIR="${RUN_DIR:-results}"

# Default to project-local results folder (requested): results/review_packages/<cluster_id>/
DEFAULT_OUT_DIR="${RUN_DIR}/review_packages/${CLUSTER_ID}"
OUT_DIR="${2:-$DEFAULT_OUT_DIR}"

echo "🎯 Generating Phase 5 Review Package for ${CLUSTER_ID}"
echo "📁 Output directory: ${OUT_DIR}"
mkdir -p "${OUT_DIR}"

# 1) Executive dashboard (HTML) - generated via UHDC CLI
PYTHONPATH=src python -m branitz_heat_decision.cli.uhdc \
  --cluster-id "${CLUSTER_ID}" \
  --run-dir "${RUN_DIR}" \
  --out-dir "${OUT_DIR}" \
  --style executive \
  --format html

if [[ -f "${OUT_DIR}/uhdc_report_${CLUSTER_ID}.html" ]]; then
  mv "${OUT_DIR}/uhdc_report_${CLUSTER_ID}.html" "${OUT_DIR}/01_Executive_Dashboard.html"
fi

# 2) Executive summary (Markdown) - generated via decision CLI
PYTHONPATH=src python -m branitz_heat_decision.cli.decision \
  --cluster-id "${CLUSTER_ID}" \
  --cha-kpis "${RUN_DIR}/cha/${CLUSTER_ID}/cha_kpis.json" \
  --dha-kpis "${RUN_DIR}/dha/${CLUSTER_ID}/dha_kpis.json" \
  --econ-summary "${RUN_DIR}/economics/${CLUSTER_ID}/monte_carlo_summary.json" \
  --out-dir "${OUT_DIR}" \
  --format md

if [[ -f "${OUT_DIR}/explanation_${CLUSTER_ID}.md" ]]; then
  mv "${OUT_DIR}/explanation_${CLUSTER_ID}.md" "${OUT_DIR}/02_Executive_Summary.md"
fi

# 3) Contract + decision JSON (technical review)
if [[ -f "${RUN_DIR}/decision/${CLUSTER_ID}/kpi_contract_${CLUSTER_ID}.json" ]]; then
  cp "${RUN_DIR}/decision/${CLUSTER_ID}/kpi_contract_${CLUSTER_ID}.json" "${OUT_DIR}/03_Technical_Contract.json"
fi
if [[ -f "${RUN_DIR}/decision/${CLUSTER_ID}/decision_${CLUSTER_ID}.json" ]]; then
  cp "${RUN_DIR}/decision/${CLUSTER_ID}/decision_${CLUSTER_ID}.json" "${OUT_DIR}/04_Decision_Logic.json"
fi

# 4) Review guide (instructions)
cat > "${OUT_DIR}/REVIEW_GUIDE.md" << 'EOF'
# Phase 5 Review Guide

## What is this package?
This package contains automated decision artifacts for a single cluster (street) to support validation by planners, engineers, and analysts.

## Contents
- **01_Executive_Dashboard.html**: Interactive dashboard (maps, charts, tables)
- **02_Executive_Summary.md**: Plain-language decision summary
- **03_Technical_Contract.json**: Full KPI contract (schema-driven, auditable)
- **04_Decision_Logic.json**: Decision output (choice, reasons, metrics used)
- **feedback_template.csv / feedback_template.xlsx**: Structured feedback form

## Reviewer tracks

### Municipal planners (15 min)
Focus: `01_Executive_Dashboard.html`
- Is the recommendation clear without scrolling?
- Does “Robust/Sensitive” make sense?
- Can you hover numbers and see helpful source tooltips?
- Do the “Reason Codes” tell a coherent story?

### Engineers (30 min)
Focus: `03_Technical_Contract.json`, `04_Decision_Logic.json`
- DH feasibility checks: velocity / Δp / convergence plausibility
- HP grid checks: undervoltage & overload counts, worst-hour indicators
- Economics: check LCOH and CO₂ medians and uncertainty bands
- Monte Carlo: does the win fraction align with your expectation?

### Data scientists (20 min)
Focus: `03_Technical_Contract.json`
- Schema completeness & null-handling
- Provenance: `metadata.inputs` and timestamps
- Uncertainty propagation: `p05/p95` sanity
- Reproducibility: `metadata.git_commit` sufficient?

## Feedback collection
Fill `feedback_template.csv` (or `.xlsx` if generated) and send it back with:
- Key concerns
- Recommended improvements
- Any missing constraints / KPIs
EOF

# 5) Feedback templates (CSV always; XLSX best-effort)
cat > "${OUT_DIR}/feedback_template.csv" << 'EOF'
Reviewer,Role,File_Reviewed,Clarity_Rating,Accuracy_Rating,Traceability_Rating,Key_Concerns,Recommendations
,,,,,,,
EOF

PYTHONPATH=src python scripts/review_package_create_xlsx.py "${OUT_DIR}" || true

echo "✅ Package generated at: ${OUT_DIR}"
echo ""
echo "📂 Contents:"
ls -lh "${OUT_DIR}"

