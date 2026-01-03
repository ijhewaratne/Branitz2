#!/usr/bin/env python3
"""
DHA pipeline: LV grid hosting analysis for heat pumps.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from branitz_heat_decision.dha import grid_builder, mapping, loadflow, kpi_extractor

def main():
    print("Running DHA pipeline...")
    # TODO: Implement DHA workflow
    print("Done.")

if __name__ == "__main__":
    main()

