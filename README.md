# Branitz Heat Decision AI System

A deterministic, auditable multi-agent framework for climate-neutral urban heat planning.

## Uniqueness
- **True Multi-Physics**: Couples pandapipes (hydraulic-thermal) + pandapower (LV grid)
- **Explainable AI**: Constrained LLM coordinator (read-only, no hallucination)
- **Standards-Aligned**: EN 13941-1 (DH), VDE-AR-N 4100 (LV grid)
- **Uncertainty-Aware**: Monte Carlo win fractions drive robustness flags
- **Street-Level Maps**: Interactive with cascading colors & pipe sizing

## Setup

### Prerequisites
- Conda (Miniconda or Anaconda)
- Git

### Installation

1. **Clone the repository** (if applicable):
   ```bash
   git clone <repository-url>
   cd branitz_heat_decision
   ```

2. **Create and activate the conda environment**:
   ```bash
   conda env create -f environment.yml
   conda activate branitz_heat
   ```

3. **Set up data directory** (optional):
   ```bash
   export BRANITZ_DATA_ROOT=/path/to/your/data
   ```

4. **Verify installation**:
   ```bash
   python -c "import pandas, geopandas, pandapipes, pandapower; print('All packages installed successfully!')"
   ```

## Quick Start
```bash
export BRANITZ_DATA_ROOT=/path/to/your/data
python -m src.scripts.pipeline --cluster-id ST001_HEINRICH_ZILLE_STRASSE
```

## Optional: Enable LLM Explanations (Gemini)

LLM explanations are **optional**. Without a key, the decision pipeline will automatically fall back to a safe template explanation.

1. **Create `.env` in the repo root** (never commit this file):

```bash
echo 'GOOGLE_API_KEY=your_key_here' > .env
echo 'GOOGLE_MODEL=gemini-2.0-flash' >> .env   # optional
echo 'LLM_TIMEOUT=30' >> .env                  # optional
echo 'UHDC_FORCE_TEMPLATE=false' >> .env       # optional
```

2. **Verify environment wiring**:

```bash
PYTHONPATH=src python -c "from branitz_heat_decision.uhdc.explainer import LLM_READY; print('LLM ready:', LLM_READY)"
```

3. **Run decision with LLM explanation**:

```bash
PYTHONPATH=src python -m branitz_heat_decision.cli.decision \
  --cluster-id ST010_HEINRICH_ZILLE_STRASSE \
  --llm-explanation \
  --explanation-style executive
```

### Security notes
- **Do not commit keys**: `.env` is gitignored (see `.gitignore`).
- **CI/CD**: inject `GOOGLE_API_KEY` via environment variables/secrets, not files.
- **If a key was committed accidentally**: remove it from git history and **rotate the key** immediately.

## Project Structure
- `data/raw/`: Original Wärmekataster, OSM, Stadtwerke data
- `data/processed/`: Validated, pipeline-ready data (GeoParquet)
- `results/`: All outputs (deterministic, versioned)
- `src/`: Modular Python package
- `scripts/`: CLI entry points

