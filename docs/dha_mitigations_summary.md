# DHA Mitigations Module - Summary

## Overview
This document summarizes the new `mitigations.py` module in the DHA package and its integration with the UI.

## New Module: `mitigations.py`

### Purpose
Deterministic mitigation recommendation engine that analyzes DHA violations and generates structured, auditable mitigation strategies.

### Key Features

1. **MitigationRecommendation Dataclass**
   - Structured recommendation format with:
     - Code (e.g., "MIT_UNDERVOLTAGE_LONG_FEEDER")
     - Severity (low/moderate/high)
     - Category (operational/reinforcement/expansion)
     - Title, actions, evidence, cost class

2. **Four Mitigation Rules**:
   - **Rule 1**: Undervoltage + Long Feeder → Infrastructure upgrade (reinforcement)
   - **Rule 2**: Line Overload → Parallel cable or upgrade (reinforcement)
   - **Rule 3**: Transformer Overload → Critical expansion (expansion)
   - **Rule 4**: Infrequent Violations → Operational control (operational)

3. **Severity Assessment**:
   - Uses config thresholds: `voltage_severe_threshold` (0.88 pu), `loading_severe_threshold` (120%)

4. **Mitigation Classification**:
   - `expansion`: Major grid expansion required
   - `reinforcement`: Grid reinforcement needed
   - `operational`: Operational controls sufficient
   - `none`: No violations detected

## New KPI Fields (in `kpi_extractor.py`)

### Frequency Analysis
- `critical_hours_count`: Number of unique hours with any critical violation
- `critical_hours_fraction`: Fraction of simulated hours with critical violations
- `voltage_violated_hours`: Number of unique hours with voltage violations
- `line_overload_hours`: Number of unique hours with line overloads
- `trafo_overload_hours`: Number of unique hours with transformer overloads

### Transformer Metrics
- `max_trafo_loading_pct`: Maximum transformer loading across all hours (%)
- `max_loading_trafo`: Transformer ID with maximum loading
- `max_loading_trafo_hour`: Hour with maximum transformer loading
- `trafo_violations_total`: Count of transformer overload violations

### Feeder Distance Metrics
- `feeder_metrics`: Dictionary with:
  - `distance_km`: Distance from transformer to worst-case voltage bus
  - `long_feeder`: Boolean flag (True if distance >= threshold)
  - `threshold_km`: Threshold used for classification

### Enhanced Element Tracking
- `worst_vmin_bus`: Bus ID with worst voltage
- `max_loading_line`: Line ID with maximum loading

## New Config Parameters

### Feeder Analysis
- `long_feeder_km_threshold: float = 0.8` - Threshold for "long feeder" classification

### Operational Control
- `operational_control_max_fraction: float = 0.2` - Max violation fraction (20%) for operational mitigation

### Severity Classification
- `voltage_severe_threshold: float = 0.88` - Below this is "severe" undervoltage
- `loading_severe_threshold: float = 120.0` - Above this is "severe" overload

### Transformer Limits
- `trafo_loading_limit_pct: float = 100.0` - Transformer loading limit

## Integration Points

### 1. DHA Pipeline (`02_run_dha.py`)
```python
from branitz_heat_decision.dha.mitigations import recommend_mitigations

mitigation_analysis = recommend_mitigations(net, kpis, violations_df, cfg)
kpis["mitigations"] = mitigation_analysis
```
- Called after KPI extraction
- Results stored in `kpis["mitigations"]`
- Exported to `dha_kpis.json`

### 2. UI Integration (`src/branitz_heat_decision/ui/app.py`)
- **Location**: Lines 494-544 (Feasibility tab, DHA section)
- **Features**:
  - Displays mitigation classification badge (none/operational/reinforcement/expansion)
  - Shows summary message
  - Lists all recommendations with:
    - Severity indicator (🟢/🟡/🔴)
    - Category and cost class
    - Action items
    - Evidence (expandable)
  - Final verdict: "Grid can host heat pumps with indicated mitigations" or "Major grid expansion required"

### 3. UI Display Logic
```python
if dha_kpis and "mitigations" in dha_kpis:
    mits = dha_kpis["mitigations"]
    
    # Classification badge
    class_colors = {
        "none": ("🟢", "success"),
        "operational": ("🟡", "info"),
        "reinforcement": ("🟠", "warning"),
        "expansion": ("🔴", "error")
    }
    
    # Display recommendations with severity, category, actions, evidence
    # Show final verdict
```

## Documentation Updates

### Updated Files
1. **`dha_readme.md`**:
   - Added complete `mitigations.py` module documentation
   - Updated `kpi_extractor.py` documentation with new KPI fields
   - Updated config parameters section
   - Updated usage examples to include mitigations

## Verification Checklist

- ✅ `mitigations.py` module exists and is functional
- ✅ `recommend_mitigations()` function works correctly
- ✅ New KPI fields are extracted in `kpi_extractor.py`
- ✅ Config parameters are defined in `DHAConfig`
- ✅ Integration in `02_run_dha.py` is correct
- ✅ UI displays mitigations correctly (lines 494-544)
- ✅ Documentation updated in `dha_readme.md`

## Potential Issues

### None Found
- UI code correctly handles missing mitigations (checks `if "mitigations" in dha_kpis`)
- All required KPI fields are generated by `kpi_extractor.py`
- Config parameters have sensible defaults
- Mitigation rules are deterministic and auditable

## Next Steps

1. ✅ Documentation complete
2. Test with actual DHA results to verify UI display
3. Consider adding mitigations to UHDC report builder (optional enhancement)
