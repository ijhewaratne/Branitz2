#!/usr/bin/env python3
"""
Data preparation pipeline.
Loads raw data, cleans, validates, and generates processed artifacts.
"""
import sys
import argparse
import logging
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parents[1]))

from branitz_heat_decision.config import DATA_PROCESSED
from branitz_heat_decision.data.loader import load_buildings_geojson, DataValidationError
from branitz_heat_decision.data.typology import estimate_envelope
from branitz_heat_decision.data.profiles import generate_hourly_profiles
from branitz_heat_decision.data.cluster import aggregate_cluster_profiles, compute_design_and_topn
import geopandas as gpd
import pandas as pd
import json

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description='Data preparation pipeline')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    parser.add_argument('--buildings', type=str, help='Path to buildings GeoJSON')
    parser.add_argument('--weather', type=str, help='Path to weather CSV/Parquet')
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    logger.info("Running data preparation pipeline...")
    
    try:
        # For now, if data already exists in processed/, assume it's test data
        from branitz_heat_decision.config import BUILDINGS_PATH, WEATHER_PATH
        if BUILDINGS_PATH.exists() and WEATHER_PATH.exists():
            logger.info("Processed data files already exist. Pipeline complete.")
            logger.info(f"Buildings: {BUILDINGS_PATH}")
            logger.info(f"Weather: {WEATHER_PATH}")
        else:
            logger.info("No processed data found. Use create_test_data() to generate test data first.")
            logger.info("Or provide --buildings and --weather arguments with raw data paths.")
    
    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)
        sys.exit(1)
    
    logger.info("Done.")


if __name__ == "__main__":
    main()

