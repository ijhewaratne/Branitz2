# Decision Pipeline

This document describes the Phase 5 decision pipeline implemented in `src/branitz_heat_decision/decision/rules.py`.

## Overview

Inputs:
- KPI contract (`kpi_contract_<cluster>.json`) built from CHA/DHA/Economics outputs

Outputs:
- Decision JSON (`decision_<cluster>.json`)
- Explanation (LLM or safe template) + UHDC HTML/MD report

## Decision Logic Flow (Mermaid)

```mermaid
graph TD
    A[KPI Contract] --> B{Feasibility Gate}
    B -->|Only DH feasible| C[Choose DH<br/>ONLY_DH_FEASIBLE]
    B -->|Only HP feasible| D[Choose HP<br/>ONLY_HP_FEASIBLE]
    B -->|Neither feasible| E[Choose UNDECIDED<br/>NONE_FEASIBLE]
    B -->|Both feasible| F{Costs close?<br/>(rel ≤ 5% OR abs ≤ 5 €/MWh)}

    F -->|No (clear winner)| G[Choose cheaper<br/>COST_DOMINANT_DH or COST_DOMINANT_HP]
    F -->|Yes| H{CO₂ tie-breaker}

    H -->|DH CO₂ ≤ HP CO₂| I[Choose DH<br/>COST_CLOSE_USE_CO2 + CO2_TIEBREAKER_DH]
    H -->|HP CO₂ < DH CO₂| J[Choose HP<br/>COST_CLOSE_USE_CO2 + CO2_TIEBREAKER_HP]

    C --> K{Monte Carlo available?}
    D --> K
    E --> K
    G --> K
    I --> K
    J --> K

    K -->|No| L[Append MC_MISSING]
    K -->|Yes| M{Win fraction ≥ robust threshold?}
    M -->|Yes| N[Append ROBUST_DECISION]
    M -->|No but ≥ sensitive threshold| O[Append SENSITIVE_DECISION]
    M -->|No (below sensitive)| P[No robustness flag]
```

