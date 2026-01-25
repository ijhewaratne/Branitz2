# Branitz Heat Decision AI System - Complete System Documentation

**Last Updated:** 2026-01-24  
**Version:** 3.1 (Enhanced Validation & Robustness)

---

## Overview

The **Branitz Heat Decision AI System** is a deterministic, auditable multi-agent framework for climate-neutral urban heat planning. It couples district heating (DH) network simulation with low-voltage (LV) power grid analysis, performs economic and environmental assessments, and uses a constrained LLM coordinator to make explainable decisions.

### Key Uniqueness

- **True Multi-Physics**: Couples pandapipes (hydraulic-thermal DH networks) + pandapower (LV electrical grid)
- **Explainable AI**: Constrained LLM coordinator (read-only, no hallucination)
- **Standards-Aligned**: EN 13941-1 (DH networks), VDE-AR-N 4100 (LV grid)
- **Uncertainty-Aware**: Monte Carlo win fractions drive robustness flags
- **Street-Level Maps**: Interactive visualizations with cascading colors & pipe sizing
- **Complete Pipeline**: Data preparation → CHA → DHA → Economics → Decision → UHDC Reports

---

## System Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    INPUT DATA LAYER                          │
│  - Buildings (GeoJSON/Parquet)                              │
│  - Streets (GeoJSON)                                         │
│  - Weather data                                              │
│  - Power grid (LV lines, substations)                        │
│  - Base electrical loads (BDEW/profiles)                     │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                  DATA PREPARATION (Phase 0)                  │
│  ✅ IMPLEMENTED                                               │
│  - Data loading & validation                                 │
│  - Building filtering (residential with heat demand)         │
│  - Building typology classification (TABULA/U-values)        │
│  - Hourly heat profile generation (8760 hours)               │
│  - Street-based cluster creation                             │
│  - Design hour and top-N hours computation                   │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│              MULTI-AGENT DECISION FRAMEWORK                  │
│                                                              │
│  ┌──────────────┐      ┌──────────────┐                    │
│  │  CHA Agent   │      │  DHA Agent   │                    │
│  │ (District    │      │ (District    │                    │
│  │  Heating)    │      │  Heat Pump   │                    │
│  │              │      │  Analysis)   │                    │
│  │ ✅ IMPL      │      │  ✅ IMPL     │                    │
│  └──────┬───────┘      └──────┬───────┘                    │
│         │                     │                             │
│         ▼                     ▼                             │
│  ┌──────────────────────────────────────┐                  │
│  │      Economics Agent                  │                  │
│  │  (LCOH, CO₂, Monte Carlo)             │                  │
│  │  ✅ IMPLEMENTED                       │                  │
│  └──────────────┬───────────────────────┘                  │
│                 │                                           │
│                 ▼                                           │
│  ┌──────────────────────────────────────┐                  │
│  │      Decision Agent                   │                  │
│  │  (KPI Contract, Rules Engine)        │                  │
│  │  ✅ IMPLEMENTED                       │                  │
│  └──────────────┬───────────────────────┘                  │
│                 │                                           │
│                 ▼                                           │
│  ┌──────────────────────────────────────┐                  │
│  │   UHDC Coordinator (LLM)              │                  │
│  │   (Constrained, Explainable)         │                  │
│  │  ✅ IMPLEMENTED                       │                  │
│  └──────────────────────────────────────┘                  │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                    OUTPUT LAYER                              │
│  - KPIs (JSON) - CHA, DHA, Economics                        │
│  - Interactive maps (HTML) - Velocity, Temperature, Pressure│
│  - QGIS exports (GeoPackage)                                │
│  - Network topology (Pickle)                                │
│  - UHDC Reports (HTML, Markdown, JSON)                      │
│  - Violations (CSV)                                         │
└─────────────────────────────────────────────────────────────┘
```

### Multi-Agent Architecture Overview

The system follows a **modular multi-agent architecture** where each agent is independently replaceable and communicates through a **schema-checked KPI contract** as the single source of truth.

```
┌─────────────────────────────────────────────────────────────────┐
│                    HDA (Heat Demand Agent)                       │
│  ✅ IMPLEMENTED                                                  │
│  Input: Buildings, Weather Data                                 │
│  Output: 8760 hourly profiles, design hour, Top-N hours         │
│  Location: src/branitz_heat_decision/data/                      │
│  - generate_hourly_profiles() → 8760 profiles                   │
│  - compute_design_and_topn() → design hour, Top-N               │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│              CHA (Centralized Heating Agent)                    │
│  ✅ IMPLEMENTED                                                  │
│  Input: Buildings, Streets, 8760 profiles, design hour         │
│  Engine: pandapipes (hydraulic-thermal simulation)             │
│  Output: KPIs (velocity, Δp, losses, topology)                 │
│  Location: src/branitz_heat_decision/cha/                       │
│  - Network building (trunk-spur topology)                        │
│  - Pipe sizing (catalog-based, velocity limits)                 │
│  - Hydraulic-thermal simulation                                 │
│  - KPI extraction (EN 13941-1 compliance)                       │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│            DHA (Decentralized Heating Agent)                     │
│  ✅ IMPLEMENTED                                                  │
│  Input: Buildings, LV grid, heat pump loads                     │
│  Engine: pandapower (powerflow simulation)                      │
│  Output: KPIs (voltage, loading, violations)                    │
│  Location: src/branitz_heat_decision/dha/                       │
│  - LV grid hosting capacity analysis                            │
│  - Powerflow simulation (BDEW base loads + HPs)                │
│  - KPI extraction (VDE-AR-N 4100 compliance)                   │
│  - Mitigation recommendations                                  │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│              Economics Agent                                    │
│  ✅ IMPLEMENTED                                                  │
│  Input: CHA KPIs, DHA KPIs, Economic parameters                 │
│  Method: Monte Carlo uncertainty propagation                    │
│  Output: LCOH/CO₂ quantiles (P10, P50, P90), win fractions     │
│  Location: src/branitz_heat_decision/economics/                 │
│  - CAPEX/OPEX calculation (pipes, pump, plant, LV upgrade)     │
│  - Monte Carlo simulation (n scenarios)                        │
│  - Quantile extraction (LCOH, CO₂ emissions)                   │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│              Decision Agent                                      │
│  ✅ IMPLEMENTED                                                  │
│  Input: CHA KPIs, DHA KPIs, Economics Summary                  │
│  Method: Deterministic rules engine + KPI contract              │
│  Output: Decision (DH/HP/UNDECIDED), robustness, reason codes   │
│  Location: src/branitz_heat_decision/decision/                  │
│  - KPI contract builder (schema-checked)                       │
│  - Decision rules (LCOH comparison, CO₂ tie-breaker)            │
│  - Robustness classification                                    │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│    UHDC (Urban Heat Decision Coordinator)                        │
│  ✅ IMPLEMENTED                                                  │
│  Input: KPI Contract, Decision, All KPIs                        │
│  Method: Constrained LLM (read-only, no hallucination)          │
│  Output: Stakeholder reports (HTML, Markdown, JSON)             │
│  Location: src/branitz_heat_decision/uhdc/                       │
│  - Schema-checked contract validation                           │
│  - LLM explanation generation (with fallback templates)          │
│  - Interactive dashboard generation                             │
└─────────────────────────────────────────────────────────────────┘
```

#### Key Architectural Principles

1. **Modularity & Replaceability**: Each agent is independently implementable and replaceable. Agents communicate only through well-defined interfaces:
   - **HDA → CHA/DHA**: 8760 hourly profiles, design hour, Top-N hours
   - **CHA → Economics**: KPIs (velocity, Δp, losses, topology stats)
   - **DHA → Economics**: KPIs (voltage, loading, violations)
   - **Economics → Decision**: LCOH/CO₂ quantiles, win fractions
   - **Decision → UHDC**: KPI contract, decision choice, robustness

2. **KPI Contract as Single Source of Truth**: All agents output standardized JSON KPIs that are validated against schemas. The Decision Agent builds a canonical **KPI contract** that serves as the authoritative data structure for:
   - Decision-making (deterministic rules)
   - LLM explanations (constrained, fact-checked)
   - Stakeholder reports (UHDC)
   - Validation (TNLI Logic Auditor)

3. **Deterministic & Auditable**: 
   - All agents produce deterministic outputs (no randomness except Monte Carlo, which is seeded)
   - All intermediate results are saved (KPIs, networks, validation reports)
   - Full traceability from input data to final decision

4. **Standards-Aligned**:
   - **CHA**: EN 13941-1 (District heating networks)
   - **DHA**: VDE-AR-N 4100 (LV grid connection)
   - **Economics**: Standard LCOH methodology
   - **Decision**: Transparent, rule-based logic

5. **Validation at Multiple Levels**:
   - **CHA Design Validation**: Geospatial, hydraulic, thermal, robustness checks
   - **DHA Compliance**: VDE-AR-N 4100 voltage/loading limits
   - **TNLI Logic Auditor**: Validates LLM explanations against KPI contract

---

## Project Structure

```
branitz_heat_decision/
├── data/
│   ├── raw/                    # Original data (Wärmekataster, OSM, etc.)
│   │   └── raw_readme.md       # Complete raw data documentation
│   └── processed/              # Validated, pipeline-ready data
│       ├── processed_readme.md # Complete processed data documentation
│       ├── buildings.parquet
│       ├── building_cluster_map.parquet
│       ├── street_clusters.parquet
│       ├── hourly_heat_profiles.parquet
│       ├── weather.parquet
│       └── cluster_design_topn.json
│
├── results/                    # Deterministic, versioned outputs
│   ├── cha/                    # CHA agent results (per cluster)
│   │   └── {cluster_id}/
│   │       ├── cha_kpis.json
│   │       ├── network.pickle
│   │       ├── interactive_map.html (velocity)
│   │       ├── interactive_map_temperature.html
│   │       ├── interactive_map_pressure.html
│   │       ├── pipe_velocities*.csv
│   │       ├── design_validation.json (NEW)
│   │       ├── design_validation_summary.txt (NEW)
│   │       ├── design_validation_metrics.csv (NEW)
│   │       └── qgis/
│   ├── dha/                    # DHA agent results
│   │   └── {cluster_id}/
│   │       ├── dha_kpis.json
│   │       ├── buses_results.geojson
│   │       ├── lines_results.geojson
│   │       ├── violations.csv
│   │       └── hp_lv_map.html
│   ├── economics/              # Economics calculations
│   │   └── {cluster_id}/
│   │       ├── economics_deterministic.json
│   │       ├── monte_carlo_summary.json
│   │       └── monte_carlo_samples.parquet
│   ├── decision/               # Decision recommendations
│   │   └── {cluster_id}/
│   │       ├── kpi_contract_{cluster_id}.json
│   │       └── decision_{cluster_id}.json
│   └── uhdc/                   # UHDC reports
│       └── {cluster_id}/
│           ├── uhdc_report_{cluster_id}.html
│           ├── uhdc_explanation_{cluster_id}.md
│           └── uhdc_report_{cluster_id}.json
│
├── src/
│   ├── branitz_heat_decision/  # Main Python package
│   │   ├── data/               # Data loading, validation, processing
│   │   │   ├── data_readme.md  # Complete data module documentation
│   │   │   ├── loader.py       # Smart building loader, street loader
│   │   │   ├── typology.py     # Building envelope estimation (TABULA)
│   │   │   ├── profiles.py     # Hourly heat profile generation
│   │   │   └── cluster.py      # Street-based clustering
│   │   ├── cha/                # Central Heating Agent
│   │   │   ├── cha_readme.md   # Complete CHA module documentation
│   │   │   ├── network_builder_trunk_spur.py  # Trunk-spur network builder
│   │   │   ├── network_builder.py             # Standard network builder
│   │   │   ├── convergence_optimizer_spur.py  # Spur-specific optimizer
│   │   │   ├── convergence_optimizer.py       # Standard optimizer
│   │   │   ├── kpi_extractor.py               # EN 13941-1 KPIs
│   │   │   ├── sizing_catalog.py              # Pipe sizing from catalog
│   │   │   ├── heat_loss.py                   # Pipe heat loss calculation
│   │   │   ├── qgis_export.py                 # Interactive maps & QGIS export
│   │   │   ├── hydraulic_checks.py            # Context-aware validation (NEW)
│   │   │   ├── design_validator.py            # Design validation system (NEW)
│   │   │   ├── geospatial_checks.py           # Geospatial validation (NEW)
│   │   │   ├── thermal_checks.py              # Thermal validation (NEW)
│   │   │   ├── robustness_checks.py           # Robustness validation (NEW)
│   │   │   ├── DESIGN_VALIDATION_EXPLAINED.md # Validation documentation (NEW)
│   │   │   ├── VALIDATION_WARNINGS_EXPLAINED.md # Warning explanations (NEW)
│   │   │   ├── HOW_TO_FIX_VALIDATION_ISSUES.md # Troubleshooting guide (NEW)
│   │   │   ├── WARNING_MITIGATION_OPTIONS.md   # Warning options (NEW)
│   │   │   └── config.py                      # CHA configuration
│   │   ├── dha/                # District Heat Pump Agent
│   │   │   ├── dha_readme.md   # Complete DHA module documentation
│   │   │   ├── grid_builder.py # LV grid builder (Option 2: MV/LV)
│   │   │   ├── mapping.py      # Building-to-bus mapping
│   │   │   ├── base_loads.py   # Base electrical load loading
│   │   │   ├── bdew_base_loads.py  # BDEW base load generation
│   │   │   ├── loadflow.py     # Powerflow simulation
│   │   │   ├── kpi_extractor.py # VDE-AR-N 4100 KPIs
│   │   │   ├── export.py       # GeoJSON and map export
│   │   │   └── config.py       # DHA configuration
│   │   ├── economics/          # Economics calculations
│   │   │   ├── economics_readme.md  # Complete economics documentation
│   │   │   ├── params.py       # Economic parameters
│   │   │   ├── lcoh.py         # LCOH calculation (CRF method)
│   │   │   ├── co2.py          # CO₂ emissions calculation
│   │   │   ├── monte_carlo.py  # Monte Carlo uncertainty propagation
│   │   │   └── utils.py        # Economic utilities
│   │   ├── decision/           # Decision logic
│   │   │   ├── decision_readme.md  # Complete decision documentation
│   │   │   ├── schemas.py      # KPI contract schemas
│   │   │   ├── kpi_contract.py # KPI contract builder
│   │   │   └── rules.py        # Decision rules engine
│   │   ├── validation/         # TNLI Logic Auditor (NEW)
│   │   │   ├── LOGIC_AUDITOR_WORKFLOW.md  # Complete validation documentation
│   │   │   ├── logic_auditor.py # Main validation orchestrator
│   │   │   ├── tnli_model.py   # LLM-based semantic validation
│   │   │   ├── claims.py       # Deterministic claim validation
│   │   │   ├── feedback_loop.py # Automatic regeneration handler
│   │   │   ├── monitoring.py   # Metrics and alerting
│   │   │   ├── config.py        # Validation configuration
│   │   │   └── INTEGRATION_GUIDE.md # Integration guide
│   │   ├── uhdc/               # UHDC coordinator (LLM)
│   │   │   ├── uhdc_readme.md  # Complete UHDC documentation
│   │   │   ├── io.py           # Artifact I/O
│   │   │   ├── orchestrator.py # Pipeline orchestration
│   │   │   ├── explainer.py    # LLM explainer (Gemini)
│   │   │   └── report_builder.py # HTML/Markdown report generation
│   │   └── cli/                # CLI interfaces
│   │       ├── cli_readme.md   # Complete CLI documentation
│   │       ├── decision.py     # Decision pipeline CLI (includes TNLI validation)
│   │       ├── economics.py    # Economics pipeline CLI
│   │       └── uhdc.py         # UHDC report generation CLI
│   │
│   └── scripts/                # Pipeline scripts
│       ├── scripts_readme.md   # Complete scripts documentation
│       ├── 00_prepare_data.py  # Data preparation pipeline
│       ├── 01_run_cha.py       # CHA pipeline (trunk-spur + standard)
│       ├── 02_run_dha.py       # DHA pipeline
│       ├── 03_run_economics.py # Economics pipeline
│       ├── 04_make_decision.py # ⚠️ DEPRECATED (use cli/decision.py)
│       ├── 05_generate_report.py # ⚠️ DEPRECATED (use cli/uhdc.py)
│       └── serve_maps.py       # ⚠️ NOT IMPLEMENTED
│
├── docs/                       # Documentation
│   ├── topology.md            # Network topology creation guide
│   ├── network_building_issues_analysis.md
│   ├── trunk_topology_issues_analysis.md
│   ├── architecture.md        # System architecture
│   ├── api_reference.md       # API reference
│   ├── decision_pipeline.md   # Decision pipeline guide
│   ├── dha_violation_mitigation_strategies.md
│   └── economics_phase4_checklist.md
│
├── tests/                      # Test suite
│   ├── test_readme.md         # Complete test documentation
│   ├── integration/           # End-to-end workflow tests (CRITICAL)
│   ├── decision/              # Decision module tests
│   ├── economics/             # Economics module tests
│   ├── uhdc/                  # UHDC module tests
│   ├── cha/                   # CHA unit tests
│   └── performance/           # Performance benchmarks
│
├── notebooks/                  # Jupyter notebooks for exploration
├── Legacy/                     # Reference implementation
└── config/                     # Configuration files
    ├── decision_config_2023.json
    ├── decision_config_2030.json
    └── decision_config_aggressive.json
```

---

## Complete Pipeline Workflow

### Phase 0: Data Preparation ✅ **IMPLEMENTED**

**Script**: `src/scripts/00_prepare_data.py`  
**CLI Module**: N/A (standalone script)

**Purpose**: Load raw data, filter buildings, create clusters, generate profiles

**Key Steps**:
1. **Load Raw Data**:
   - Buildings GeoJSON (`hausumringe_mit_adressenV3.geojson`)
   - Streets GeoJSON (`strassen_mit_adressenV3_fixed.geojson`)
   - Weather data (8760 hours)
   - Building attributes (`output_branitzer_siedlungV11.json`)
   - Building analysis (`gebaeudeanalyse.json`)

2. **Filter Buildings**:
   - Filter to residential buildings with heat demand
   - Uses `filter_residential_buildings_with_heat_demand()`
   - Saves to `data/processed/buildings.parquet`

3. **Enrich Buildings**:
   - Load Branitzer attributes (building function, street, floor area)
   - Load gebaeudeanalyse (renovation state, heat density)
   - Estimate envelope parameters (TABULA/U-values)

4. **Match Buildings to Streets**:
   - Address-based matching (preferred)
   - Spatial proximity fallback

5. **Create Street-Based Clusters**:
   - Group buildings by street
   - Generate cluster IDs: `ST{number}_{STREET_NAME}`
   - Calculate plant locations
   - Save `building_cluster_map.parquet` and `street_clusters.parquet`

6. **Generate Hourly Profiles**:
   - Generate 8760-hour heat demand profiles per building
   - Save to `data/processed/hourly_heat_profiles.parquet`

7. **Compute Design/Top-N Hours**:
   - Compute design hour (peak load)
   - Compute top-N hours (N=10)
   - Save to `data/processed/cluster_design_topn.json`

**Outputs**:
- `data/processed/buildings.parquet` - Filtered residential buildings with heat demand
- `data/processed/building_cluster_map.parquet` - Building → cluster mapping
- `data/processed/street_clusters.parquet` - Cluster metadata
- `data/processed/hourly_heat_profiles.parquet` - 8760 hours × n_buildings
- `data/processed/cluster_design_topn.json` - Design hour and top-N hours per cluster

**Usage**:
```bash
conda activate branitz_env
python src/scripts/00_prepare_data.py --create-clusters
```

**Documentation**: See `src/branitz_heat_decision/data/data_readme.md`

---

### Phase 1: CHA (Central Heating Agent) ✅ **IMPLEMENTED**

**Script**: `src/scripts/01_run_cha.py`  
**CLI Module**: N/A (standalone script)

**Purpose**: Analyze district heating network feasibility and performance

**Key Steps**:
1. **Load Cluster Data**:
   - Load filtered residential buildings with heat demand
   - Load streets (all streets, for plant siting)
   - Load hourly heat profiles
   - Load design hour and design load

2. **Extract Per-Building Heat Demands**:
   - Extract each building's heat demand at design hour from hourly profiles
   - Creates `design_loads_kw` dictionary: `{building_id: heat_demand_kw}`

3. **Build Network** (Trunk-Spur or Standard):
   - **Trunk-Spur Mode** (`--use-trunk-spur`): Recommended
     - Filter streets to cluster
     - Compute building attach points (project to nearest street edges)
     - Build trunk path through all buildings (radial spanning tree from plant)
     - Create path sequence (plant → ... → last building)
     - Create pandapipes network (dual-network structure: supply + return)
     - Size pipes from technical catalog
     - Apply heat loss calculations
     - Optimize for convergence
   - **Standard Mode** (default):
     - Build street graph
     - Attach buildings to streets
     - Build trunk topology (paths from plant to buildings)
     - Create pandapipes network
     - Size pipes
     - Run simulation
     - Optimize for convergence

4. **Run Simulation**:
   - Run `pp.pipeflow()` for hydraulic-thermal simulation
   - Check convergence

5. **Extract KPIs**:
   - EN 13941-1 compliance metrics
   - Velocity limits (v ≤ 1.5 m/s for 95% of pipes)
   - Pressure drop limits (Δp ≤ 0.3 bar/100m)
   - Heat loss calculations
   - Topology statistics
   - Convergence status

6. **Generate Interactive Maps**:
   - Velocity map (`interactive_map.html`) - Cascading red/blue colors
   - Temperature map (`interactive_map_temperature.html`) - Cascading red/blue colors
   - Pressure map (`interactive_map_pressure.html`) - Cascading red/blue colors
   - Pipe sizing by line thickness
   - Separate supply/return layers

7. **Export Pipe CSVs**:
   - `pipe_velocities_supply_return.csv`
   - `pipe_velocities_supply_return_with_temp.csv`
   - `pipe_velocities_plant_to_plant_main_path.csv`
   - Includes min/max scaling and hex colors for maps

**Key Features**:
- **Trunk-Spur Topology**: Radial spanning tree from plant with service connections
- **Dual-Network Structure**: Separate supply and return networks
- **Heat Loss Modeling**: Linear (W/m) and thermal resistance (U-value) methods
- **Fixed Plant Location**: WGS84 coordinates (default: Cottbus CHP: 51.76274, 14.3453979)
- **Pipe Sizing**: Role-based velocity limits (trunk ≤ 1.5 m/s, service ≤ 1.5 m/s)
- **Design Margin (NEW)**: 25% design margin applied to pipe sizing for robustness
  - Ensures pipes can handle ±20% demand variation in Monte Carlo scenarios
  - Uses conservative velocity limits (1.2 m/s) for improved robustness
- **Convergence Optimization**: Spur-specific optimizer for trunk-spur networks
- **Design Validation (NEW)**: Comprehensive validation system
  - Geospatial validation (building connectivity, network topology)
  - Hydraulic validation (EN 13941-1 with context-aware warnings)
  - Thermal validation (temperature distribution, heat losses)
  - Robustness validation (Monte Carlo uncertainty analysis, 50 scenarios)
- **Context-Aware Warnings (NEW)**: Automatically detects trunk-spur networks and provides context-aware warnings
  - Explains why low velocity in return pipes and spurs is expected
  - Explains why flow distribution imbalance is a design feature, not a flaw

**Command Line Arguments**:
- `--cluster-id` (required): Cluster identifier (e.g., `ST010_HEINRICH_ZILLE_STRASSE`)
- `--use-trunk-spur`: Use trunk-spur network builder (recommended)
- `--optimize-convergence`: Enable convergence optimization
- `--plant-wgs84-lat`: Fixed plant latitude (WGS84)
- `--plant-wgs84-lon`: Fixed plant longitude (WGS84)
- `--disable-auto-plant-siting`: Disable automatic re-siting to nearby different street
- `--verbose`: Detailed logging

**Outputs**:
- `results/cha/{cluster_id}/cha_kpis.json` - KPIs with convergence status, topology statistics
- `results/cha/{cluster_id}/network.pickle` - Complete pandapipes network
- `results/cha/{cluster_id}/interactive_map*.html` - Interactive visualizations (velocity/temp/pressure)
- `results/cha/{cluster_id}/pipe_velocities*.csv` - Pipe velocity/temperature/pressure data
- `results/cha/{cluster_id}/design_validation.json` (NEW) - Comprehensive design validation report
- `results/cha/{cluster_id}/design_validation_summary.txt` (NEW) - Human-readable validation summary
- `results/cha/{cluster_id}/design_validation_metrics.csv` (NEW) - Validation metrics in CSV format
- `results/cha/{cluster_id}/qgis/*.gpkg` - QGIS-compatible exports

**Usage**:
```bash
# Trunk-spur mode (recommended)
python src/scripts/01_run_cha.py \
  --cluster-id ST010_HEINRICH_ZILLE_STRASSE \
  --use-trunk-spur \
  --plant-wgs84-lat 51.76274 \
  --plant-wgs84-lon 14.3453979 \
  --disable-auto-plant-siting

# Standard mode
python src/scripts/01_run_cha.py \
  --cluster-id ST010_HEINRICH_ZILLE_STRASSE \
  --optimize-convergence
```

**Documentation**: See `src/branitz_heat_decision/cha/cha_readme.md`

---

### Phase 2: DHA (District Heat Pump Agent) ✅ **IMPLEMENTED**

**Script**: `src/scripts/02_run_dha.py`  
**CLI Module**: N/A (standalone script)

**Purpose**: Analyze LV power grid hosting capacity for heat pumps

**Key Steps**:
1. **Load Cluster Buildings**:
   - Load residential buildings with heat demand (same as CHA)
   - Filter to buildings with hourly heat profiles

2. **Load Design Hour + TopN Hours**:
   - Load from `cluster_design_topn.json`

3. **Load Hourly Heat Profiles**:
   - Load from `hourly_heat_profiles.parquet`
   - Filter to cluster buildings

4. **Load Base Electrical Loads**:
   - **Scenario JSON** (`scenario_json`): Load from `gebaeude_lastphasenV2.json`
   - **BDEW Time Series** (`bdew_timeseries`): Generate from BDEW SLP profiles
     - Requires `building_population_resultsV6.json` for deterministic H0 scaling

5. **Build LV Grid** (Option 2: MV bus + MV/LV transformer + ext_grid at MV):
   - **Legacy JSON** (`legacy_json`): Load from `Legacy/DHA/HP New /Data/branitzer_siedlung_ns_v3_ohne_UW.json`
   - **GeoData** (`geodata`): Build from `data/processed/power_lines.geojson` and `power_substations.geojson`
   - Create MV bus (20 kV) with `ext_grid`
   - Create LV buses (0.4 kV) per substation
   - Create transformers (MV → LV) with parameters (Sn, vk%, vkr%, tap settings)
   - Create LV lines with length from geometry

6. **Map Buildings to LV Buses**:
   - Spatial matching (max distance configurable)
   - Validate all buildings mapped

7. **Assign HP Loads**:
   - Convert heat demand to electrical via COP: `P_el_kw = Q_th_kw / COP`
   - Combine with base load: `P_total_kw = P_base_kw + P_hp_kw`
   - Compute reactive power: `Q_total = P_total * tan(arccos(pf))`
   - Option: Split PF for base vs. HP loads

8. **Run Loadflow**:
   - For design hour and TopN hours
   - Run `pp.runpp()` (balanced 3-phase or single-phase imbalance)
   - Extract bus voltages and line loadings

9. **Extract KPIs**:
   - VDE-AR-N 4100 compliance metrics
   - Voltage violations (v_min < 0.9 pu or v_max > 1.1 pu)
   - Line loading violations (loading > 100%)
   - Max feeder loading percentage
   - Violations table (CSV)

10. **Export Outputs**:
    - GeoJSON: `buses_results.geojson`, `lines_results.geojson`
    - Violations CSV: `violations.csv`
    - Interactive map: `hp_lv_map.html` - Cascading colors by voltage/loading

**Key Features**:
- **MV/LV Boundary (Option 2)**: ext_grid at MV (20 kV), transformers to LV (0.4 kV)
- **Base Electrical Loads**: Normal household/commercial demand (P_base + P_hp)
- **BDEW Integration**: Standardized load profiles (H0, G0-G6, L0, Y1)
- **Three-Phase Support**: Balanced or single-phase imbalance mode
- **Violation Tracking**: Comprehensive violations CSV with severity levels

**Command Line Arguments**:
- `--cluster-id` (required): Cluster identifier
- `--cop`: Heat pump COP (default: 2.8)
- `--pf`: Power factor (default: 0.95)
- `--hp-three-phase`: Model HP loads as balanced 3-phase (default)
- `--single-phase`: Model HP loads as single-phase imbalance
- `--topn`: Number of top hours to include (default: 10)
- `--base-load-source`: Base load source (`scenario_json`, `bdew_timeseries`)
- `--bdew-population-json`: REQUIRED for `bdew_timeseries` - Path to `building_population_resultsV6.json`
- `--grid-source`: Grid source (`legacy_json`, `geodata`)

**Outputs**:
- `results/dha/{cluster_id}/dha_kpis.json` - VDE-AR-N 4100 compliance KPIs
- `results/dha/{cluster_id}/buses_results.geojson` - Bus voltage results
- `results/dha/{cluster_id}/lines_results.geojson` - Line loading results
- `results/dha/{cluster_id}/violations.csv` - Detailed violations table
- `results/dha/{cluster_id}/hp_lv_map.html` - Interactive LV grid map

**Usage**:
```bash
# With scenario-based base loads
python src/scripts/02_run_dha.py --cluster-id ST010_HEINRICH_ZILLE_STRASSE

# With BDEW time series base loads
python src/scripts/02_run_dha.py \
  --cluster-id ST010_HEINRICH_ZILLE_STRASSE \
  --base-load-source bdew_timeseries \
  --bdew-population-json data/raw/building_population_resultsV6.json

# Single-phase imbalance (worst-case)
python src/scripts/02_run_dha.py \
  --cluster-id ST010_HEINRICH_ZILLE_STRASSE \
  --single-phase
```

**Documentation**: See `src/branitz_heat_decision/dha/dha_readme.md`

---

### Phase 3: Economics ✅ **IMPLEMENTED**

**Script**: `src/scripts/03_run_economics.py`  
**CLI Module**: `src/branitz_heat_decision/cli/economics.py`

**Purpose**: Calculate Levelized Cost of Heat (LCOH) and CO₂ emissions with Monte Carlo uncertainty propagation

**Key Steps**:
1. **Load Cluster Data**:
   - Building IDs, design hour, annual heat demand (MWh/year), design capacity (kW)

2. **Load CHA KPIs**:
   - Pipe lengths (trunk_m, service_m)
   - Pipe CAPEX (from per-pipe CSV with DN costs)
   - Pump power (kW)
   - Pipe lengths by DN

3. **Load DHA KPIs**:
   - Max feeder loading (%)

4. **Get Default Parameters**:
   - Load via `get_default_economics_params()`
   - CAPEX multipliers, O&M rates, fuel costs, electricity prices, discount rate

5. **Compute Deterministic LCOH/CO₂**:
   - **DH LCOH**: `compute_lcoh_dh()` - CRF method with pipe costs, pump O&M, fuel costs
   - **HP LCOH**: `compute_lcoh_hp()` - CRF method with HP costs, electricity costs, LV upgrade costs
   - **DH CO₂**: `compute_co2_dh()` - Annual emissions (gas/biomass/electricity)
   - **HP CO₂**: `compute_co2_hp()` - Annual emissions from grid electricity

6. **Save Deterministic Results**:
   - Save to `economics_deterministic.json`

7. **Run Monte Carlo** (N=500 by default):
   - Propagate uncertainty through parameters:
     - CAPEX multiplier: 0.8-1.2 (lognormal)
     - Electricity price multiplier: 0.7-1.3 (lognormal)
     - Fuel price multiplier: 0.7-1.3 (lognormal)
     - Grid CO₂ multiplier: 0.7-1.3 (lognormal)
     - HP COP: 2.0-3.5 (triangular)
     - Discount rate: 0.02-0.08 (uniform)
   - Compute LCOH and CO₂ for each sample
   - Calculate win fractions: `dh_wins_fraction`, `hp_wins_fraction`
   - Extract quantiles (p05, p50, p95)

8. **Save Monte Carlo Results**:
   - Summary: `monte_carlo_summary.json` (quantiles, win fractions)
   - Samples: `monte_carlo_samples.parquet` (all 500 samples)

**Key Features**:
- **CRF Method**: Capital Recovery Factor for LCOH calculation
- **Monte Carlo Simulation**: N=500 samples with bounded parameter distributions
- **Win Fractions**: Probabilistic robustness metrics
- **Quantiles**: p05, p50, p95 for uncertainty quantification

**Command Line Arguments**:
- `--cluster-id` (required): Cluster identifier
- `--n`: Monte Carlo samples (default: 500)
- `--seed`: Random seed (default: 42)

**Outputs**:
- `results/economics/{cluster_id}/economics_deterministic.json` - Deterministic LCOH/CO₂
- `results/economics/{cluster_id}/monte_carlo_summary.json` - Monte Carlo summary (quantiles, win fractions)
- `results/economics/{cluster_id}/monte_carlo_samples.parquet` - All Monte Carlo samples

**Usage**:
```bash
# Using script
python src/scripts/03_run_economics.py --cluster-id ST010_HEINRICH_ZILLE_STRASSE

# Using CLI
python -m branitz_heat_decision.cli.economics \
  --cluster-id ST010_HEINRICH_ZILLE_STRASSE \
  --n 500 \
  --seed 42
```

**Documentation**: See `src/branitz_heat_decision/economics/economics_readme.md`

---

### Phase 4: Decision ✅ **IMPLEMENTED**

**CLI Module**: `src/branitz_heat_decision/cli/decision.py`  
**Script**: `src/scripts/04_make_decision.py` ⚠️ **DEPRECATED** (use CLI instead)

**Purpose**: Build KPI contracts and apply decision rules to recommend DH or HP

**Key Steps**:
1. **Discover Artifacts**:
   - CHA KPIs: `results/cha/{cluster_id}/cha_kpis.json`
   - DHA KPIs: `results/dha/{cluster_id}/dha_kpis.json`
   - Economics Summary: `results/economics/{cluster_id}/monte_carlo_summary.json`
   - Supports multiple path patterns (nested, flat, fallback order)

2. **Build KPI Contract**:
   - Call `build_kpi_contract()` to create canonical contract structure
   - Validates schema via `ContractValidator`
   - Handles missing KPIs gracefully (marks infeasible with reason codes)

3. **Apply Decision Rules**:
   - Call `decide_from_contract()` with decision rules:
     - **Feasibility Check**: Only feasible option wins
     - **Cost Dominance**: If one option is >5% cheaper, choose it
     - **CO₂ Tiebreaker**: If costs within 5%, use CO₂ emissions
     - **Robustness Classification**: MC win fraction ≥70% = robust, 55-70% = sensitive
   - Returns decision: `DH`, `HP`, or `UNDECIDED`
   - Returns reason codes (e.g., `COST_DOMINANT_DH`, `COST_CLOSE_USE_CO2`, `ROBUST_DECISION`)

4. **Generate Explanation** (optional):
   - LLM explanation (if API key available)
   - Template fallback (if LLM unavailable)
   - Safety checks (hallucination detection, rounding tolerance)

5. **Validate Explanation** (NEW) ⭐ **TNLI Logic Auditor**:
   - **TNLI (Tabular Natural Language Inference) Logic Auditor**: Validates LLM-generated explanations against KPI data
   - **Deterministic Validation**: Rule-based validation of structured claims (100% deterministic, no AI)
   - **Semantic Validation**: LLM-based fact-checking for free-text explanations
   - **Sentence-by-Sentence Validation**: Validates each statement in the explanation individually
   - **Contradiction Detection**: Identifies statements that contradict KPI data
   - **Evidence Extraction**: Provides evidence for each validation result
   - **Feedback Loop**: Optional automatic regeneration of explanations when contradictions are detected
   - **Validation Report**: Comprehensive report with validation status, verified count, contradictions, and sentence-by-sentence results
   - Validation results saved to `decision_{cluster_id}.json` (includes full `validation` field with `sentence_results`)

6. **Save Outputs**:
   - `kpi_contract_{cluster_id}.json` - Canonical KPI contract
   - `decision_{cluster_id}.json` - Decision result with reason codes
   - `explanation_{cluster_id}.md` - Natural language explanation (optional)

**Key Features**:
- **KPI Contract**: Canonical, validated data structure for KPIs
- **Decision Rules**: Deterministic if-then logic with robustness flags
- **Schema Validation**: JSON schema validation via `ContractValidator`
- **Reason Codes**: Comprehensive reason code system (16+ codes)
- **Config Validation**: Decision thresholds configurable (robust/sensitive win fractions, cost threshold)
- **TNLI Logic Auditor** (NEW): Validates LLM explanations against KPI data
  - Prevents hallucinations in decision explanations
  - Sentence-by-sentence validation with evidence
  - Automatic contradiction detection
  - Integration with decision pipeline

**Command Line Arguments**:
- `--cluster-id` (required): Cluster identifier
- `--cha-kpis`: Explicit path to CHA KPIs (optional, auto-discovers)
- `--dha-kpis`: Explicit path to DHA KPIs (optional, auto-discovers)
- `--econ-summary`: Explicit path to economics summary (optional, auto-discovers)
- `--run-dir`: Base results directory (default: `results`)
- `--llm-explanation`: Use LLM explanation (requires API key)
- `--no-fallback`: Fail if LLM unavailable (no template fallback)
- `--explanation-style`: Explanation style (`executive`, `technical`, `detailed`)
- `--config`: Path to decision config JSON (optional)
- `--out-dir`: Output directory (default: `results/decision/{cluster_id}`)

**Outputs**:
- `results/decision/{cluster_id}/kpi_contract_{cluster_id}.json` - Canonical KPI contract
- `results/decision/{cluster_id}/decision_{cluster_id}.json` - Decision result with validation report
  - Includes `validation` field with:
    - `validation_status`: "pass", "warning", or "fail"
    - `overall_confidence`: Confidence score (0.0-1.0)
    - `sentence_results`: Sentence-by-sentence validation results (NEW)
    - `contradictions`: List of detected contradictions
    - `verified_count`, `unverified_count`, `contradiction_count`
- `results/decision/{cluster_id}/explanation_{cluster_id}.md` - Explanation (optional)
- `results/decision/{cluster_id}/explanation_{cluster_id}.html` - HTML explanation (optional)
- `results/decision/{cluster_id}/validation_{cluster_id}.json` (NEW) - Full validation report

**Usage**:
```bash
# Auto-discover artifacts
python -m branitz_heat_decision.cli.decision \
  --cluster-id ST010_HEINRICH_ZILLE_STRASSE

# Explicit artifact paths
python -m branitz_heat_decision.cli.decision \
  --cluster-id ST010_HEINRICH_ZILLE_STRASSE \
  --cha-kpis results/cha/ST010/cha_kpis.json \
  --dha-kpis results/dha/ST010/dha_kpis.json \
  --econ-summary results/economics/ST010/monte_carlo_summary.json

# With LLM explanation
python -m branitz_heat_decision.cli.decision \
  --cluster-id ST010_HEINRICH_ZILLE_STRASSE \
  --llm-explanation \
  --explanation-style executive
```

**Documentation**: See `src/branitz_heat_decision/decision/decision_readme.md`

---

### Phase 5: UHDC (Unified Heat Decision Coordinator) ✅ **IMPLEMENTED**

**CLI Module**: `src/branitz_heat_decision/cli/uhdc.py`  
**Script**: `src/scripts/05_generate_report.py` ⚠️ **DEPRECATED** (use CLI instead)

**Purpose**: Generate comprehensive HTML/Markdown/JSON reports from decision artifacts

**Key Steps**:
1. **Discover Artifacts**:
   - CHA KPIs, DHA KPIs, Economics Summary, KPI Contract, Decision
   - Supports multiple path patterns with fallback order

2. **Build UHDC Report**:
   - Call `build_uhdc_report()` to orchestrate complete report generation
   - Loads all artifacts from discovered paths
   - Builds KPI contract (if not exists)
   - Makes decision (if not exists)
   - Generates explanation (LLM or template)

3. **Generate Reports**:
   - **HTML Report**: `save_reports()` with interactive dashboard:
     - Executive summary with metric cards
     - Technical details table (sortable, filterable)
     - DHA violations detail table
     - Interactive charts (Plotly.js)
     - Embedded maps (CHA velocity/temp/pressure, DHA LV grid)
     - Export options (JSON, CSV, Print)
   - **Markdown Report**: Plain text explanation with KPIs
   - **JSON Report**: Complete report data structure

4. **Discover Maps**:
   - CHA maps: `interactive_map.html`, `interactive_map_temperature.html`, `interactive_map_pressure.html`
   - DHA map: `hp_lv_map.html`
   - Embed as iframes in HTML report

**Key Features**:
- **Artifact Discovery**: Automatic discovery of CHA/DHA/Economics/Decision artifacts
- **Report Generation**: HTML (interactive dashboard), Markdown, JSON
- **LLM Integration**: Gemini API for natural language explanations (optional)
- **Safety Checks**: Hallucination detection, rounding tolerance, template fallback
- **Interactive Dashboard**: Plotly.js charts, DataTables.js tables, embedded maps
- **Standards References**: EN 13941-1 (×3) and VDE-AR-N 4100 (×2) in footer
- **Auditability**: JSON source paths as tooltips for all metrics

**Command Line Arguments**:
- `--cluster-id` (required) or `--all-clusters`: Cluster identifier(s)
- `--run-dir`: Base results directory (default: `results`)
- `--out-dir` (required): Output directory for reports
- `--llm`: Use LLM explanation (if available)
- `--style`: Explanation style (`executive`, `technical`, `detailed`)
- `--format`: Output format (`html`, `md`, `json`, `all`)

**Outputs**:
- `results/uhdc/{cluster_id}/uhdc_report_{cluster_id}.html` - Interactive HTML dashboard
- `results/uhdc/{cluster_id}/uhdc_explanation_{cluster_id}.md` - Markdown explanation
- `results/uhdc/{cluster_id}/uhdc_report_{cluster_id}.json` - JSON report data

**Usage**:
```bash
# Single cluster
python -m branitz_heat_decision.cli.uhdc \
  --cluster-id ST010_HEINRICH_ZILLE_STRASSE \
  --out-dir results/uhdc/ST010 \
  --format all

# All clusters
python -m branitz_heat_decision.cli.uhdc \
  --all-clusters \
  --out-dir results/uhdc_all \
  --format html

# With LLM explanation
python -m branitz_heat_decision.cli.uhdc \
  --cluster-id ST010_HEINRICH_ZILLE_STRASSE \
  --out-dir results/uhdc/ST010 \
  --llm \
  --style executive
```

**Documentation**: See `src/branitz_heat_decision/uhdc/uhdc_readme.md`

---

## Complete Pipeline Execution Example

### Step-by-Step Complete Workflow

```bash
# Step 0: Data Preparation
conda activate branitz_env
python src/scripts/00_prepare_data.py --create-clusters

# Step 1: CHA Pipeline
python src/scripts/01_run_cha.py \
  --cluster-id ST010_HEINRICH_ZILLE_STRASSE \
  --use-trunk-spur \
  --plant-wgs84-lat 51.76274 \
  --plant-wgs84-lon 14.3453979 \
  --disable-auto-plant-siting

# Step 2: DHA Pipeline
python src/scripts/02_run_dha.py \
  --cluster-id ST010_HEINRICH_ZILLE_STRASSE \
  --base-load-source bdew_timeseries \
  --bdew-population-json data/raw/building_population_resultsV6.json

# Step 3: Economics Pipeline
python src/scripts/03_run_economics.py \
  --cluster-id ST010_HEINRICH_ZILLE_STRASSE \
  --n 500 \
  --seed 42

# Step 4: Decision Pipeline
python -m branitz_heat_decision.cli.decision \
  --cluster-id ST010_HEINRICH_ZILLE_STRASSE \
  --llm-explanation \
  --explanation-style executive

# Step 5: UHDC Report Generation
python -m branitz_heat_decision.cli.uhdc \
  --cluster-id ST010_HEINRICH_ZILLE_STRASSE \
  --out-dir results/uhdc/ST010 \
  --format all \
  --llm \
  --style executive
```

---

## Core Components

### 1. Data Layer (`src/branitz_heat_decision/data/`)

**Status**: ✅ **IMPLEMENTED**

**Purpose**: Load, validate, and preprocess geospatial and time-series data

**Key Modules**:
- **`loader.py`**: Smart building loader, street loader, data validation
- **`typology.py`**: Building envelope estimation (TABULA/U-values)
- **`profiles.py`**: Hourly heat profile generation (8760 hours)
- **`cluster.py`**: Street-based cluster creation, profile aggregation, design/top-N computation

**Documentation**: See `src/branitz_heat_decision/data/data_readme.md`

---

### 2. CHA Agent (`src/branitz_heat_decision/cha/`)

**Status**: ✅ **IMPLEMENTED**

**Purpose**: Analyze district heating network feasibility and performance

**Key Modules**:
- **`network_builder_trunk_spur.py`**: Trunk-spur network builder (recommended)
  - **Design Margin (NEW)**: Applies 25% design margin to pipe sizing for robustness
  - Conservative velocity limits (1.2 m/s) for improved robustness validation
- **`network_builder.py`**: Standard network builder
- **`convergence_optimizer_spur.py`**: Spur-specific convergence optimizer
- **`convergence_optimizer.py`**: Standard convergence optimizer
- **`kpi_extractor.py`**: EN 13941-1 KPIs extraction
- **`sizing_catalog.py`**: Pipe sizing from technical catalog
- **`heat_loss.py`**: Pipe heat loss calculation (linear + thermal resistance)
- **`qgis_export.py`**: Interactive maps (velocity/temp/pressure) and QGIS exports
- **`hydraulic_checks.py`** (NEW): Context-aware hydraulic validation
  - Automatically detects trunk-spur networks
  - Provides context-aware warnings explaining expected behavior
  - Low velocity pipes: Explains return pipes and spurs naturally have lower flow
  - Flow distribution imbalance: Explains high CV is a design feature, not a flaw
- **`design_validator.py`** (NEW): Comprehensive design validation system
  - Geospatial validation (building connectivity, network topology)
  - Hydraulic validation (EN 13941-1 with context-aware warnings)
  - Thermal validation (temperature distribution, heat losses)
  - Robustness validation (Monte Carlo uncertainty analysis, 50 scenarios)
- **`config.py`**: CHA configuration

**Network Topology**:
- **Trunk-Spur Topology**: Radial spanning tree from plant with service connections
- **Dual-Network Structure**: Separate supply and return networks
- **Heat Consumers**: `pp.create_heat_consumer()` with `qext_w` and `controlled_mdot`
- **Fixed Plant Location**: WGS84 coordinates (default: Cottbus CHP)

**Documentation**: See `src/branitz_heat_decision/cha/cha_readme.md`

---

### 3. DHA Agent (`src/branitz_heat_decision/dha/`)

**Status**: ✅ **IMPLEMENTED**

**Purpose**: Analyze LV power grid hosting capacity for heat pumps

**Key Modules**:
- **`grid_builder.py`**: LV grid builder (Option 2: MV/LV transformer)
- **`mapping.py`**: Building-to-bus spatial mapping
- **`base_loads.py`**: Base electrical load loading (scenario JSON)
- **`bdew_base_loads.py`**: BDEW base load generation (time series)
- **`loadflow.py`**: Powerflow simulation (balanced or unbalanced)
- **`kpi_extractor.py`**: VDE-AR-N 4100 KPIs extraction
- **`export.py`**: GeoJSON and interactive map export
- **`config.py`**: DHA configuration

**Grid Topology**:
- **MV/LV Boundary (Option 2)**: ext_grid at MV (20 kV), transformers to LV (0.4 kV)
- **Base Electrical Loads**: Normal household/commercial demand (P_base + P_hp)
- **BDEW Integration**: Standardized load profiles (H0, G0-G6, L0, Y1)

**Documentation**: See `src/branitz_heat_decision/dha/dha_readme.md`

---

### 4. Economics Agent (`src/branitz_heat_decision/economics/`)

**Status**: ✅ **IMPLEMENTED**

**Purpose**: Calculate Levelized Cost of Heat (LCOH) and CO₂ emissions with Monte Carlo uncertainty

**Key Modules**:
- **`params.py`**: Economic parameters (CAPEX, O&M, fuel costs, discount rate)
- **`lcoh.py`**: LCOH calculation (CRF method)
- **`co2.py`**: CO₂ emissions calculation
- **`monte_carlo.py`**: Monte Carlo uncertainty propagation (N=500)
- **`utils.py`**: Economic utilities

**Key Features**:
- **CRF Method**: Capital Recovery Factor for LCOH calculation
- **Monte Carlo Simulation**: N=500 samples with bounded parameter distributions
- **Win Fractions**: Probabilistic robustness metrics (dh_wins_fraction, hp_wins_fraction)

**Documentation**: See `src/branitz_heat_decision/economics/economics_readme.md`

---

### 5. Decision Agent (`src/branitz_heat_decision/decision/`)

**Status**: ✅ **IMPLEMENTED**

**Purpose**: Build KPI contracts and apply decision rules to recommend DH or HP

**Key Modules**:
- **`schemas.py`**: KPI contract JSON schemas and validation
- **`kpi_contract.py`**: KPI contract builder
- **`rules.py`**: Decision rules engine (deterministic if-then logic)

**Key Features**:
- **KPI Contract**: Canonical, validated data structure for KPIs
- **Decision Rules**: Deterministic if-then logic with robustness flags
- **Reason Codes**: Comprehensive reason code system (16+ codes)
- **Config Validation**: Decision thresholds configurable
- **TNLI Logic Auditor Integration** (NEW): Validates LLM explanations against KPI data

**Documentation**: See `src/branitz_heat_decision/decision/decision_readme.md`

---

### 5.5. Validation Module (`src/branitz_heat_decision/validation/`) ⭐ **NEW**

**Status**: ✅ **IMPLEMENTED**

**Purpose**: TNLI (Tabular Natural Language Inference) Logic Auditor - Validates LLM-generated decision explanations against KPI data to prevent hallucinations

**Key Modules**:
- **`logic_auditor.py`**: Main validation orchestrator
- **`tnli_model.py`**: LLM-based semantic validation (Gemini API)
- **`claims.py`**: Deterministic structured claim validation
- **`feedback_loop.py`**: Automatic regeneration handler
- **`monitoring.py`**: Metrics and performance monitoring
- **`config.py`**: Validation configuration

**Key Features**:
- **Deterministic Validation**: Rule-based validation of structured claims (100% deterministic, no AI)
- **Semantic Validation**: LLM-based fact-checking for free-text explanations
- **Sentence-by-Sentence Validation**: Validates each statement individually with evidence
- **Contradiction Detection**: Identifies statements that contradict KPI data
- **Feedback Loop**: Optional automatic regeneration of explanations when contradictions are detected
- **Validation Report**: Comprehensive report with:
  - Validation status: "pass", "warning", or "fail"
  - Overall confidence score (0.0-1.0)
  - Sentence-by-sentence results with evidence
  - Contradiction details with evidence
  - Verified/unverified/contradiction counts

**Integration**:
- **Called by**: `cli/decision.py` (after explanation generation)
- **Uses**: KPI contract data, decision result, LLM explanation
- **Outputs**: Validation report → `decision_{cluster_id}.json` (includes full validation data)

**Documentation**: See `src/branitz_heat_decision/validation/LOGIC_AUDITOR_WORKFLOW.md`

---

### 6. UHDC Coordinator (`src/branitz_heat_decision/uhdc/`)

**Status**: ✅ **IMPLEMENTED**

**Purpose**: Constrained LLM coordinator for explainable decision-making and report generation

**Key Modules**:
- **`io.py`**: Artifact I/O operations
- **`orchestrator.py`**: Pipeline orchestration (artifact discovery, contract building, decision, explanation)
- **`explainer.py`**: LLM explainer (Gemini API) with safety checks
- **`report_builder.py`**: HTML/Markdown/JSON report generation

**Key Features**:
- **Artifact Discovery**: Automatic discovery of CHA/DHA/Economics/Decision artifacts
- **LLM Integration**: Gemini API for natural language explanations (optional)
- **Safety Checks**: Hallucination detection, rounding tolerance, template fallback
- **Interactive Dashboard**: Plotly.js charts, DataTables.js tables, embedded maps
- **Standards References**: EN 13941-1 (×3) and VDE-AR-N 4100 (×2) in footer

**Documentation**: See `src/branitz_heat_decision/uhdc/uhdc_readme.md`

---

### 7. CLI Module (`src/branitz_heat_decision/cli/`)

**Status**: ✅ **IMPLEMENTED**

**Purpose**: Command-line interfaces for Decision, Economics, and UHDC pipelines

**Key Modules**:
- **`decision.py`**: Decision pipeline CLI
- **`economics.py`**: Economics pipeline CLI
- **`uhdc.py`**: UHDC report generation CLI

**Key Features**:
- **Artifact Auto-Discovery**: Automatic discovery of pipeline artifacts
- **Batch Processing**: Support for `--all-clusters` mode
- **LLM Status**: Shows API key status (enabled/disabled/warning)
- **Error Handling**: Clear error messages and validation

**Documentation**: See `src/branitz_heat_decision/cli/cli_readme.md`

---

## Street-Based Clustering

### Concept

Clusters are defined by **streets** in the geodata. Each street forms a cluster, and buildings are assigned to clusters based on their street addresses.

### Cluster ID Format

```
ST{number}_{STREET_NAME}
```

Examples:
- `ST010_HEINRICH_ZILLE_STRASSE`
- `ST001_AN_DEN_WEINBERGEN`
- `ST002_AN_DER_BAHN`
- `ST290_STREET_817`

### Cluster Creation Process

1. **Load buildings with addresses** (`hausumringe_mit_adressenV3.geojson`)
2. **Filter to residential with heat demand**
3. **Load streets** (`strassen_mit_adressenV3_fixed.geojson`)
4. **Enrich buildings** (Branitzer attributes, gebaeudeanalyse, TABULA/U-values)
5. **Match buildings to streets** (address-based + spatial fallback)
6. **Create clusters** (group by street, generate cluster IDs, calculate plant locations)
7. **Generate hourly profiles** (8760 hours per building)
8. **Compute design/top-N hours** (design hour = peak load, top-N = top N hours)

### Files

- **`building_cluster_map.parquet`**: Maps `building_id` → `cluster_id`
- **`street_clusters.parquet`**: Cluster metadata (street_id, plant coordinates, building counts)
- **`cluster_design_topn.json`**: Design hour and top-N hours per cluster

---

## Network Topology

### Trunk-Spur Topology

The system implements a **trunk-spur topology** with the following characteristics:

1. **Trunk**: Main distribution network along streets
   - Supply trunk: Plant → Building1 → Building2 → ... → Last Building (radial spanning tree)
   - Return trunk: Last Building → ... → Building2 → Building1 → Plant (reverse)
   - Trunk is a **radial spanning tree** rooted at the plant

2. **Spurs**: Service connections from trunk to buildings
   - Each building has exclusive trunk tee nodes (created by edge splitting)
   - Service pipes connect buildings to trunk at tee nodes
   - No `trunk_conn_*` pipes (direct tee connections)

3. **Dual-Network Structure**:
   - Separate supply and return junctions for each trunk node
   - Separate supply and return pipes for each trunk edge
   - Proper flow directions (supply forward, return reverse)

4. **Street-Based**:
   - Trunk only runs on streets where buildings are located
   - Street filtering by name (primary) and spatial (secondary)
   - Plant sited on a nearby different street (unless fixed via WGS84 coordinates)

5. **Heat Consumers**:
   - Each building uses `pp.create_heat_consumer()` with `qext_w` and `controlled_mdot`
   - No sinks or sources for buildings (mass conservation)
   - Return temperature becomes a result (depends on network conditions and losses)

6. **Plant Boundary**:
   - Exactly one `ext_grid` at plant supply (p, T)
   - Circulation pump from return → supply (Δp only)
   - No `ext_grid` at plant return (avoids over-constraining)

See `docs/topology.md` for complete topology documentation.

---

## Key Technologies

### Simulation Engines

- **pandapipes** (v0.8.0+): Hydraulic-thermal network simulation
  - Newton-Raphson solver
  - Pipe flow calculations
  - Temperature distribution
  - Heat loss modeling (`u_w_per_m2k`, `text_k`)
  
- **pandapower** (v2.13.0+): Electrical power flow
  - Load flow analysis
  - Voltage drop calculations
  - Three-phase support (balanced and unbalanced)

### Geospatial

- **geopandas** (v0.14.0+): GeoDataFrames, spatial operations
- **shapely** (v2.0.0+): Geometric operations
- **pyproj**: Coordinate transformations
- **folium** (v0.15.0+): Interactive maps
- **branca**: Map styling

### Data Processing

- **pandas** (v2.0.0+): DataFrames, time-series
- **numpy** (v1.24.0+): Numerical operations
- **networkx**: Graph algorithms (topology, shortest paths)

### Machine Learning (Optional)

- **google-genai** (v0.3.0+): Gemini API for LLM explanations
- **python-dotenv**: Environment variable loading

### Web Technologies (Reports)

- **Plotly.js**: Interactive charts
- **DataTables.js**: Sortable, filterable tables
- **Bootstrap 5**: Responsive UI components

### Standards Compliance

- **EN 13941-1**: District heating network design
  - Velocity limits: v ≤ 1.5 m/s (for 95% of pipes)
  - Pressure drop: Δp ≤ 0.3 bar/100m
  - Compliance checking in KPI extractor
  - Heat loss modeling standards

- **VDE-AR-N 4100**: LV grid voltage limits
  - Voltage band: 0.9 pu ≤ v ≤ 1.1 pu
  - Line loading: ≤ 100% operational
  - Compliance checking in DHA KPI extractor

---

## Configuration

### Environment Variables

- `BRANITZ_DATA_ROOT`: Path to data directory (default: `project_root/data`)
- `GOOGLE_API_KEY`: Gemini API key for LLM explanations (optional)
- `GOOGLE_MODEL`: Gemini model name (default: `gemini-2.0-flash`)
- `LLM_TIMEOUT`: LLM API timeout in seconds (default: 30)
- `UHDC_FORCE_TEMPLATE`: Force template mode (skip LLM) (default: false)
- `UHDC_LOG_LEVEL`: Logging level for UHDC (default: INFO)
- `UHDC_TEMPLATE_DIR`: Template directory path (optional)

### Configuration Files

- **`src/branitz_heat_decision/config.py`**: Centralized paths and settings
- **`src/branitz_heat_decision/cha/config.py`**: CHA-specific configuration
  - Supply/return temperatures
  - Pressure settings
  - Velocity/pressure drop limits
  - Heat loss parameters
  - Plant location (WGS84 coordinates)
- **`src/branitz_heat_decision/dha/config.py`**: DHA-specific configuration
  - MV/LV transformer parameters
  - Voltage limits
  - Line loading limits
  - BDEW paths
- **`src/branitz_heat_decision/config/validation_standards.py`** (NEW): Validation configuration
  - EN 13941-1 standards (velocity, pressure, temperature, heat loss limits)
  - Geospatial tolerances (street alignment, building connectivity)
  - Robustness thresholds (Monte Carlo scenarios, variation ranges)
  - Validation strictness settings
- **`src/branitz_heat_decision/validation/config.py`** (NEW): TNLI Logic Auditor configuration
  - TNLI model settings
  - Validation thresholds
  - Feedback loop settings
- **`config/decision_config_*.json`**: Decision rules configuration
  - Robust/sensitive win fraction thresholds
  - Cost dominance threshold
  - CO₂ tiebreaker settings

### Cluster Configuration

- **`data/processed/street_clusters.parquet`**: Cluster metadata
- **`data/processed/cluster_design_topn.json`**: Design loads per cluster

---

## Validation Systems

The system includes **two complementary validation systems**:

### 1. CHA Design Validation System

**Location**: `src/branitz_heat_decision/cha/design_validator.py`

**Purpose**: Validates district heating network design against engineering standards

**Validation Categories**:
1. **Geospatial Validation**:
   - Building connectivity (all buildings connected to network)
   - Network topology (single connected component)
   - Street alignment (pipes follow streets)
   - Service pipe lengths (within limits)

2. **Hydraulic Validation** (EN 13941-1):
   - Velocity limits (≤1.5 m/s recommended, ≤3.0 m/s absolute)
   - Minimum velocity (≥0.2 m/s to avoid sedimentation)
   - Pressure limits (1.0-16.0 bar)
   - Pressure drops (≤1.0 bar/km, ≤2.0 bar total)
   - Pump power (≤30 W/kW_th)
   - Flow distribution (coefficient of variation)
   - **Context-Aware Warnings**: Automatically detects trunk-spur networks and explains expected behavior

3. **Thermal Validation**:
   - Heat losses (≤5% recommended, ≤10% absolute)
   - Supply/return temperatures (within limits)
   - Temperature decay (along network)

4. **Robustness Validation**:
   - Monte Carlo uncertainty analysis (50 scenarios)
   - Demand variation: ±20%
   - Temperature variation: ±5°C
   - Flow variation: ±15%
   - Success rate threshold: ≥95%

**Outputs**:
- `design_validation.json`: Complete validation report
- `design_validation_summary.txt`: Human-readable summary
- `design_validation_metrics.csv`: Metrics in CSV format

**Documentation**: See `src/branitz_heat_decision/cha/DESIGN_VALIDATION_EXPLAINED.md`

---

### 2. TNLI Logic Auditor (Decision Explanation Validation)

**Location**: `src/branitz_heat_decision/validation/logic_auditor.py`

**Purpose**: Validates LLM-generated decision explanations against KPI data to prevent hallucinations

**Validation Methods**:
1. **Deterministic Validation**:
   - Rule-based validation of structured claims
   - 100% deterministic (no AI)
   - Validates numerical comparisons, ranges, thresholds

2. **Semantic Validation**:
   - LLM-based fact-checking (Gemini API)
   - Validates free-text explanations
   - Sentence-by-sentence validation with evidence

3. **Contradiction Detection**:
   - Identifies statements that contradict KPI data
   - Provides evidence for each contradiction
   - Confidence scores for each validation result

4. **Feedback Loop** (optional):
   - Automatic regeneration of explanations when contradictions detected
   - Iterative improvement with context

**Integration**:
- **Called by**: `cli/decision.py` (after explanation generation)
- **Inputs**: KPI contract, decision result, LLM explanation
- **Outputs**: Validation report → `decision_{cluster_id}.json` (includes full validation data)

**Validation Report Structure**:
```json
{
  "validation_status": "pass" | "warning" | "fail",
  "overall_confidence": 0.0-1.0,
  "statements_validated": N,
  "verified_count": N,
  "unverified_count": N,
  "contradiction_count": N,
  "sentence_results": [
    {
      "statement": "...",
      "status": "ENTAILMENT" | "CONTRADICTION" | "NEUTRAL",
      "confidence": 0.0-1.0,
      "evidence": "...",
      "label": "ENTAILMENT" | "CONTRADICTION" | "NEUTRAL"
    }
  ],
  "contradictions": [...]
}
```

**Documentation**: See `src/branitz_heat_decision/validation/LOGIC_AUDITOR_WORKFLOW.md`

---

## Standards Compliance

### EN 13941-1 (District Heating)

**Velocity Limits**:
- 95% of pipes must have v ≤ 1.5 m/s
- Maximum velocity: v ≤ 2.5 m/s (absolute limit)

**Pressure Drop Limits**:
- Maximum pressure drop: Δp ≤ 0.3 bar/100m (design limit)
- Pressure drop limit: 100-300 Pa/m for trunk, 100-500 Pa/m for service

**Heat Loss Modeling**:
- Linear heat loss method: `q'` [W/m]
- Thermal resistance method: `U` [W/m²K] via thermal resistances
- Area convention: `A_eff = d_o` (default) or `A_eff = π × d_o`

**Compliance Checking**:
- Implemented in `kpi_extractor.py`
- Reports compliance status in KPIs
- Provides detailed pipe-level metrics

### VDE-AR-N 4100 (LV Grid)

**Voltage Band**:
- Minimum voltage: v_min ≥ 0.9 pu
- Maximum voltage: v_max ≤ 1.1 pu
- Planning warnings: v_min < 0.92 pu or v_max > 1.08 pu

**Line Loading**:
- Operational limit: ≤ 100% loading
- Planning warnings: > 80% loading

**Compliance Checking**:
- Implemented in `dha/kpi_extractor.py`
- Reports violations in KPIs
- Provides detailed violations CSV

---

## Current Implementation Status

### ✅ **IMPLEMENTED** (All Phases Complete)

#### Phase 0: Data Preparation ✅
- Smart building loader with filtering
- Residential building filtering
- CRS transformation
- Building enrichment (Branitzer, gebaeudeanalyse, TABULA)
- Street-based cluster creation
- Hourly heat profile generation (8760 hours)
- Design hour and top-N hours computation

#### Phase 1: CHA Agent ✅
- Trunk-spur network builder (dual-network structure)
- Standard network builder
- Spur-specific convergence optimizer
- Standard convergence optimizer
- EN 13941-1 KPI extraction
- Pipe sizing from technical catalog
- **Design margin (25%) for robustness** (NEW)
- Heat loss calculation (linear + thermal resistance)
- Interactive map generation (velocity/temp/pressure with cascading colors)
- QGIS export (separated layers)
- Convergence tracking
- Fixed plant location (WGS84 coordinates)
- **Comprehensive design validation system** (NEW)
  - Geospatial validation (building connectivity, network topology)
  - Hydraulic validation (EN 13941-1 with context-aware warnings)
  - Thermal validation (temperature distribution, heat losses)
  - Robustness validation (Monte Carlo uncertainty analysis, 50 scenarios)
- **Context-aware validation warnings** (NEW)
  - Automatically detects trunk-spur networks
  - Provides context-aware warnings explaining expected behavior

#### Phase 2: DHA Agent ✅
- LV grid builder (Option 2: MV/LV transformer)
- Building-to-bus spatial mapping
- Base electrical load loading (scenario JSON)
- BDEW base load generation (time series)
- Powerflow simulation (balanced and unbalanced)
- VDE-AR-N 4100 KPI extraction
- Violations tracking (voltage and line loading)
- GeoJSON export (buses, lines)
- Interactive map generation (cascading colors)

#### Phase 3: Economics Agent ✅
- LCOH calculation (CRF method) for DH and HP
- CO₂ emissions calculation for DH and HP
- Monte Carlo uncertainty propagation (N=500)
- Win fraction calculations (dh_wins_fraction, hp_wins_fraction)
- Quantile extraction (p05, p50, p95)

#### Phase 4: Decision Agent ✅
- KPI contract builder (canonical, validated structure)
- Decision rules engine (deterministic if-then logic)
- Schema validation (JSON schema)
- Reason code system (16+ codes)
- Config validation
- Robustness classification (robust/sensitive)
- **TNLI Logic Auditor integration** (NEW)
  - Validates LLM explanations against KPI data
  - Sentence-by-sentence validation with evidence
  - Contradiction detection and reporting
  - Full validation report in decision output

#### Phase 5: UHDC Coordinator ✅
- Artifact discovery (automatic, multiple path patterns)
- LLM explainer (Gemini API with safety checks)
- Template fallback (if LLM unavailable)
- Report generation (HTML interactive dashboard, Markdown, JSON)
- Interactive dashboard (Plotly.js charts, DataTables.js tables, embedded maps)
- Standards references (EN 13941-1 ×3, VDE-AR-N 4100 ×2)

### 🔄 **ENHANCEMENTS** (Future Work)

1. **Network Convergence**: Further improvements to convergence algorithms
2. **Batch Processing**: Process multiple clusters in parallel
3. **API Server**: REST API for pipeline access
4. **Report Customization**: Custom report templates and styling
5. **Performance Optimization**: Caching, parallel processing
6. **Extended Standards**: Additional compliance checks (e.g., EN 15316)

---

## Usage Examples

### Complete Pipeline Execution

```bash
# Step 0: Data Preparation
conda activate branitz_env
python src/scripts/00_prepare_data.py --create-clusters

# Step 1: CHA Pipeline
python src/scripts/01_run_cha.py \
  --cluster-id ST010_HEINRICH_ZILLE_STRASSE \
  --use-trunk-spur \
  --plant-wgs84-lat 51.76274 \
  --plant-wgs84-lon 14.3453979 \
  --disable-auto-plant-siting

# Step 2: DHA Pipeline
python src/scripts/02_run_dha.py \
  --cluster-id ST010_HEINRICH_ZILLE_STRASSE \
  --base-load-source bdew_timeseries \
  --bdew-population-json data/raw/building_population_resultsV6.json

# Step 3: Economics Pipeline
python src/scripts/03_run_economics.py \
  --cluster-id ST010_HEINRICH_ZILLE_STRASSE \
  --n 500 \
  --seed 42

# Step 4: Decision Pipeline
python -m branitz_heat_decision.cli.decision \
  --cluster-id ST010_HEINRICH_ZILLE_STRASSE \
  --llm-explanation \
  --explanation-style executive

# Step 5: UHDC Report Generation
python -m branitz_heat_decision.cli.uhdc \
  --cluster-id ST010_HEINRICH_ZILLE_STRASSE \
  --out-dir results/uhdc/ST010 \
  --format all \
  --llm \
  --style executive
```

---

## Output Formats

### CHA Outputs

**KPIs (JSON)**:
- `cha_kpis.json`: EN 13941-1 compliance KPIs, topology statistics, convergence status
- Structure: `en13941_compliance`, `aggregate`, `losses`, `pump`, `detailed`, `topology`, `convergence`

**Design Validation (JSON)** (NEW):
- `design_validation.json`: Comprehensive design validation report
  - Overall status: `PASS`, `PASS_WITH_WARNINGS`, or `FAIL`
  - Individual check results (geospatial, hydraulic, thermal, robustness)
  - All issues and warnings (with context-aware explanations)
  - Comprehensive metrics (velocity, pressure, heat loss, robustness success rate)
- `design_validation_summary.txt`: Human-readable validation summary
- `design_validation_metrics.csv`: Validation metrics in CSV format

**Interactive Maps (HTML)**:
- `interactive_map.html`: Velocity map with cascading red/blue colors
- `interactive_map_temperature.html`: Temperature map with cascading red/blue colors
- `interactive_map_pressure.html`: Pressure map with cascading red/blue colors
- Features: Separate supply/return layers, pipe sizing by line thickness, building markers, plant marker

**CSV Exports**:
- `pipe_velocities_supply_return.csv`: Pipe velocities with min/max scaling and hex colors
- `pipe_velocities_supply_return_with_temp.csv`: Velocities + temperatures with scaling and colors
- `pipe_velocities_plant_to_plant_main_path.csv`: Main path velocities
- `pipe_pressure_supply_return.csv`: Pressure data with scaling and colors

**Network Topology**:
- `network.pickle`: Complete pandapipes network object

---

### DHA Outputs

**KPIs (JSON)**:
- `dha_kpis.json`: VDE-AR-N 4100 compliance KPIs
- Structure: `kpis` (feasible, reasons, max_feeder_loading_pct, voltage_violations_total, line_violations_total)

**GeoJSON Exports**:
- `buses_results.geojson`: Bus voltage results
- `lines_results.geojson`: Line loading results

**Violations CSV**:
- `violations.csv`: Detailed violations table (hour, type, element, value, limit, severity)

**Interactive Map**:
- `hp_lv_map.html`: LV grid map with cascading colors by voltage/loading

---

### Economics Outputs

**Deterministic Results (JSON)**:
- `economics_deterministic.json`: Deterministic LCOH and CO₂ for DH and HP

**Monte Carlo Results**:
- `monte_carlo_summary.json`: Monte Carlo summary (quantiles p05/p50/p95, win fractions)
- `monte_carlo_samples.parquet`: All 500 Monte Carlo samples

---

### Decision Outputs

**KPI Contract (JSON)**:
- `kpi_contract_{cluster_id}.json`: Canonical, validated KPI contract structure

**Decision Result (JSON)**:
- `decision_{cluster_id}.json`: Decision result (choice: DH/HP/UNDECIDED, robust, reason_codes, metrics_used)
  - **Includes `validation` field** (NEW) with TNLI Logic Auditor results:
    - `validation_status`: "pass", "warning", or "fail"
    - `overall_confidence`: Confidence score (0.0-1.0)
    - `sentence_results`: Array of sentence-by-sentence validation results
      - Each result includes: `statement`, `status` (ENTAILMENT/CONTRADICTION/NEUTRAL), `confidence`, `evidence`, `label`
    - `contradictions`: List of detected contradictions with evidence
    - `verified_count`, `unverified_count`, `contradiction_count`
    - `statements_validated`: Total number of statements validated

**Explanation (Markdown)** (optional):
- `explanation_{cluster_id}.md`: Natural language explanation (LLM or template)

---

### UHDC Outputs

**HTML Report**:
- `uhdc_report_{cluster_id}.html`: Interactive HTML dashboard with:
  - Executive summary with metric cards
  - Technical details table (sortable, filterable)
  - DHA violations detail table
  - Interactive charts (Plotly.js)
  - Embedded maps (CHA velocity/temp/pressure, DHA LV grid)
  - Export options (JSON, CSV, Print)
  - Standards references (EN 13941-1 ×3, VDE-AR-N 4100 ×2)

**Markdown Report**:
- `uhdc_explanation_{cluster_id}.md`: Plain text explanation with KPIs

**JSON Report**:
- `uhdc_report_{cluster_id}.json`: Complete report data structure

---

## Known Limitations and Future Work

### Current Limitations

1. **Network Convergence**: Some networks may not converge despite optimization (requires manual intervention)
2. **Test Data**: Some test clusters may have connectivity issues
3. **LLM Dependency**: LLM explanations require API key (template fallback available)
4. **Performance**: Monte Carlo simulation can be slow for large parameter spaces (N=500)
5. **Batch Processing**: Multi-cluster processing not yet optimized

### Recent Improvements

#### v3.1 (2026-01-24)
1. ✅ **Design Validation System**: Comprehensive validation with geospatial, hydraulic, thermal, and robustness checks
2. ✅ **Context-Aware Warnings**: Automatically detects trunk-spur networks and provides context-aware warnings
3. ✅ **Design Margin**: 25% design margin applied to pipe sizing for improved robustness
4. ✅ **Robustness Validation**: Monte Carlo uncertainty analysis (50 scenarios) with success rate tracking
5. ✅ **TNLI Logic Auditor**: Validates LLM explanations against KPI data to prevent hallucinations
   - Sentence-by-sentence validation with evidence
   - Contradiction detection and reporting
   - Integration with decision pipeline
6. ✅ **Validation Documentation**: Complete documentation for validation system and troubleshooting

#### v3.0 (2026-01-16)
1. ✅ **Complete Pipeline**: All phases (0-5) fully implemented
2. ✅ **DHA Integration**: LV grid hosting analysis with BDEW base loads
3. ✅ **Economics Integration**: LCOH, CO₂, Monte Carlo uncertainty
4. ✅ **Decision Integration**: KPI contracts, decision rules, robustness classification
5. ✅ **UHDC Integration**: LLM explanations, interactive dashboard reports
6. ✅ **Heat Loss Modeling**: Linear and thermal resistance methods
7. ✅ **Pipe Sizing**: Role-based velocity limits, downstream-demand sizing
8. ✅ **Fixed Plant Location**: WGS84 coordinates support
9. ✅ **Interactive Maps**: Velocity, temperature, pressure maps with cascading colors
10. ✅ **Standards Compliance**: EN 13941-1 and VDE-AR-N 4100 validation

### Future Enhancements

1. **Performance Optimization**: Parallel processing, caching, incremental updates
2. **Extended Standards**: Additional compliance checks (e.g., EN 15316)
3. **API Server**: REST API for pipeline access
4. **Batch Processing**: Optimized multi-cluster processing
5. **Report Customization**: Custom report templates and styling
6. **Network Convergence**: Further improvements to convergence algorithms
7. **Extended Metrics**: Additional KPIs and visualizations

---

## Troubleshooting

### Common Issues

1. **Convergence failures**: 
   - Use `--optimize-convergence` flag
   - Check network topology in interactive map
   - Review convergence logs in `cha_kpis.json`

2. **Missing data**: 
   - Check data paths in `config.py`
   - Verify `BRANITZ_DATA_ROOT` environment variable
   - Run `00_prepare_data.py --create-clusters` first

3. **CRS mismatches**: 
   - System auto-transforms, but verify input CRS
   - Check for geographic CRS (EPSG:4326) in input data

4. **Cluster not found**: 
   - Verify cluster ID exists in `street_clusters.parquet`
   - Check cluster ID format: `ST{number}_{STREET_NAME}`

5. **LLM unavailable**: 
   - Create `.env` file with `GOOGLE_API_KEY`
   - System automatically falls back to template explanation
   - Check API key status with `--llm-explanation` flag

6. **Negative pressures**: 
   - Increase `system_pressure_bar` (default: 8 bar)
   - Increase `plift_bar` (default: 2-4 bar)
   - Check for pressure violations in KPIs

7. **DHA violations**: 
   - Review `violations.csv` for detailed violation list
   - See `docs/dha_violation_mitigation_strategies.md` for mitigation strategies

### Debugging

- Enable verbose logging: `--verbose` flag
- Check convergence status in `cha_kpis.json`
- Inspect network: Load `network.pickle` and examine structure
- Review logs: Check console output for warnings/errors
- View interactive maps: Check network topology visualization
- Validate contracts: Use `ContractValidator.validate()` on KPI contracts

---

## Documentation

### Comprehensive Module Documentation

Each module has comprehensive documentation:

- **`src/branitz_heat_decision/data/data_readme.md`**: Complete data module documentation
- **`src/branitz_heat_decision/cha/cha_readme.md`**: Complete CHA module documentation
  - Includes new sections: `hydraulic_checks.py`, `design_validator.py`, design margin feature
  - Documentation files: `DESIGN_VALIDATION_EXPLAINED.md`, `VALIDATION_WARNINGS_EXPLAINED.md`, `HOW_TO_FIX_VALIDATION_ISSUES.md`, `WARNING_MITIGATION_OPTIONS.md`
- **`src/branitz_heat_decision/dha/dha_readme.md`**: Complete DHA module documentation
- **`src/branitz_heat_decision/economics/economics_readme.md`**: Complete economics module documentation
- **`src/branitz_heat_decision/decision/decision_readme.md`**: Complete decision module documentation
- **`src/branitz_heat_decision/validation/LOGIC_AUDITOR_WORKFLOW.md`**: Complete TNLI Logic Auditor documentation (NEW)
- **`src/branitz_heat_decision/validation/INTEGRATION_GUIDE.md`**: Integration guide for validation system (NEW)
- **`src/branitz_heat_decision/uhdc/uhdc_readme.md`**: Complete UHDC module documentation
- **`src/branitz_heat_decision/cli/cli_readme.md`**: Complete CLI module documentation
- **`src/scripts/scripts_readme.md`**: Complete scripts module documentation

### Data Documentation

- **`data/raw/raw_readme.md`**: Complete raw data documentation
- **`data/processed/processed_readme.md`**: Complete processed data documentation

### Test Documentation

- **`tests/test_readme.md`**: Complete test documentation (critical tests vs. unit tests)

### Additional Documentation

- **`docs/topology.md`**: Complete network topology creation guide
- **`docs/network_building_issues_analysis.md`**: Network building fixes and improvements
- **`docs/trunk_topology_issues_analysis.md`**: Trunk topology analysis
- **`docs/architecture.md`**: System architecture
- **`docs/api_reference.md`**: API reference
- **`docs/decision_pipeline.md`**: Decision pipeline guide
- **`docs/dha_violation_mitigation_strategies.md`**: DHA violation mitigation strategies
- **`docs/economics_phase4_checklist.md`**: Economics implementation checklist

---

## Dependencies

### Core Scientific

- pandas >= 2.0.0
- numpy >= 1.24.0
- scipy >= 1.10.0

### Geospatial

- geopandas >= 0.14.0
- shapely >= 2.0.0
- pyproj >= 3.5.0
- folium >= 0.15.0
- branca >= 0.7.0

### Energy Simulation

- pandapipes >= 0.8.0
- pandapower >= 2.13.0

### Machine Learning (Optional)

- google-genai >= 0.3.0 (for UHDC LLM explanations)
- python-dotenv >= 1.0.0 (for environment variable loading)

### Testing & Development

- pytest >= 7.4.0
- pytest-cov >= 4.1.0
- black >= 23.0.0
- flake8 >= 6.0.0
- mypy >= 1.0.0

---

## Installation

### Prerequisites

- Conda (Miniconda or Anaconda)
- Git

### Setup

```bash
# Clone repository
git clone <repository-url>
cd branitz_heat_decision

# Create conda environment
conda env create -f environment.yml
conda activate branitz_env  # Check environment.yml for exact name

# Verify installation
python -c "import pandas, geopandas, pandapipes, pandapower; print('OK')"
```

### Environment Configuration

**Set data root** (optional):
```bash
export BRANITZ_DATA_ROOT=/path/to/your/data
```

**Configure LLM** (optional, for UHDC explanations):
```bash
# Create .env file (never commit this file)
echo 'GOOGLE_API_KEY=your_key_here' > .env
echo 'GOOGLE_MODEL=gemini-2.0-flash' >> .env
echo 'LLM_TIMEOUT=30' >> .env
```

**Verify LLM setup**:
```bash
python -c "from branitz_heat_decision.uhdc.explainer import LLM_AVAILABLE; print('LLM ready:', LLM_AVAILABLE)"
```

---

## Data Requirements

### Input Data Format

**Buildings** (`data/raw/hausumringe_mit_adressenV3.geojson`):
- Geometry: Polygon/MultiPolygon (EPSG:4326 or EPSG:25833)
- Required: `building_id` (or auto-generated), `adressen` (address data)
- Optional: `floor_area_m2`, `year_of_construction`, `annual_heat_demand_kwh_a`, `use_type`

**Streets** (`data/raw/strassen_mit_adressenV3_fixed.geojson`):
- Geometry: LineString/MultiLineString (EPSG:4326 or EPSG:25833)
- Required: Street identifier (`street_name`, `name`, or `id`)
- Optional: Street attributes

**Weather** (`data/processed/weather.parquet`):
- Hourly time series (8760 hours)
- Temperature data for heat demand calculation

**Power Grid** (for DHA):
- `Legacy/DHA/HP New /Data/branitzer_siedlung_ns_v3_ohne_UW.json` (legacy nodes/ways)
- OR `data/processed/power_lines.geojson` and `power_substations.geojson` (GeoData)

**Base Electrical Loads** (for DHA):
- `data/raw/gebaeude_lastphasenV2.json` (scenario-based)
- OR BDEW profiles: `data/raw/bdew_profiles.csv`, `data/raw/building_population_resultsV6.json`, `data/raw/bdew_slp_gebaeudefunktionen.json` (time series)

### Processed Data

All processed data is stored in Parquet format for efficiency:
- `buildings.parquet`: Validated, filtered building data (residential with heat demand)
- `building_cluster_map.parquet`: Building → cluster mapping
- `street_clusters.parquet`: Cluster metadata
- `hourly_heat_profiles.parquet`: 8760-hour profiles per building
- `cluster_design_topn.json`: Design loads and top-N hours

---

## Coordinate Reference Systems

- **Input**: EPSG:4326 (WGS84) or EPSG:25833 (UTM Zone 33N)
- **Internal processing**: EPSG:25833 (UTM Zone 33N) - projected CRS for distance calculations
- **Map display**: EPSG:4326 (WGS84) - for Folium/Leaflet compatibility

The system automatically transforms coordinates as needed.

---

## Contributing

### Code Style

- **Formatter**: Black (line length: 100)
- **Linter**: flake8
- **Type checking**: mypy (strict mode)

### Testing

- Write tests for new features
- Use appropriate markers (`@pytest.mark.unit`, `@pytest.mark.integration`)
- Maintain test coverage
- See `tests/test_readme.md` for test categorization

### Documentation

- Update this document for architectural changes
- Add docstrings to functions/classes
- Update module README files for module changes
- Update README.md for user-facing changes

---

## License

MIT License

---

## Contact

- **Author**: Ishantha Hewaratne
- **Email**: ishantha.hewaratne@ieg.fraunhofer.de
- **Institution**: Fraunhofer IEG

---

**Last Updated**: 2026-01-24  
**Version**: 3.1 (Enhanced Validation & Robustness)  
**Status**: All phases (0-5) fully implemented and tested with comprehensive design validation
