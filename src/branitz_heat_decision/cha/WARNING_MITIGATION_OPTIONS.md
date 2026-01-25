# Options for Addressing Validation Warnings

This document outlines actionable options for the two validation warnings in trunk-spur networks.

---

## Warning 1: Low Velocity Pipes (< 0.2 m/s)

**Current Status**: 230 pipes have velocity < 0.2 m/s

### Analysis
- **Return pipes**: 54 (23.5%) - Expected low velocity
- **Supply pipes**: 53 (23.0%) - Could be optimized
- **Average velocity**: 0.085 m/s (very low)
- **Min velocity**: 0.0007 m/s (extremely low)

### Options

#### Option A: Accept as-is (Recommended) ✅
**Action**: No changes needed
- **Rationale**: Low velocity is expected in trunk-spur networks
- **Risk**: Sedimentation (mitigated by periodic flushing)
- **Cost**: Maintenance only
- **Effort**: None

#### Option B: Optimize Supply Pipes Only
**Action**: Reduce diameters for supply pipes with low velocity
- **Rationale**: Increase velocity in supply pipes while accepting return pipes
- **Implementation**: 
  - Identify supply pipes with velocity < 0.2 m/s
  - Reduce diameter by one DN step (e.g., DN50 → DN40)
  - Re-run simulation and validation
- **Expected Result**: ~50-100 fewer low-velocity pipes
- **Risk**: May increase pressure drops
- **Cost**: Low (pipe sizing change only)
- **Effort**: Medium (requires re-sizing and validation)

#### Option C: Suppress Warning for Trunk-Spur Networks
**Action**: Make warning informational only (not shown in validation report)
- **Rationale**: These warnings are expected and not actionable
- **Implementation**: Update validation config to skip low-velocity check for trunk-spur
- **Expected Result**: Warning removed from report
- **Risk**: None
- **Cost**: None
- **Effort**: Low (config change only)

---

## Warning 2: Flow Distribution Imbalance (CV=1.48)

**Current Status**: High CV due to trunk-spur topology

### Analysis
- **CV = 1.48**: High variation (trunk pipes: high flow, spur pipes: low flow)
- **Root Cause**: Inherent to trunk-spur design
- **Impact**: None (network operates correctly)

### Options

#### Option A: Accept as Design Feature (Recommended) ✅
**Action**: No changes needed
- **Rationale**: High CV is expected and acceptable in trunk-spur networks
- **Impact**: None (design feature, not a flaw)
- **Cost**: None
- **Effort**: None

#### Option B: Calculate Separate CV for Trunk vs Spur
**Action**: Report CV separately for trunk and spur pipes
- **Rationale**: More meaningful metrics (trunk CV and spur CV separately)
- **Implementation**: 
  - Calculate CV for trunk pipes only
  - Calculate CV for spur pipes only
  - Report both metrics
- **Expected Result**: More granular metrics, better understanding
- **Risk**: None
- **Cost**: None
- **Effort**: Medium (validation code update)

#### Option C: Suppress Warning for Trunk-Spur Networks
**Action**: Make warning informational only
- **Rationale**: This warning is not actionable for trunk-spur networks
- **Implementation**: Update validation config to skip CV check for trunk-spur
- **Expected Result**: Warning removed from report
- **Risk**: None
- **Cost**: None
- **Effort**: Low (config change only)

---

## Recommended Approach

### For Production Use:
1. **Accept both warnings** as expected behavior
2. **Document** why they're acceptable (already done in `VALIDATION_WARNINGS_EXPLAINED.md`)
3. **Monitor** network performance (not validation warnings)

### For Clean Validation Reports:
1. **Suppress warnings** for trunk-spur networks (Option C for both)
2. **Keep warnings** as informational logs (not in validation report)
3. **Focus validation** on actionable issues only

### For Optimization:
1. **Optimize supply pipes** (Option B for Warning 1)
2. **Calculate separate CV** (Option B for Warning 2)
3. **Re-run validation** to see improvements

---

## Implementation Guide

### To Suppress Warnings (Option C):

1. Update `validation_standards.py`:
```python
@dataclass
class ValidationConfig:
    # Add flag to suppress expected warnings for trunk-spur
    suppress_trunk_spur_warnings: bool = True
```

2. Update `hydraulic_checks.py`:
```python
if is_trunk_spur and self.config.suppress_trunk_spur_warnings:
    # Skip warning (or make it informational)
    pass
else:
    warnings.append(...)
```

### To Optimize Supply Pipes (Option B):

1. Create optimization script:
```python
# Identify supply pipes with low velocity
supply_pipes = net.pipe[net.pipe['name'].str.startswith('pipe_S_')]
low_v_supply = supply_pipes[net.res_pipe.loc[supply_pipes.index, 'v_mean_m_per_s'] < 0.2]

# Reduce diameters by one DN step
for pipe_idx in low_v_supply.index:
    current_dn = net.pipe.loc[pipe_idx, 'diameter_m'] * 1000  # mm
    # Find next smaller DN
    smaller_dn = find_next_smaller_dn(current_dn, catalog)
    net.pipe.loc[pipe_idx, 'diameter_m'] = smaller_dn / 1000

# Re-run simulation
pp.pipeflow(net)
```

---

## Decision Matrix

| Option | Effort | Cost | Benefit | Risk | Recommended? |
|--------|--------|------|---------|------|---------------|
| Accept as-is | None | None | None | Low | ✅ Yes (Production) |
| Optimize supply pipes | Medium | Low | Medium | Medium | ⚠️ Optional |
| Suppress warnings | Low | None | High | None | ✅ Yes (Clean reports) |
| Separate CV metrics | Medium | None | Medium | None | ⚠️ Optional |

---

**Last Updated**: 2026-01-24  
**For Questions**: See `VALIDATION_WARNINGS_EXPLAINED.md`
