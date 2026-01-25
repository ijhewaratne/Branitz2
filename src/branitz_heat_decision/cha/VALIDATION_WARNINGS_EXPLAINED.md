# Validation Warnings Explained

This document explains why certain validation warnings are **expected and acceptable** in trunk-spur district heating networks.

---

## 1. Low Velocity Pipes (< 0.2 m/s)

### Warning Message
```
230 pipes have velocity < 0.2 m/s (expected in trunk-spur networks: return pipes and spurs naturally have lower flow; sedimentation risk mitigated by periodic flushing)
```

### Why This Is Expected

In trunk-spur networks, low velocities are **normal** due to the network topology:

1. **Return Pipes**: 
   - Return pipes carry water back to the plant after heat extraction
   - Flow is typically lower than supply pipes (water cools, contracts slightly)
   - **Expected**: ~50% of pipes are return pipes with lower velocities

2. **Spur Pipes**:
   - Spur pipes serve individual buildings
   - Each spur carries flow for only one building (typically 5-50 kW)
   - **Expected**: Low flow = low velocity

3. **End-of-Line Pipes**:
   - Pipes at the end of branches have minimal flow
   - Both supply and return end-of-line pipes have low velocities
   - **Expected**: Natural consequence of tree topology

### Risk Assessment

- **Risk**: Sedimentation (particles settling in low-flow pipes)
- **Mitigation**: 
  - Periodic flushing during maintenance
  - Proper pipe sizing (already done)
  - Network design accounts for this
- **Severity**: **Low** - Acceptable with proper maintenance

### When to Worry

⚠️ **Action Required** if:
- Low-velocity pipes are in **main trunk lines** (not return/spur)
- Low-velocity pipes are causing **actual blockages**
- Network has **no maintenance plan** for flushing

✅ **Acceptable** if:
- Low-velocity pipes are primarily return pipes or spurs
- Network has >50% low-velocity pipes (typical for trunk-spur)
- No operational issues observed

---

## 2. Flow Distribution Imbalance (CV > 1.0)

### Warning Message
```
High flow distribution imbalance (CV=1.48), expected in trunk-spur networks: trunk pipes carry aggregated high flow, spur pipes carry single-building low flow (design feature, not a flaw)
```

### Why This Is Expected

**CV (Coefficient of Variation)** measures how evenly flow is distributed:
- **CV = 0**: All pipes have identical flow (unrealistic)
- **CV = 1.0**: Moderate variation
- **CV > 1.0**: High variation (expected in trunk-spur)

In trunk-spur networks, **high CV is a design feature**:

1. **Trunk Pipes**:
   - Carry **aggregated flow** from many buildings
   - Example: 50 buildings × 20 kW = 1000 kW → high flow
   - **High velocity** (1.0-1.5 m/s)

2. **Spur Pipes**:
   - Carry **single-building flow**
   - Example: 1 building × 20 kW = 20 kW → low flow
   - **Low velocity** (0.1-0.5 m/s)

3. **Natural Variation**:
   - Flow varies by **100x** between trunk and spur
   - This is **intentional** - efficient design
   - **Not a flaw** - it's how trunk-spur works!

### Risk Assessment

- **Risk**: None - this is expected behavior
- **Impact**: **None** - network operates correctly
- **Severity**: **Informational** - not a problem

### When to Worry

⚠️ **Action Required** if:
- CV > 2.0 **within trunk pipes only** (indicates poor trunk sizing)
- CV > 2.0 **within spur pipes only** (indicates inconsistent building loads)
- Network has **operational issues** (pressure drops, flow problems)

✅ **Acceptable** if:
- CV > 1.0 **overall** (trunk + spur combined)
- Trunk pipes have reasonable CV (< 0.5)
- Spur pipes have reasonable CV (< 0.5)
- Network operates correctly

---

## Summary

| Warning | Expected? | Action Required? | Notes |
|---------|-----------|------------------|-------|
| Low velocity pipes | ✅ Yes | ❌ No | Normal in trunk-spur; mitigate with flushing |
| Flow imbalance (CV>1.0) | ✅ Yes | ❌ No | Design feature, not a flaw |

---

## Validation Logic

The validation system now **automatically detects** trunk-spur networks and provides context-aware warnings:

1. **Detects trunk-spur** by checking for:
   - Dual pipes (supply "S" + return "R")
   - Pipe names containing "spur" or "trunk"

2. **Adjusts warnings** to explain:
   - Why the warning occurs
   - That it's expected in trunk-spur networks
   - How to mitigate risks (if any)

3. **Maintains strict checks** for:
   - High velocity violations (still critical)
   - Pressure issues (still critical)
   - Connectivity problems (still critical)

---

## References

- **EN 13941-1**: Design and installation of district heating networks
- **VDI 2067**: Economic efficiency of building services
- **Trunk-Spur Design**: Standard topology for district heating networks

---

**Last Updated**: 2026-01-24  
**For Questions**: See `HOW_TO_FIX_VALIDATION_ISSUES.md`
