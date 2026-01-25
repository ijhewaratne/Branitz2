## Phase 4: Economics & Monte Carlo — Implementation Checklist

**Goal**: Deterministic LCOH/CO₂ + Monte Carlo (N=500) uncertainty with auditable outputs.

Status legend:
- **[x]** implemented in this repo
- **[ ]** not implemented yet / needs verification

---

## Pre-Implementation Setup

- [x] **Directory structure created**
  - [x] `src/branitz_heat_decision/economics/` (`params.py`, `lcoh.py`, `co2.py`, `monte_carlo.py`, `utils.py`, `__init__.py`)
  - [x] `src/branitz_heat_decision/cli/economics.py`
  - [x] `src/scripts/03_run_economics.py`

- [ ] **Dependencies installed / declared**
  - [x] `numpy>=1.24.0` (used; in `requirements.txt`)
  - [x] `pandas>=2.0.0` (used; in `requirements.txt`)
  - [x] `tqdm>=4.64.0` (optional progress bar; added to `requirements.txt`)
  - [x] `pyyaml>=6.0` (scenario YAML support; added to `requirements.txt`)
  - [x] `pytest>=7.4.0` (repo uses pytest; economics tests added)

---

## Core Implementation

### 1) Economic Parameters (`params.py`)

- [x] **`EconomicParameters` dataclass defined**
  - [x] Attributes from spec present (lifetime, discount_rate, prices, emission factors, costs, O&M, generation type)
  - [x] `__post_init__` validates ranges (discount_rate in (0,1), lifetime > 0, generation type valid)
  - [x] `load_default_params()`
  - [x] `load_params_from_yaml(path)` (YAML)
  - [x] Includes `feeder_loading_planning_limit` for HP LV-upgrade heuristic

- [x] **Cost tables populated**
  - [x] `pipe_cost_eur_per_m` includes DN20..DN200 defaults

---

### 2) LCOH Core Engine (`lcoh.py`)

- [x] **`compute_lcoh_dh()` implemented**
  - [x] Accepts `pipe_lengths_by_dn` OR `total_pipe_length_m`
  - [x] CAPEX: pipes + plant + pump
  - [x] OPEX: O&M + energy (gas/biomass/electric)
  - [x] CRF calculated via `utils.crf()` (includes r=0 special case)
  - [x] Returns `(lcoh, breakdown)`

- [x] **`compute_lcoh_hp()` implemented**
  - [x] CAPEX: HP equipment + LV upgrade heuristic (if loading > planning limit)
  - [x] OPEX: O&M + electricity
  - [x] Returns `(lcoh, breakdown)`

- [x] **Helper functions in `utils.py`**
  - [x] `calculate_crf(discount_rate, lifetime_years)`
  - [x] `calculate_pv_factor(discount_rate, lifetime_years)`
  - [x] `calculate_npv(cash_flows, discount_rate)`

---

### 3) CO₂ Engine (`co2.py`)

- [x] **`compute_co2_dh()` implemented**
  - [x] gas (90% eff), biomass (85% eff), electric (central COP=3)
  - [x] Returns `(kg_co2_per_mwh, breakdown)`
  - [x] Acceptance check: gas=200/0.9=222.2 kg/MWh; biomass=25/0.85=29.4 kg/MWh

- [x] **`compute_co2_hp()` implemented**
  - [x] Formula: \((Heat / COP) * EF_{electricity}\)
  - [x] Returns `(kg_co2_per_mwh, breakdown)`
  - [x] Acceptance check: COP=2.8, EF=350 → 125 kg/MWh

---

### 4) Monte Carlo (`monte_carlo.py`)

- [x] **`sample_param()` implemented**
  - [x] normal / lognormal / triangular / uniform
  - [x] clip supported

- [x] **`run_monte_carlo_for_cluster()` implemented**
  - [x] Returns `pd.DataFrame` with `sample_id`, LCOH/CO₂, winner flags, `param_*`
  - [x] Default randomness config exists (if none provided)
  - [x] Reproducible seeds (deterministic per-sample seed generation)
  - [x] Optional `tqdm` progress bar
  - [x] `n_jobs>1` supported; macOS-safe via `fork` context where available

- [x] **`compute_mc_summary()` implemented**
  - [x] Filters NaN samples
  - [x] Computes p05/p50/p95/mean/std for LCOH and CO₂
  - [x] Computes win fractions
  - [x] Includes `n_samples`, `n_valid`

---

## CLI Integration (Phase 4.4)

- [x] **CLI module exists**: `src/branitz_heat_decision/cli/economics.py`
  - [x] Reads CHA KPIs + DHA KPIs
  - [x] Reads `cluster_load_summary.parquet` **or falls back** to computing `annual_heat_mwh`/`design_load_kw` from processed profiles when cluster_id mismatch exists
  - [x] Supports `--scenario` YAML + `--randomness-config` JSON
  - [x] Writes:
    - [x] `monte_carlo_samples.parquet`
    - [x] `monte_carlo_summary.json` (with metadata + decision insight)

---

## Testing & Validation

- [x] Create `tests/economics/` test suite
  - [x] `test_params.py`
  - [x] `test_lcoh.py`
  - [x] `test_co2.py`
  - [x] `test_monte_carlo.py`
  - [x] Integration test: `test_full_pipeline.py` (end-to-end `run_economics_for_cluster`)

### How to run tests

From repo root:

```bash
PYTHONPATH=src pytest tests/economics -v --tb=short
```

---

## Documentation

- [x] Add `docs/economics.md` (CRF method, parameter table, scenario YAMLs, how to interpret outputs)
- [x] Add scenario YAML examples under `scripts/scenarios/`:
  - [x] `scripts/scenarios/2023_baseline.yaml`
  - [x] `scripts/scenarios/2030_optimistic.yaml`
  - [x] `scripts/scenarios/custom.yaml`

### How to run economics with a scenario YAML

```bash
PYTHONPATH=src python -m branitz_heat_decision.cli.economics \
  --cluster-id ST010_HEINRICH_ZILLE_STRASSE \
  --cha-kpis results/cha/ST010_HEINRICH_ZILLE_STRASSE/cha_kpis.json \
  --dha-kpis results/dha/ST010_HEINRICH_ZILLE_STRASSE/dha_kpis.json \
  --cluster-summary data/processed/cluster_load_summary.parquet \
  --out results/economics/ST010_HEINRICH_ZILLE_STRASSE \
  --scenario scripts/scenarios/2023_baseline.yaml \
  --n-samples 500 \
  --seed 42
```

---

## Phase 5 Blocking “Must-Haves”

- [x] `compute_lcoh_dh()` and `compute_lcoh_hp()` return correct values + breakdown
- [x] `run_monte_carlo_for_cluster()` produces reproducible DataFrame
- [x] `compute_mc_summary()` calculates win fractions correctly
- [x] CLI runs end-to-end and writes samples + summary
- [x] `monte_carlo_summary.json` schema matches Phase 5 contract shape:
  - [x] `lcoh.dh.p05/p50/p95`, `lcoh.hp.p05/p50/p95`
  - [x] `co2.dh.p05/p50/p95`, `co2.hp.p05/p50/p95`
  - [x] `monte_carlo.dh_wins_fraction`, `monte_carlo.hp_wins_fraction`

