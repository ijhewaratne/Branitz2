# UHDC Module Documentation

Complete documentation for the UHDC (Unified Heat Decision Communication) module implementing report generation, LLM explanations, and artifact orchestration for the Branitz Heat Decision pipeline.

**Module Location**: `src/branitz_heat_decision/uhdc/`  
**Total Lines of Code**: ~2,143 lines  
**Primary Language**: Python 3.9+  
**Dependencies**: jinja2, matplotlib, seaborn, pandas, google-genai (optional), dotenv (optional), pathlib, json, logging, base64, shutil

---

## Module Overview

The UHDC module provides unified report generation and explanation capabilities for the Branitz Heat Decision pipeline:

1. **Orchestrator** (`orchestrator.py`): Discovers artifacts, builds KPI contracts, makes decisions, and generates reports
2. **Explainer** (`explainer.py`): Generates natural language explanations using LLM (Gemini) or template fallbacks
3. **Report Builder** (`report_builder.py`): Renders HTML, Markdown, and JSON reports with interactive charts and maps
4. **IO** (`io.py`): Simple JSON loading utilities for artifact discovery

### Architecture

The UHDC module follows a pipeline architecture with clear separation of concerns:

```
UHDC Module
├─ orchestrator.py → Artifact Discovery & Report Orchestration
├─ explainer.py → LLM/Template Explanation Generation
├─ report_builder.py → HTML/Markdown/JSON Report Rendering
└─ io.py → JSON Loading Utilities
```

---

## Module Files & Functions

### `__init__.py` (Empty) ⭐ **MODULE INITIALIZATION**
**Purpose**: Module initialization (currently empty, exports handled by individual modules)

---

### `io.py` (27 lines) ⭐ **JSON LOADING UTILITIES**
**Purpose**: Simple JSON loading utilities for artifact discovery

**Main Functions**:

#### `load_json()` ⭐ **GENERIC JSON LOADER**
```python
def load_json(path: Path) -> Dict[str, Any]
```

**Purpose**: Load JSON file from path

**Returns**: Dictionary with JSON contents

**Usage**: Generic JSON loader used by all artifact loaders

---

#### `load_kpi_contract()` ⭐ **KPI CONTRACT LOADER**
```python
def load_kpi_contract(path: Path) -> Dict[str, Any]
```

**Purpose**: Load KPI contract JSON file

**Returns**: KPI contract dictionary

**Usage**: Loads pre-built KPI contract from `results/decision/<cluster_id>/kpi_contract.json`

---

#### `load_cha_kpis()` ⭐ **CHA KPIS LOADER**
```python
def load_cha_kpis(path: Path) -> Dict[str, Any]
```

**Purpose**: Load CHA KPIs JSON file

**Returns**: CHA KPIs dictionary

**Usage**: Loads CHA KPIs from `results/cha/<cluster_id>/cha_kpis.json`

---

#### `load_dha_kpis()` ⭐ **DHA KPIS LOADER**
```python
def load_dha_kpis(path: Path) -> Dict[str, Any]
```

**Purpose**: Load DHA KPIs JSON file

**Returns**: DHA KPIs dictionary

**Usage**: Loads DHA KPIs from `results/dha/<cluster_id>/dha_kpis.json`

---

#### `load_econ_summary()` ⭐ **ECONOMICS SUMMARY LOADER**
```python
def load_econ_summary(path: Path) -> Dict[str, Any]
```

**Purpose**: Load economics Monte Carlo summary JSON file

**Returns**: Economics summary dictionary

**Usage**: Loads economics summary from `results/economics/<cluster_id>/monte_carlo_summary.json`

---

**Interactions**:
- **Used by**: `orchestrator.py` (for loading artifacts during discovery)
- **Outputs**: Dictionary representations of JSON artifacts

---

### `orchestrator.py` (300 lines) ⭐ **ARTIFACT ORCHESTRATION**
**Purpose**: Discovers artifacts, builds KPI contracts, makes decisions, and generates reports

**Main Functions**:

#### `discover_artifact_paths()` ⭐ **ARTIFACT PATH DISCOVERY**
```python
def discover_artifact_paths(
    cluster_id: str,
    base_dir: Path,
) -> Dict[str, Optional[Path]]
```

**Purpose**: Discover all artifact paths using intelligent search with multiple fallback patterns

**Workflow**:

1. **Cache Check**: Check in-memory cache for previously discovered paths (key: `(base_dir, cluster_id)`)

2. **Pattern Search**: For each artifact type (`kpi_contract`, `cha_kpis`, `dha_kpis`, `econ_summary`):
   - Iterate through `SEARCH_PATTERNS[artifact_type]` (multiple fallback patterns)
   - For each pattern:
     - Format pattern with `cluster_id`: `base_dir / pattern.format(cluster_id=cluster_id)`
     - Log attempt (debug level)
     - If path exists: return immediately (skip remaining patterns)
   - If no pattern matches: log error with all attempted paths

3. **Cache Storage**: Store discovered paths in cache for future lookups

**Returns**: Dictionary mapping artifact type to discovered `Path` or `None`

**Search Patterns** (from `config_paths.py`):
- **kpi_contract**: `decision/{cluster_id}/kpi_contract.json`, `results/decision/{cluster_id}/kpi_contract.json`
- **cha_kpis**: `cha/{cluster_id}/cha_kpis.json`, `results/cha/{cluster_id}/cha_kpis.json`
- **dha_kpis**: `dha/{cluster_id}/dha_kpis.json`, `results/dha/{cluster_id}/dha_kpis.json`
- **econ_summary**: `economics/{cluster_id}/monte_carlo_summary.json`, `results/economics/{cluster_id}/monte_carlo_summary.json`

**Logging**:
- **Info**: Search start, found paths
- **Debug**: Every pattern attempt, cache hits
- **Error**: Missing artifacts with all attempted paths

---

#### `build_uhdc_report()` ⭐ **PRIMARY REPORT BUILDER**
```python
def build_uhdc_report(
    cluster_id: str,
    run_dir: Path,
    kpi_contract_path: Optional[Path] = None,
    use_llm: bool = False,
    explanation_style: str = "executive",
) -> Dict[str, Any]
```

**Purpose**: Build complete UHDC report from artifacts

**Workflow**:

1. **Fast Path (KPI Contract Provided)**:
   - If `kpi_contract_path` provided and exists:
     - Load KPI contract directly via `load_kpi_contract()`
     - Set `sources['kpi_contract'] = kpi_contract_path`
     - Skip artifact discovery

2. **Discovery Path (Build from Components)**:
   - Call `discover_artifact_paths(cluster_id, run_dir)`
   - Validate: raise `FileNotFoundError` if no artifacts found
   - Load individual components:
     - `cha_kpis = load_cha_kpis(sources['cha_kpis'])` (if exists)
     - `dha_kpis = load_dha_kpis(sources['dha_kpis'])` (if exists)
     - `econ_summary = load_econ_summary(sources['econ_summary'])` (if exists)
   - Build metadata:
     ```python
     metadata = {
         'created_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ'),
         'sources': {k: str(v) if v else None for k, v in sources.items()},
         'notes': [],
     }
     ```
   - Build KPI contract via `build_kpi_contract()`:
     ```python
     contract = build_kpi_contract(
         cluster_id=cluster_id,
         cha_kpis=cha_kpis or {},
         dha_kpis=dha_kpis or {},
         econ_summary=econ_summary or {},
         metadata=metadata,
     )
     ```

3. **Decision Making**:
   - Call `decide_from_contract(contract)` to get `DecisionResult`
   - Convert to dictionary: `decision_result.to_dict()`

4. **Explanation Generation**:
   - If `use_llm=True`:
     - Try `explain_with_llm(contract, decision_result.to_dict(), style=explanation_style)`
     - On exception: fallback to `_fallback_template_explanation()`
   - Else: Use `_fallback_template_explanation()` (template-based)

5. **Report Compilation**:
   ```python
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
   ```

**Returns**: Complete report dictionary

**Raises**:
- `FileNotFoundError`: If run directory does not exist or no artifacts found
- `ValueError`: If required artifacts are missing

---

#### `clear_discovery_cache()` ⭐ **CACHE CLEARER**
```python
def clear_discovery_cache() -> None
```

**Purpose**: Clear the in-memory artifact discovery cache (useful for tests)

**Usage**: Call before tests to ensure fresh discovery

---

#### `_configure_logging_from_env()` ⭐ **LOGGING CONFIGURATION**
```python
def _configure_logging_from_env() -> None
```

**Purpose**: Configure logging level from `UHDC_LOG_LEVEL` environment variable

**Default**: `INFO` if not set

**Usage**: Called by CLI `main()` function

---

#### `main()` ⭐ **CLI ENTRY POINT**
```python
def main() -> None
```

**Purpose**: CLI entry point for UHDC orchestrator

**Arguments**:
- `--cluster-id` (required): Cluster identifier
- `--run-dir` (default: `results`): Base results directory
- `--out-dir` (required): Output directory for reports
- `--llm`: Enable LLM explanations (requires `GOOGLE_API_KEY`)
- `--style` (default: `executive`): Explanation style (`executive`, `technical`, `detailed`)
- `--contract-path`: Use specific KPI contract file (fast path)
- `--html`: Write HTML report
- `--md`: Write Markdown report

**Workflow**:
1. Configure logging from environment
2. Parse arguments
3. Validate `run_dir` exists
4. Call `build_uhdc_report()`
5. Save JSON report (always)
6. Discover interactive maps (CHA: velocity/temp/pressure, DHA: hp_lv_map)
7. Call `save_reports()` for HTML/Markdown

**Map Discovery**:
- **CHA Maps**: `interactive_map.html`, `interactive_map_temperature.html`, `interactive_map_pressure.html`
- **DHA Map**: `hp_lv_map.html`
- Maps are bundled into `_maps/` subdirectory to avoid browser file:// restrictions

---

**Interactions**:
- **Uses**: `io.py` (load_* functions), `explainer.py` (explain_with_llm, _fallback_template_explanation), `report_builder.py` (save_reports), `decision/kpi_contract.py` (build_kpi_contract), `decision/rules.py` (decide_from_contract), `config_paths.py` (SEARCH_PATTERNS)
- **Used by**: CLI (`cli/uhdc.py`), direct Python calls
- **Outputs**: Complete UHDC report dictionary (JSON, HTML, Markdown)

---

### `explainer.py` (713 lines) ⭐ **LLM/TEMPLATE EXPLANATION GENERATION**
**Purpose**: Generate natural language explanations using LLM (Gemini) or template fallbacks

**Main Functions**:

#### `explain_with_llm()` ⭐ **PRIMARY LLM EXPLAINER**
```python
def explain_with_llm(
    contract: Dict[str, Any],
    decision: Dict[str, Any],
    style: str = "executive",
    model: str = GOOGLE_MODEL_DEFAULT,
    no_fallback: bool = False,
) -> str
```

**Purpose**: Generate natural language explanation using LLM (Gemini)

**Workflow**:

1. **Guard Checks**:
   - If `UHDC_FORCE_TEMPLATE=true`: fallback to template (unless `no_fallback=True`)
   - If `LLM_AVAILABLE=False`: fallback to template (unless `no_fallback=True`)
   - If `GOOGLE_API_KEY` missing: fallback to template (unless `no_fallback=True`)
   - Validate contract has critical fields (`district_heating.feasible`, `heat_pumps.feasible`)

2. **Prompt Building**:
   - Call `_build_constrained_prompt(contract, decision, style)`
   - Prompt includes:
     - System role definition
     - Strict rules (no invention, cite sources)
     - Contract data (all numbers explicit)
     - Decision data (choice, reasons)
     - Style-specific instructions

3. **LLM Call**:
   - Call `_call_llm(prompt, model)` with timeout and error handling
   - On exception: fallback to template (unless `no_fallback=True`)

4. **Safety Validation**:
   - Call `_validate_explanation_safety(explanation, contract, decision)`
   - Checks:
     - All numbers in explanation exist in contract (with ±1% tolerance)
     - No numbers deviate >1% from contract values
     - Standard references are correct (EN 13941-1, VDE-AR-N 4100)
     - Choice matches decision choice
   - On failure: fallback to template (unless `no_fallback=True`)

**Returns**: Natural language explanation string

**Raises**:
- `ValueError`: If LLM produces invalid output (safety check fails) and `no_fallback=True`
- `RuntimeError`: If LLM SDK not available and `no_fallback=True`

**Safety Guarantees**:
- Prompt contains ONLY contract data (no external retrieval)
- Temperature=0.0 for determinism
- Output validated against contract values (no hallucination)
- References only provided standards (EN 13941-1, VDE-AR-N 4100)

---

#### `_call_llm()` ⭐ **LLM API CALLER**
```python
def _call_llm(prompt: str, model: str) -> str
```

**Purpose**: Call Gemini via google-genai with best-effort timeout and error handling

**Workflow**:
1. **Validation**: Check `LLM_AVAILABLE`, `UHDC_FORCE_TEMPLATE`, `GOOGLE_API_KEY`
2. **Client Initialization**: `client = genai.Client(api_key=GOOGLE_API_KEY)`
3. **Config Setup**:
   ```python
   cfg = types.GenerateContentConfig(
       temperature=0.0,  # Deterministic
       max_output_tokens=500,
       top_p=0.95,
       top_k=40,
   )
   ```
4. **Timeout Support**: Best-effort timeout via `RequestOptions(timeout=LLM_TIMEOUT)` (varies by google-genai version)
5. **API Call**: `client.models.generate_content(model, contents=prompt, config=cfg, request_options=request_options)`
6. **Response**: Return `response.text` or empty string

**Returns**: LLM-generated text

**Raises**: `RuntimeError` if LLM unavailable or API key missing

---

#### `_build_constrained_prompt()` ⭐ **PROMPT BUILDER**
```python
def _build_constrained_prompt(
    contract: Dict[str, Any],
    decision: Dict[str, Any],
    style: str,
) -> str
```

**Purpose**: Build tightly constrained prompt from contract data only

**Structure**:
1. **System Role**: "You are an energy planning assistant specialized in municipal heating decisions."
2. **Strict Rules**:
   - CITE ONLY the metrics provided above - do not invent numbers
   - REFERENCE ONLY standards: EN 13941-1 (DH), VDE-AR-N 4100 (LV grid)
   - STATE ASSUMPTIONS explicitly if needed
   - KEEP length: style-specific (e.g., "3-4 sentences" for executive)
   - FORMAT: Plain text, no markdown headings except "Summary" if needed
   - NO HALLUCINATION: Every numeric value must be traceable to the metrics above
3. **Contract Data**:
   - District Heating Metrics (feasible, LCOH, CO₂, velocity, losses)
   - Heat Pump Metrics (feasible, LCOH, CO₂, loading, violations)
   - Monte Carlo Robustness (win fractions, samples)
4. **Decision Data**:
   - Choice (DH/HP/UNDECIDED)
   - Robust (True/False)
   - Reason Codes (list)
   - Logic Flow (formatted decision logic steps)
5. **Style Instructions**: Style-specific requirements (tone, must_include, length)

**Returns**: Complete prompt string

---

#### `_validate_explanation_safety()` ⭐ **SAFETY VALIDATOR**
```python
def _validate_explanation_safety(
    explanation: str,
    contract: Dict[str, Any],
    decision: Dict[str, Any],
) -> None
```

**Purpose**: Validate LLM output against contract data to detect hallucination

**Validation Checks**:

1. **Number Extraction**:
   - Extract all numbers from explanation using regex: `r'\d+\.?\d*'`
   - Build set of allowed numbers from contract:
     - LCOH values (median, p05, p95)
     - CO₂ values (median, p05, p95)
     - Velocity (v_max_ms)
     - Loading (max_feeder_loading_pct)
     - Violations (voltage_violations_total, line_violations_total)
     - MC fractions (dh_wins_fraction, hp_wins_fraction, n_samples)
     - Loss share percent (loss_share_pct)
     - Derived values (LCOH difference, relative difference %)

2. **Number Validation**:
   - Skip obvious non-metrics (year, cluster ID, standard identifiers like "13941", "4100", "95% CI")
   - Skip small ordinal numbers (1-10) used for enumerations
   - Skip numbers outside reasonable range (>10000 or <0)
   - For each number: check if it's in allowed set (with ±1% tolerance)
   - If not allowed: raise `ValueError` with hallucination message

3. **Choice Consistency**:
   - If `decision['choice'] == "DH"`: explanation must mention "district heating" or "DH"
   - If `decision['choice'] == "HP"`: explanation must mention "heat pump" or "HP"
   - If missing: raise `ValueError`

4. **Standard References**:
   - Check if "EN 13941" or "VDE" mentioned in explanation
   - Log warning if no standards mentioned (not fatal)

**Raises**: `ValueError` if hallucination detected

---

#### `_fallback_template_explanation()` ⭐ **TEMPLATE FALLBACK**
```python
def _fallback_template_explanation(
    contract: Dict[str, Any],
    decision: Dict[str, Any],
    style: str,
) -> str
```

**Purpose**: Safe fallback when LLM is unavailable or fails safety check

**Workflow**:
1. **Defensive Checks**: Extract `dh`, `hp`, `mc` with defaults (never crash)
2. **Critical Field Check**: If `dh['feasible']` or `hp['feasible']` missing: use `_minimal_safe_template()`
3. **Style Routing**:
   - `style == "executive"`: `_exec_template()`
   - `style == "technical"`: `_tech_template()`
   - `style == "detailed"`: `_detailed_template()`
   - Default: `_exec_template()`

**Returns**: Template-based explanation string

**Guarantees**:
- Deterministic (same inputs → same output)
- Verifiable against contract
- Professional in tone
- Style-adapted

---

#### `_exec_template()` ⭐ **EXECUTIVE TEMPLATE**
```python
def _exec_template(dh: Dict[str, Any], hp: Dict[str, Any], decision: Dict[str, Any], mc: Dict[str, Any]) -> str
```

**Purpose**: Executive summary template (3-4 sentences)

**Structure**:
1. **Recommendation**: `"{decision['choice']} is recommended for this cluster."`
2. **Robustness**: `"This option is {'robust' if decision['robust'] else 'sensitive to parameter uncertainty'}."`
3. **Feasibility**: If only one feasible, explain why other failed
4. **Cost**: If LCOH difference >5 EUR/MWh: "Economics clearly favor {choice}"; else: "Costs are close; {choice} chosen based on lower CO₂ emissions."
5. **Uncertainty**: If robust and MC data available: "Uncertainty analysis supports this in {win_frac:.0%} of scenarios."

**Returns**: Executive summary string

---

#### `_tech_template()` ⭐ **TECHNICAL TEMPLATE**
```python
def _tech_template(dh: Dict[str, Any], hp: Dict[str, Any], decision: Dict[str, Any], mc: Dict[str, Any]) -> str
```

**Purpose**: Technical template (bulleted KPIs)

**Structure**:
1. **Header**: "# Technical Assessment"
2. **District Heating Performance (EN 13941-1)**:
   - Velocity compliance, pressure drop, thermal losses, pump power
3. **Heat Pump Performance (VDE-AR-N 4100)**:
   - Feasible, max feeder loading, voltage violations
4. **Economics & Uncertainty**:
   - LCOH (median, 95% CI) for DH and HP
   - CO₂ (median) for DH and HP
   - Monte Carlo win fractions (if available)
5. **Decision**:
   - Choice, robust, reason codes

**Returns**: Technical assessment string (Markdown)

---

#### `_detailed_template()` ⭐ **DETAILED TEMPLATE**
```python
def _detailed_template(dh: Dict[str, Any], hp: Dict[str, Any], decision: Dict[str, Any], mc: Dict[str, Any]) -> str
```

**Purpose**: Detailed template (step-by-step with assumptions)

**Structure**:
1. **Header**: "# Detailed Decision Rationale"
2. **Step 1: Technical Feasibility Assessment**:
   - Both feasible, or only one feasible (with reasons)
3. **Step 2: Economic Comparison**:
   - LCOH comparison with 95% CI, relative difference
4. **Step 3: CO₂ Tie-Breaker (if applied)**:
   - CO₂ comparison, tie-breaker explanation
5. **Step 4: Uncertainty & Robustness**:
   - Monte Carlo samples, win fractions, robustness conclusion
6. **Key Assumptions**:
   - Technical constraints per standards
   - Building heat demand from TABULA typology
7. **Recommendations for Planners**:
   - Proceed with implementation
   - Validate input data quality
   - Monitor actual vs. projected heat demand
   - Sensitivity analysis (if not robust)

**Returns**: Detailed rationale string (Markdown)

---

#### `_minimal_safe_template()` ⭐ **MINIMAL SAFE TEMPLATE**
```python
def _minimal_safe_template(contract: Dict[str, Any], decision: Dict[str, Any], style: str) -> str
```

**Purpose**: Minimal fallback that never crashes (used when contract is missing critical fields)

**Structure**:
- Recommendation: `"{decision['choice']} is recommended (data incomplete; using safe template)."`
- Key available metrics: LCOH DH/HP, CO₂ DH/HP (formatted with defaults if missing)

**Returns**: Minimal safe explanation string

---

#### `_format_decision_logic()` ⭐ **DECISION LOGIC FORMATTER**
```python
def _format_decision_logic(reason_codes: List[str]) -> str
```

**Purpose**: Format decision logic steps in plain language

**Logic Map**:
- `ONLY_DH_FEASIBLE`: "Only DH meets technical standards"
- `ONLY_HP_FEASIBLE`: "Only HP meets technical standards"
- `COST_DOMINANT_DH`: "DH clearly cheaper (>5%)"
- `COST_DOMINANT_HP`: "HP clearly cheaper (>5%)"
- `COST_CLOSE_USE_CO2`: "Costs within 5% → CO₂ tie-breaker"
- `CO2_TIEBREAKER_DH`: "DH has lower emissions"
- `CO2_TIEBREAKER_HP`: "HP has lower emissions"

**Returns**: Formatted decision logic string (e.g., "1. Only DH meets technical standards → 2. DH clearly cheaper (>5%)")

---

#### `_load_env_if_present()` ⭐ **ENV LOADER**
```python
def _load_env_if_present() -> None
```

**Purpose**: Load `.env` file if present (safe, no override)

**Workflow**:
- Walk up parent directories from `__file__` looking for `.env`
- If found: call `load_dotenv(dotenv_path=env_path, override=False)`
- Log info message

**Called**: On module import

---

#### `_get_google_api_key()` ⭐ **API KEY GETTER**
```python
def _get_google_api_key() -> str | None
```

**Purpose**: Retrieve `GOOGLE_API_KEY` from environment

**Validation**:
- Strip whitespace and quotes
- Return `None` if missing or placeholder (`"YOUR_ACTUAL_API_KEY_HERE"`)

**Returns**: API key string or `None`

---

**Module-Level Constants**:
- `LLM_AVAILABLE`: `True` if `google-genai` SDK installed
- `GOOGLE_API_KEY`: Retrieved via `_get_google_api_key()`
- `LLM_READY`: `bool(LLM_AVAILABLE and GOOGLE_API_KEY and not UHDC_FORCE_TEMPLATE)`
- `GOOGLE_MODEL_DEFAULT`: `os.getenv("GOOGLE_MODEL", "gemini-2.0-flash")`
- `LLM_TIMEOUT`: `int(os.getenv("LLM_TIMEOUT", "30"))`
- `UHDC_FORCE_TEMPLATE`: `os.getenv("UHDC_FORCE_TEMPLATE", "false").lower() == "true"`

**Style Templates**:
- `STYLE_TEMPLATES`: Dictionary with `executive`, `technical`, `detailed` configurations (instruction, tone, must_include)

---

**Interactions**:
- **Uses**: `google-genai` (optional), `dotenv` (optional), `decision/schemas.py` (REASON_CODES)
- **Used by**: `orchestrator.py` (for explanation generation)
- **Outputs**: Natural language explanation strings

---

### `report_builder.py` (1,107 lines) ⭐ **REPORT RENDERING**
**Purpose**: Render reports in multiple formats (HTML, Markdown, JSON) with interactive charts and maps

**Main Functions**:

#### `render_html_report()` ⭐ **HTML REPORT RENDERER**
```python
def render_html_report(
    report_data: Dict[str, Any],
    map_path: Optional[Path] = None,
    map_paths: Optional[Mapping[str, Path]] = None,
    map_specs: Optional[List[Dict[str, Any]]] = None,
    reason_descriptions: Optional[Dict[str, str]] = None,
    violations_csv_path: Optional[Path] = None,
) -> str
```

**Purpose**: Render complete HTML report

**Workflow**:

1. **Template Loading**:
   - Try to load from file system: `UHDC_TEMPLATE_DIR` (default: `src/branitz_heat_decision/templates`)
   - If not found: use embedded `HTML_TEMPLATE` (Jinja2 string)

2. **Data Preparation**:
   - Load violations CSV if provided (convert to list of dicts)
   - Prepare template data:
     ```python
     template_data = {
         'cluster_id': report_data['cluster_id'],
         'contract': DictObject(report_data['contract']),  # Dot notation access
         'decision': DictObject(report_data['decision']),
         'explanation': report_data['explanation'],
         'metadata': DictObject(report_data['metadata']),
         'reason_descriptions': reason_descriptions or REASON_CODES,
         'map_specs': [DictObject(m) for m in resolved_map_specs],
         'violations_table': violations_table,
         'lcoh_chart_html': _render_lcoh_chart(report_data),
         'robustness_chart_html': _render_robustness_chart(report_data),
         'report_json_b64': base64.b64encode(json.dumps(report_data).encode()).decode(),
         'standards_refs': [EN_13941_1×3, VDE_AR_N_4100×2],  # Phase 5 checklist
     }
     ```

3. **Template Rendering**:
   - Render Jinja2 template with `template_data`
   - Return HTML string

**HTML Features**:
- **Bootstrap 5**: Responsive layout, modern UI
- **Plotly.js**: Interactive LCOH and robustness charts (CDN)
- **DataTables.js**: Sortable, filterable technical details table
- **Bootstrap Icons**: Icon library for visual elements
- **Glassmorphism**: Metric cards with backdrop blur
- **Interactive Maps**: Tabbed interface with loading states and error handling
- **Export Options**: JSON download, CSV download, print
- **Source Hints**: Hover tooltips showing contract JSON paths (auditability)
- **Standards Footer**: References to EN 13941-1 and VDE-AR-N 4100

**Returns**: HTML string

---

#### `_render_lcoh_chart()` ⭐ **LCOH CHART RENDERER**
```python
def _render_lcoh_chart(report_data: Dict[str, Any]) -> str
```

**Purpose**: Render interactive LCOH comparison using Plotly.js (CDN, no Python plotly dependency)

**Chart Features**:
- **Bar Chart**: District Heating vs. Heat Pumps
- **Error Bars**: 95% CI (asymmetric: p05-p50, p50-p95)
- **Highlighting**: Chosen option has thicker outline (3px vs 0px)
- **Hover Tooltips**: LCOH value, 95% CI range
- **Colors**: Green (#28a745) for DH, Red (#dc3545) for HP

**Returns**: HTML string with `<div>` and `<script>` for Plotly.js

---

#### `_render_robustness_chart()` ⭐ **ROBUSTNESS CHART RENDERER**
```python
def _render_robustness_chart(report_data: Dict[str, Any]) -> str
```

**Purpose**: Render Monte Carlo win fractions as animated Bootstrap progress bars

**Chart Features**:
- **Progress Bars**: Animated width transition (1.0s ease)
- **Two Bars**: District Heating (green) and Heat Pumps (red)
- **Percentages**: Win fractions displayed as percentages
- **Sample Count**: Monte Carlo sample count displayed
- **Animation**: JavaScript animates bars on page load

**Returns**: HTML string with Bootstrap progress bars and animation script

---

#### `render_markdown_report()` ⭐ **MARKDOWN REPORT RENDERER**
```python
def render_markdown_report(report_data: Dict[str, Any]) -> str
```

**Purpose**: Render Markdown report (simpler than HTML)

**Structure**:
1. **Header**: Cluster ID, generated timestamp
2. **Recommendation**: Choice, robust status
3. **Executive Summary**: Explanation text
4. **Key Metrics**:
   - District Heating: LCOH, CO₂, feasible, max velocity
   - Heat Pumps: LCOH, CO₂, feasible, max loading
5. **Decision Rationale**: Reason codes with descriptions
6. **Data Sources**: Source paths for each artifact type
7. **Standards Footer**: References to EN 13941-1 (×3) and VDE-AR-N 4100 (×2)

**Returns**: Markdown string

---

#### `save_reports()` ⭐ **REPORT SAVER**
```python
def save_reports(
    report_data: Dict[str, Any],
    out_dir: Path,
    include_html: bool = True,
    include_markdown: bool = True,
    include_json: bool = True,
    map_path: Optional[Path] = None,
    map_paths: Optional[Mapping[str, Path]] = None,
    map_specs: Optional[List[Dict[str, Any]]] = None,
    violations_csv_path: Optional[Path] = None,
) -> None
```

**Purpose**: Save all report formats to disk

**Workflow**:

1. **Create Output Directory**: `out_dir.mkdir(parents=True, exist_ok=True)`

2. **JSON Report** (if `include_json=True`):
   - Path: `out_dir / f'uhdc_report_{cluster_id}.json'`
   - Content: Complete `report_data` dictionary (indented JSON)

3. **Markdown Report** (if `include_markdown=True`):
   - Path: `out_dir / f'uhdc_explanation_{cluster_id}.md'`
   - Content: Rendered Markdown string

4. **HTML Report** (if `include_html=True`):
   - **Map Bundling**: If `map_specs` provided:
     - Create `_maps/` subdirectory
     - Copy each map HTML file to `_maps/{key}.html`
     - Update `map_specs` with relative paths (for browser file:// compatibility)
   - **Render HTML**: Call `render_html_report()` with bundled maps
   - **Save**: `out_dir / f'uhdc_report_{cluster_id}.html'`

**Map Bundling Rationale**:
- Chrome often blocks local iframes pointing outside the current directory tree
- Bundling maps into `_maps/` ensures all files are in the same directory tree
- Relative paths ensure maps work when HTML is opened from disk

---

#### `DictObject` ⭐ **DOT NOTATION DICT WRAPPER**
```python
class DictObject(dict):
    def __getattr__(self, key: str) -> Any
```

**Purpose**: Dictionary with dot notation access for Jinja2 templates

**Usage**: Wraps nested dictionaries to enable `contract.district_heating.lcoh.median` syntax in templates

**Returns**: Attribute value (recursively wraps nested dicts)

---

**Module-Level Constants**:
- `STANDARDS_REFERENCES`: Dictionary with EN 13941-1 and VDE-AR-N 4100 metadata (name, URL, description)
- `HTML_TEMPLATE`: Embedded Jinja2 HTML template (1,000+ lines)

---

**Interactions**:
- **Uses**: `jinja2`, `matplotlib`, `seaborn`, `pandas`, `base64`, `shutil`, `decision/schemas.py` (REASON_CODES)
- **Used by**: `orchestrator.py` (for saving reports), CLI (`cli/uhdc.py`)
- **Outputs**: HTML, Markdown, JSON report files

---

## Complete Workflow

### UHDC Pipeline

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. Artifact Discovery (orchestrator.py)                          │
│    - discover_artifact_paths(cluster_id, run_dir)                 │
│    - Search multiple patterns for each artifact type              │
│    - Cache results for performance                                │
│    Output: Dict[artifact_type, Optional[Path]]                   │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 2. Artifact Loading (io.py)                                      │
│    - load_cha_kpis(sources['cha_kpis'])                          │
│    - load_dha_kpis(sources['dha_kpis'])                           │
│    - load_econ_summary(sources['econ_summary'])                  │
│    Output: Individual KPI dictionaries                            │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 3. KPI Contract Building (decision/kpi_contract.py)              │
│    - build_kpi_contract(cha_kpis, dha_kpis, econ_summary)        │
│    - Validate and canonicalize KPIs                               │
│    Output: Validated KPI contract dictionary                      │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 4. Decision Making (decision/rules.py)                            │
│    - decide_from_contract(contract)                              │
│    - Apply deterministic decision rules                           │
│    Output: DecisionResult (choice, robust, reason_codes)          │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 5. Explanation Generation (explainer.py)                          │
│    - explain_with_llm(contract, decision, style) [if use_llm]     │
│      OR                                                           │
│    - _fallback_template_explanation(contract, decision, style)   │
│    - Safety validation (no hallucination)                         │
│    Output: Natural language explanation string                    │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 6. Report Compilation (orchestrator.py)                           │
│    - Compile report dictionary:                                   │
│      {cluster_id, contract, decision, explanation, sources, metadata}│
│    Output: Complete UHDC report dictionary                        │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 7. Report Rendering (report_builder.py)                           │
│    - render_html_report(report_data, map_specs, violations_csv)  │
│    - render_markdown_report(report_data)                          │
│    - Bundle interactive maps into _maps/ subdirectory            │
│    Output: HTML, Markdown, JSON files                             │
└─────────────────────────────────────────────────────────────────┘
```

---

## File Interactions & Dependencies

### Internal Dependencies (Within UHDC Module)

```
UHDC Module
├─ io.py (JSON LOADING)
│  └─ Used by: orchestrator.py (for loading artifacts)
│
├─ orchestrator.py (ORCHESTRATION)
│  ├─ Uses: io.py, explainer.py, report_builder.py
│  └─ Used by: CLI (cli/uhdc.py), direct Python calls
│
├─ explainer.py (EXPLANATION)
│  ├─ Uses: google-genai (optional), dotenv (optional)
│  └─ Used by: orchestrator.py (for explanation generation)
│
└─ report_builder.py (REPORT RENDERING)
   ├─ Uses: jinja2, matplotlib, seaborn, pandas
   └─ Used by: orchestrator.py (for saving reports)
```

### External Dependencies (Outside UHDC Module)

```
UHDC Module
  ├─ Uses:
  │  ├─ decision/kpi_contract.py → build_kpi_contract()
  │  ├─ decision/rules.py → decide_from_contract()
  │  ├─ decision/schemas.py → REASON_CODES
  │  ├─ config_paths.py → SEARCH_PATTERNS
  │  ├─ CHA KPIs: results/cha/<cluster_id>/cha_kpis.json
  │  ├─ DHA KPIs: results/dha/<cluster_id>/dha_kpis.json
  │  ├─ Economics Summary: results/economics/<cluster_id>/monte_carlo_summary.json
  │  ├─ Interactive Maps: results/cha/<cluster_id>/*.html, results/dha/<cluster_id>/*.html
  │  └─ Violations CSV: results/dha/<cluster_id>/violations.csv
  │
  ├─ Called by:
  │  ├─ CLI: cli/uhdc.py (main entry point)
  │  └─ Direct Python: build_uhdc_report() function
  │
  └─ Outputs:
     ├─ JSON Report: results/uhdc/<cluster_id>/uhdc_report_<cluster_id>.json
     ├─ HTML Report: results/uhdc/<cluster_id>/uhdc_report_<cluster_id>.html
     ├─ Markdown Report: results/uhdc/<cluster_id>/uhdc_explanation_<cluster_id>.md
     └─ Bundled Maps: results/uhdc/<cluster_id>/_maps/*.html
```

---

## Key Workflows & Patterns

### 1. Artifact Discovery Pattern (`discover_artifact_paths()`)

**Pattern**: Intelligent path discovery with multiple fallback patterns and caching

```python
# 1. Check cache
cache_key = (str(base_dir.resolve()), str(cluster_id))
if cache_key in _discovered_paths_cache:
    return _discovered_paths_cache[cache_key]

# 2. Search patterns
for artifact_type, patterns in SEARCH_PATTERNS.items():
    for pattern in patterns:
        path = base_dir / pattern.format(cluster_id=cluster_id)
        if path.exists():
            discovered[artifact_type] = path
            break  # First match wins

# 3. Cache results
_discovered_paths_cache[cache_key] = discovered
return discovered
```

**Benefits**:
- Multiple fallback patterns (handles different directory structures)
- Caching (avoids repeated filesystem checks)
- Logging (every attempt logged for debugging)

---

### 2. LLM Safety Pattern (`explain_with_llm()`)

**Pattern**: Constrained LLM generation with safety validation

```python
# 1. Build constrained prompt (only contract data)
prompt = _build_constrained_prompt(contract, decision, style)

# 2. Call LLM with deterministic settings
explanation = _call_llm(prompt, model)  # temperature=0.0

# 3. Validate output (no hallucination)
_validate_explanation_safety(explanation, contract, decision)

# 4. Fallback on failure
if validation_fails:
    explanation = _fallback_template_explanation(...)
```

**Benefits**:
- No hallucination (all numbers validated against contract)
- Deterministic (temperature=0.0)
- Safe fallback (template if LLM fails)

---

### 3. Template Fallback Pattern (`_fallback_template_explanation()`)

**Pattern**: Deterministic template-based explanations

```python
# 1. Defensive extraction (never crash)
dh = contract.get('district_heating') or {}
hp = contract.get('heat_pumps') or {}

# 2. Critical field check
if dh.get("feasible") is None:
    return _minimal_safe_template(...)

# 3. Style routing
if style == "executive":
    return _exec_template(dh, hp, decision, mc)
elif style == "technical":
    return _tech_template(dh, hp, decision, mc)
elif style == "detailed":
    return _detailed_template(dh, hp, decision, mc)
```

**Benefits**:
- Deterministic (same inputs → same output)
- Verifiable (all values from contract)
- Professional (consistent tone)

---

### 4. Map Bundling Pattern (`save_reports()`)

**Pattern**: Bundle interactive maps to avoid browser file:// restrictions

```python
# 1. Create bundle directory
bundle_dir = out_dir / "_maps"
bundle_dir.mkdir(parents=True, exist_ok=True)

# 2. Copy maps to bundle
for spec in map_specs:
    src = Path(spec["path"])
    dest = bundle_dir / f"{spec['key']}.html"
    shutil.copyfile(src, dest)
    
    # 3. Update spec with relative path
    spec["src"] = os.path.relpath(str(dest), start=str(out_dir))
```

**Benefits**:
- Browser compatibility (all files in same directory tree)
- Relative paths (works when HTML opened from disk)
- Clean organization (maps in `_maps/` subdirectory)

---

## Usage Examples

### Complete UHDC Report Generation

```python
from pathlib import Path
from branitz_heat_decision.uhdc.orchestrator import build_uhdc_report
from branitz_heat_decision.uhdc.report_builder import save_reports

# 1. Build report
report = build_uhdc_report(
    cluster_id="ST010_HEINRICH_ZILLE_STRASSE",
    run_dir=Path("results"),
    use_llm=True,  # Requires GOOGLE_API_KEY
    explanation_style="executive",
)

# 2. Discover maps
map_specs = [
    {
        "key": "cha-velocity",
        "label": "CHA — Velocity",
        "path": Path("results/cha/ST010/interactive_map.html"),
        "icon": "bi-wind",
        "spinner_class": "text-primary",
    },
    {
        "key": "dha-grid",
        "label": "DHA — LV Grid",
        "path": Path("results/dha/ST010/hp_lv_map.html"),
        "icon": "bi-lightning-charge",
        "spinner_class": "text-warning",
    },
]

# 3. Save reports
save_reports(
    report_data=report,
    out_dir=Path("results/uhdc/ST010"),
    include_html=True,
    include_markdown=True,
    include_json=True,
    map_specs=map_specs,
    violations_csv_path=Path("results/dha/ST010/violations.csv"),
)
```

### CLI Usage

```bash
# Basic usage (template explanation)
python -m branitz_heat_decision.uhdc.orchestrator \
    --cluster-id ST010_HEINRICH_ZILLE_STRASSE \
    --run-dir results \
    --out-dir results/uhdc/ST010 \
    --html \
    --md

# With LLM explanation
export GOOGLE_API_KEY="your_api_key_here"
python -m branitz_heat_decision.uhdc.orchestrator \
    --cluster-id ST010_HEINRICH_ZILLE_STRASSE \
    --run-dir results \
    --out-dir results/uhdc/ST010 \
    --llm \
    --style executive

# Fast path (use existing KPI contract)
python -m branitz_heat_decision.uhdc.orchestrator \
    --cluster-id ST010_HEINRICH_ZILLE_STRASSE \
    --run-dir results \
    --out-dir results/uhdc/ST010 \
    --contract-path results/decision/ST010/kpi_contract.json \
    --html
```

### Direct Explanation Generation

```python
from branitz_heat_decision.uhdc.explainer import explain_with_llm, _fallback_template_explanation

# LLM explanation (requires GOOGLE_API_KEY)
try:
    explanation = explain_with_llm(
        contract=contract_dict,
        decision=decision_dict,
        style="executive",
        model="gemini-2.0-flash",
    )
except Exception as e:
    # Fallback to template
    explanation = _fallback_template_explanation(
        contract=contract_dict,
        decision=decision_dict,
        style="executive",
    )

print(explanation)
```

---

## Error Handling & Validation

### Artifact Discovery

- **Missing Artifacts**: Logs error with all attempted paths, returns `None` for missing artifacts
- **Cache Errors**: Gracefully handles cache misses (re-discovers)

### LLM Explanation

- **API Key Missing**: Falls back to template (unless `no_fallback=True`)
- **LLM SDK Missing**: Falls back to template (unless `no_fallback=True`)
- **API Call Failure**: Falls back to template (unless `no_fallback=True`)
- **Safety Check Failure**: Falls back to template (unless `no_fallback=True`)
- **Critical Fields Missing**: Uses minimal safe template

### Report Rendering

- **Template Not Found**: Falls back to embedded template
- **Map File Missing**: Skips map (shows placeholder in HTML)
- **Violations CSV Missing**: Skips violations table (no error)

---

## Performance Considerations

### Artifact Discovery Caching

- **Cache Key**: `(base_dir.resolve(), cluster_id)` tuple
- **Cache Lifetime**: In-memory (cleared on `clear_discovery_cache()`)
- **Performance**: O(1) for cached lookups, O(N×M) for discovery (N=artifact types, M=patterns per type)

### LLM API Calls

- **Timeout**: `LLM_TIMEOUT` seconds (default: 30)
- **Retry**: No automatic retry (falls back to template on failure)
- **Rate Limiting**: Handled by Google API (429 errors fall back to template)

### Map Bundling

- **File Copy**: Uses `shutil.copyfile()` (fast for small HTML files)
- **Relative Paths**: `os.path.relpath()` for browser compatibility

---

## Standards Compliance

### Report Standards

- **EN 13941-1**: Referenced 3× in HTML/Markdown reports (Phase 5 checklist)
- **VDE-AR-N 4100**: Referenced 2× in HTML/Markdown reports (Phase 5 checklist)
- **Standards Footer**: All reports include standards references with URLs

### Auditability

- **Source Hints**: HTML reports include hover tooltips showing contract JSON paths
- **Metadata**: All reports include `metadata` with `timestamp`, `sources`, `uhdc_version`
- **JSON Export**: Complete report data available as JSON for programmatic access

---

## Environment Variables

### LLM Configuration

- **`GOOGLE_API_KEY`**: Google Gemini API key (required for LLM explanations)
- **`GOOGLE_MODEL`**: Gemini model name (default: `gemini-2.0-flash`)
- **`LLM_TIMEOUT`**: LLM API timeout in seconds (default: `30`)
- **`UHDC_FORCE_TEMPLATE`**: Force template mode, disable LLM (default: `false`)

### Logging Configuration

- **`UHDC_LOG_LEVEL`**: Logging level (default: `INFO`)

### Template Configuration

- **`UHDC_TEMPLATE_DIR`**: Custom template directory for HTML reports (default: `src/branitz_heat_decision/templates`)

---

## References & Standards

- **EN 13941-1:2023**: District heating pipes - Design and installation
- **VDE-AR-N 4100:2022**: Technical connection rules for low-voltage grids
- **Google Gemini API**: https://ai.google.dev/
- **Jinja2**: https://jinja.palletsprojects.com/
- **Plotly.js**: https://plotly.com/javascript/
- **Bootstrap 5**: https://getbootstrap.com/
- **DataTables.js**: https://datatables.net/

---

**Last Updated**: 2026-01-19  
**Module Version**: v1.1  
**Primary Maintainer**: UHDC Module Development Team

## Recent Updates (2026-01-19)

- **UI Integration**: Explanations now accessible via UI ResultService
- **Enhanced Report Builder**: Displays DHA violations table with sortable/filterable DataTables
- **Violations CSV Support**: Loads and displays detailed violations from `violations.csv`
