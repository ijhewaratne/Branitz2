#!/usr/bin/env python3
"""
CHA pipeline: District heating network analysis.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from branitz_heat_decision.cha import network_builder, convergence_optimizer, kpi_extractor

def main():
    print("Running CHA pipeline...")
    # TODO: Implement CHA workflow
    print("Done.")

if __name__ == "__main__":
    main()

