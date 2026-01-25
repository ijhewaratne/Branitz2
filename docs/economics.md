## Economics Module Guide (Phase 4)

This document explains how the economics module computes **LCOH** (Levelized Cost of Heat) and **CO₂** for:
- District Heating (DH)
- Heat Pumps (HP)

It also explains how **Monte Carlo (N=500)** uncertainty propagation works and how to interpret outputs.

---

## LCOH Method (CRF / annuitized CAPEX)

We use an annuitized cost method with the **Capital Recovery Factor (CRF)**:

\[
\text{LCOH} = \frac{\text{CAPEX} \cdot \text{CRF} + \text{OPEX}_{annual}}{\text{AnnualHeat}_{MWh}}
\]

\[
\text{CRF} = \frac{r(1+r)^n}{(1+r)^n-1}
\]

Special case: if \(r=0\), then \(\text{CRF}=1/n\).

Implementation:
- `src/branitz_heat_decision/economics/utils.py`
- `src/branitz_heat_decision/economics/lcoh.py`

---

## Default Parameters

Parameters are defined in:
- `src/branitz_heat_decision/economics/params.py` (`EconomicParameters`)

Key defaults (baseline):
- **lifetime_years**: 20 years
- **discount_rate**: 0.04
- **electricity_price_eur_per_mwh**: 250
- **gas_price_eur_per_mwh**: 80
- **biomass_price_eur_per_mwh**: 110
- **plant_cost_base_eur**: 1,500,000
- **cop_default**: 2.8
- **dh_generation_type**: biomass

Pipe cost table:
- `pipe_cost_eur_per_m` (DN20..DN200)

---

## CO₂ Method

### DH

Generation-specific assumptions (in `compute_co2_dh`):
- **gas**: efficiency 0.90
- **biomass**: efficiency 0.85
- **electric**: central COP=3.0 (large HP)

Returns:
- **kgCO₂/MWh_th** (specific)
- annual total (kg/year) in breakdown

### HP

\[
E_{el,MWh}=\frac{Q_{heat,MWh}}{COP}
\]
\[
CO_2=\;E_{el,MWh} \cdot EF_{el,kg/MWh}
\]

Implementation:
- `src/branitz_heat_decision/economics/co2.py`

---

## Monte Carlo (Uncertainty)

We sample parameter distributions (normal/lognormal/triangular/uniform) and run LCOH/CO₂ per sample.

Outputs:
- `monte_carlo_samples.parquet`: per-sample results + `param_*` sampled values
- `monte_carlo_summary.json`: p05/p50/p95/mean/std + win fractions

Implementation:
- `src/branitz_heat_decision/economics/monte_carlo.py`

Interpretation:
- **p50**: median (“most likely”)
- **p05–p95**: 90% interval
- **dh_wins_fraction**: fraction of samples where DH is cheaper than HP

---

## Running Economics via CLI

Because this repo is typically run without installation, use `PYTHONPATH=src`:

```bash
PYTHONPATH=src python -m branitz_heat_decision.cli.economics \
  --cluster-id ST010_HEINRICH_ZILLE_STRASSE \
  --cha-kpis results/cha/ST010_HEINRICH_ZILLE_STRASSE/cha_kpis.json \
  --dha-kpis results/dha/ST010_HEINRICH_ZILLE_STRASSE/dha_kpis.json \
  --cluster-summary data/processed/cluster_load_summary.parquet \
  --out results/economics/ST010_HEINRICH_ZILLE_STRASSE \
  --n-samples 500 \
  --seed 42
```

Optional:
- `--scenario <yaml>`: override parameters from YAML
- `--randomness-config <json>`: override Monte Carlo distributions
- `--n-jobs -1`: parallel processing (when supported)

