# Where CHA, DHA, Economics, UHDC, and Decision Agents Are Defined

This document shows exactly where each agent/module is defined in the codebase.

---

## Overview

The Branitz Heat Decision system has **6 main agents** (DataPrep, CHA, DHA, Economics, Decision, UHDC) that are defined in multiple layers:

1. **Module Level**: Core functionality in dedicated directories
2. **ADK Agent Classes**: Agent wrappers in `adk/agent.py`
3. **CLI Scripts**: Command-line entry points in `scripts/`
4. **Tools**: Tool functions in `adk/tools.py`

---

## 1. DataPrepAgent (Data Preparation Agent)

### Module Definition
**Location**: `src/branitz_heat_decision/data/`

**Main Files**:
- `loader.py` → `load_buildings_geojson()`, `load_streets_geojson()`, `filter_residential_buildings_with_heat_demand()`
- `profiles.py` → `generate_hourly_profiles()`
- `cluster.py` → `create_street_clusters()`, `match_buildings_to_streets()`, `aggregate_cluster_profiles()`, `compute_design_and_topn()`
- `typology.py` → `estimate_envelope()` (building envelope parameters)

**Key Functions**:
```python
# src/branitz_heat_decision/data/loader.py
def load_buildings_geojson(path: Union[str, Path]) -> gpd.GeoDataFrame:
    """Load buildings from GeoJSON with comprehensive validation."""

def load_streets_geojson(path: Union[str, Path]) -> gpd.GeoDataFrame:
    """Load streets from GeoJSON with validation."""

def filter_residential_buildings_with_heat_demand(
    buildings: gpd.GeoDataFrame,
    min_heat_demand_kwh_a: float = 0.0
) -> gpd.GeoDataFrame:
    """Filter buildings to only include residential buildings with heat demand."""

# src/branitz_heat_decision/data/profiles.py
def generate_hourly_profiles(
    buildings: gpd.GeoDataFrame,
    weather_df: pd.DataFrame,
    t_base: float = 15.0,
    space_share: float = 0.85,
    dhw_share: float = 0.15,
    blend_alpha: float = 0.7,
    seed: int = 42
) -> pd.DataFrame:
    """Generate 8760 hourly heat demand profiles for all buildings."""

# src/branitz_heat_decision/data/cluster.py
def create_street_clusters(
    buildings: gpd.GeoDataFrame,
    streets: gpd.GeoDataFrame
) -> Tuple[pd.DataFrame, gpd.GeoDataFrame]:
    """Create street-based clusters from buildings and streets geodata."""
```

---

### ADK Agent Class
**Location**: `src/branitz_heat_decision/adk/agent.py` (lines 169-195)

```python
class DataPrepAgent(BaseADKAgent):
    """
    Agent responsible for data preparation (Phase 0).
    Wraps src/scripts/00_prepare_data.py.
    """
    
    def run(
        self,
        buildings_path: Optional[str] = None,
        streets_path: Optional[str] = None,
    ) -> AgentAction:
        """
        Execute data preparation.
        
        Args:
            buildings_path: Path to buildings GeoJSON (optional)
            streets_path: Path to streets GeoJSON (optional)
        """
        action = self._execute_tool(
            "prepare_data",
            phase="data",
            buildings_path=buildings_path,
            streets_path=streets_path,
            verbose=self.verbose,
        )
        self.trajectory.actions.append(action)
        return action
```

**Note**: `DataPrepAgent` does **not** require a `cluster_id` (unlike other agents), as it processes all data globally.

---

### CLI Script
**Location**: `src/scripts/00_prepare_data.py`

**Main Function**: `create_street_based_clusters()`
- Load raw buildings/streets GeoJSON
- Validate and filter residential buildings with heat demand
- Match buildings to streets
- Create street-based clusters
- Generate hourly heat demand profiles (8760 hours)
- Compute design hour and top-N hours
- Save processed data to `data/processed/`

**Key Outputs**:
- `data/processed/buildings.parquet` → Validated buildings
- `data/processed/building_cluster_map.parquet` → Building-to-cluster mapping
- `data/processed/street_clusters.parquet` → Street cluster metadata
- `data/processed/hourly_profiles.parquet` → Hourly heat demand profiles
- `data/processed/cluster_design_topn.json` → Design hour and top-N hours per cluster

**Entry Point**: `if __name__ == "__main__": main()`

---

### Tool Function
**Location**: `src/branitz_heat_decision/adk/tools.py` (lines 21-96)

```python
def prepare_data_tool(
    buildings_path: Optional[str] = None,
    streets_path: Optional[str] = None,
    verbose: bool = False,
) -> Dict[str, Any]:
    """
    Tool wrapper for data preparation pipeline (00_prepare_data.py).
    
    Args:
        buildings_path: Path to buildings GeoJSON (optional)
        streets_path: Path to streets GeoJSON (optional)
        verbose: Enable verbose logging
    
    Returns:
        Dict with status and outputs
    """
    # Build command: python src/scripts/00_prepare_data.py --create-clusters
    # Run subprocess → Check outputs exist → Return status
```

---

## 2. CHA (Central Heating Agent)

### Module Definition
**Location**: `src/branitz_heat_decision/cha/`

**Main Files**:
- `__init__.py` → Empty (module structure only)
- `config.py` → `CHAConfig` class
- `network_builder.py` → `build_dh_network_for_cluster()`
- `network_builder_trunk_spur.py` → `build_trunk_spur_network()`
- `kpi_extractor.py` → `CHAExtractor` class, `extract_kpis()`
- `convergence_optimizer.py` → `ConvergenceOptimizer` class
- `qgis_export.py` → `create_interactive_map()`

**Key Classes/Functions**:
```python
# src/branitz_heat_decision/cha/config.py
@dataclass
class CHAConfig:
    """Configuration for Central Heating Agent."""
    system_pressure_bar: float = 8.0
    pump_plift_bar: float = 3.0
    supply_temp_k: float = 363.15
    # ... more parameters

# src/branitz_heat_decision/cha/kpi_extractor.py
class CHAExtractor:
    def __init__(self, net: pp.pandapipesNet, config: Optional[CHAConfig] = None)
    def extract_kpis(self, cluster_id: str, design_hour: int) -> Dict[str, Any]
```

---

### ADK Agent Class
**Location**: `src/branitz_heat_decision/adk/agent.py` (lines 198-237)

```python
class CHAAgent(BaseADKAgent):
    """
    Agent responsible for Cluster Heat Assessment (Phase 1).
    Wraps src/scripts/01_run_cha.py.
    """
    
    def __init__(self, cluster_id: str, **kwargs):
        super().__init__(cluster_id=cluster_id, **kwargs)

    def run(
        self,
        use_trunk_spur: bool = True,
        plant_wgs84_lat: Optional[float] = None,
        plant_wgs84_lon: Optional[float] = None,
        disable_auto_plant_siting: bool = False,
        optimize_convergence: bool = True,
    ) -> AgentAction:
        """Execute CHA pipeline."""
        action = self._execute_tool(
            "run_cha",
            phase="cha",
            cluster_id=self.cluster_id,
            ...
        )
        return action
```

---

### CLI Script
**Location**: `src/scripts/01_run_cha.py`

**Main Function**:
```python
def run_cha_pipeline(
    cluster_id: str,
    attach_mode: str = 'split_edge_per_building',
    trunk_mode: str = 'paths_to_buildings',
    optimize_convergence: bool = False,
    output_dir: Optional[Path] = None,
    use_trunk_spur: bool = False,
    ...
):
    """Run complete CHA pipeline for a cluster."""
    # Load data → Build network → Run simulation → Extract KPIs → Export
```

**Entry Point**: `if __name__ == "__main__": main()`

---

### Tool Function
**Location**: `src/branitz_heat_decision/adk/tools.py` (lines 99-197)

```python
def run_cha_tool(
    cluster_id: str,
    use_trunk_spur: bool = True,
    plant_wgs84_lat: Optional[float] = None,
    plant_wgs84_lon: Optional[float] = None,
    disable_auto_plant_siting: bool = False,
    optimize_convergence: bool = True,
    verbose: bool = False,
) -> Dict[str, Any]:
    """
    Tool function for CHA agent.
    Calls src/scripts/01_run_cha.py via subprocess.
    """
    # Build command → Run subprocess → Return results
```

---

## 2. DHA (Decentralized Heating Agent)

### Module Definition
**Location**: `src/branitz_heat_decision/dha/`

**Main Files**:
- `__init__.py` → Exports key functions:
  ```python
  from .config import DHAConfig, get_default_config
  from .grid_builder import build_lv_grid_option2, build_lv_grid_from_nodes_ways_json
  from .mapping import map_buildings_to_lv_buses
  from .loadflow import assign_hp_loads, run_loadflow
  from .kpi_extractor import extract_dha_kpis
  from .export import export_dha_outputs
  ```
- `config.py` → `DHAConfig` class
- `grid_builder.py` → `build_lv_grid_option2()`, `build_lv_grid_from_nodes_ways_json()`
- `mapping.py` → `map_buildings_to_lv_buses()`
- `loadflow.py` → `assign_hp_loads()`, `run_loadflow()`
- `kpi_extractor.py` → `extract_dha_kpis()`
- `export.py` → `export_dha_outputs()`

**Key Classes/Functions**:
```python
# src/branitz_heat_decision/dha/config.py
@dataclass
class DHAConfig:
    """Configuration for DHA (LV grid hosting analysis for heat pumps)."""
    lv_vn_kv: float = 0.4
    mv_vn_kv: float = 20.0
    line_r_ohm_per_km: float = 0.206
    line_x_ohm_per_km: float = 0.080
    v_min_pu: float = 0.90
    v_max_pu: float = 1.10
    # ... more parameters

# src/branitz_heat_decision/dha/kpi_extractor.py
def extract_dha_kpis(
    results_by_hour: Dict[int, Dict[str, object]],
    cfg: DHAConfig | None = None,
    net=None,
) -> Tuple[Dict[str, object], pd.DataFrame]:
    """Extract auditable DHA KPIs + violations table."""
```

---

### ADK Agent Class
**Location**: `src/branitz_heat_decision/adk/agent.py` (lines 240-282)

```python
class DHAAgent(BaseADKAgent):
    """
    Agent responsible for District Heat Assessment (Phase 2).
    Wraps src/scripts/02_run_dha.py.
    """
    
    def __init__(self, cluster_id: str, **kwargs):
        super().__init__(cluster_id=cluster_id, **kwargs)

    def run(
        self,
        cop: float = 2.8,
        base_load_source: str = "scenario_json",
        bdew_population_json: Optional[str] = None,
        hp_three_phase: bool = True,
        topn: int = 10,
        grid_source: str = "legacy_json",
    ) -> AgentAction:
        """Execute DHA pipeline."""
        action = self._execute_tool(
            "run_dha",
            phase="dha",
            cluster_id=self.cluster_id,
            ...
        )
        return action
```

---

### CLI Script
**Location**: `src/scripts/02_run_dha.py`

**Main Function**: Script runs DHA pipeline:
- Load LV grid data
- Build pandapower network
- Map buildings to buses
- Assign HP loads
- Run loadflow
- Extract KPIs
- Export results

**Entry Point**: `if __name__ == "__main__": main()`

---

### Tool Function
**Location**: `src/branitz_heat_decision/adk/tools.py` (lines 198-297)

```python
def run_dha_tool(
    cluster_id: str,
    cop: float = 2.8,
    base_load_source: str = "scenario_json",
    bdew_population_json: Optional[str] = None,
    hp_three_phase: bool = True,
    topn: int = 10,
    grid_source: str = "legacy_json",
    verbose: bool = False,
) -> Dict[str, Any]:
    """
    Tool function for DHA agent.
    Calls src/scripts/02_run_dha.py via subprocess.
    """
```

---

## 3. Economics Agent

### Module Definition
**Location**: `src/branitz_heat_decision/economics/`

**Main Files**:
- `__init__.py` → Exports key functions:
  ```python
  from .params import (
      EconomicParameters,
      EconomicsParams,
      MonteCarloParams,
      get_default_economics_params,
      get_default_monte_carlo_params,
      ...
  )
  from .lcoh import DHInputs, HPInputs, compute_lcoh_dh, compute_lcoh_hp, ...
  from .co2 import compute_co2_dh, compute_co2_hp, ...
  from .monte_carlo import compute_mc_summary, run_monte_carlo, ...
  ```
- `params.py` → `EconomicParameters`, `EconomicsParams`, `MonteCarloParams`
- `lcoh.py` → `compute_lcoh_dh()`, `compute_lcoh_hp()`, `lcoh_dh_crf()`, `lcoh_hp_crf()`
- `co2.py` → `compute_co2_dh()`, `compute_co2_hp()`
- `monte_carlo.py` → `run_monte_carlo()`, `compute_mc_summary()`
- `sensitivity.py` → Sensitivity analysis
- `stress_tests.py` → Stress testing

**Key Classes/Functions**:
```python
# src/branitz_heat_decision/economics/params.py
@dataclass(frozen=True)
class EconomicParameters:
    discount_rate: float = 0.03
    lifetime_years: int = 30
    dh_generation_type: str = "biomass"
    gas_price_eur_per_mwh: float = 80.0
    electricity_price_eur_per_mwh: float = 150.0
    # ... more parameters

# src/branitz_heat_decision/economics/lcoh.py
def compute_lcoh_dh(
    annual_heat_mwh: float,
    pipe_lengths_by_dn: Dict[str, float],
    pump_power_kw: float,
    plant_capex_eur: float,
    params: EconomicParameters,
    ...
) -> float:
    """Compute LCOH for District Heating using CRF method."""

# src/branitz_heat_decision/economics/monte_carlo.py
def run_monte_carlo(
    dh_inputs: DHInputs,
    hp_inputs: HPInputs,
    base_params: EconomicsParams,
    mc: MonteCarloParams,
) -> MonteCarloResult:
    """Run Monte Carlo uncertainty propagation (N=500 samples)."""
```

---

### ADK Agent Class
**Location**: `src/branitz_heat_decision/adk/agent.py` (lines 285-315)

```python
class EconomicsAgent(BaseADKAgent):
    """
    Agent responsible for Economics (Phase 3).
    Wraps src/scripts/03_run_economics.py.
    """
    
    def __init__(self, cluster_id: str, **kwargs):
        super().__init__(cluster_id=cluster_id, **kwargs)

    def run(
        self,
        n_samples: int = 500,
        seed: int = 42,
    ) -> AgentAction:
        """Execute economics pipeline."""
        action = self._execute_tool(
            "run_economics",
            phase="economics",
            cluster_id=self.cluster_id,
            n_samples=n_samples,
            seed=seed,
            ...
        )
        return action
```

---

### CLI Script
**Location**: `src/scripts/03_run_economics.py`

**Main Function**: Script runs economics pipeline:
- Load CHA/DHA KPIs
- Calculate LCOH (DH and HP)
- Calculate CO₂ emissions
- Run Monte Carlo simulation
- Generate sensitivity/stress test results

**Entry Point**: `if __name__ == "__main__": main()`

---

### Tool Function
**Location**: `src/branitz_heat_decision/adk/tools.py` (lines 299-397)

```python
def run_economics_tool(
    cluster_id: str,
    n_samples: int = 500,
    seed: int = 42,
    verbose: bool = False,
) -> Dict[str, Any]:
    """
    Tool function for Economics agent.
    Calls src/scripts/03_run_economics.py via subprocess.
    """
```

---

## 4. Decision Agent

### Module Definition
**Location**: `src/branitz_heat_decision/decision/`

**Main Files**:
- `kpi_contract.py` → `build_kpi_contract()`, `KPIContract` dataclass
- `schemas.py` → `ContractValidator`, `REASON_CODES`, `KPIContract`, `DecisionResult`
- `rules.py` → `decide_from_contract()`, `validate_config()`, `DecisionResult`

**Key Classes/Functions**:
```python
# src/branitz_heat_decision/decision/kpi_contract.py
def build_kpi_contract(
    cluster_id: str,
    cha_kpis: Optional[Dict[str, Any]] = None,
    dha_kpis: Optional[Dict[str, Any]] = None,
    econ_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build KPI contract from CHA/DHA/Economics KPIs."""

# src/branitz_heat_decision/decision/rules.py
def decide_from_contract(
    contract: Dict[str, Any],
    config: Optional[Dict[str, Any]] = None,
) -> DecisionResult:
    """Apply rule-based decision logic to KPI contract."""
```

---

### ADK Agent Class
**Location**: `src/branitz_heat_decision/adk/agent.py` (lines 318-354)

```python
class DecisionAgent(BaseADKAgent):
    """
    Agent responsible for Decision Making (Phase 4).
    Wraps cli/decision.py (deterministic rules engine).
    """

    def __init__(self, cluster_id: str, **kwargs):
        super().__init__(cluster_id=cluster_id, **kwargs)
    
    def run(
        self,
        llm_explanation: bool = True,
        explanation_style: str = "executive",
        no_fallback: bool = False,
        config_path: Optional[str] = None,
    ) -> AgentAction:
        """Execute decision pipeline."""
        action = self._execute_tool(
            "run_decision",
            phase="decision",
            cluster_id=self.cluster_id,
            ...
        )
        return action
```

---

### CLI Script
**Location**: `src/branitz_heat_decision/cli/decision.py`

**Main Function**: `main()`
- Build KPI contract
- Validate contract schema
- Apply decision rules
- Generate explanation (LLM or template)
- Save decision JSON and explanation files

**Entry Point**: `if __name__ == "__main__": main()`

---

### Tool Function
**Location**: `src/branitz_heat_decision/adk/tools.py` (lines 399-497)

```python
def run_decision_tool(
    cluster_id: str,
    llm_explanation: bool = True,
    explanation_style: str = "executive",
    no_fallback: bool = False,
    config_path: Optional[str] = None,
    verbose: bool = False,
) -> Dict[str, Any]:
    """
    Tool function for Decision agent.
    Calls cli/decision.py via subprocess.
    """
```

---

## 5. UHDC (Urban Heat Decision Coordinator)

### Module Definition
**Location**: `src/branitz_heat_decision/uhdc/`

**Main Files**:
- `__init__.py` → Empty (module structure only)
- `orchestrator.py` → `build_uhdc_report()`
- `explainer.py` → `explain_with_llm()`, `_validate_explanation_safety()`
- `report_builder.py` → `render_html_report()`, `render_markdown_report()`, `save_reports()`
- `io.py` → `load_cha_kpis()`, `load_dha_kpis()`

**Key Classes/Functions**:
```python
# src/branitz_heat_decision/uhdc/orchestrator.py
def build_uhdc_report(
    cluster_id: str,
    run_dir: Path = Path("results"),
    use_llm: bool = True,
    explanation_style: str = "executive",
) -> Dict[str, Any]:
    """Build comprehensive UHDC report from all artifacts."""

# src/branitz_heat_decision/uhdc/explainer.py
def explain_with_llm(
    contract: Dict[str, Any],
    decision: Dict[str, Any],
    style: str = "executive",
) -> str:
    """Generate LLM explanation (constrained to contract data)."""

# src/branitz_heat_decision/uhdc/report_builder.py
def render_html_report(
    report_data: Dict[str, Any],
    map_specs: Optional[List[Dict[str, Any]]] = None,
    violations_csv_path: Optional[Path] = None,
) -> str:
    """Render UHDC report as HTML using Jinja2."""
```

---

### ADK Agent Class
**Location**: `src/branitz_heat_decision/adk/agent.py` (lines 357-393)

```python
class UHDCAgent(BaseADKAgent):
    """
    Agent responsible for UHDC Reporting (Phase 5).
    Wraps cli/uhdc.py.
    """

    def __init__(self, cluster_id: str, **kwargs):
        super().__init__(cluster_id=cluster_id, **kwargs)

    def run(
        self,
        out_dir: Optional[str] = None,
        llm: bool = True,
        style: str = "executive",
        format: str = "all",
    ) -> AgentAction:
        """Execute UHDC report generation."""
        action = self._execute_tool(
            "run_uhdc",
            phase="uhdc",
            cluster_id=self.cluster_id,
            ...
        )
        return action
```

---

### CLI Script
**Location**: `src/branitz_heat_decision/cli/uhdc.py`

**Main Function**: `main()`
- Build UHDC report from artifacts
- Discover maps and violations CSV
- Render HTML/MD/JSON reports
- Save to output directory

**Entry Point**: `if __name__ == "__main__": main()`

---

### Tool Function
**Location**: `src/branitz_heat_decision/adk/tools.py` (lines 499-597)

```python
def run_uhdc_tool(
    cluster_id: str,
    out_dir: Optional[str] = None,
    llm: bool = True,
    style: str = "executive",
    format: str = "all",
    verbose: bool = False,
) -> Dict[str, Any]:
    """
    Tool function for UHDC agent.
    Calls cli/uhdc.py via subprocess.
    """
```

---

## Summary Table

| Agent | Module Directory | ADK Agent Class | CLI Script | Tool Function |
|-------|------------------|-----------------|-------------|---------------|
| **DataPrep** | `data/` | `DataPrepAgent` (line 169) | `00_prepare_data.py` | `prepare_data_tool()` (line 21) |
| **CHA** | `cha/` | `CHAAgent` (line 198) | `01_run_cha.py` | `run_cha_tool()` (line 99) |
| **DHA** | `dha/` | `DHAAgent` (line 240) | `02_run_dha.py` | `run_dha_tool()` (line 198) |
| **Economics** | `economics/` | `EconomicsAgent` (line 285) | `03_run_economics.py` | `run_economics_tool()` (line 299) |
| **Decision** | `decision/` | `DecisionAgent` (line 318) | `cli/decision.py` | `run_decision_tool()` (line 399) |
| **UHDC** | `uhdc/` | `UHDCAgent` (line 357) | `cli/uhdc.py` | `run_uhdc_tool()` (line 499) |

---

## File Structure

```
src/branitz_heat_decision/
├── data/                   # DataPrep Module
│   ├── loader.py          # load_buildings_geojson, load_streets_geojson
│   ├── profiles.py        # generate_hourly_profiles
│   ├── cluster.py         # create_street_clusters, match_buildings_to_streets
│   └── typology.py        # estimate_envelope
├── cha/                    # CHA Module
│   ├── __init__.py
│   ├── config.py           # CHAConfig
│   ├── network_builder.py
│   ├── kpi_extractor.py
│   └── ...
├── dha/                    # DHA Module
│   ├── __init__.py         # Exports key functions
│   ├── config.py           # DHAConfig
│   ├── grid_builder.py
│   ├── kpi_extractor.py
│   └── ...
├── economics/              # Economics Module
│   ├── __init__.py         # Exports key functions
│   ├── params.py
│   ├── lcoh.py
│   ├── co2.py
│   ├── monte_carlo.py
│   └── ...
├── decision/               # Decision Module
│   ├── kpi_contract.py
│   ├── schemas.py
│   └── rules.py
├── uhdc/                  # UHDC Module
│   ├── __init__.py
│   ├── orchestrator.py
│   ├── explainer.py
│   └── report_builder.py
├── adk/                   # Agent Development Kit
│   ├── agent.py           # Agent classes (CHAAgent, DHAAgent, etc.)
│   ├── tools.py           # Tool functions (run_cha_tool, etc.)
│   └── ...
└── cli/                   # CLI Entry Points
    ├── decision.py
    └── uhdc.py

src/scripts/               # Script Entry Points
├── 00_prepare_data.py     # DataPrep Pipeline
├── 01_run_cha.py          # CHA Pipeline
├── 02_run_dha.py          # DHA Pipeline
└── 03_run_economics.py    # Economics Pipeline
```

---

## Summary

The system has **6 agents** organized in phases:

1. **Phase 0: DataPrepAgent** → Data preparation (load, validate, cluster, generate profiles)
2. **Phase 1: CHAAgent** → Central Heating Analysis (District Heating feasibility)
3. **Phase 2: DHAAgent** → Decentralized Heating Analysis (Heat Pump grid feasibility)
4. **Phase 3: EconomicsAgent** → Techno-Economic Analysis (LCOH, CO₂, Monte Carlo)
5. **Phase 4: DecisionAgent** → Decision Making (KPI contract, rules, explanation)
6. **Phase 5: UHDCAgent** → Urban Heat Decision Coordinator (Stakeholder report)

All agents inherit from `BaseADKAgent` and use the ADK (Agent Development Kit) framework for policy enforcement, tool execution, and trajectory tracking.
