#!/usr/bin/env python3
"""
Economics pipeline: LCOH & CO₂ calculations with Monte Carlo.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from branitz_heat_decision.economics import lcoh, co2, monte_carlo

def main():
    print("Running economics pipeline...")
    # TODO: Implement economics workflow
    print("Done.")

if __name__ == "__main__":
    main()

