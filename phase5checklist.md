# Phase 5 Implementation Checklist

Complete this checklist **before proceeding to Phase 6**. Each item must be ticked off with a commit hash or test result.

---

## Known errors encountered during Phase 5 implementation (and fixes applied)

Use this section as an audit trail of the real problems we hit while wiring Phase 5 end-to-end.

- [x] **`cli/decision.py` was empty on disk (0 bytes) → decision CLI silently did nothing**
  - **Symptom**: `python -m branitz_heat_decision.cli.decision ...` produced no output and no files.
  - **Root cause**: `src/branitz_heat_decision/cli/decision.py` file size was 0 bytes.
  - **Fix**: Recreated `src/branitz_heat_decision/cli/decision.py` with a working CLI entrypoint and output writers.

- [x] **`KPIContract` dataclass crashed imports (`TypeError: non-default argument 'cluster_id' follows default argument`)**
  - **Symptom**: decision CLI crashed during import of `decision/schemas.py`.
  - **Root cause**: `version: str = "1.0"` was declared before non-default fields in `KPIContract`.
  - **Fix**: Moved `version` to the end of `KPIContract` in `src/branitz_heat_decision/decision/schemas.py`.

- [x] **`decision/rules.py` missing `List` import**
  - **Symptom**: runtime import/type errors in rules module.
  - **Fix**: Added `from typing import List` in `src/branitz_heat_decision/decision/rules.py`.

- [x] **Decision robustness step crashed when Monte Carlo block was `None`**
  - **Symptom**: `AttributeError: 'NoneType' object has no attribute 'get'` in `decide_from_contract`.
  - **Root cause**: `mc = contract.get('monte_carlo', {})` returns `None` when the key exists but value is `None`.
  - **Fix**: Use `mc = contract.get('monte_carlo') or {}` in `src/branitz_heat_decision/decision/rules.py`.

- [x] **Contract validation rejected real overload cases (ST010 max feeder loading > 200%)**
  - **Symptom**: `ValueError: lv_grid.max_feeder_loading_pct must be 0-200%` on ST010 (219.96%).
  - **Fix**: Relaxed validator upper bound to 1000% in `src/branitz_heat_decision/decision/schemas.py`.

- [x] **`decision/kpi_contract.py` did not match current output schemas (CHA/DHA/Economics)**
  - **Symptom**: wrong/missing values in contract; schema validation failures.
  - **Root cause**: contract builder expected flat keys (e.g., `cha_kpis['total_length_m']`) but current outputs are nested:
    - CHA: `aggregate.*`, `losses.*`, `pump.*`, `en13941_compliance.*`
    - DHA: `kpis.*`
    - Economics summary: `lcoh.*`, `co2.*`, `monte_carlo.*`
  - **Fix**: Updated extractors and MC block mapping in `src/branitz_heat_decision/decision/kpi_contract.py`.

- [x] **UHDC orchestrator imported missing module `uhdc/io.py`**
  - **Symptom**: import error in `uhdc/orchestrator.py`.
  - **Fix**: Added `src/branitz_heat_decision/uhdc/io.py` with basic JSON loaders.

- [x] **UHDC artifact discovery used wrong path prefixes (produced `results/results/...`)**
  - **Symptom**: UHDC couldn’t find artifacts when invoked with `--run-dir results`.
  - **Root cause**: `SEARCH_PATTERNS` had entries starting with `results/...` while `run_dir` was already `results/`.
  - **Fix**: Made patterns relative to `run_dir` in `src/branitz_heat_decision/uhdc/orchestrator.py`.

- [x] **UHDC economics search patterns used wrong folder name (`econ` vs `economics`)**
  - **Symptom**: UHDC could not find `monte_carlo_summary.json`.
  - **Fix**: Updated patterns to `economics/{cluster_id}/monte_carlo_summary.json` (and CLI run variant) in `src/branitz_heat_decision/uhdc/orchestrator.py`.

- [x] **`uhdc/report_builder.py` had non-Python “note text” embedded → file wouldn’t import**
  - **Symptom**: syntax/name errors at module import.
  - **Fix**: Removed the accidental note block and restored valid module header in `src/branitz_heat_decision/uhdc/report_builder.py`.

- [x] **`uhdc/report_builder.py` referenced wrong REASON_CODES module**
  - **Symptom**: Import resolution errors / incorrect module path.
  - **Fix**: Import `REASON_CODES` from `src/branitz_heat_decision/decision/schemas.py`.

- [x] **`uhdc/explainer.py` used `logger` before initialization**
  - **Symptom**: `NameError` / warning path crashes when GenAI SDK missing.
  - **Fix**: Initialize `logger = logging.getLogger(__name__)` before the optional import block.

- [x] **Parallel Monte Carlo (`n_jobs>1`) broke on macOS spawn when run from `<stdin>`**
  - **Symptom**: `FileNotFoundError: .../<stdin>` + `BrokenProcessPool`.
  - **Fix**: Use a fork multiprocessing context when available in `src/branitz_heat_decision/economics/monte_carlo.py`.

- [x] **`cli/decision.py` contained a duplicated second CLI block (two CLIs in one file)**
  - **Symptom**: confusing behavior and brittle imports; file had two `main()` definitions and two `if __name__ == "__main__":` blocks.
  - **Fix**: Removed the duplicated tail block, leaving a single CLI implementation in `src/branitz_heat_decision/cli/decision.py`.

---

## 1. KPI Contract Schema & Validation

### 1.1 Schema Definitions
- [x] `schemas.py` contains all dataclasses: `KPIContract`, `DistrictHeatingBlock`, `HeatPumpsBlock`, `MonteCarloBlock`, `LCOHMetrics`, `CO2Metrics`, `HydraulicsKPIs`, `LossesKPIs`, `LVGridKPIs`
- [x] `REASON_CODES` dictionary is complete (30+ codes covering feasibility, economics, robustness, data quality)
  - **Current status**: `REASON_CODES` now contains **32 codes** (see `src/branitz_heat_decision/decision/schemas.py`).
- [x] Docstrings explain each field and validation rule (see dataclass docstrings in `src/branitz_heat_decision/decision/schemas.py`)

### 1.2 Validation Logic
- [x] `ContractValidator.validate()` checks **all** required top-level keys (`version`, `cluster_id`, `metadata`, `district_heating`, `heat_pumps`)
- [x] Validates recursive structure (nested blocks)
- [x] Checks reason codes exist in `REASON_CODES`
- [x] Distinguishes `None` from `0` for violation counts (critical for feasibility inference)
- [x] Raises `ValueError` with **specific path** (e.g., `"district_heating.lcoh.median must be numeric"`)

### 1.3 Test Coverage
- [x] Unit test: `test_schema_validates_correct_contract` (see `tests/decision/test_schemas.py`)
- [x] Unit test: `test_schema_rejects_missing_keys` (see `tests/decision/test_schemas.py`)
- [x] Unit test: `test_schema_rejects_invalid_reason_code` (see `tests/decision/test_schemas.py`)
- [x] Unit test: `test_schema_allows_missing_mc_block` (see `tests/decision/test_schemas.py`)
- [x] Integration test: Build contract from real CHA/DHA/Economics outputs → validate → pass (see `tests/integration/test_full_pipeline.py::test_decision_cli_on_real_cluster`)

---

## 2. KPI Contract Builder

### 2.1 Core Function
- [x] `build_kpi_contract()` accepts `cluster_id`, `cha_kpis`, `dha_kpis`, `econ_summary`, `metadata`
- [x] Returns **validated** contract (calls `ContractValidator.validate()`)
- [x] Handles missing fields gracefully (inference with warnings, never crashes)
- [x] Logs warnings for missing KPIs (`"Cannot infer DH feasibility: missing v_share_within_limits"`)

### 2.2 Inference Logic
- [x] `_infer_dh_feasibility()`: Uses velocity share threshold (≥0.95) as fallback (see `src/branitz_heat_decision/decision/kpi_contract.py`)
- [x] `_infer_hp_feasibility()`: **Returns False if violation counts are None** (see `src/branitz_heat_decision/decision/kpi_contract.py`)
- [x] `_infer_dh_reasons()`: Maps metrics to `DH_VELOCITY_VIOLATION`, `DH_DP_VIOLATION`, `CHA_MISSING_KPIS` (see `src/branitz_heat_decision/decision/kpi_contract.py`)
- [x] `_infer_hp_reasons()`: Maps metrics to `HP_UNDERVOLTAGE`, `HP_OVERCURRENT_OR_OVERLOAD`, `DHA_MISSING_KPIS` (see `src/branitz_heat_decision/decision/kpi_contract.py`)

### 2.3 Metric Extraction
- [x] `_extract_lcoh_metrics()`: Handles nested dict (`econ_summary['lcoh']['dh'|'hp']`) and fallback flat values (see `src/branitz_heat_decision/decision/kpi_contract.py`)
- [x] `_extract_co2_metrics()`: Same fallback logic as LCOH (see `src/branitz_heat_decision/decision/kpi_contract.py`)
- [x] All extractions preserve `None` for missing optional fields (e.g., `mean/std` may be `None`)

### 2.4 Test Coverage
- [x] Test builds contract from **minimal** CHA/DHA dicts (only required fields) → passes validation (see `tests/decision/test_contract_builder.py`)
- [x] Test builds contract from **full** nested dicts → passes validation (see `tests/decision/test_contract_builder.py`)
- [x] Test missing `monte_carlo` block → contract still valid (see `tests/decision/test_schemas.py`)
- [x] Test missing violation counts → feasibility = False, reason = `*_MISSING_KPIS` (see `tests/decision/test_contract_builder.py`)

---

## 3. Decision Rules Engine

### 3.1 Configuration Management
- [x] `DEFAULT_DECISION_CONFIG` defined with 4 parameters (see `src/branitz_heat_decision/decision/rules.py`)
- [x] `decide_from_contract()` accepts optional `config` dict (see `src/branitz_heat_decision/decision/rules.py`)
- [x] Config values **must be validated** (thresholds between 0-1, positive abs threshold)
  - **Implementation**: `validate_config()` in `src/branitz_heat_decision/decision/rules.py`
  - **Tests**: `tests/decision/test_config_validation.py`

### 3.2 Decision Logic (4 Steps)
- [x] **Step 1 (Feasibility)**: Returns immediately if only one option feasible (see `src/branitz_heat_decision/decision/rules.py`)
- [x] **Step 2 (Cost)**: Computes `rel_diff` + `abs_diff`; uses `is_close` flag (see `src/branitz_heat_decision/decision/rules.py`)
- [x] **Step 3 (CO₂ Tie-Breaker)**: Only runs if `is_close=True` (see `src/branitz_heat_decision/decision/rules.py`)
- [x] **Step 4 (Robustness)**: Checks win fraction against `robust_win_fraction` (0.70) and `sensitive_win_fraction` (0.55) (see `src/branitz_heat_decision/decision/rules.py`)

### 3.3 Output Structure
- [x] Returns `DecisionResult` with fields: `choice`, `robust`, `reason_codes`, `metrics_used` (see `src/branitz_heat_decision/decision/rules.py`)
- [x] `metrics_used` includes all numbers used in decision (for LLM citation) (see `src/branitz_heat_decision/decision/rules.py`)
- [x] `reason_codes` list is ordered by decision steps (feasibility → cost → CO₂ → robustness) (see `src/branitz_heat_decision/decision/rules.py`)

### 3.4 Edge Cases
- [x] Both infeasible → `UNDECIDED`, reason `NONE_FEASIBLE` (covered in `tests/decision/test_rules.py`)
- [x] MC data missing → `robust=False`, reason `MC_MISSING` (covered in `tests/decision/test_rules.py`)
- [x] Costs equal → Falls through to CO₂ tie-breaker (implicit via `is_close=True` path)
- [x] CO₂ also equal → **Deterministic tie-break**: Choose DH (implemented in `src/branitz_heat_decision/decision/rules.py`)

### 3.5 Test Coverage
- [x] `test_only_dh_feasible`: Returns DH, reason `ONLY_DH_FEASIBLE` (see `tests/decision/test_rules.py`)
- [x] `test_only_hp_feasible`: Returns HP, reason `ONLY_HP_FEASIBLE` (see `tests/decision/test_rules.py`)
- [x] `test_both_infeasible`: Returns `UNDECIDED`, reason `NONE_FEASIBLE` (see `tests/decision/test_rules.py`)
- [x] `test_cost_clear_dh`: Cost diff >5% → DH, no CO₂ tie-breaker (see `tests/decision/test_rules.py`)
- [x] `test_cost_close_co2_tiebreaker`: Cost diff ≤5% → CO₂ decides (see `tests/decision/test_rules.py`)
- [x] `test_robust_threshold_70`: Win fraction 0.75 → `robust=True` (see `tests/decision/test_rules.py`)
- [x] `test_sensitive_threshold_55`: Win fraction 0.60 → `robust=False`, reason `SENSITIVE_DECISION` (see `tests/decision/test_rules.py`)

---

## 4. LLM Coordinator (Read-Only Explainer)

### 4.1 Safe Prompt Engineering
- [x] `STYLE_TEMPLATES` define 3 styles (executive, technical, detailed) with explicit instructions (see `src/branitz_heat_decision/uhdc/explainer.py`)
- [x] `_build_constrained_prompt()` includes:
  - [x] System role definition
  - [x] **STRICT RULES** (6 bullet points, numbered)
  - [x] Contract data section with **all explicit numbers**
  - [x] Decision logic section
  - [x] Style-specific instructions

### 4.2 LLM Call Configuration
- [x] Uses `temperature=0.0` (deterministic) (see `src/branitz_heat_decision/uhdc/explainer.py`)
- [x] `max_output_tokens=500` (prevents rambling) (see `src/branitz_heat_decision/uhdc/explainer.py`)
- [x] `top_p=0.95`, `top_k=40` (standard but explicit) (see `src/branitz_heat_decision/uhdc/explainer.py`)
- [x] Model default `'gemini-2.0-flash'` (configurable) (see `src/branitz_heat_decision/uhdc/explainer.py`)

### 4.3 Safety Validation
- [x] `_validate_explanation_safety()` extracts **all numbers** from explanation (see `src/branitz_heat_decision/uhdc/explainer.py`)
- [x] Builds `allowed_numbers` set from contract (LCOH, CO₂, velocity, loading, win fractions) with ±1% tolerance
- [x] **Raises `ValueError`** if any number not in allowed set
- [x] Checks that `decision['choice']` is mentioned in explanation
- [x] Checks that **at least one** standard reference appears (`EN 13941` or `VDE`) (warn-level if missing)

### 4.4 Fallback Mechanism
- [x] If `LLM_AVAILABLE=False` → uses template explanation (call site in decision/UHDC CLIs uses fallback)
- [x] If LLM API fails → **catches exception**, logs, uses template (see `src/branitz_heat_decision/uhdc/explainer.py`)
- [x] If safety check fails → **catches `ValueError`**, logs, uses template (see `src/branitz_heat_decision/uhdc/explainer.py`)
- [x] Template explanation is **deterministic** and **verifiable** (validated by tests below)

### 4.5 Template Quality
- [x] `_exec_template()`: 3-4 sentences, covers feasibility, cost, robustness (see `src/branitz_heat_decision/uhdc/explainer.py`)
- [x] `_tech_template()`: Bulleted KPIs, explicit numbers, standards (see `src/branitz_heat_decision/uhdc/explainer.py`)
- [x] `_detailed_template()`: Step-by-step logic, assumptions, planner recommendations (see `src/branitz_heat_decision/uhdc/explainer.py`)
- [x] All templates reference **only** contract data (no invented numbers) (enforced by safety validator in tests)

### 4.6 Test Coverage
- [x] `test_llm_safety_pass`: Valid explanation passes validation (see `tests/uhdc/test_explainer_safety.py`)
- [x] `test_llm_safety_fail_hallucinated_number`: Hallucinated number raises `ValueError` (see `tests/uhdc/test_explainer_safety.py`)
- [x] `test_llm_fallback_on_api_error`: API exception → fallback template used (see `tests/uhdc/test_explainer_fallback.py`)
- [x] `test_llm_fallback_on_missing_kpis`: Missing data → fallback (safe) (see `tests/uhdc/test_explainer_fallback.py`)
- [x] Test all 3 styles use only contract-traceable numbers (exec/tech/detailed) (see `tests/uhdc/test_explainer_fallback.py`)

---

## 5. Path Discovery & Orchestrator

### 5.1 Discovery Patterns
- [x] ⚠️ `SEARCH_PATTERNS` dict defines 4 artifact types with ≥4 patterns each (nested → flat)
  - Implemented centrally in `src/branitz_heat_decision/config_paths.py` and imported by `src/branitz_heat_decision/uhdc/orchestrator.py`.
- [x] Patterns include: `decision/`, `{type}/{cluster_id}/...`, and legacy fallbacks (see `src/branitz_heat_decision/uhdc/orchestrator.py`)
- [x] ⚠️ `discover_artifact_paths()` logs **every checked path** (debugging aid)
  - Implemented as `logger.debug(...)` per checked path in `discover_artifact_paths()`.
- [x] Returns `Dict[str, Optional[Path]]` (None = not found)

### 5.2 Orchestrator Logic
- [x] `build_uhdc_report()` tries **fast path** (`kpi_contract_path`) first (see `src/branitz_heat_decision/uhdc/orchestrator.py`)
- [x] If no contract, **discovers** individual artifacts, loads them, builds contract (see `src/branitz_heat_decision/uhdc/orchestrator.py`)
- [x] If no artifacts found → raises `FileNotFoundError` with helpful message (see `src/branitz_heat_decision/uhdc/orchestrator.py`)
- [x] Compiles metadata with **all source paths** (for traceability)
- [x] Returns complete `report` dict (contract + decision + explanation + sources + metadata)

### 5.3 Test Coverage
- [x] `test_discover_nested_structure`: Files in `results/cha/{id}/` → found (see `tests/uhdc/test_orchestrator_discovery.py`)
- [x] `test_discover_flat_structure`: Flat artifacts under run_dir root → found (see `tests/uhdc/test_orchestrator_discovery.py`)
- [x] `test_discover_fallback_order`: First matching pattern wins (see `tests/uhdc/test_orchestrator_discovery.py`)
- [x] `test_no_artifacts_raises_error`: No artifacts → `build_uhdc_report()` raises `FileNotFoundError` (see `tests/uhdc/test_orchestrator_discovery.py`)

---

## 6. CLI Integration

### 6.1 Decision CLI
- [x] `cli/decision.py` has **epilogue** with usage examples (see `src/branitz_heat_decision/cli/decision.py`)
- [x] All arguments have help text and type validation (uses `Path` + explicit choices; see `src/branitz_heat_decision/cli/decision.py`)
- [x] `--no-fallback` flag allows failing on LLM error (for testing) (wired via `explain_with_llm(..., no_fallback=...)`)
- [x] `--all-clusters` flag processes all clusters under `results/cha/` (batch mode)
- [x] `--format` option selects `{json, md, html, all}`
- [x] Saves outputs with consistent naming:
  - `kpi_contract_<cluster_id>.json`
  - `decision_<cluster_id>.json`
  - `explanation_<cluster_id>.md` / `explanation_<cluster_id>.html` (when requested)

### 6.2 Orchestrator CLI
- [x] `cli/uhdc.py` wraps `build_uhdc_report()` (see `src/branitz_heat_decision/cli/uhdc.py`)
- [x] `--all-clusters` flag iterates all cluster subdirectories under `results/cha/` (see `src/branitz_heat_decision/cli/uhdc.py`)
- [x] `--format` option selects `{html, md, json, all}` output (see `src/branitz_heat_decision/cli/uhdc.py`)

---

## 7. Testing Requirements

### 7.1 Unit Tests (100% coverage for decision logic)
- [x] `test_build_contract_validates_output`: Ensures contract passes validation (see `tests/decision/test_contract_builder.py`)
- [x] `test_decide_all_paths`: Tests all 16 decision path combinations (feasibility × cost × CO₂ × robustness) (see `tests/decision/test_rules.py::test_decide_all_paths`)
- [ ] `test_llm_prompt_contains_all_metrics`: Inspects prompt string for contract numbers (not implemented)
- [x] `test_llm_safety_allows_rounding`: Rounding tolerance validated (see `tests/uhdc/test_explainer_safety.py::test_llm_safety_allows_rounding`)
- [x] `test_fallback_template_no_hallucination`: Template output contains **only** contract numbers (see `tests/uhdc/test_explainer_safety.py`)

### 7.2 Integration Tests
- [x] `test_full_pipeline_with_real_data`: Run on one real Branitz cluster → generates all Phase 5 artifacts (decision + UHDC report) (see `tests/integration/test_full_pipeline.py`)
- [ ] `test_report_html_contains_map_iframe`: If map exists, iframe src is correct
- [x] `test_report_html_validates`: Offline HTML parse + structure sanity check (CI-safe) (see `tests/integration/test_report_outputs.py::test_report_html_validates_offline`)
- [x] `test_report_json_roundtrip`: Save JSON → load → same as original (see `tests/integration/test_report_outputs.py::test_report_json_roundtrip`)

### 7.2.1 UHDC smoke tests (local)
- [x] `test_save_reports_writes_html_and_md`: report builder writes HTML/MD/JSON without template files present (see `tests/uhdc/test_report_builder_smoke.py`)

### 7.4 Phase 5 test execution evidence (local)
- [x] **All Phase 5 unit tests green**: `pytest -q tests/decision tests/uhdc` → **20 passed** (run in `branitz_env`)

### 7.3 Performance & Robustness
- [ ] Decision logic runs in **<10ms** (no LLM) for 1000 clusters
- [ ] LLM explanation runs in **<2s** per cluster (API latency)
- [ ] Path discovery handles **1000+ result files** without slowdown (uses `Path.glob()` efficiently)

---

## 8. Documentation

### 8.1 Code Documentation
- [ ] Every function has docstring with **Args, Returns, Raises**
- [ ] Type hints on **all** parameters and returns
- [ ] Complex logic (robustness calculation) has inline comments

### 8.2 User Documentation
- [x] `docs/decision_pipeline.md`: Flowchart of decision logic (Mermaid diagram)
- [x] `docs/uhdc_output_formats.md`: JSON schema, HTML features, Markdown structure
- [x] `docs/reason_codes.md`: Table of all 30+ codes with examples (see `docs/reason_codes.md`)
- [ ] `docs/troubleshooting.md`: "Why did decision return UNDECIDED?" with debugging steps

### 8.3 API Reference
- [ ] Sphinx autodoc generates pages for `decision.kpi_contract`, `decision.rules`, `uhdc.*`
- [x] Include example contract JSON in docs (downloadable) (`examples/kpi_contract_example.json`, linked from `docs/uhdc_output_formats.md`)

---

## 9. Deployment & Configuration

### 9.1 Environment Variables
- [x] `GOOGLE_API_KEY`: Required for LLM explanations (checked at runtime, graceful fallback)
- [x] `GOOGLE_MODEL`: Optional override for Gemini model (default: `gemini-2.0-flash`)
- [x] `LLM_TIMEOUT`: Optional timeout seconds for LLM call (default: `30`)
- [x] `UHDC_FORCE_TEMPLATE`: Optional kill-switch to force template mode (`true|false`)
- [x] `UHDC_LOG_LEVEL`: Controls verbosity (`DEBUG` = log all checked paths)
- [x] `UHDC_TEMPLATE_DIR`: Override default templates path (optional)

### 9.2 Configuration Files
- [x] Example `config/decision_config_2023.json`: Named scenario config
- [x] Example `config/decision_config_2030.json`: Named scenario config

---

## 10. Final Sign-Off

### 10.1 Determinism Guarantee
- [x] Run decision pipeline **2 times** on same cluster → **identical** decision output (choice/reasons/metrics) (see `tests/integration/test_full_pipeline.py::test_decision_is_deterministic_on_real_cluster`)
  - **Note**: explanation may differ if LLM is enabled; determinism check intentionally runs without LLM.
- [x] Commit hash recorded in metadata for reproducibility (`metadata.git_commit` in KPI contract)

### 10.1.1 LLM Key Integration (Phase 5 add-on)
- [x] `.env` gitignored (`.gitignore` includes `.env` + `.env.*`)
- [x] `python-dotenv` installed (`requirements.txt`)
- [x] `.env` loaded safely (no override of existing env vars) in `src/branitz_heat_decision/uhdc/explainer.py`
- [x] API key presence is enforced for LLM mode; otherwise graceful template fallback (or hard fail with `--no-fallback`)
- [x] `_call_llm()` passes `GOOGLE_API_KEY` securely + best-effort timeout (`LLM_TIMEOUT`)
- [x] CLI prints LLM status when `--llm-explanation` is used (enabled/missing/forced-template) and errors early with `--no-fallback`
- [x] Test added for env wiring without external API calls: `tests/uhdc/test_llm_integration.py`
- [x] Manual smoke run with LLM enabled on ST010:
  - Command: `PYTHONPATH=src python -m branitz_heat_decision.cli.decision --cluster-id ST010_HEINRICH_ZILLE_STRASSE --llm-explanation --format all`
  - Outputs: `results/decision/ST010_HEINRICH_ZILLE_STRASSE/explanation_*.md` + `.html`

### 10.2 Auditability Guarantee
- [x] Reason codes **100% traceable** to contract fields (reason taxonomy in `decision/schemas.py`, used in contract + report)
- [x] Every numeric value in HTML report has **tooltip** showing source path in contract JSON (implemented in `uhdc/report_builder.py`)
- [x] Contract includes **full source paths** to CHA/DHA/Economics files (written into `metadata.inputs` by decision CLI)

### 10.3 Standards Compliance
- [x] Reference EN 13941-1 in HTML report **3 times** (hydraulics, Δp, velocity)
- [x] Reference VDE-AR-N 4100 in HTML report **2 times** (voltage, loading)
- [x] Link to official standard documents in report footer

### 10.4 Stakeholder Review
- [ ] Share HTML report with **3 municipal planners** → collect feedback (comprehensible?)
- [ ] Share markdown with **2 engineers** → verify technical accuracy
- [ ] Share JSON with **1 data scientist** → confirm schema completeness

---

## 🎯 Phase 5 Completion Criteria

All checklist items must be **✅ completed and tested**. This phase is **complete** when:

1. **Automated tests pass**: `pytest tests/test_decision_pipeline.py -v` → **0 failures**
2. **Manual test successful**: Run on one real Branitz cluster → **all 3 outputs generated and validated**
3. **Determinism verified**: 3 runs → **diff shows only timestamp differences**
4. **Stakeholder sign-off**: At least 1 municipal planner confirms explanation is **understandable and traceable**

---

**Proceed to Phase 6 only after this checklist is fully checked off.**

