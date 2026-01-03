#!/usr/bin/env python3
"""
Interactive map server for visualizing results.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from branitz_heat_decision.cha.qgis_export import create_interactive_map

def main():
    print("Starting map server...")
    # TODO: Implement Flask/FastAPI server
    print("Done.")

if __name__ == "__main__":
    main()

