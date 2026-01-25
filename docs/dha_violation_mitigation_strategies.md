# DHA Violation Mitigation Strategies

## Current Violations Summary
- **Line Overloads**: 74 violations (loading > 100%)
- **Planning Warnings**: 106 violations (loading 80-100%)
- **Worst Case**: Line_1449 at 197.1% loading (critical bottleneck)
- **Affected Elements**: 19 lines across 10 hours (design + TopN)

## Mitigation Strategies (in order of impact/cost)

### 1. **Grid Reinforcement (Highest Impact, Higher Cost)**

#### A. Cable/Line Upgrading
- **Action**: Replace overloaded cables with larger cross-sections
- **Implementation**: Increase `std_type` rating for affected lines
- **Impact**: Directly addresses overloads by increasing capacity
- **Cost**: Medium-High (material + labor)
- **Timeline**: Months to years (planning + construction)

**Example for line_1449 (197% → <100%):**
- Current: 150 mm² cable (estimated 50-80 A capacity)
- Required: 240 mm² or 300 mm² (estimated 100-150 A capacity)
- Reduction factor: ~1.5-2x capacity increase

#### B. Transformer Upgrading
- **Action**: Replace MV/LV transformers with higher rated units
- **Implementation**: Increase `sn_mva` in transformer parameters
- **Impact**: Increases headroom for all downstream loads
- **Cost**: High (transformers are expensive)
- **Timeline**: Years (procurement + installation)

**Example:**
- Current: 400 kVA transformer
- Required: 630 kVA or 1000 kVA transformer
- Impact: Reduces all feeder loading by 1.5-2.5x

### 2. **Load Management (Moderate Impact, Lower Cost)**

#### A. Time-of-Use (TOU) Controls
- **Action**: Shift HP operation to off-peak hours
- **Implementation**: Add control logic to delay HP starts during peak hours
- **Impact**: Reduces peak loading if peaks don't coincide with base load peaks
- **Cost**: Low (smart controls only)
- **Timeline**: Months (control system deployment)

#### B. Power Limiting / Peak Shaving
- **Action**: Limit HP power during grid peak hours
- **Implementation**: Reduce HP `P_el_kw` during critical hours (e.g., 70-80% of rated power)
- **Impact**: Reduces peak loading proportionally
- **Cost**: Very Low (software configuration)
- **Timeline**: Immediate

**Example for 197% → ~140%:**
- Apply 70% power limit: 197% × 0.7 = 138%
- Still above 100%, but reduces severity

#### C. Distributed Storage (Batteries)
- **Action**: Deploy battery storage to absorb HP loads
- **Implementation**: Add battery inverters that charge during low-load hours, discharge during peaks
- **Impact**: Can shift 20-50% of peak load
- **Cost**: High (batteries + inverters)
- **Timeline**: Months to years

### 3. **Penetration Reduction (Effective but Less Desirable)**

#### A. Reduce HP Capacity
- **Action**: Install smaller HP units or reduce rollout percentage
- **Implementation**: Reduce `hp_total_kw_design` in DHA config
- **Impact**: Linear reduction in violations (e.g., 50% capacity = ~50% violations)
- **Cost**: Low (smaller units cost less)
- **Timeline**: Immediate (design change)
- **Trade-off**: Lower heat supply, may need backup systems

**Example:**
- Current: 964 kW total HP capacity → 197% loading
- Reduce to: 490 kW (50%) → ~100% loading (marginal)
- Reduce to: 400 kW (41%) → ~80% loading (acceptable)

#### B. Selective Deployment
- **Action**: Install HPs only on buildings with sufficient grid capacity
- **Implementation**: Filter buildings by available grid headroom
- **Impact**: Targets violations directly
- **Cost**: Low (planning only)
- **Timeline**: Immediate

### 4. **Grid Topology Optimization (Moderate Impact, Medium Cost)**

#### A. Reconfiguration / Load Redistribution
- **Action**: Re-switch loads to distribute loading more evenly
- **Implementation**: Modify LV network topology (add switches, re-route lines)
- **Impact**: Can reduce worst-case loading by 10-30%
- **Cost**: Medium (switching equipment + planning)
- **Timeline**: Months

#### B. Additional Substations / Transformers
- **Action**: Add new MV/LV transformers to split loads
- **Implementation**: Add new substation points in `substations_gdf`
- **Impact**: Reduces feeder length and loading per transformer
- **Cost**: High (new substation infrastructure)
- **Timeline**: Years

### 5. **Advanced Technologies (Long-term)**

#### A. Smart Inverters / Grid-Forming Inverters
- **Action**: Use grid-supporting HP inverters with reactive power control
- **Implementation**: Configure HP power factor to support voltage
- **Impact**: Can improve voltage stability, reduce apparent loading
- **Cost**: Medium (premium inverters)
- **Timeline**: Years (technology maturity)

#### B. Demand Response Integration
- **Action**: Coordinate HP operation with DSO demand response signals
- **Implementation**: Connect HP controls to grid operator signals
- **Impact**: Enables dynamic load reduction during emergencies
- **Cost**: Low (communication infrastructure)
- **Timeline**: Months

### 6. **Combined Strategies (Recommended)**

**Hybrid Approach for line_1449 (197% → <100%):**
1. **Immediate** (0-6 months): Apply 70% power limiting → 138% loading
2. **Short-term** (6-12 months): Upgrade line_1449 cable → 100-120% loading
3. **Medium-term** (1-2 years): Add TOU controls → 80-100% loading
4. **Long-term** (2-5 years): Consider transformer upgrade if multiple feeders affected

## Implementation Priority Matrix

| Strategy | Impact | Cost | Timeline | Priority |
|----------|--------|------|----------|----------|
| Cable Upgrade (critical lines) | High | Medium | Months | **High** |
| Power Limiting | Medium | Very Low | Immediate | **High** |
| TOU Controls | Medium | Low | Months | **Medium** |
| Transformer Upgrade | Very High | High | Years | **Medium** |
| Load Reduction | High | Low | Immediate | **Low** (last resort) |
| Storage | High | High | Years | **Low** (future) |

## Code Integration Points

### 1. Load Management
- **File**: `src/branitz_heat_decision/dha/loadflow.py`
- **Modification**: Add `power_limiting_factor` parameter to `assign_hp_loads()`
- **Usage**: Apply 0.7-0.9 factor during peak hours

### 2. Grid Reinforcement
- **File**: `src/branitz_heat_decision/dha/grid_builder.py`
- **Modification**: Support `line_upgrade_map` to override std_type for specific lines
- **Usage**: Map critical lines to larger std_types

### 3. Transformer Upgrading
- **File**: `src/branitz_heat_decision/dha/config.py`
- **Modification**: Add `transformer_upgrade_sn_mva` parameter
- **Usage**: Increase transformer rating when violations detected

### 4. Violation-Aware Deployment
- **File**: `src/branitz_heat_decision/dha/kpi_extractor.py`
- **Modification**: Add `violation_mitigation_report()` function
- **Usage**: Generate recommendations based on violation patterns

## Recommended Next Steps

1. **Immediate Analysis**:
   - Identify critical bottleneck (line_1449)
   - Calculate required capacity increase
   - Estimate cost for cable upgrade

2. **Short-term Actions**:
   - Implement power limiting in DHA config
   - Re-run simulation to verify violation reduction
   - Document remaining violations

3. **Planning Phase**:
   - Contact DSO for grid reinforcement approval
   - Evaluate TOU control feasibility
   - Cost-benefit analysis of transformer upgrade

4. **Monitoring**:
   - Track violations across scenarios
   - Monitor actual grid loading post-deployment
   - Adjust controls based on real-world data

## References
- VDE-AR-N 4100: Technical connection rules for LV grids
- DIN EN 50604-1: LV grid design standards
- Grid hosting capacity studies typically allow 80% planning limit, 100% operational limit
