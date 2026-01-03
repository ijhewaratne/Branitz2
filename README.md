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

## Project Structure
- `data/raw/`: Original Wärmekataster, OSM, Stadtwerke data
- `data/processed/`: Validated, pipeline-ready data (GeoParquet)
- `results/`: All outputs (deterministic, versioned)
- `src/`: Modular Python package
- `scripts/`: CLI entry points

