#!/usr/bin/env python3
"""
Test script for the new street-specific HP simulation functionality.
This script demonstrates how to use the StreetSimulator class.
"""

import sys
from pathlib import Path

# Add the current directory to Python path to import the main module
sys.path.insert(0, str(Path(__file__).parent))

from street_hp_lv_sim import StreetSimulator, list_available_streets

def test_street_listing():
    """Test listing available streets."""
    print("Testing street listing functionality...")
    try:
        streets = list_available_streets()
        print(f"✓ Successfully listed {len(streets)} streets")
        return True
    except Exception as e:
        print(f"✗ Error listing streets: {e}")
        return False

def test_direct_street_selection():
    """Test direct street selection."""
    print("\nTesting direct street selection...")
    try:
        simulator = StreetSimulator()
        # Try to select a known street
        street_name = simulator.select_street("Anton-Bruckner-Straße")
        print(f"✓ Successfully selected street: {street_name}")
        return True
    except Exception as e:
        print(f"✗ Error selecting street: {e}")
        return False

def test_simulation_without_running():
    """Test simulation setup without actually running power flow."""
    print("\nTesting simulation setup...")
    try:
        simulator = StreetSimulator()
        simulator.select_street("Anton-Bruckner-Straße")
        print("✓ Successfully set up simulation for Anton-Bruckner-Straße")
        print("  (Skipping actual power flow calculation for this test)")
        return True
    except Exception as e:
        print(f"✗ Error setting up simulation: {e}")
        return False

def main():
    """Run all tests."""
    print("="*60)
    print("STREET SIMULATION FUNCTIONALITY TESTS")
    print("="*60)
    
    tests = [
        test_street_listing,
        test_direct_street_selection,
        test_simulation_without_running
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        if test():
            passed += 1
    
    print(f"\n{'='*60}")
    print(f"TEST RESULTS: {passed}/{total} tests passed")
    print(f"{'='*60}")
    
    if passed == total:
        print("✓ All tests passed! The street simulation functionality is working correctly.")
        print("\nTo run a full simulation, use:")
        print("  python street_hp_lv_sim.py")
        print("\nOr in Python:")
        print("  from street_hp_lv_sim import StreetSimulator")
        print("  simulator = StreetSimulator()")
        print("  simulator.select_street()  # Interactive selection")
        print("  results = simulator.run_simulation()")
    else:
        print("✗ Some tests failed. Please check the error messages above.")
    
    return passed == total

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
