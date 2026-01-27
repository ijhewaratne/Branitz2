# Branitz Heat Decision: Comprehensive Architecture Overview

## 1. Executive Summary

The Branitz Heat Decision project is a **Service-Oriented** system designed to assess heating decarbonization strategies for street clusters. It utilizes a **Multi-Agent Architecture** where independent execution units ("Agents") are orchestrated by either a **User Interface (UI)** or the **Agent Development Kit (ADK)**.

- **Dual Triggers**: Simulations can be triggered manually via the UI (`app.py`) or programmatically via Agents (`agent.py`).
- **Shared Core**: Both triggers drive the exact same **CLI Scripts** (`scripts/*.py`), ensuring consistency.
- **Artifact Communication**: Components decouple by communicating strictly via **Artifacts** (JSON/HTML files) stored in the `results/` directory.

> **Terminology Note**: The acronym **"HDA"** corresponds to the **DHA (District Heat Assessment)** module. The system comprises five key agents: **CHA**, **DHA**, **Economics**, **Decision**, and **UHDC**.

---

## 2. High-Level Architecture Diagram

The system separates **Execution** (Who asks?) from **Core Logic** (Who does the work?) and **Visualization** (Who shows the result?).

```mermaid
graph TD
    User((User)) -->|1. Selects Street & Clicks 'Run'| UI[Streamlit UI]
    UI -->|2. Request| JS[JobService]
    JS -->|3. Lookup Command| REG[Scenario Registry]
    
    subgraph "Execution Layer"
        JS -->|4. UI Trigger| CMD[CLI Command]
        Agent[DHA/CHA Agent] -->|Alt. Trigger| Tool[Tool Wrapper]
        Tool -->|Constructs| CMD
    end
    
    CMD -->|5. Spawns Subprocess| SCRIPT[Core Scripts (e.g. 02_run_dha.py)]
    
    subgraph "Core Logic"
        SCRIPT -->|6. Loads Data| DATA[processed/*.parquet]
        SCRIPT -->|7. Simulates| CALC[Pandapipes / Pandapower / NumPy]
        SCRIPT -->|8. Writes| ART[Artifacts (results/)]
    end
    
    subgraph "Feedback Loop"
        ART -->|dha_kpis.json| JSON[Metrics]
        ART -->|hp_lv_map.html| HTML[Visuals]
    end
    
    JSON -->|9. Validation| Agent
    HTML -->|10. Display| UI
```

---

## 3. Structural Analogy

To understand the codebase, use this anatomical analogy:

| Component | Analogy | Location | Responsibility |
| :--- | :--- | :--- | :--- |
| **Agent** | **The Brain** | `adk/agent.py` | Manages "Trajectory" (history), enforces "Guardrails" (policies), and decides *when* to act. |
| **Tool** | **The Hand** | `adk/tools.py` | Bridges the gap between Python objects and the OS. Sanitizes inputs and constructs CLI commands. |
| **Script** | **The Muscle** | `scripts/*.py` | Performs the heavy lifting (Physics/Math). Headless and agnostic to who triggered it. |
| **UI** | **The Face** | `ui/` | Provides a user-friendly way to trigger the "Muscle" (via Registry) and view the results. |

---

## 4. Agent-to-Script Mapping

Each logical "Agent" corresponds to a specific script and set of tools.

| Agent Phase | Script | Core Tools | Outputs (Artifacts) |
| :--- | :--- | :--- | :--- |
| **CHA** (Dist. Heat) | `01_run_cha.py` | `pandapipes`, `networkx` | `cha_kpis.json`, `interactive_map.html`, `network.pickle` |
| **DHA** (Heat Pump) | `02_run_dha.py` | `pandapower`, `geopandas` | `dha_kpis.json`, `hp_lv_map.html` |
| **Economics** | `03_run_economics.py` | `numpy` (Monte Carlo) | `economics_deterministic.json`, `economics_monte_carlo.json` |
| **Decision** | `cli/decision.py` | `ContractValidator`, `LLM` | `decision_*.json`, `explanation_*.html` |
| **UHDC** | `cli/uhdc.py` | `Jinja2` | `uhdc_report_*.html` |

---

## 5. Detailed Workflow: From UI to Result

This section specifically details the flow when a user interacts with the system, using the **CHA** (Cluster Heat Assessment) workflow as the primary example.

### Step 1: Selection & Trigger
**Location**: `src/branitz_heat_decision/ui/app.py`
1.  **Selection**: User chooses a street (e.g., "Heinrich Zille Strasse") from the sidebar. The UI resolves this to `cluster_id="ST010_..."`.
2.  **Trigger**: User clicks **"Check District Heating Feasibility"**.
3.  **Action**: `JobService.start_job("cha", "ST010_...")` is called.

### Step 2: Command Construction
**Location**: `src/branitz_heat_decision/ui/registry.py` & `services.py`
1.  **Registry Lookup**: The service looks up the "cha" key in `SCENARIO_REGISTRY`.
2.  **Template Resolution**: It fills the command template:
    ```python
    ["python", "src/scripts/01_run_cha.py", "--cluster-id", "ST010_...", "--use-trunk-spur"]
    ```
3.  **Execution**: The command is run in a background thread using `subprocess.run()`, keeping the UI responsive.

### Step 3: Core execution (The Script)
**Location**: `src/scripts/01_run_cha.py`
The script runs independently of the UI.
1.  **Data Loading**: Reads `buildings.parquet` and `streets.geojson`.
2.  **Network Building**: Uses `network_builder_trunk_spur.py` to create a district heating topology.
3.  **Simulation**: Runs `pandapipes.pipeflow()` to simulate pressure and flow.
4.  **Optimization**: Iteratively adjusts the network for convergence.
5.  **Artifact Generation**: Checks for EN 13941-1 compliance and writes results.

### Step 4: Visualization & Feedback
**Location**: `src/branitz_heat_decision/ui/app.py`
1.  **Polling**: The `ResultService` periodically checks the `results/cha/ST010_.../` folder.
2.  **Detection**: Once `cha_kpis.json` and `interactive_map.html` appear, the status updates to "Analysis Complete".
3.  **Display**:
    *   **Map**: The HTML file is embedded in an `<iframe>`.
    *   **Metrics**: The JSON data is parsed and displayed as "Feasible / Not Feasible" badges.

---

## 6. Directory Structure: Results

All components coordinate through this folder structure:

```text
results/
├── cha/
│   └── ST010_HEINRICH_ZILLE_STRASSE/
│       ├── cha_kpis.json           <-- Status (Agent reads this)
│       └── interactive_map.html    <-- Visual (UI shows this)
├── dha/
│   └── ST010_HEINRICH_ZILLE_STRASSE/
│       ├── dha_kpis.json
│       └── hp_lv_map.html
├── economics/
│   └── ... (financial JSONs)
└── uhdc/
    └── ... (Final HTML Report)
```
