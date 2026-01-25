# CLI (Command-Line Interface) Module Documentation

Complete documentation for the CLI module implementing command-line interfaces for the Branitz Heat Decision pipeline phases (Decision, Economics, UHDC).

**Module Location**: `src/branitz_heat_decision/cli/`  
**Total Lines of Code**: ~801 lines  
**Primary Language**: Python 3.9+  
**Dependencies**: argparse, json, logging, pathlib, pandas (optional)

---

## Module Overview

The CLI (Command-Line Interface) module provides command-line access to the Branitz Heat Decision pipeline:

1. **Decision CLI** (`decision.py`): Generate KPI contracts, apply decision rules, and generate explanations
2. **Economics CLI** (`economics.py`): Run Monte Carlo economics analysis (LCOH, CO₂)
3. **UHDC CLI** (`uhdc.py`): Generate comprehensive UHDC reports (HTML/MD/JSON) from pipeline artifacts

### Architecture

The CLI module follows a modular architecture with separate entry points for each pipeline phase:

```
CLI Module
├─ decision.py → Decision Pipeline CLI
├─ economics.py → Economics Pipeline CLI
└─ uhdc.py → UHDC Report Generation CLI
```

Each CLI script:
- Parses command-line arguments (`argparse`)
- Discovers or accepts input file paths
- Orchestrates pipeline modules
- Writes outputs to specified directories
- Provides logging and error handling

---

## Module Files & Functions

### `__init__.py` (Empty)
**Purpose**: Module initialization (currently empty)  
**Usage**: Python package marker

---

### `decision.py` (373 lines) ⭐ **DECISION PIPELINE CLI**
**Purpose**: Command-line interface for the Decision pipeline (KPI contract → decision rules → explanation)

**Main Functions**:

#### `main()` ⭐ **PRIMARY ENTRY POINT**
```python
def main() -> None
```

**Workflow**:
1. **Parse Arguments**: Load CLI arguments (cluster ID, paths, config, LLM options)
2. **Configure Logging**: Set logging level from environment (`UHDC_LOG_LEVEL`)
3. **LLM Status Check**: Validate LLM availability if `--llm-explanation` is requested
4. **Mode Selection**:
   - **Single Cluster Mode**: Process one cluster
   - **Batch Mode** (`--all-clusters`): Process all clusters under `results/cha/`
5. **Path Discovery**: Auto-discover CHA/DHA/economics artifacts or use explicit paths
6. **KPI Contract Building**: Load CHA/DHA/economics KPIs → build KPI contract
7. **Contract Validation**: Validate contract schema (`ContractValidator`)
8. **Decision Rules**: Apply decision rules (`decide_from_contract`) with optional custom config
9. **Explanation Generation**: Generate explanation (LLM or template fallback)
10. **Output Generation**: Save contract, decision, explanation (JSON/MD/HTML)

**Helper Functions**:

#### `parse_args()` ⭐ **ARGUMENT PARSER**
```python
def parse_args() -> argparse.Namespace
```

**Arguments**:
- **Cluster Selection** (mutually exclusive):
  - `--cluster-id <ID>`: Single cluster identifier
  - `--all-clusters`: Process all clusters under `results/cha/`
- **Input Paths** (optional, auto-discovered if not provided):
  - `--cha-kpis` or `--cha-kpis-path <path>`: Path to CHA KPIs JSON
  - `--dha-kpis` or `--dha-kpis-path <path>`: Path to DHA KPIs JSON
  - `--econ-summary` or `--econ-summary-path <path>`: Path to economics summary JSON
- **Output**:
  - `--out-dir` or `--output-dir <dir>`: Output directory (default: `results/decision/<cluster_id>`)
- **Explanation Options**:
  - `--llm-explanation`: Generate LLM explanation (requires API key)
  - `--explanation-style <style>`: Style (`executive`, `technical`, `detailed`, default: `executive`)
  - `--no-fallback`: Fail if LLM unavailable/API fails/safety fails (no template fallback)
- **Format Options**:
  - `--format <format>`: Output format (`json`, `md`, `html`, `all`, default: `all`)
- **Configuration**:
  - `--config <path>`: Custom decision config JSON file

#### `load_json()` ⭐ **JSON LOADER**
```python
def load_json(path: str) -> Dict[str, Any]
```
Load JSON file with error handling.

#### `save_json()` ⭐ **JSON SAVER**
```python
def save_json(data: Dict[str, Any], path: Path) -> None
```
Save JSON file with parent directory creation and confirmation message.

#### `_discover_paths_for_cluster()` ⭐ **PATH DISCOVERY**
```python
def _discover_paths_for_cluster(cluster_id: str) -> Tuple[Path, Path, Path]
```

**Purpose**: Auto-discover CHA/DHA/economics artifact paths for a cluster

**Discovery Pattern**:
```
results/
├─ cha/<cluster_id>/cha_kpis.json
├─ dha/<cluster_id>/dha_kpis.json
└─ economics/<cluster_id>/monte_carlo_summary.json
```

**Returns**: `(cha_path, dha_path, econ_path)`

#### `_list_clusters()` ⭐ **CLUSTER LISTER**
```python
def _list_clusters() -> List[str]
```

**Purpose**: List all clusters available under `results/cha/`

**Returns**: Sorted list of cluster IDs (directory names)

#### `_write_explanation_outputs()` ⭐ **EXPLANATION EXPORTER**
```python
def _write_explanation_outputs(
    out_dir: Path,
    cluster_id: str,
    contract: Dict[str, Any],
    decision: Dict[str, Any],
    explanation: str,
    fmt: str,
) -> None
```

**Purpose**: Write explanation outputs in requested format(s)

**Outputs**:
- **Markdown** (`--format md` or `all`): `explanation_<cluster_id>.md`
- **HTML** (`--format html` or `all`): `explanation_<cluster_id>.html`
- **JSON**: Not written (explanation is text, not structured)

#### `_configure_logging_from_env()` ⭐ **LOGGING CONFIGURATION**
```python
def _configure_logging_from_env() -> None
```

**Purpose**: Configure logging level from environment variable

**Environment Variable**: `UHDC_LOG_LEVEL` (default: `INFO`)

**Usage**:
```bash
export UHDC_LOG_LEVEL=DEBUG
python -m branitz_heat_decision.cli.decision --cluster-id ST010
```

**Interactions**:
- **Imports**: `decision.kpi_contract.build_kpi_contract()`, `decision.rules.decide_from_contract()`, `uhdc.explainer.explain_with_llm()`, `uhdc.report_builder.render_html_report()`
- **Uses**: CHA/DHA/economics KPI files, decision config JSON (optional)
- **Outputs**: `kpi_contract_<cluster_id>.json`, `decision_<cluster_id>.json`, `explanation_<cluster_id>.md/html`

**Example Usage**:
```bash
# Single cluster, auto-discover paths
python -m branitz_heat_decision.cli.decision --cluster-id ST010_HEINRICH_ZILLE_STRASSE

# Single cluster with explicit paths
python -m branitz_heat_decision.cli.decision \
  --cluster-id ST010_HEINRICH_ZILLE_STRASSE \
  --cha-kpis results/cha/ST010_HEINRICH_ZILLE_STRASSE/cha_kpis.json \
  --dha-kpis results/dha/ST010_HEINRICH_ZILLE_STRASSE/dha_kpis.json \
  --econ-summary results/economics/ST010_HEINRICH_ZILLE_STRASSE/monte_carlo_summary.json

# LLM explanation (fail hard if unavailable)
python -m branitz_heat_decision.cli.decision \
  --cluster-id ST010_HEINRICH_ZILLE_STRASSE \
  --llm-explanation \
  --no-fallback

# Batch mode for all clusters
python -m branitz_heat_decision.cli.decision \
  --all-clusters \
  --output-dir results/decision_all \
  --format json

# Custom decision config
python -m branitz_heat_decision.cli.decision \
  --cluster-id ST010_HEINRICH_ZILLE_STRASSE \
  --config config/decision_config_2030.json
```

**Batch Mode Features**:
- Processes all clusters under `results/cha/`
- Writes `summary.csv` with columns: `[cluster_id, choice, robust, lcoh_dh, lcoh_hp]`
- Skips clusters with missing prerequisites
- Continues on errors (unless `--no-fallback`)

---

### `economics.py` (318 lines) ⭐ **ECONOMICS PIPELINE CLI**
**Purpose**: Command-line interface for Economics analysis (Monte Carlo LCOH/CO₂)

**Main Functions**:

#### `main()` ⭐ **PRIMARY ENTRY POINT**
```python
def main() -> None
```

**Workflow**:
1. **Parse Arguments**: Load CLI arguments (cluster ID, paths, Monte Carlo parameters)
2. **Configure Logging**: Set logging level (quiet/debug/info)
3. **Validate Inputs**: Check all input files exist
4. **Run Economics Pipeline**: Call `run_economics_for_cluster()`
5. **Print Summary**: Display results summary (unless `--quiet`)

#### `run_economics_for_cluster()` ⭐ **ECONOMICS PIPELINE ORCHESTRATOR**
```python
def run_economics_for_cluster(
    cluster_id: str,
    cha_kpis_path: Path,
    dha_kpis_path: Path,
    cluster_summary_path: Path,
    output_dir: Path,
    n_samples: int = 500,
    seed: int = 42,
    scenario_file: Optional[Path] = None,
    randomness_config_file: Optional[Path] = None,
    quiet: bool = False,
    n_jobs: int = 1,
) -> dict
```

**Workflow**:
1. **Load Parameters**:
   - Load economic scenario from YAML (if `--scenario`) or use defaults
   - Load randomness config from JSON (if `--randomness-config`) or use defaults
2. **Load Inputs**:
   - Load CHA KPIs (`cha_kpis.json`)
   - Load DHA KPIs (`dha_kpis.json`)
   - Load cluster summary (`cluster_load_summary.parquet` or fallback to profiles)
3. **Run Monte Carlo**:
   - Call `run_monte_carlo_for_cluster()` with N samples
   - Propagate uncertainty through LCOH/CO₂ calculations
4. **Compute Summary Stats**:
   - Call `compute_mc_summary()` to compute quantiles, means, win fractions
5. **Save Outputs**:
   - Save raw samples: `monte_carlo_samples.parquet`
   - Save summary JSON: `monte_carlo_summary.json` (with metadata)
6. **Decision Insight**:
   - Classify robustness: `robust_dh`, `robust_hp`, `sensitive`, `inconclusive`
   - Based on win fractions: `>70%` = robust, `>55%` = sensitive, else inconclusive

**Helper Functions**:

#### `_compute_cluster_summary_fallback()` ⭐ **FALLBACK SUMMARY**
```python
def _compute_cluster_summary_fallback(cluster_id: str) -> Dict[str, float]
```

**Purpose**: Compute cluster summary from processed profiles when `cluster_load_summary.parquet` doesn't contain the cluster

**Fallback Logic**:
- **Annual Heat**: Sum hourly profiles for cluster buildings (`kWh`) → convert to `MWh`
- **Design Load**: Extract peak load at design hour (`kW`)

**Returns**: `{"annual_heat_mwh": float, "design_load_kw": float}`

#### `_print_summary()` ⭐ **SUMMARY PRINTER**
```python
def _print_summary(cluster_id: str, summary: dict) -> None
```

**Purpose**: Print formatted summary to console

**Summary Sections**:
- **Levelized Cost of Heat**: DH and HP LCOH (EUR/MWh) with 95% CI
- **CO₂ Emissions**: DH and HP CO₂ (kg/MWh) with 95% CI
- **Monte Carlo Robustness**: Win fractions (cost and CO₂)
- **Valid Samples**: Count and percentage

**Interactions**:
- **Imports**: `economics.params.EconomicParameters`, `economics.monte_carlo.run_monte_carlo_for_cluster()`, `economics.monte_carlo.compute_mc_summary()`, `config.BUILDING_CLUSTER_MAP_PATH`, `config.HOURLY_PROFILES_PATH`, `config.DESIGN_TOPN_PATH`
- **Uses**: CHA/DHA KPI files, cluster summary parquet, scenario YAML (optional), randomness config JSON (optional)
- **Outputs**: `monte_carlo_samples.parquet`, `monte_carlo_summary.json`

**Example Usage**:
```bash
# Basic economics analysis (defaults: 500 samples, seed=42)
python -m branitz_heat_decision.cli.economics \
  --cluster-id ST010_HEINRICH_ZILLE_STRASSE \
  --cha-kpis results/cha/ST010_HEINRICH_ZILLE_STRASSE/cha_kpis.json \
  --dha-kpis results/dha/ST010_HEINRICH_ZILLE_STRASSE/dha_kpis.json \
  --cluster-summary data/processed/cluster_load_summary.parquet \
  --out results/economics/ST010_HEINRICH_ZILLE_STRASSE

# Custom Monte Carlo parameters
python -m branitz_heat_decision.cli.economics \
  --cluster-id ST010_HEINRICH_ZILLE_STRASSE \
  --cha-kpis results/cha/ST010/cha_kpis.json \
  --dha-kpis results/dha/ST010/dha_kpis.json \
  --cluster-summary data/processed/cluster_load_summary.parquet \
  --out results/economics/ST010 \
  --n-samples 1000 \
  --seed 12345 \
  --n-jobs -1  # Use all CPU cores

# Custom economic scenario
python -m branitz_heat_decision.cli.economics \
  --cluster-id ST010_HEINRICH_ZILLE_STRASSE \
  --cha-kpis results/cha/ST010/cha_kpis.json \
  --dha-kpis results/dha/ST010/dha_kpis.json \
  --cluster-summary data/processed/cluster_load_summary.parquet \
  --out results/economics/ST010 \
  --scenario scripts/scenarios/2030_scenario.yaml \
  --randomness-config scripts/scenarios/uncertainty_config.json

# Quiet mode (suppress summary output)
python -m branitz_heat_decision.cli.economics \
  --cluster-id ST010_HEINRICH_ZILLE_STRASSE \
  --cha-kpis results/cha/ST010/cha_kpis.json \
  --dha-kpis results/dha/ST010/dha_kpis.json \
  --cluster-summary data/processed/cluster_load_summary.parquet \
  --out results/economics/ST010 \
  --quiet
```

---

### `uhdc.py` (112 lines) ⭐ **UHDC REPORT CLI**
**Purpose**: Command-line interface for UHDC (Unified Heat Decision Communication) report generation

**Main Functions**:

#### `main()` ⭐ **PRIMARY ENTRY POINT**
```python
def main() -> None
```

**Workflow**:
1. **Parse Arguments**: Load CLI arguments (cluster ID, run directory, output directory, format, LLM options)
2. **Configure Logging**: Set logging level from environment (`UHDC_LOG_LEVEL`)
3. **Mode Selection**:
   - **Single Cluster Mode**: Generate report for one cluster
   - **Batch Mode** (`--all-clusters`): Generate reports for all clusters under `results/cha/`
4. **Report Building**: Call `build_uhdc_report()` to discover and load artifacts
5. **Map Discovery**: Discover CHA (3) and DHA (1) interactive maps
6. **Violations CSV Discovery**: Discover DHA violations CSV (if available)
7. **Report Export**: Save reports in requested format(s) (HTML/MD/JSON)

#### `_discover_map_specs()` ⭐ **MAP DISCOVERY**
```python
def _discover_map_specs(cluster_id: str, out_dir: Path) -> List[Dict[str, Any]]
```

**Purpose**: Discover CHA and DHA interactive maps for a cluster

**CHA Maps** (3):
- `interactive_map.html` → Velocity map (`cha-velocity`)
- `interactive_map_temperature.html` → Temperature map (`cha-temperature`)
- `interactive_map_pressure.html` → Pressure map (`cha-pressure`)

**DHA Map** (1):
- `hp_lv_map.html` → LV grid map (`dha-grid`)

**Returns**: List of map specs with `{key, label, path, icon, spinner_class}`

#### `_discover_violations_csv()` ⭐ **VIOLATIONS CSV DISCOVERY**
```python
def _discover_violations_csv(cluster_id: str) -> Optional[Path]
```

**Purpose**: Discover DHA violations CSV

**Path**: `results/dha/<cluster_id>/violations.csv`

**Returns**: Path if exists, `None` otherwise

#### `_configure_logging_from_env()` ⭐ **LOGGING CONFIGURATION**
```python
def _configure_logging_from_env() -> None
```

**Purpose**: Configure logging level from environment variable

**Environment Variable**: `UHDC_LOG_LEVEL` (default: `INFO`)

**Interactions**:
- **Imports**: `uhdc.orchestrator.build_uhdc_report()`, `uhdc.report_builder.save_reports()`
- **Uses**: Artifacts from `run_dir/` (CHA/DHA/economics/decision), interactive maps, violations CSV
- **Outputs**: `report_<cluster_id>.html/md/json` in `out_dir/`

**Example Usage**:
```bash
# Single cluster, all formats
python -m branitz_heat_decision.cli.uhdc \
  --cluster-id ST010_HEINRICH_ZILLE_STRASSE \
  --out-dir results/decision/ST010_HEINRICH_ZILLE_STRASSE/report

# Single cluster, HTML only
python -m branitz_heat_decision.cli.uhdc \
  --cluster-id ST010_HEINRICH_ZILLE_STRASSE \
  --out-dir results/decision/ST010/report \
  --format html

# Batch mode for all clusters
python -m branitz_heat_decision.cli.uhdc \
  --all-clusters \
  --out-dir results/decision_all/reports \
  --format html

# Custom run directory
python -m branitz_heat_decision.cli.uhdc \
  --cluster-id ST010_HEINRICH_ZILLE_STRASSE \
  --run-dir custom_results \
  --out-dir results/decision/ST010/report

# LLM explanation (if available)
python -m branitz_heat_decision.cli.uhdc \
  --cluster-id ST010_HEINRICH_ZILLE_STRASSE \
  --out-dir results/decision/ST010/report \
  --llm \
  --style executive
```

**Batch Mode Features**:
- Processes all clusters under `results/cha/` (or `--run-dir/cha/`)
- Generates reports for each cluster in `out_dir/<cluster_id>/`
- Continues on errors (does not fail entire batch)

---

## Complete Workflow

### End-to-End Pipeline CLI Execution

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. DATA PREPARATION (scripts/00_prepare_data.py)                │
│    - Prepare buildings, streets, clusters, profiles              │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 2. CHA PIPELINE (scripts/01_run_cha.py)                         │
│    - Build district heating network                              │
│    - Run simulation                                              │
│    - Extract KPIs                                                │
│    - Generate maps                                               │
│    Output: results/cha/<cluster_id>/cha_kpis.json               │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 3. DHA PIPELINE (scripts/02_run_dha.py)                         │
│    - Build LV grid                                               │
│    - Map buildings to buses                                      │
│    - Assign HP loads                                             │
│    - Run powerflows                                              │
│    - Extract KPIs                                                │
│    Output: results/dha/<cluster_id>/dha_kpis.json               │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 4. ECONOMICS PIPELINE (cli/economics.py)                        │
│    python -m branitz_heat_decision.cli.economics \              │
│      --cluster-id ST010 \                                       │
│      --cha-kpis results/cha/ST010/cha_kpis.json \               │
│      --dha-kpis results/dha/ST010/dha_kpis.json \               │
│      --cluster-summary data/processed/cluster_load_summary.parquet \│
│      --out results/economics/ST010                              │
│    Output: results/economics/<cluster_id>/monte_carlo_summary.json│
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 5. DECISION PIPELINE (cli/decision.py)                          │
│    python -m branitz_heat_decision.cli.decision \               │
│      --cluster-id ST010 \                                       │
│      --llm-explanation \                                        │
│      --format all                                               │
│    Output: results/decision/<cluster_id>/                       │
│      - kpi_contract_<cluster_id>.json                           │
│      - decision_<cluster_id>.json                               │
│      - explanation_<cluster_id>.md/html                         │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 6. UHDC REPORT (cli/uhdc.py)                                    │
│    python -m branitz_heat_decision.cli.uhdc \                   │
│      --cluster-id ST010 \                                       │
│      --out-dir results/decision/ST010/report \                  │
│      --format html                                              │
│    Output: results/decision/<cluster_id>/report/                │
│      - report_<cluster_id>.html/md/json                         │
└─────────────────────────────────────────────────────────────────┘
```

---

## File Interactions & Dependencies

### Internal Dependencies (Within CLI Module)

```
CLI Module
├─ decision.py (DECISION PIPELINE CLI)
│  ├─ imports: decision.kpi_contract.build_kpi_contract()
│  ├─ imports: decision.rules.decide_from_contract(), validate_config()
│  ├─ imports: uhdc.explainer.explain_with_llm(), _fallback_template_explanation()
│  └─ imports: uhdc.report_builder.render_html_report(), render_markdown_report()
│
├─ economics.py (ECONOMICS PIPELINE CLI)
│  ├─ imports: economics.params.EconomicParameters, load_params_from_yaml()
│  ├─ imports: economics.monte_carlo.run_monte_carlo_for_cluster(), compute_mc_summary()
│  └─ imports: config.BUILDING_CLUSTER_MAP_PATH, HOURLY_PROFILES_PATH, DESIGN_TOPN_PATH
│
└─ uhdc.py (UHDC REPORT CLI)
   ├─ imports: uhdc.orchestrator.build_uhdc_report()
   └─ imports: uhdc.report_builder.save_reports()
```

### External Dependencies (Outside CLI Module)

```
CLI Module
  ├─ uses argparse (command-line parsing)
  ├─ uses pathlib (path handling)
  ├─ uses logging (logging configuration)
  └─ uses pandas (optional, for economics)

Called by:
  └─ User via command line: python -m branitz_heat_decision.cli.<script>

Inputs from other modules:
  ├─ CHA KPIs: results/cha/<cluster_id>/cha_kpis.json
  ├─ DHA KPIs: results/dha/<cluster_id>/dha_kpis.json
  ├─ Economics summary: results/economics/<cluster_id>/monte_carlo_summary.json
  ├─ Cluster summary: data/processed/cluster_load_summary.parquet
  ├─ Decision config: config/decision_config_*.json (optional)
  └─ Scenario files: scripts/scenarios/*.yaml (optional)

Outputs to other modules:
  ├─ Decision outputs: results/decision/<cluster_id>/
  ├─ Economics outputs: results/economics/<cluster_id>/
  └─ UHDC reports: results/decision/<cluster_id>/report/
```

---

## Key Workflows & Patterns

### 1. Path Discovery Pattern (`_discover_paths_for_cluster()`)

**Pattern**: Auto-discover artifact paths with explicit path override

```python
# Auto-discovery pattern
cha_path, dha_path, econ_path = _discover_paths_for_cluster(cluster_id)

# Override with explicit paths if provided
if args.cha_kpis:
    cha_path = Path(args.cha_kpis)
if args.dha_kpis:
    dha_path = Path(args.dha_kpis)
if args.econ_summary:
    econ_path = Path(args.econ_summary)

# Validate existence
if not (cha_path.exists() and dha_path.exists() and econ_path.exists()):
    raise FileNotFoundError("Missing prerequisite artifacts")
```

**Benefits**:
- User-friendly: Works without explicit paths
- Flexible: Allows explicit path override
- Robust: Validates existence before processing

---

### 2. Batch Processing Pattern (`--all-clusters`)

**Pattern**: Process multiple clusters with error handling

```python
if args.all_clusters:
    clusters = _list_clusters()  # Discover from results/cha/
    for cluster_id in clusters:
        try:
            # Process cluster
            process_cluster(cluster_id, args)
        except Exception as e:
            if args.no_fallback:
                raise  # Fail hard
            print(f"✗ Failed on {cluster_id}: {e}", file=sys.stderr)
            continue  # Continue with next cluster
    
    # Generate summary
    write_summary_csv(clusters, results)
```

**Benefits**:
- Automated batch processing
- Error resilience (continues on errors)
- Summary generation for all clusters

---

### 3. LLM Integration Pattern (`--llm-explanation`)

**Pattern**: LLM explanation with fallback handling

```python
if args.llm_explanation:
    if not LLM_AVAILABLE:
        if args.no_fallback:
            raise RuntimeError("LLM unavailable and --no-fallback specified")
        print("⚠️  Warning: LLM unavailable, using template fallback")
        explanation = _fallback_template_explanation(...)
    else:
        try:
            explanation = explain_with_llm(...)
        except Exception as e:
            if args.no_fallback:
                raise
            print(f"! LLM explanation failed: {e}, using template fallback")
            explanation = _fallback_template_explanation(...)
else:
    explanation = _fallback_template_explanation(...)
```

**Benefits**:
- Graceful degradation (template fallback)
- Explicit failure mode (`--no-fallback`)
- User feedback (warnings/errors)

---

### 4. Configuration Loading Pattern (`--config`)

**Pattern**: Load custom config with validation

```python
config = None
if args.config:
    config = load_json(args.config)
    print(f"Loaded custom decision config: {args.config}")
    config = validate_config(config)  # Validate schema

# Use config in decision rules
decision_result = decide_from_contract(contract, config)
```

**Benefits**:
- Customizable decision rules
- Schema validation (catches errors early)
- Backward compatible (defaults if not provided)

---

### 5. Logging Configuration Pattern (`_configure_logging_from_env()`)

**Pattern**: Environment-based logging configuration

```python
def _configure_logging_from_env() -> None:
    level = os.getenv("UHDC_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(level=getattr(logging, level, logging.INFO))
```

**Usage**:
```bash
export UHDC_LOG_LEVEL=DEBUG
python -m branitz_heat_decision.cli.decision --cluster-id ST010
```

**Benefits**:
- Environment-based configuration
- No code changes needed
- Consistent across CLI scripts

---

## Command-Line Arguments Reference

### `decision.py` Arguments

#### Cluster Selection (Required, Mutually Exclusive)
| Argument | Description |
|----------|-------------|
| `--cluster-id <ID>` | Single cluster identifier (e.g., `ST010_HEINRICH_ZILLE_STRASSE`) |
| `--all-clusters` | Process all clusters under `results/cha/` |

#### Input Paths (Optional, Auto-Discovered)
| Argument | Description |
|----------|-------------|
| `--cha-kpis <path>` or `--cha-kpis-path <path>` | Path to CHA KPIs JSON |
| `--dha-kpis <path>` or `--dha-kpis-path <path>` | Path to DHA KPIs JSON |
| `--econ-summary <path>` or `--econ-summary-path <path>` | Path to economics summary JSON |

#### Output Options
| Argument | Description |
|----------|-------------|
| `--out-dir <dir>` or `--output-dir <dir>` | Output directory (default: `results/decision/<cluster_id>`) |
| `--format <format>` | Output format: `json`, `md`, `html`, `all` (default: `all`) |

#### Explanation Options
| Argument | Description |
|----------|-------------|
| `--llm-explanation` | Generate LLM explanation (requires API key) |
| `--explanation-style <style>` | Style: `executive`, `technical`, `detailed` (default: `executive`) |
| `--no-fallback` | Fail if LLM unavailable/API fails/safety fails (no template fallback) |

#### Configuration
| Argument | Description |
|----------|-------------|
| `--config <path>` | Custom decision config JSON file |

---

### `economics.py` Arguments

#### Required Arguments
| Argument | Description |
|----------|-------------|
| `--cluster-id <ID>` | Cluster identifier (e.g., `ST010_HEINRICH_ZILLE_STRASSE`) |
| `--cha-kpis <path>` | Path to CHA KPIs JSON |
| `--dha-kpis <path>` | Path to DHA KPIs JSON |
| `--cluster-summary <path>` | Path to cluster summary parquet |
| `--out <dir>` | Output directory for results |

#### Monte Carlo Parameters
| Argument | Description | Default |
|----------|-------------|---------|
| `--n-samples <N>` | Number of Monte Carlo samples | 500 |
| `--seed <seed>` | Random seed for reproducibility | 42 |
| `--n-jobs <N>` | Parallel jobs (`-1` = all cores) | 1 |

#### Configuration (Optional)
| Argument | Description |
|----------|-------------|
| `--scenario <path>` | YAML file with economic scenario parameters |
| `--randomness-config <path>` | JSON file with parameter distribution specifications |

#### Logging Options
| Argument | Description |
|----------|-------------|
| `--quiet` | Suppress detailed logging and summary output |
| `--debug` | Enable debug logging |

---

### `uhdc.py` Arguments

#### Cluster Selection (Required, Mutually Exclusive)
| Argument | Description |
|----------|-------------|
| `--cluster-id <ID>` | Single cluster identifier |
| `--all-clusters` | Generate reports for all clusters under `results/cha/` |

#### Directory Options
| Argument | Description | Default |
|----------|-------------|---------|
| `--run-dir <dir>` | Base results directory | `results` |
| `--out-dir <dir>` | Output directory for report files | **Required** |

#### Format Options
| Argument | Description | Default |
|----------|-------------|---------|
| `--format <format>` | Output format: `html`, `md`, `json`, `all` | `all` |

#### Explanation Options
| Argument | Description |
|----------|-------------|
| `--llm` | Use LLM explanation (if available); else template fallback |
| `--style <style>` | Explanation style: `executive`, `technical`, `detailed` | `executive` |

---

## Integration with Other Modules

### CLI → Decision Pipeline

```
decision.py CLI
    ↓
decision.kpi_contract.build_kpi_contract()
    ↓
decision.rules.decide_from_contract()
    ↓
uhdc.explainer.explain_with_llm() or _fallback_template_explanation()
    ↓
uhdc.report_builder.render_html_report() or render_markdown_report()
```

### CLI → Economics Pipeline

```
economics.py CLI
    ↓
economics.params.load_params_from_yaml() or EconomicParameters()
    ↓
economics.monte_carlo.run_monte_carlo_for_cluster()
    ↓
economics.monte_carlo.compute_mc_summary()
```

### CLI → UHDC Pipeline

```
uhdc.py CLI
    ↓
uhdc.orchestrator.build_uhdc_report()
    ↓
uhdc.report_builder.save_reports()
```

---

## Usage Examples

### Complete Pipeline Execution (Single Cluster)

```bash
# 1. Data Preparation
python -m src.scripts.00_prepare_data

# 2. CHA Pipeline
python -m src.scripts.01_run_cha --cluster-id ST010_HEINRICH_ZILLE_STRASSE

# 3. DHA Pipeline
python -m src.scripts.02_run_dha --cluster-id ST010_HEINRICH_ZILLE_STRASSE

# 4. Economics Pipeline
python -m branitz_heat_decision.cli.economics \
  --cluster-id ST010_HEINRICH_ZILLE_STRASSE \
  --cha-kpis results/cha/ST010_HEINRICH_ZILLE_STRASSE/cha_kpis.json \
  --dha-kpis results/dha/ST010_HEINRICH_ZILLE_STRASSE/dha_kpis.json \
  --cluster-summary data/processed/cluster_load_summary.parquet \
  --out results/economics/ST010_HEINRICH_ZILLE_STRASSE

# 5. Decision Pipeline
python -m branitz_heat_decision.cli.decision \
  --cluster-id ST010_HEINRICH_ZILLE_STRASSE \
  --llm-explanation \
  --format all

# 6. UHDC Report
python -m branitz_heat_decision.cli.uhdc \
  --cluster-id ST010_HEINRICH_ZILLE_STRASSE \
  --out-dir results/decision/ST010_HEINRICH_ZILLE_STRASSE/report \
  --format html
```

### Batch Processing (All Clusters)

```bash
# Decision for all clusters
python -m branitz_heat_decision.cli.decision \
  --all-clusters \
  --output-dir results/decision_all \
  --format json

# UHDC reports for all clusters
python -m branitz_heat_decision.cli.uhdc \
  --all-clusters \
  --out-dir results/decision_all/reports \
  --format html
```

### Custom Configuration

```bash
# Custom decision config
python -m branitz_heat_decision.cli.decision \
  --cluster-id ST010_HEINRICH_ZILLE_STRASSE \
  --config config/decision_config_2030.json

# Custom economic scenario
python -m branitz_heat_decision.cli.economics \
  --cluster-id ST010_HEINRICH_ZILLE_STRASSE \
  --cha-kpis results/cha/ST010/cha_kpis.json \
  --dha-kpis results/dha/ST010/dha_kpis.json \
  --cluster-summary data/processed/cluster_load_summary.parquet \
  --out results/economics/ST010 \
  --scenario scripts/scenarios/2030_scenario.yaml \
  --randomness-config scripts/scenarios/uncertainty_config.json
```

### LLM Explanation (With Fallback)

```bash
# LLM explanation with fallback (default)
python -m branitz_heat_decision.cli.decision \
  --cluster-id ST010_HEINRICH_ZILLE_STRASSE \
  --llm-explanation

# LLM explanation without fallback (fail hard)
python -m branitz_heat_decision.cli.decision \
  --cluster-id ST010_HEINRICH_ZILLE_STRASSE \
  --llm-explanation \
  --no-fallback
```

---

## Error Handling & Validation

### Input Validation

#### Path Validation
```python
# Check file existence before processing
if not (cha_path.exists() and dha_path.exists() and econ_path.exists()):
    raise FileNotFoundError(f"Missing prerequisite artifacts for {cluster_id}")
```

#### JSON Validation
```python
# Validate JSON structure
contract = build_kpi_contract(...)
ContractValidator.validate(contract)  # Raises on invalid schema
```

#### Config Validation
```python
# Validate custom config
if args.config:
    config = load_json(args.config)
    config = validate_config(config)  # Raises on invalid config
```

### Error Handling Patterns

#### Graceful Degradation
```python
# LLM fallback
try:
    explanation = explain_with_llm(...)
except Exception as e:
    if args.no_fallback:
        raise
    explanation = _fallback_template_explanation(...)
    print(f"! LLM explanation failed, used template fallback ({e})")
```

#### Cluster Fallback
```python
# Cluster summary fallback
rows = summary_df[summary_df["cluster_id"] == cluster_id]
if len(rows) == 0:
    logger.warning(f"Cluster {cluster_id} not found, falling back to computed summary")
    row = _compute_cluster_summary_fallback(cluster_id)
```

#### Batch Error Resilience
```python
# Continue on errors in batch mode
for cluster_id in clusters:
    try:
        process_cluster(cluster_id, args)
    except Exception as e:
        print(f"✗ Failed on {cluster_id}: {e}", file=sys.stderr)
        if args.no_fallback:
            raise
        continue  # Continue with next cluster
```

---

## Environment Variables

### Logging Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `UHDC_LOG_LEVEL` | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

**Usage**:
```bash
export UHDC_LOG_LEVEL=DEBUG
python -m branitz_heat_decision.cli.decision --cluster-id ST010
```

### LLM Configuration

| Variable | Description | Source |
|----------|-------------|--------|
| `GOOGLE_API_KEY` | Google Gemini API key | `.env` file (loaded by `uhdc.explainer`) |
| `GOOGLE_MODEL` | LLM model name | `.env` file (default: `gemini-2.0-flash`) |
| `LLM_TIMEOUT` | LLM API timeout (seconds) | `.env` file (default: 30) |
| `UHDC_FORCE_TEMPLATE` | Force template mode (skip LLM) | `.env` file (default: `false`) |

**Usage**:
```bash
# Create .env file
echo 'GOOGLE_API_KEY=your_key_here' > .env
echo 'GOOGLE_MODEL=gemini-2.0-flash' >> .env
echo 'LLM_TIMEOUT=30' >> .env

# Use LLM explanations
python -m branitz_heat_decision.cli.decision --cluster-id ST010 --llm-explanation
```

---

## Output File Formats

### Decision Pipeline Outputs

#### `kpi_contract_<cluster_id>.json`
**Format**: JSON  
**Structure**: KPI contract with CHA/DHA/economics blocks

```json
{
  "cluster_id": "ST010_HEINRICH_ZILLE_STRASSE",
  "metadata": {...},
  "district_heating": {
    "hydraulics": {...},
    "losses": {...},
    "pump": {...},
    "feasible": true,
    ...
  },
  "heat_pumps": {
    "lv_grid": {...},
    "feasible": true,
    ...
  },
  "economics": {
    "lcoh": {...},
    "co2": {...},
    "monte_carlo": {...},
    ...
  }
}
```

#### `decision_<cluster_id>.json`
**Format**: JSON  
**Structure**: Decision result with choice, reasons, metrics

```json
{
  "cluster_id": "ST010_HEINRICH_ZILLE_STRASSE",
  "choice": "DH",
  "robust": true,
  "reason_codes": ["DH_OK", "DH_COST_ADVANTAGE"],
  "metrics_used": {
    "lcoh_dh_median": 45.2,
    "lcoh_hp_median": 52.8,
    ...
  },
  "confidence": "high",
  ...
}
```

#### `explanation_<cluster_id>.md`
**Format**: Markdown  
**Structure**: Natural language explanation in Markdown format

#### `explanation_<cluster_id>.html`
**Format**: HTML  
**Structure**: HTML report with embedded maps, charts, and interactive features

---

### Economics Pipeline Outputs

#### `monte_carlo_samples.parquet`
**Format**: Parquet  
**Structure**: DataFrame with N samples (rows) and metrics (columns)

**Columns**: `lcoh_dh`, `lcoh_hp`, `co2_dh`, `co2_hp`, `dh_wins_cost`, `hp_wins_cost`, `dh_wins_co2`, `hp_wins_co2`, ...

#### `monte_carlo_summary.json`
**Format**: JSON  
**Structure**: Summary statistics with metadata

```json
{
  "lcoh": {
    "dh": {"p05": 42.1, "p50": 45.2, "p95": 48.5, "mean": 45.3, "std": 1.8},
    "hp": {"p05": 49.2, "p50": 52.8, "p95": 56.5, "mean": 52.9, "std": 2.1}
  },
  "co2": {...},
  "monte_carlo": {
    "n_samples": 500,
    "n_valid": 498,
    "dh_wins_fraction": 0.85,
    "hp_wins_fraction": 0.15,
    ...
  },
  "metadata": {
    "cluster_id": "ST010_HEINRICH_ZILLE_STRASSE",
    "timestamp": "2026-01-16T12:00:00",
    "seed": 42,
    "n_samples": 500,
    ...
  }
}
```

---

### UHDC Pipeline Outputs

#### `report_<cluster_id>.html`
**Format**: HTML  
**Structure**: Comprehensive HTML report with:
- Executive summary dashboard
- Interactive maps (CHA velocity/temperature/pressure, DHA LV grid)
- Violations table (sortable, filterable)
- Technical details table
- Charts (Plotly.js interactive)

#### `report_<cluster_id>.md`
**Format**: Markdown  
**Structure**: Markdown version of report (no interactive features)

#### `report_<cluster_id>.json`
**Format**: JSON  
**Structure**: Raw report data (for programmatic access)

---

## Troubleshooting

### Common Issues

#### 1. Missing Prerequisite Artifacts
**Symptoms**: `FileNotFoundError: Missing prerequisite artifacts`

**Solutions**:
- Run CHA pipeline first: `01_run_cha.py`
- Run DHA pipeline: `02_run_dha.py`
- Run economics pipeline: `cli/economics.py`
- Verify paths: Check `results/cha/<cluster_id>/`, `results/dha/<cluster_id>/`, `results/economics/<cluster_id>/`

#### 2. LLM Not Available
**Symptoms**: `⚠️  Warning: GOOGLE_API_KEY not found` or `LLM unavailable`

**Solutions**:
- Create `.env` file: `echo 'GOOGLE_API_KEY=your_key' > .env`
- Install google-genai: `pip install google-genai`
- Use template fallback: Remove `--llm-explanation` flag
- Use `--no-fallback` only if LLM is explicitly required

#### 3. Invalid JSON/Config
**Symptoms**: `ValueError: Invalid JSON` or `validate_config()` raises

**Solutions**:
- Validate JSON syntax: `json.load()` should succeed
- Check schema: Use `ContractValidator.validate()` to check contract
- Verify config format: Check `config/decision_config_*.json` structure

#### 4. Batch Mode Skipping Clusters
**Symptoms**: `! Skipping <cluster_id>: missing prerequisites`

**Solutions**:
- Check prerequisites: Verify CHA/DHA/economics outputs exist for skipped clusters
- Run missing pipelines: Complete CHA/DHA/economics for skipped clusters
- Verify cluster IDs: Check `results/cha/` directory names match expected IDs

#### 5. Economics Fallback Warning
**Symptoms**: `Cluster <cluster_id> not found in cluster_load_summary.parquet; falling back`

**Solutions**:
- Verify cluster ID: Check cluster ID matches `building_cluster_map.parquet`
- Check cluster summary: Ensure `cluster_load_summary.parquet` contains the cluster
- Use fallback: Fallback computes from profiles (acceptable for single clusters)

---

## Performance Considerations

### Large Batch Processing
- **Parallelization**: Economics CLI supports `--n-jobs -1` (all cores) for Monte Carlo
- **Memory**: Batch processing loads one cluster at a time (low memory footprint)
- **I/O**: Path discovery is O(1) per cluster (directory listing cached)

### LLM API Calls
- **Rate Limiting**: Google API has rate limits (60 queries/minute for free tier)
- **Timeout**: Default 30 seconds per LLM call (`LLM_TIMEOUT`)
- **Retry**: No automatic retry (failures fall back to template if `--no-fallback` not set)

---

## Best Practices

### 1. Use Auto-Discovery
```bash
# Prefer auto-discovery (works if standard structure)
python -m branitz_heat_decision.cli.decision --cluster-id ST010

# Only use explicit paths if non-standard structure
python -m branitz_heat_decision.cli.decision \
  --cluster-id ST010 \
  --cha-kpis custom/path/cha_kpis.json
```

### 2. Batch Processing for Multiple Clusters
```bash
# Use batch mode instead of loops
python -m branitz_heat_decision.cli.decision --all-clusters

# Instead of:
for cluster in clusters; do
  python -m branitz_heat_decision.cli.decision --cluster-id $cluster
done
```

### 3. LLM Fallback Strategy
```bash
# Use fallback for robustness (default)
python -m branitz_heat_decision.cli.decision --cluster-id ST010 --llm-explanation

# Use --no-fallback only if LLM is required
python -m branitz_heat_decision.cli.decision --cluster-id ST010 --llm-explanation --no-fallback
```

### 4. Logging Configuration
```bash
# Use environment variable for logging
export UHDC_LOG_LEVEL=DEBUG
python -m branitz_heat_decision.cli.decision --cluster-id ST010
```

### 5. Output Format Selection
```bash
# Use specific format if only one needed
python -m branitz_heat_decision.cli.decision --cluster-id ST010 --format json

# Use `all` only if multiple formats needed
python -m branitz_heat_decision.cli.decision --cluster-id ST010 --format all
```

---

## Standards Compliance

### Decision Pipeline Compliance

- **KPI Contract Schema**: Validated via `ContractValidator.validate()` (enforces structure)
- **Decision Rules**: Deterministic logic with auditable reason codes
- **Explanation Safety**: LLM output validated (hallucination checks, allowed numbers)

### Economics Pipeline Compliance

- **Monte Carlo Reproducibility**: Seed-based random sampling (`--seed 42`)
- **Summary Statistics**: Standard quantiles (p05, p50, p95), mean, std
- **Win Fraction Calculation**: Robustness metrics (dh_wins_fraction, hp_wins_fraction)

### UHDC Report Compliance

- **Interactive Maps**: Embedded CHA/DHA maps with loading states and error handling
- **Violations Table**: DataTables.js for sorting, filtering, highlighting
- **Accessibility**: Bootstrap 5 responsive layout, semantic HTML

---

## References & Standards

- **argparse**: Python standard library for command-line parsing
- **pathlib**: Python standard library for path handling
- **logging**: Python standard library for logging
- **pandas**: Data analysis library (for economics pipeline)

---

**Last Updated**: 2026-01-19  
**Module Version**: v1.1  
**Primary Maintainer**: CLI Development Team

## Recent Updates (2026-01-19)

- **Economics File Discovery**: Enhanced to prioritize `economics_monte_carlo.json` over legacy `monte_carlo_summary.json`
- **Error Handling**: Improved error handling in decision CLI for LLM explanation failures
- **Default LLM Usage**: Decision and UHDC CLIs now default to using LLM explanations (if available)
