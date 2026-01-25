# ADK (Agent Development Kit) Module

**Purpose**: Minimal-intrusion agent orchestration layer for Branitz Heat Decision pipeline.

**Status**: ✅ **IMPLEMENTED**

---

## Overview

The ADK module provides an agent-based interface to the Branitz Heat Decision pipeline **without modifying any existing modules**. It wraps existing scripts/CLIs/functions as tools and enforces guardrails to ensure deterministic, auditable execution.

### Key Principles

1. **Minimal Intrusion**: No changes to existing proven modules (`cha/`, `dha/`, `economics/`, `decision/`, `uhdc/`)
2. **Tool Wrappers**: Existing functionality wrapped as tools for agent orchestration
3. **Guardrails**: Policies enforce "LLM cannot decide" and other critical constraints
4. **Evaluation**: Trajectory validation and artifact checks

---

## Module Structure

```
src/branitz_heat_decision/adk/
├── __init__.py       # Module exports
├── agent.py          # Root ADK agent/team definition
├── tools.py          # Tool wrappers (call existing scripts/CLIs/functions)
├── policies.py       # Guardrails: "LLM cannot decide" and other policies
└── evals.py          # Trajectory checks + artifact checks
```

---

## Core Components

### 1. Agent (`agent.py`)

**`BranitzADKAgent`**: Root agent for single-cluster pipeline orchestration.

**Features**:
- Orchestrates complete pipeline (data → CHA → DHA → Economics → Decision → UHDC)
- Enforces policies via `enforce_guardrails()`
- Tracks execution trajectory
- Provides high-level methods for each phase

**Usage**:
```python
from branitz_heat_decision.adk import BranitzADKAgent

# Create agent
agent = BranitzADKAgent(
    cluster_id="ST010_HEINRICH_ZILLE_STRASSE",
    enforce_policies=True,
    verbose=True,
)

# Run full pipeline
trajectory = agent.run_full_pipeline(
    skip_data_prep=False,
    cha_params={"use_trunk_spur": True},
    dha_params={"cop": 2.8},
    economics_params={"n_samples": 500},
    decision_params={"llm_explanation": False},
    uhdc_params={"format": "all"},
)

# Or run phases individually
agent.prepare_data()
agent.run_cha(use_trunk_spur=True)
agent.run_dha(cop=2.8)
agent.run_economics(n_samples=500)
agent.run_decision()
agent.run_uhdc(format="all")
```

**`BranitzADKTeam`**: Multi-agent team for parallel cluster processing.

**Usage**:
```python
from branitz_heat_decision.adk import BranitzADKTeam

# Create team
team = BranitzADKTeam(
    cluster_ids=["ST010_HEINRICH_ZILLE_STRASSE", "ST001_AN_DEN_WEINBERGEN"],
    enforce_policies=True,
    verbose=True,
)

# Run batch
results = team.run_batch(
    skip_data_prep=False,
    cha_params={"use_trunk_spur": True},
)
```

---

### 2. Tools (`tools.py`)

**Tool Wrappers**: Wrap existing scripts/CLIs/functions without modifying them.

**Available Tools**:
1. **`prepare_data_tool`**: Data preparation pipeline (wraps `00_prepare_data.py`)
2. **`run_cha_tool`**: CHA pipeline (wraps `01_run_cha.py`)
3. **`run_dha_tool`**: DHA pipeline (wraps `02_run_dha.py`)
4. **`run_economics_tool`**: Economics pipeline (wraps `03_run_economics.py`)
5. **`run_decision_tool`**: Decision pipeline (wraps `cli/decision.py`)
6. **`run_uhdc_tool`**: UHDC report generation (wraps `cli/uhdc.py`)

**Usage**:
```python
from branitz_heat_decision.adk.tools import (
    prepare_data_tool,
    run_cha_tool,
    run_dha_tool,
    run_economics_tool,
    run_decision_tool,
    run_uhdc_tool,
)

# Execute tools directly
result = run_cha_tool(
    cluster_id="ST010_HEINRICH_ZILLE_STRASSE",
    use_trunk_spur=True,
    optimize_convergence=True,
)

# Check result
if result["status"] == "success":
    print(f"CHA outputs: {result['outputs']}")
    print(f"Convergence: {result['convergence']}")
else:
    print(f"Error: {result['error']}")
```

**Tool Metadata**:
```python
from branitz_heat_decision.adk.tools import get_available_tools

tools = get_available_tools()
for tool in tools:
    print(f"{tool['name']}: {tool['description']}")
    print(f"  Parameters: {tool['parameters']}")
```

---

### 3. Policies (`policies.py`)

**Guardrails**: Policies enforce critical constraints.

**Core Policies**:
1. **`llm_cannot_decide`**: LLM cannot make decisions. Decision must come from deterministic rules.
   - ✅ Allowed: `run_decision` (uses deterministic rules), `run_uhdc` (LLM only for explanation)
   - ❌ Blocked: `modify_kpi_contract`, `override_decision`, `manual_decision`

2. **`readonly_artifacts`**: Artifacts from previous phases are read-only.
   - ✅ Allowed: `read_kpis`, `load_contract`, `discover_artifacts`
   - ❌ Blocked: `modify_kpis`, `delete_artifacts`, `edit_kpis`

3. **`required_phases`**: Enforce phase dependencies (e.g., Decision requires CHA/DHA/Economics).
   - Checks if required artifacts exist before allowing actions

4. **`deterministic_outputs`**: All outputs must be deterministic (no randomness in decision paths).
   - ✅ Allowed: Monte Carlo (controlled via seed), LLM explanation (optional, doesn't affect decision)
   - ❌ Blocked: Random decision choices, non-deterministic parameter modifications

**Usage**:
```python
from branitz_heat_decision.adk.policies import (
    validate_agent_action,
    enforce_guardrails,
    PolicyViolation,
)

# Validate action
allowed, reason = validate_agent_action(
    action="run_decision",
    context={"cluster_id": "ST010_HEINRICH_ZILLE_STRASSE"},
)

if not allowed:
    print(f"Action blocked: {reason}")

# Enforce guardrails (raises PolicyViolation if blocked)
try:
    enforce_guardrails(
        action="run_decision",
        context={"cluster_id": "ST010_HEINRICH_ZILLE_STRASSE"},
    )
except PolicyViolation as e:
    print(f"Policy violation: {e}")
```

**Custom Policies**:
```python
from branitz_heat_decision.adk.policies import register_policy

def my_custom_policy(action: str, context: dict) -> tuple[bool, Optional[str]]:
    """Custom policy validator."""
    if action == "blocked_action":
        return False, "This action is blocked"
    return True, None

# Register policy
register_policy("my_custom_policy", my_custom_policy)
```

---

### 4. Evaluations (`evals.py`)

**Trajectory Validation**: Validate agent execution trajectory.

**Artifact Checks**: Verify artifact completeness and validity.

**Usage**:
```python
from branitz_heat_decision.adk.evals import (
    validate_trajectory,
    validate_artifacts,
    check_artifact_completeness,
)

# Validate trajectory
trajectory = [
    {"phase": "data", "status": "success"},
    {"phase": "cha", "status": "success"},
    {"phase": "dha", "status": "success"},
]

valid, issues = validate_trajectory(
    trajectory=trajectory,
    cluster_id="ST010_HEINRICH_ZILLE_STRASSE",
    expected_phases=["data", "cha", "dha", "economics", "decision", "uhdc"],
)

if not valid:
    for issue in issues:
        print(f"Issue: {issue}")

# Validate artifacts
all_valid, issues_by_phase = validate_artifacts(
    cluster_id="ST010_HEINRICH_ZILLE_STRASSE",
    phases=["cha", "dha", "economics", "decision"],
)

for phase, issues in issues_by_phase.items():
    print(f"{phase}: {issues}")

# Check artifact completeness
complete, missing = check_artifact_completeness(
    cluster_id="ST010_HEINRICH_ZILLE_STRASSE",
    phase="cha",
)

if not complete:
    print(f"Missing artifacts: {missing}")
```

---

## Complete Example

```python
from branitz_heat_decision.adk import BranitzADKAgent
from branitz_heat_decision.adk.evals import validate_trajectory, validate_artifacts

# Create agent
agent = BranitzADKAgent(
    cluster_id="ST010_HEINRICH_ZILLE_STRASSE",
    enforce_policies=True,
    verbose=True,
)

# Run full pipeline
trajectory = agent.run_full_pipeline(
    skip_data_prep=False,
    cha_params={
        "use_trunk_spur": True,
        "plant_wgs84_lat": 51.76274,
        "plant_wgs84_lon": 14.3453979,
        "disable_auto_plant_siting": True,
    },
    dha_params={
        "cop": 2.8,
        "base_load_source": "bdew_timeseries",
        "bdew_population_json": "data/raw/building_population_resultsV6.json",
    },
    economics_params={"n_samples": 500, "seed": 42},
    decision_params={"llm_explanation": False},
    uhdc_params={"format": "all", "llm": False},
)

# Validate trajectory
trajectory_list = [
    {
        "phase": action.phase,
        "status": action.status,
        "name": action.name,
        "error": action.error,
    }
    for action in trajectory.actions
]

valid, issues = validate_trajectory(
    trajectory=trajectory_list,
    cluster_id="ST010_HEINRICH_ZILLE_STRASSE",
)

if not valid:
    print("Trajectory validation failed:")
    for issue in issues:
        print(f"  - {issue}")

# Validate artifacts
all_valid, issues_by_phase = validate_artifacts(
    cluster_id="ST010_HEINRICH_ZILLE_STRASSE",
)

if not all_valid:
    print("Artifact validation failed:")
    for phase, issues in issues_by_phase.items():
        print(f"  {phase}:")
        for issue in issues:
            print(f"    - {issue}")

# Print summary
print(f"\nPipeline Status: {trajectory.status}")
print(f"Started: {trajectory.started_at}")
print(f"Completed: {trajectory.completed_at}")
print(f"Actions: {len(trajectory.actions)}")

for action in trajectory.actions:
    print(f"  {action.phase}: {action.name} - {action.status}")
    if action.error:
        print(f"    Error: {action.error}")
```

---

## Integration with Existing Pipeline

The ADK module **does not modify** existing modules. It only:

1. **Wraps** existing scripts/CLIs as tools
2. **Validates** actions against policies
3. **Orchestrates** pipeline execution
4. **Evaluates** trajectories and artifacts

Existing modules remain unchanged:
- ✅ `cha/` - No changes
- ✅ `dha/` - No changes
- ✅ `economics/` - No changes
- ✅ `decision/` - No changes
- ✅ `uhdc/` - No changes
- ✅ `cli/` - No changes
- ✅ `scripts/` - No changes

---

## Policies Explained

### Policy: LLM Cannot Decide

**Rationale**: Decisions must be deterministic and auditable. LLM explanations are optional and do not affect the decision.

**Enforcement**:
- ✅ `run_decision`: Uses deterministic rules engine (`decision/rules.py`)
- ✅ `run_uhdc`: LLM only for explanation (optional), decision from deterministic rules
- ❌ `modify_kpi_contract`: Would change decision input
- ❌ `override_decision`: No manual/LLM overrides

### Policy: Read-Only Artifacts

**Rationale**: Artifacts from previous phases are immutable to ensure reproducibility.

**Enforcement**:
- ✅ Read operations: `read_kpis`, `load_contract`, `discover_artifacts`
- ❌ Write operations: `modify_kpis`, `delete_artifacts`, `edit_kpis`

### Policy: Required Phases

**Rationale**: Enforce phase dependencies (e.g., Decision requires CHA/DHA/Economics).

**Enforcement**:
- Checks if required artifacts exist before allowing actions
- Raises `PolicyViolation` if dependencies missing

### Policy: Deterministic Outputs

**Rationale**: All outputs must be deterministic (no randomness in decision paths).

**Enforcement**:
- ✅ Monte Carlo randomness: OK (controlled via seed)
- ✅ LLM explanation randomness: OK (optional, doesn't affect decision)
- ❌ Random decision choices: Blocked
- ❌ Non-deterministic parameter modifications: Blocked

---

## Error Handling

The ADK module provides robust error handling:

1. **Policy Violations**: Raise `PolicyViolation` exception
2. **Tool Errors**: Return error status in tool result
3. **Trajectory Validation**: Return validation issues list
4. **Artifact Checks**: Return missing/invalid artifacts list

**Example**:
```python
try:
    agent = BranitzADKAgent(cluster_id="ST010_HEINRICH_ZILLE_STRASSE")
    trajectory = agent.run_full_pipeline()
except PolicyViolation as e:
    print(f"Policy violation: {e}")
except Exception as e:
    print(f"Error: {e}")
```

---

## Logging

The ADK module uses Python's standard `logging` module:

```python
import logging

# Enable debug logging
logging.basicConfig(level=logging.DEBUG)

# Or set per-module
logging.getLogger("branitz_heat_decision.adk").setLevel(logging.DEBUG)
```

---

## Testing

The ADK module can be tested independently:

```python
from branitz_heat_decision.adk import BranitzADKAgent
from branitz_heat_decision.adk.policies import PolicyViolation

# Test policy enforcement
agent = BranitzADKAgent(cluster_id="ST010", enforce_policies=True)

try:
    # This should raise PolicyViolation
    agent._execute_tool("modify_kpi_contract", phase="decision", cluster_id="ST010")
except PolicyViolation:
    print("✓ Policy enforcement working")

# Test trajectory validation
from branitz_heat_decision.adk.evals import validate_trajectory

trajectory = [
    {"phase": "cha", "status": "success"},
    {"phase": "dha", "status": "success"},
]

valid, issues = validate_trajectory(trajectory, cluster_id="ST010")
assert not valid  # Should fail (missing economics/decision)
```

---

## Summary

The ADK module provides:

1. ✅ **Minimal Intrusion**: No changes to existing modules
2. ✅ **Tool Wrappers**: Existing functionality wrapped as tools
3. ✅ **Guardrails**: Policies enforce critical constraints
4. ✅ **Evaluation**: Trajectory validation and artifact checks
5. ✅ **Agent Orchestration**: High-level pipeline orchestration
6. ✅ **Team Support**: Multi-agent batch processing

**Next Steps**:
- Integrate with LLM agent frameworks (e.g., LangChain, AutoGen)
- Add custom policies for specific use cases
- Extend evaluation metrics
- Add visualization of trajectories

---

**Last Updated**: 2026-01-19  
**Version**: 1.1

## Recent Updates (2026-01-19)

- **Default LLM Usage**: Decision and UHDC agents now default to using LLM explanations (`llm=True` by default)
- **Tool Path Fixes**: Corrected paths to pipeline scripts in `tools.py`
- **Agent Delegation**: Refined specialized agent structure (DataPrepAgent, CHAAgent, DHAAgent, etc.)
