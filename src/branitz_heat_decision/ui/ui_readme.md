# UI (User Interface) Module Documentation

Complete documentation for the Streamlit-based web application providing an interactive interface for the Branitz Heat Decision system.

**Module Location**: `src/branitz_heat_decision/ui/`  
**Total Lines of Code**: ~985 lines  
**Primary Language**: Python 3.9+  
**Dependencies**: streamlit, pandas, geopandas, pydeck, altair, google-generativeai

---

## Module Overview

The UI module provides a comprehensive web-based interface for:
1. **Street Cluster Selection**: Interactive map and list of available street clusters
2. **Technical Feasibility Analysis**: CHA (District Heating) and DHA (Heat Pump Grid) visualization
3. **Economics Comparison**: LCoH, CO₂, and Monte Carlo robustness analysis
4. **Decision Support**: AI-powered recommendations with LLM explanations
5. **Job Management**: Background execution of pipeline stages
6. **AI Assistant**: Natural language interface for workflow orchestration

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Streamlit App (app.py)                                     │
│  ├─ Sidebar: Cluster Selection, AI Chat, Jobs              │
│  └─ Main Content: Tabs (Overview, Feasibility, Economics,  │
│                    Compare & Decide, Portfolio, Jobs)       │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│  Services Layer                                             │
│  ├─ ClusterService: Cluster data loading                    │
│  ├─ JobService: Background job execution                    │
│  ├─ ResultService: Artifact discovery & status              │
│  └─ LLMRouter: Intent classification & planning             │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│  External Systems                                           │
│  ├─ Results: results/cha/, results/dha/, etc.              │
│  ├─ Data: data/processed/                                   │
│  └─ LLM: Google Gemini API (optional)                       │
└─────────────────────────────────────────────────────────────┘
```

---

## Module Files & Functions

### `app.py` (985 lines) ⭐ **MAIN APPLICATION**
**Purpose**: Main Streamlit application entry point

**Key Features**:
- **Multi-tab Interface**: Overview, Feasibility, Economics, Compare & Decide, Portfolio, Jobs
- **Interactive Maps**: PyDeck-based 3D visualization of streets and buildings
- **Real-time Updates**: Session state management for cluster selection and job status
- **AI Assistant**: Sidebar chat interface with LLM-powered intent routing

**Main Sections**:

#### 1. Sidebar (Cluster Selection & AI Chat)
- **Cluster Selection**: Dropdown and interactive map for street selection
- **AI Assistant**: Natural language interface for workflow planning
- **Job Status**: Real-time job execution monitoring

#### 2. Overview Tab
- Cluster summary metrics (buildings, heat demand, design hour)
- Interactive 3D map (PyDeck) with streets and buildings
- Hourly heat demand profile visualization (Altair charts)
- Data readiness checks

#### 3. Feasibility Tab
**Sub-tabs**: District Heating (CHA) | Heat Pump Grid (DHA)

**CHA Sub-tab**:
- Displays all 3 interactive maps sequentially:
  - 🌊 Flow Velocity Map
  - 📊 Pressure Distribution Map
  - 🌡️ Temperature Map
- Each map rendered at 500px height with scrolling
- CHA data files (JSON) in expandable section

**DHA Sub-tab**:
- Grid Mitigation Analysis (if available):
  - Classification badge (none/operational/reinforcement/expansion)
  - Recommended actions with severity indicators
  - Evidence with detailed metrics
  - Final feasibility verdict
- Grid Hosting Capacity Map
- DHA data files (JSON) in expandable section

#### 4. Economics Tab
- LCoH comparison (DH vs HP) with metrics
- CO₂ emissions comparison
- Monte Carlo robustness analysis:
  - Win probability metrics
  - Percentile ranges (P10-P90)
- Cost breakdown (expandable)
- System configuration (expandable)
- Validation results (sensitivity analysis, stress tests)

#### 5. Compare & Decide Tab
- **Decision Badge**: Prominent display of recommended solution (DH/HP/UNDECIDED)
- **Robustness Indicator**: Visual indicator of decision confidence
- **🤖 AI Explanation**: LLM-generated explanation (HTML or MD format)
  - Displays full narrative explanation if available
  - Falls back to reason codes if explanation not found
- **Decision Rationale**: Technical reason codes with human-readable descriptions
- **Key Metrics**: Side-by-side comparison of LCoH and CO₂
- **Monte Carlo Win Fractions**: Probability metrics
- **Raw Data**: Expandable JSON view

#### 6. Portfolio Tab
- Overview of all clusters with completion status
- Progress indicators for each pipeline stage
- Quick access to results

#### 7. Jobs Tab
- Real-time job execution status
- Log viewing
- Job cancellation

**Environment Setup**:
- Loads `.env` file automatically via `bootstrap_env()`
- Requires `GOOGLE_API_KEY` for LLM features (optional, with keyword fallback)

---

### `services.py` (413 lines) ⭐ **BACKEND SERVICES**
**Purpose**: Backend services for data loading, job management, and artifact discovery

**Classes**:

#### `ClusterService`
```python
class ClusterService:
    def get_cluster_index() -> pd.DataFrame
    def get_cluster_geometry(cluster_id: str) -> Optional[gpd.GeoDataFrame]
    def get_buildings_for_cluster(cluster_id: str) -> gpd.GeoDataFrame
    def get_design_hour(cluster_id: str) -> Optional[int]
    def get_heat_demand_profile(cluster_id: str) -> Optional[pd.DataFrame]
    def check_data_readiness(cluster_id: str) -> Dict[str, Any]
```

**Responsibilities**:
- Load cluster index from `cluster_ui_index.parquet`
- Load street geometries from `street_clusters.parquet`
- Load building data and filter by cluster
- Load hourly heat profiles
- Validate data completeness

#### `JobService`
```python
class JobService:
    def start_job(scenario: str, cluster_id: str) -> str
    def get_job_status(job_id: str) -> Dict[str, Any]
    def list_active_jobs() -> List[Dict[str, Any]]
    def cancel_job(job_id: str) -> bool
```

**Responsibilities**:
- Execute pipeline scripts in background threads
- Track job execution status
- Manage job logs
- Provide real-time status updates

#### `ResultService`
```python
class ResultService:
    def get_result_status(cluster_id: str) -> Dict[str, bool]
    def get_existing_artifacts(cluster_id: str, scenario: str) -> List[Path]
    def get_report_path(cluster_id: str) -> Optional[Path]
    def get_cha_map_path(cluster_id: str, map_type: str) -> Optional[Path]
    def get_decision_explanation_path(cluster_id: str, format: str) -> Optional[Path]
```

**Responsibilities**:
- Check existence of result artifacts
- Discover paths to generated files
- Support multiple map types (velocity, pressure, temperature)
- Load explanation files (MD or HTML)

**New Features** (Recent Updates):
- `get_decision_explanation_path()`: Loads LLM explanation files for decision display
- Enhanced map path resolution for multiple CHA map types

**Caching**:
- All data loading functions use `@st.cache_data` for performance
- Caches cluster index, buildings, profiles, etc.

---

### `llm.py` (131 lines) ⭐ **AI ASSISTANT**
**Purpose**: LLM-powered intent routing and workflow planning

**Classes**:

#### `LLMRouter`
```python
class LLMRouter:
    def route_intent(prompt: str, cluster_id: str) -> Dict[str, Any]
    def _query_llm(prompt: str, cluster_id: str) -> Dict[str, Any]
```

**Features**:
- **LLM Integration**: Uses Google Gemini 1.5 Flash for intent classification
- **Keyword Fallback**: Falls back to keyword matching if LLM unavailable
- **Workflow Planning**: Generates multi-step plans based on user intent

**Keyword Aliases**:
```python
KEYWORD_ALIASES = {
    "cha": ["district heat", "dh", "network", "cha", "pipeline", "district heating"],
    "dha": ["heat pump", "hp", "grid", "electricity", "dha", "power"],
    "economics": ["cost", "price", "lcoh", "money", "expensive", "economics", "euro"],
    "decision": ["decide", "compare", "recommend", "best", "decision", "feasibility"],
    "uhdc": ["report", "summary", "explain", "uhdc"]
}
```

**Workflow**:
1. User enters prompt in sidebar chat
2. LLMRouter interprets intent
3. Returns plan (list of steps) and confirmation message
4. User approves plan
5. Jobs are executed sequentially

**Environment Variables**:
- `GOOGLE_API_KEY`: Required for LLM features (optional, with fallback)

---

### `registry.py` (90 lines) ⭐ **SCENARIO REGISTRY**
**Purpose**: Central registry of available pipeline scenarios/workflows

**Structure**:
```python
SCENARIO_REGISTRY = {
    "cha": {
        "title": "Check District Heating Feasibility",
        "description": "...",
        "command_template": [...],
        "outputs": [...],
        "estimated_runtime": "medium"
    },
    # ... other scenarios
}
```

**Scenarios**:
1. **CHA**: District Heating network analysis
2. **DHA**: Heat Pump grid hosting analysis
3. **Economics**: Cost and CO₂ calculation
4. **Decision**: Recommendation generation
5. **UHDC**: Comprehensive stakeholder report

**Recent Updates**:
- CHA command template includes `--use-trunk-spur` and `--optimize-convergence` by default
- Economics includes `--full-validation` by default
- Output paths updated to match actual file names

---

### `env.py` (30 lines)
**Purpose**: Environment variable loading and validation

**Functions**:
- `bootstrap_env()`: Loads `.env` file if present
- Safe loading (doesn't override existing env vars)

---

## Key Features & Recent Updates

### 1. **Multi-Map Display (CHA)**
The Feasibility tab now displays all 3 CHA maps sequentially:
- Flow Velocity Map
- Pressure Distribution Map
- Temperature Map

Each map is rendered at 500px height with full scrolling capability.

### 2. **LLM Explanation Display**
The "Compare & Decide" tab now displays AI-generated explanations:
- Checks for HTML explanation file first (preferred)
- Falls back to Markdown explanation
- Displays in dedicated "🤖 AI Explanation" section
- Positioned before technical reason codes

### 3. **Sub-Tabs in Feasibility**
The Feasibility tab now uses sub-tabs:
- **District Heating (CHA)**: CHA maps and data
- **Heat Pump Grid (DHA)**: DHA analysis and mitigation recommendations

### 4. **Mitigation Analysis Display**
DHA sub-tab displays grid mitigation analysis:
- Classification badge with color coding
- Recommended actions with severity indicators
- Evidence with detailed metrics
- Final feasibility verdict

### 5. **Enhanced Map Visualization**
- PyDeck-based 3D maps for street/building visualization
- Multiple tile layer options (Light, Dark, Satellite, OSM)
- Interactive tooltips and hover information
- Street layer rendering as lines (not polygons)

---

## Usage

### Starting the UI
```bash
# From project root
streamlit run src/branitz_heat_decision/ui/app.py
```

Or:
```bash
cd src/branitz_heat_decision/ui
streamlit run app.py
```

### Environment Setup
Create a `.env` file in the project root:
```bash
GOOGLE_API_KEY=your_api_key_here
GOOGLE_MODEL=gemini-1.5-flash
```

### Typical Workflow

1. **Select Cluster**: Choose a street from the sidebar dropdown or map
2. **View Overview**: Check cluster summary and data readiness
3. **Run Analysis**:
   - Click "Run CHA Analysis" in Feasibility tab
   - Click "Run DHA Analysis" in Feasibility tab
   - Click "Run Economics" in Economics tab
4. **Review Results**: View maps, metrics, and analysis in respective tabs
5. **Make Decision**: Review recommendation in "Compare & Decide" tab
6. **View Report**: Access comprehensive UHDC report (if generated)

---

## Integration with Other Modules

### UI → Pipeline Scripts
- Executes: `01_run_cha.py`, `02_run_dha.py`, `03_run_economics.py`
- Executes: `cli/decision.py`, `cli/uhdc.py`
- Passes cluster_id and optional parameters

### UI ← Results
- Reads: `results/cha/<cluster_id>/cha_kpis.json`, `interactive_map*.html`
- Reads: `results/dha/<cluster_id>/dha_kpis.json`, `hp_lv_map.html`
- Reads: `results/economics/<cluster_id>/economics_deterministic.json`
- Reads: `results/decision/<cluster_id>/decision_*.json`, `explanation_*.{md,html}`
- Reads: `results/uhdc/<cluster_id>/uhdc_report_*.html`

### UI → Data
- Reads: `data/processed/cluster_ui_index.parquet`
- Reads: `data/processed/street_clusters.parquet`
- Reads: `data/processed/buildings.parquet`
- Reads: `data/processed/hourly_heat_profiles.parquet`

---

## File Interactions & Dependencies

### Internal Dependencies
```
app.py
  ├─→ uses ClusterService (services.py)
  ├─→ uses JobService (services.py)
  ├─→ uses ResultService (services.py)
  ├─→ uses LLMRouter (llm.py)
  └─→ uses SCENARIO_REGISTRY (registry.py)

services.py
  ├─→ uses ClusterService, JobService, ResultService
  └─→ uses SCENARIO_REGISTRY (registry.py)

llm.py
  ├─→ uses JobService (services.py)
  └─→ uses SCENARIO_REGISTRY (registry.py)
```

### External Dependencies
- **Streamlit**: Web framework
- **Pandas/GeoPandas**: Data handling
- **PyDeck**: 3D map visualization
- **Altair**: Statistical charts
- **Google Generative AI**: LLM integration (optional)

---

## Recent Updates Summary

### 2026-01-19 Updates
1. **Feasibility Tab Reorganization**: 
   - Sub-tabs for CHA and DHA
   - Sequential display of all 3 CHA maps (velocity, pressure, temperature)
   - Improved artifact organization

2. **LLM Explanation Display**:
   - Added `get_decision_explanation_path()` to ResultService
   - Display explanation in "Compare & Decide" tab
   - HTML preferred, MD fallback

3. **Enhanced Map Support**:
   - Support for multiple map types in CHA
   - Improved map path resolution

4. **DHA Mitigation Display**:
   - Full mitigation analysis visualization
   - Color-coded classification badges
   - Detailed recommendations with evidence

---

## Troubleshooting

### UI Not Starting
- **Issue**: Module import errors
- **Solution**: Ensure `src/` is in Python path, or run from project root

### Maps Not Displaying
- **Issue**: Map files not found
- **Solution**: Ensure CHA/DHA pipelines have completed and generated HTML maps

### LLM Assistant Not Working
- **Issue**: "Offline (Keyword Fallback Mode)"
- **Solution**: Set `GOOGLE_API_KEY` in `.env` file or environment

### Jobs Not Starting
- **Issue**: Background jobs fail silently
- **Solution**: Check job logs in `results/jobs/` directory

### Explanation Not Showing
- **Issue**: No explanation in "Compare & Decide" tab
- **Solution**: Re-run decision pipeline with `--llm-explanation --format all`

---

## Performance Considerations

- **Caching**: All data loaders use `@st.cache_data` for performance
- **Lazy Loading**: Maps and large artifacts loaded only when needed
- **Background Jobs**: Pipeline stages execute in background threads (non-blocking)

---

**Last Updated**: 2026-01-19  
**Module Version**: v1.0  
**Primary Maintainer**: UI Development Team
