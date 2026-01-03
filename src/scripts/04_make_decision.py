#!/usr/bin/env python3
"""
Decision pipeline: Build KPI contract and generate recommendation.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from branitz_heat_decision.decision import kpi_contract, rules
from branitz_heat_decision.uhdc import explainer, renderer

def main():
    print("Running decision pipeline...")
    # TODO: Implement decision workflow
    print("Done.")

if __name__ == "__main__":
    main()

