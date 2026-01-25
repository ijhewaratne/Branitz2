# Reason Codes Reference

This document is the **auditable taxonomy** of reason codes used by Phase 5 (Decision & UHDC).

- **Source of truth**: `src/branitz_heat_decision/decision/schemas.py` (`REASON_CODES`)
- **Used by**:
  - `src/branitz_heat_decision/decision/kpi_contract.py` (inference)
  - `src/branitz_heat_decision/decision/rules.py` (decision rationale)
  - `src/branitz_heat_decision/uhdc/*` (report rendering / explainer)

## Table (all codes)

| Code | Category | Description | Example trigger |
|------|----------|-------------|-----------------|
| `DH_OK` | feasibility | District heating meets all EN 13941-1 hydraulic and thermal constraints | EN checks pass |
| `DH_VELOCITY_VIOLATION` | feasibility | DH velocity exceeds 1.5 m/s limit | \(v_{max}\) > 1.5 m/s |
| `DH_DP_VIOLATION` | feasibility | DH pressure drop per 100m exceeds EN 13941-1 envelope | \(\Delta p/100m\) too high |
| `DH_HARD_VIOLATION` | feasibility | DH has hard constraint violations (e.g., negative pressures) | any hard violation flag set |
| `DH_HIGH_LOSSES_WARNING` | feasibility | DH thermal losses exceed 5% threshold | loss_share_pct > 5 |
| `HP_OK` | feasibility | Heat pumps meet all VDE-AR-N 4100 LV grid constraints | no voltage/line violations |
| `HP_UNDERVOLTAGE` | feasibility | HP rollout causes voltage < 0.95 pu | vm_pu below v_min |
| `HP_OVERCURRENT_OR_OVERLOAD` | feasibility | HP rollout causes line loading > 100% | loading_percent > 100 |
| `HP_PLANNING_WARNING_80PCT` | feasibility | HP rollout exceeds 80% planning headroom | max loading > 80% |
| `ONLY_DH_FEASIBLE` | decision | Only district heating is technically feasible | DH feasible, HP infeasible |
| `ONLY_HP_FEASIBLE` | decision | Only heat pumps are technically feasible | HP feasible, DH infeasible |
| `NONE_FEASIBLE` | decision | Neither option meets technical constraints | both infeasible |
| `COST_DOMINANT_DH` | economics | DH LCOH is >5% lower than HP (clear economic winner) | LCOH_DH << LCOH_HP |
| `COST_DOMINANT_HP` | economics | HP LCOH is >5% lower than DH (clear economic winner) | LCOH_HP << LCOH_DH |
| `COST_CLOSE_USE_CO2` | tie-breaker | LCOH difference ≤5% → using CO₂ as tie-breaker | costs close |
| `CO2_TIEBREAKER_DH` | tie-breaker | DH chosen due to lower CO₂ emissions (costs close) | CO2_DH < CO2_HP |
| `CO2_TIEBREAKER_HP` | tie-breaker | HP chosen due to lower CO₂ emissions (costs close) | CO2_HP < CO2_DH |
| `ROBUST_DECISION` | robustness | Monte Carlo win fraction ≥70% → decision stable | wins ≥ 0.70 |
| `SENSITIVE_DECISION` | robustness | Monte Carlo win fraction 55-70% → decision sensitive | 0.55 ≤ wins < 0.70 |
| `CHA_MISSING_KPIS` | data quality | Missing critical CHA KPIs (cannot assess DH feasibility) | missing v_share / dp |
| `DHA_MISSING_KPIS` | data quality | Missing critical DHA KPIs (cannot assess HP feasibility) | missing violation counts |
| `MC_MISSING` | data quality | Monte Carlo data missing → robustness cannot be assessed | no MC block |
| `CHA_DATA_INCOMPLETE` | data quality | CHA: Missing envelope or typology data; using TABULA defaults | missing building attributes |
| `DHA_SYNTHETIC_GRID_WARNING` | data quality | DHA: LV grid is synthetic/approximated; validation with utility data required | grid_source=synthetic |
| `ECON_DATA_ESTIMATED` | data quality | Economics: Annual heat demand estimated from design load; real meter data preferred | fallback heat estimate used |
| `MC_SAMPLE_WARNING_LT100` | data quality | Monte Carlo: <100 samples; confidence intervals may be unreliable | n_samples < 100 |
| `COST_RATIO_EXTREME_GT3X` | economics | Economics: LCOH ratio >3x between options; sensitivity analysis strongly recommended | max(LCOH)/min(LCOH) > 3 |
| `CO2_NEGATIVE_HP` | economics | CO2: HP emissions negative in scenario (grid factor <0); check emission factor assumptions | ef_electricity < 0 |
| `LCOH_EQUALITY` | economics | LCOH tie: Costs are identical; decision based purely on CO2 or robustness | LCOH_DH == LCOH_HP |
| `DH_OVERSIZED_MINOR` | technical | DH: Network slightly oversized (v_avg <0.3 m/s); minor cost optimization possible | v_avg < 0.3 |
| `HP_LOADING_MARGINAL_80_85` | technical | HP: Max feeder loading 80-85%; marginal planning warning; monitor grid evolution | 80 ≤ loading ≤ 85 |
| `CHOROPLETH_MISSING` | visualization | Visualization: Interactive map missing; QGIS export failed or not requested | map file missing |

