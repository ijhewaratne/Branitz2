# Workflow: UI Selection to Agent Execution to Results

This document explains the complete workflow from selecting a street in the UI (e.g., "Heinrich Zille Strasse") through agent invocation, tool execution, and result display.

---

## Overview

The Branitz Heat Decision system uses a **multi-agent architecture** where specialized agents (CHA, DHA, Economics, Decision, UHDC) are invoked through Python scripts triggered by the UI. Each agent uses specific tools (pandapipes, pandapower, Monte Carlo, LLM) to produce results that flow back to the UI.

---

## 1. UI Selection (User Action)

### Example: Selecting "Heinrich Zille Strasse"

**Location**: `src/branitz_heat_decision/ui/app.py`

**User Action**:
1. User opens Streamlit UI (`streamlit run src/branitz_heat_decision/ui/app.py`)
2. Sidebar shows dropdown: "Select Street Cluster"
3. User selects: **"Heinrich Zille Strasse (ST010_HEINRICH_ZILLE_STRASSE)"**

**Code Flow**:
```python
# Line 64: User selects from dropdown
selection = st.sidebar.selectbox("Select Street Cluster", cluster_options)

# Line 67: Extract cluster_id
selected_cluster_id = selection.split(" (")[-1].strip(")")  
# Result: "ST010_HEINRICH_ZILLE_STRASSE"
```

**What Happens**:
- `ClusterService.get_cluster_index()` loads `data/processed/cluster_ui_index.parquet`
- UI displays cluster name and ID
- `selected_cluster_id` is stored in Streamlit session state

---

## 2. Agent Invocation (Scenario Selection)

### User Clicks "Check District Heating Feasibility"

**Location**: `src/branitz_heat_decision/ui/app.py` (lines 77-82)

**User Action**:
- User clicks button: **"Check District Heating Feasibility"** (from Scenario Catalog)

**Code Flow**:
```python
# Line 78: Button click
if st.button(spec["title"], key=f"btn_{key}"):
    # Line 79: Start job via JobService
    job_id = services["job"].start_job("cha", selected_cluster_id)
    # Result: job_id = "cha_ST010_HEINRICH_ZILLE_STRASSE_1234567890"
```

---

## 3. Job Service: Command Building

**Location**: `src/branitz_heat_decision/ui/services.py`

### 3.1 `JobService.start_job()`

**Function**: `start_job(scenario="cha", cluster_id="ST010_HEINRICH_ZILLE_STRASSE")`

**Steps**:

1. **Generate Job ID**:
   ```python
   job_id = f"{scenario}_{cluster_id}_{int(time.time())}"
   # Result: "cha_ST010_HEINRICH_ZILLE_STRASSE_1737820800"
   ```

2. **Build Command** (via `_build_command()`):
   - Looks up scenario in `SCENARIO_REGISTRY` (`src/branitz_heat_decision/ui/registry.py`)
   - For `"cha"`:
     ```python
     command_template = [
         "{python}", "src/scripts/01_run_cha.py", 
         "--cluster-id", "{cluster_id}",
         "--use-trunk-spur",
         "--optimize-convergence"
     ]
     ```
   - Resolves placeholders:
     ```python
     cmd = [
         "/path/to/python", 
         "src/scripts/01_run_cha.py",
         "--cluster-id", "ST010_HEINRICH_ZILLE_STRASSE",
         "--use-trunk-spur",
         "--optimize-convergence"
     ]
     ```

3. **Start Background Thread**:
   ```python
   thread = threading.Thread(
       target=self._run_process, 
       args=(job_id, cmd, log_file, scenario, cluster_id)
   )
   thread.start()
   ```

4. **Store Job Metadata**:
   ```python
   self.jobs[job_id] = {
       "id": job_id,
       "cluster_id": "ST010_HEINRICH_ZILLE_STRASSE",
       "scenario": "cha",
       "status": "running",
       "start_time": datetime.now(),
       "log_file": "results/jobs/cha_ST010_...log",
       "cmd": [...]
   }
   ```

---

## 4. Agent Execution: CHA Script

**Location**: `src/scripts/01_run_cha.py`

### 4.1 Script Entry Point

**Subprocess Execution**:
```python
# JobService._run_process() runs:
subprocess.run(
    cmd,  # ["python", "src/scripts/01_run_cha.py", "--cluster-id", "ST010_...", ...]
    stdout=log_file,
    stderr=subprocess.STDOUT,
    env={"PYTHONPATH": src_path}
)
```

### 4.2 CHA Pipeline (`run_cha_pipeline()`)

**Function**: `run_cha_pipeline(cluster_id="ST010_HEINRICH_ZILLE_STRASSE", ...)`

**Step-by-Step Execution**:

#### Step 1: Load Cluster Data
```python
buildings, streets, plant_coords, design_hour, design_load_kw, hourly_profiles, cluster_street_name = load_cluster_data(cluster_id)
```
**Tools Used**:
- `geopandas.read_parquet()` → Load buildings/streets GeoDataFrames
- `pandas.read_parquet()` → Load cluster map, hourly profiles
- `branitz_heat_decision.data.loader.load_buildings_geojson()` → Validate buildings
- `branitz_heat_decision.data.loader.load_streets_geojson()` → Validate streets

**Output**: Validated geospatial data for cluster

---

#### Step 2: Build Network (Trunk-Spur Mode)
```python
net, topology_info = build_trunk_spur_network(
    cluster_id=cluster_id,
    buildings=buildings,
    streets=streets,
    plant_coords=plant_coords,
    design_loads_kw=design_loads_kw,
    pipe_catalog=pipe_catalog,
    config=config,
    ...
)
```
**Location**: `src/branitz_heat_decision/cha/network_builder_trunk_spur.py`

**Tools Used**:
- `networkx.Graph()` → Build street graph
- `shapely.geometry` → Snap buildings to streets, create pipe geometries
- `pandapipes.create_empty_network()` → Create pandapipes network
- `pandapipes.create_junction()` → Add junctions (nodes)
- `pandapipes.create_pipe()` → Add pipes (edges)
- `pandapipes.create_sink()` → Add heat sinks (buildings)
- `pandapipes.create_source()` → Add heat source (plant)

**Output**: `pandapipesNet` object with topology

---

#### Step 3: Size Pipes
```python
pipe_sizing = size_pipes_from_catalog(
    net=net,
    street_graph=street_graph,
    trunk_edges=trunk_edges,
    design_loads_kw=design_loads_kw,
    pipe_catalog=pipe_catalog,
    v_max_m_s=1.5
)
```
**Location**: `src/branitz_heat_decision/cha/sizing_catalog.py`

**Tools Used**:
- Mass flow calculation: `mdot = Q / (cp * ΔT)`
- Velocity check: `v = mdot / (ρ * A)`
- Pipe catalog lookup: Select DN based on velocity limits

**Output**: Dict mapping `(u, v)` edges to DN labels (e.g., `DN50`, `DN80`)

---

#### Step 4: Optimize for Convergence
```python
optimize_network_for_convergence(net, config)
```
**Location**: `src/branitz_heat_decision/cha/convergence_optimizer_spur.py`

**Tools Used**:
- `pandapipes.pipeflow()` → Run hydraulic simulation
- `ConvergenceOptimizer._validate_all()` → Check topology (parallel paths, loops, connectivity)
- `ConvergenceOptimizer._apply_fixes()` → Add minimal loops, adjust roughness, fix pressures

**Output**: Converged network (or optimized topology)

---

#### Step 5: Run Hydraulic Simulation
```python
pp.pipeflow(net, mode="all", init="auto")
```
**Tool**: `pandapipes.pipeflow()` (Newton-Raphson solver)

**What It Does**:
- Solves mass balance equations
- Calculates pressure drops (Darcy-Weisbach)
- Computes velocities, temperatures, heat losses
- Iterates until convergence (`net.converged = True`)

**Output**: Network with `net.res_pipe`, `net.res_junction` (results tables)

---

#### Step 6: Extract KPIs
```python
kpis = extract_kpis(net, cluster_id, design_hour)
```
**Location**: `src/branitz_heat_decision/cha/kpi_extractor.py`

**Tools Used**:
- `pandas.DataFrame` → Aggregate pipe/junction results
- EN 13941-1 compliance checks:
  - Velocity: `v_share_within_limits >= 0.95`
  - Pressure drop: `dp_max_bar_per_100m <= 0.3`
  - Feasibility: `feasible = velocity_ok AND dp_ok`

**Output**: `cha_kpis.json`:
```json
{
  "cluster_id": "ST010_HEINRICH_ZILLE_STRASSE",
  "feasible": true,
  "hydraulics": {
    "velocity_ok": true,
    "v_share_within_limits": 0.98,
    "max_velocity_ms": 1.45
  },
  "losses": {
    "loss_share_percent": 12.5
  },
  ...
}
```

---

#### Step 7: Generate Interactive Map
```python
create_interactive_map(net, buildings, cluster_id, output_path)
```
**Location**: `src/branitz_heat_decision/cha/qgis_export.py`

**Tools Used**:
- `folium.Map()` → Create Leaflet map
- `branca.LinearColormap` → Color pipes by velocity/temperature
- `folium.PolyLine()` → Draw pipes with thickness = DN/20
- `folium.CircleMarker()` → Mark buildings/plant

**Output**: `interactive_map.html` (standalone HTML)

---

#### Step 8: Save Results
```python
# Save KPIs
with open(output_dir / "cha_kpis.json", "w") as f:
    json.dump(kpis, f, indent=2)

# Save network
with open(output_dir / "network.pickle", "wb") as f:
    pickle.dump(net, f)
```

**Output Directory**: `results/cha/ST010_HEINRICH_ZILLE_STRASSE/`

**Files Created**:
- `cha_kpis.json` → KPIs
- `network.pickle` → Network object
- `interactive_map.html` → Velocity map
- `interactive_map_temperature.html` → Temperature map
- `interactive_map_pressure.html` → Pressure map

---

## 5. Other Agents (DHA, Economics, Decision, UHDC)

### 5.1 DHA Agent (`02_run_dha.py`)

**Triggered By**: User clicks "Check Heat Pump Grid Feasibility"

**Workflow**:
1. Load LV grid data (`power_lines.geojson`, `power_substations.geojson`)
2. Build LV grid (`build_lv_grid_option2()`)
   - **Tool**: `pandapower.create_empty_network()`
   - Create buses, lines, transformers, ext_grid
3. Map buildings to LV buses (`map_buildings_to_lv_buses()`)
   - **Tool**: Nearest-neighbor search (NumPy)
4. Assign HP loads (`assign_hp_loads()`)
   - Convert thermal demand → electrical: `P_el = Q_th / COP`
5. Run loadflow (`run_loadflow()`)
   - **Tool**: `pandapower.runpp()` (Newton-Raphson)
6. Extract KPIs (`extract_dha_kpis()`)
   - VDE-AR-N 4100 compliance: voltage violations, line overloads
7. Generate map (`_create_map()`)
   - **Tool**: `folium` → Color buses by voltage, lines by loading

**Output**: `results/dha/ST010_HEINRICH_ZILLE_STRASSE/dha_kpis.json`, `hp_lv_map.html`

---

### 5.2 Economics Agent (`03_run_economics.py`)

**Triggered By**: User clicks "Estimate Costs & CO₂"

**Workflow**:
1. Load CHA/DHA KPIs
2. Calculate LCOH (`compute_lcoh_dh()`, `compute_lcoh_hp()`)
   - **Tool**: CRF formula, CAPEX/OPEX breakdown
3. Calculate CO₂ (`compute_co2_dh()`, `compute_co2_hp()`)
   - **Tool**: Emission factors (UBA 2025)
4. Run Monte Carlo (`run_monte_carlo()`)
   - **Tool**: NumPy random sampling (Normal, Triangular, Log-normal)
   - N=500 samples, recompute LCOH/CO₂ per sample
5. Extract win fractions (`prob_dh_cheaper`, `prob_dh_lower_co2`)

**Output**: `results/economics/ST010_HEINRICH_ZILLE_STRASSE/economics_deterministic.json`, `economics_monte_carlo.json`

---

### 5.3 Decision Agent (`cli/decision.py`)

**Triggered By**: User clicks "Compare & Recommend"

**Workflow**:
1. Build KPI Contract (`build_kpi_contract()`)
   - Aggregates CHA, DHA, Economics KPIs
   - **Tool**: `ContractValidator.validate()` → Schema validation
2. Apply Decision Rules (`decide_from_contract()`)
   - **Tool**: Rule-based logic (feasibility → cost → CO₂)
3. Generate Explanation (`explain_with_llm()` or `_fallback_template_explanation()`)
   - **Tool**: Google Gemini API (if available) or template
   - **Safety**: `_validate_explanation_safety()` → Check for hallucination

**Output**: `results/decision/ST010_HEINRICH_ZILLE_STRASSE/decision_ST010_HEINRICH_ZILLE_STRASSE.json`, `explanation_*.md`, `explanation_*.html`

---

### 5.4 UHDC Agent (`cli/uhdc.py`)

**Triggered By**: User clicks "Generate Stakeholder Report"

**Workflow**:
1. Build UHDC Report (`build_uhdc_report()`)
   - Aggregates all artifacts (CHA, DHA, Economics, Decision)
2. Render HTML (`render_html_report()`)
   - **Tool**: Jinja2 templating
   - Embeds interactive maps, KPIs, explanations

**Output**: `results/uhdc/ST010_HEINRICH_ZILLE_STRASSE/uhdc_report_ST010_HEINRICH_ZILLE_STRASSE.html`

---

## 6. Results Flow Back to UI

### 6.1 Job Status Update

**Location**: `JobService._run_process()`

**When Script Completes**:
```python
# Script finishes (subprocess.run returns)
self.jobs[job_id]["status"] = "completed"
self.jobs[job_id]["end_time"] = datetime.now()
```

**On Error**:
```python
# Write error.json
err_data = {
    "job_id": job_id,
    "error_type": "ValueError",
    "message": "...",
    "log_path": str(log_file)
}
with open(out_dir / "error.json", "w") as f:
    json.dump(err_data, f)
```

---

### 6.2 UI Polling for Results

**Location**: `src/branitz_heat_decision/ui/app.py` (lines 461-494)

**Code Flow**:
```python
# Check if CHA results exist
cha_status = services["result"].get_result_status(selected_cluster_id)["cha"]
# Result: True if results/cha/ST010_.../cha_kpis.json exists

if cha_status:
    st.success("Analysis Complete")
    
    # Load map
    map_path = services["result"].get_cha_map_path(selected_cluster_id, "velocity")
    if map_path.exists():
        with open(map_path, "r") as f:
            st.components.v1.html(f.read(), height=600)
    
    # Load KPIs
    artifacts = services["result"].get_existing_artifacts(selected_cluster_id, "cha")
    kpis = json.load(open(artifacts[0]))  # cha_kpis.json
    st.json(kpis)
```

**ResultService Methods**:
- `get_result_status(cluster_id)` → Check which scenarios have results
- `get_existing_artifacts(cluster_id, scenario)` → List result files
- `get_cha_map_path(cluster_id, map_type)` → Get map HTML path

---

## 7. Complete Workflow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. USER SELECTS STREET                                          │
│    UI: "Heinrich Zille Strasse (ST010_HEINRICH_ZILLE_STRASSE)" │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. USER CLICKS "Check District Heating Feasibility"             │
│    JobService.start_job("cha", "ST010_...")                     │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│ 3. JOB SERVICE BUILDS COMMAND                                    │
│    ["python", "src/scripts/01_run_cha.py",                       │
│     "--cluster-id", "ST010_...", "--use-trunk-spur"]            │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│ 4. BACKGROUND THREAD STARTS SUBPROCESS                          │
│    subprocess.run(cmd, stdout=log_file, env=PYTHONPATH)        │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│ 5. CHA AGENT EXECUTES (01_run_cha.py)                           │
│    ├─ load_cluster_data() → geopandas, pandas                   │
│    ├─ build_trunk_spur_network() → networkx, pandapipes        │
│    ├─ size_pipes_from_catalog() → pipe catalog lookup          │
│    ├─ optimize_network_for_convergence() → convergence fixes  │
│    ├─ pp.pipeflow() → pandapipes solver                        │
│    ├─ extract_kpis() → EN 13941-1 compliance                   │
│    └─ create_interactive_map() → folium                        │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│ 6. RESULTS SAVED                                                │
│    results/cha/ST010_.../                                       │
│    ├─ cha_kpis.json                                             │
│    ├─ network.pickle                                            │
│    └─ interactive_map.html                                     │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│ 7. JOB STATUS UPDATED                                           │
│    jobs[job_id]["status"] = "completed"                         │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│ 8. UI POLLS FOR RESULTS                                         │
│    ResultService.get_result_status() → True                      │
│    UI displays: map, KPIs, artifacts                            │
└─────────────────────────────────────────────────────────────────┘
```

---

## 8. Agent-to-Tool Mapping

| Agent | Script | Primary Tools | Outputs |
|-------|--------|---------------|---------|
| **CHA** | `01_run_cha.py` | `pandapipes`, `networkx`, `folium`, `geopandas` | `cha_kpis.json`, `interactive_map.html` |
| **DHA** | `02_run_dha.py` | `pandapower`, `geopandas`, `folium` | `dha_kpis.json`, `hp_lv_map.html` |
| **Economics** | `03_run_economics.py` | `numpy` (Monte Carlo), financial formulas | `economics_deterministic.json`, `economics_monte_carlo.json` |
| **Decision** | `cli/decision.py` | `ContractValidator`, `decide_from_contract()`, Google Gemini API | `decision_*.json`, `explanation_*.md` |
| **UHDC** | `cli/uhdc.py` | `Jinja2` templating, artifact aggregation | `uhdc_report_*.html` |

---

## 9. Key Files Reference

| Component | File Path |
|-----------|-----------|
| **UI App** | `src/branitz_heat_decision/ui/app.py` |
| **Job Service** | `src/branitz_heat_decision/ui/services.py` |
| **Scenario Registry** | `src/branitz_heat_decision/ui/registry.py` |
| **CHA Script** | `src/scripts/01_run_cha.py` |
| **DHA Script** | `src/scripts/02_run_dha.py` |
| **Economics Script** | `src/scripts/03_run_economics.py` |
| **Decision CLI** | `src/branitz_heat_decision/cli/decision.py` |
| **UHDC CLI** | `src/branitz_heat_decision/cli/uhdc.py` |

---

## 10. Example: Complete Run for Heinrich Zille Strasse

**User Actions**:
1. Select "Heinrich Zille Strasse (ST010_HEINRICH_ZILLE_STRASSE)"
2. Click "Check District Heating Feasibility" → CHA runs
3. Click "Check Heat Pump Grid Feasibility" → DHA runs
4. Click "Estimate Costs & CO₂" → Economics runs
5. Click "Compare & Recommend" → Decision runs
6. Click "Generate Stakeholder Report" → UHDC runs

**Result Files**:
```
results/
├── cha/ST010_HEINRICH_ZILLE_STRASSE/
│   ├── cha_kpis.json
│   ├── network.pickle
│   └── interactive_map.html
├── dha/ST010_HEINRICH_ZILLE_STRASSE/
│   ├── dha_kpis.json
│   └── hp_lv_map.html
├── economics/ST010_HEINRICH_ZILLE_STRASSE/
│   ├── economics_deterministic.json
│   └── economics_monte_carlo.json
├── decision/ST010_HEINRICH_ZILLE_STRASSE/
│   ├── decision_ST010_HEINRICH_ZILLE_STRASSE.json
│   └── explanation_ST010_HEINRICH_ZILLE_STRASSE.html
└── uhdc/ST010_HEINRICH_ZILLE_STRASSE/
    └── uhdc_report_ST010_HEINRICH_ZILLE_STRASSE.html
```

**UI Displays**:
- Maps (CHA velocity/temperature, DHA voltage/loading)
- KPIs (feasibility, LCOH, CO₂, violations)
- Decision recommendation (DH or HP)
- AI explanation (LLM or template)
- Stakeholder report (HTML)

---

## Summary

The workflow follows this pattern:

1. **UI Selection** → User selects street cluster
2. **Agent Invocation** → User clicks scenario button → `JobService.start_job()`
3. **Command Building** → `SCENARIO_REGISTRY` maps scenario to Python script
4. **Background Execution** → Subprocess runs script in separate thread
5. **Agent Tools** → Script calls specialized tools (pandapipes, pandapower, Monte Carlo, LLM)
6. **Results Saved** → JSON, HTML, pickle files written to `results/{scenario}/{cluster_id}/`
7. **UI Polling** → `ResultService` checks for files, UI displays results

Each agent is **independent** and can be run in any order, but typically: CHA → DHA → Economics → Decision → UHDC.
