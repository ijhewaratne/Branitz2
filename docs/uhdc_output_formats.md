# UHDC Output Formats

This document describes the output artifacts produced by the Phase 5 Decision + UHDC reporting pipeline.

## Output files (per cluster)

When running `python -m branitz_heat_decision.cli.decision --cluster-id <CLUSTER> --format all`, outputs are written to:

- `results/decision/<CLUSTER>/kpi_contract_<CLUSTER>.json`
- `results/decision/<CLUSTER>/decision_<CLUSTER>.json`
- `results/decision/<CLUSTER>/explanation_<CLUSTER>.md` (template or LLM)
- `results/decision/<CLUSTER>/explanation_<CLUSTER>.html` (template or LLM)
- `results/decision/<CLUSTER>/report/uhdc_report_<CLUSTER>.json`
- `results/decision/<CLUSTER>/report/uhdc_report_<CLUSTER>.html`
- `results/decision/<CLUSTER>/report/uhdc_explanation_<CLUSTER>.md`

---

## KPI Contract Schema v1.0 (`kpi_contract_*.json`)

This is the canonical, validated KPI structure used by the decision engine and UHDC report rendering.

### Downloadable example
- `examples/kpi_contract_example.json`

```json
{
  "version": "1.0",
  "cluster_id": "ST010_HEINRICH_ZILLE_STRASSE",
  "metadata": {
    "created_utc": "2026-01-14T05:43:07Z",
    "git_commit": "80f3b9610a891b654bf6e11c2b09d14c6900761f",
    "inputs": {
      "cha_kpis_path": "results/cha/ST010_HEINRICH_ZILLE_STRASSE/cha_kpis.json",
      "dha_kpis_path": "results/dha/ST010_HEINRICH_ZILLE_STRASSE/dha_kpis.json",
      "econ_summary_path": "results/economics/ST010_HEINRICH_ZILLE_STRASSE/monte_carlo_summary.json",
      "decision_config": "defaults"
    },
    "notes": []
  },
  "district_heating": {
    "feasible": true,
    "reasons": ["DH_OK"],
    "lcoh": { "median": 85.5, "p05": 75.2, "p95": 95.8 },
    "co2":  { "median": 120.5, "p05": 110.2, "p95": 130.8 },
    "hydraulics": {
      "velocity_ok": true,
      "dp_ok": true,
      "v_max_ms": 1.2,
      "v_min_ms": 0.3,
      "v_share_within_limits": 0.98,
      "dp_per_100m_max": 0.25,
      "hard_violations": []
    },
    "losses": {
      "total_length_m": 1250.5,
      "trunk_length_m": 900.0,
      "service_length_m": 350.5,
      "loss_share_pct": 5.2,
      "pump_power_kw": 12.5
    }
  },
  "heat_pumps": {
    "feasible": true,
    "reasons": ["HP_OK"],
    "lcoh": { "median": 92.3, "p05": 82.1, "p95": 102.5 },
    "co2":  { "median": 95.2, "p05": 85.0, "p95": 105.4 },
    "lv_grid": {
      "planning_warning": false,
      "max_feeder_loading_pct": 65.2,
      "voltage_violations_total": 0,
      "line_violations_total": 0,
      "worst_bus_id": null,
      "worst_line_id": null
    },
    "hp_system": {
      "hp_total_kw_design": 450.5,
      "hp_total_kw_topn_max": 450.5
    }
  },
  "monte_carlo": {
    "dh_wins_fraction": 0.75,
    "hp_wins_fraction": 0.25,
    "n_samples": 500,
    "seed": 42
  }
}
```

### Notes
- `metadata.git_commit` is best-effort (may be `"unknown"` if git is unavailable).
- `monte_carlo` can be `null` if economics MC results are missing.

---

## Decision JSON (`decision_*.json`)

This is the deterministic output of `branitz_heat_decision.decision.rules.decide_from_contract(...)`.

```json
{
  "choice": "DH",
  "robust": true,
  "reason_codes": ["ONLY_DH_FEASIBLE", "ROBUST_DECISION"],
  "metrics_used": {
    "lcoh_dh_median": 85.5,
    "lcoh_hp_median": 92.3,
    "co2_dh_median": 120.5,
    "co2_hp_median": 95.2,
    "dh_wins_fraction": 0.75,
    "hp_wins_fraction": 0.25
  }
}
```

---

## UHDC Report JSON (`uhdc_report_*.json`)

This is a single payload used for rendering the HTML/MD reports. It includes:
- `contract` (the KPI contract)
- `decision` (decision JSON)
- `explanation` (LLM or safe template output)
- `sources` (resolved artifact paths used to build the report)
- `metadata` (report generation metadata)

```json
{
  "cluster_id": "ST010_HEINRICH_ZILLE_STRASSE",
  "contract": { "version": "1.0", "...": "..." },
  "decision": { "choice": "DH", "robust": true, "reason_codes": ["ONLY_DH_FEASIBLE"], "metrics_used": {} },
  "explanation": "…",
  "sources": {
    "cha_kpis": "results/cha/ST010_HEINRICH_ZILLE_STRASSE/cha_kpis.json",
    "dha_kpis": "results/dha/ST010_HEINRICH_ZILLE_STRASSE/dha_kpis.json",
    "econ_summary": "results/economics/ST010_HEINRICH_ZILLE_STRASSE/monte_carlo_summary.json"
  },
  "metadata": {
    "uhdc_version": "1.0",
    "generated_by": "uhdc.orchestrator",
    "timestamp": "2026-01-14T05:45:00Z"
  }
}
```

---

## Report Markdown (`uhdc_explanation_*.md`)

This is a human-readable report containing:
- headline + timestamp
- recommendation + robustness
- executive summary
- key metrics for DH + HP
- decision reason codes with descriptions
- data sources
- standards references footer (**EN 13941-1 ×3**, **VDE-AR-N 4100 ×2**)

---

## Report HTML (`uhdc_report_*.html`)

The HTML report includes:
- decision banner (DH / HP / UNDECIDED)
- DH + HP key metric cards
- embedded charts (SVG)
- optional interactive map iframe
- reason code table
- standards references footer (**EN 13941-1 ×3**, **VDE-AR-N 4100 ×2**)

### Auditability tooltips
Key numeric values in the HTML are wrapped with a hover tooltip:
- Example: hovering LCOH shows `district_heating.lcoh.median`
- Implemented via `<span class="source-hint" data-source="...">…</span>`

