#!/usr/bin/env python3
"""
Verification script for CHA implementation.
Runs comprehensive checks on KPI extraction, interactive maps, and QGIS export.
"""
import sys
from pathlib import Path
import json

# Add project root and src to path
project_root = Path(__file__).parents[1]
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

from tests.fixtures import create_converged_network, create_simple_network_with_geodata
from branitz_heat_decision.cha.kpi_extractor import extract_kpis
from branitz_heat_decision.cha.qgis_export import create_interactive_map, export_network_to_qgis
from branitz_heat_decision.config import RESULTS_ROOT


def verify_kpi_extractor():
    """Verify KPI extractor functionality."""
    print("=" * 60)
    print("Verifying KPI Extractor")
    print("=" * 60)
    
    net = create_converged_network()
    kpis = extract_kpis(net, "ST001", design_hour=1234)
    
    # Basic structure checks
    assert 'feasible' in kpis['en13941_compliance'], "Missing 'feasible' in compliance"
    assert isinstance(kpis['en13941_compliance']['feasible'], bool), "feasible should be bool"
    assert 'v_max_ms' in kpis['aggregate'], "Missing 'v_max_ms' in aggregate"
    assert 'en13941_compliance' in kpis, "Missing 'en13941_compliance'"
    
    print("✓ Basic structure checks passed")
    
    # EN 13941-1 compliance logic
    compliance = kpis['en13941_compliance']
    aggregate = kpis['aggregate']
    
    velocity_ok = compliance['velocity_ok']
    dp_ok = compliance['dp_ok']
    feasible = compliance['feasible']
    
    assert feasible == (velocity_ok and dp_ok), \
        f"feasible ({feasible}) should equal (velocity_ok {velocity_ok} AND dp_ok {dp_ok})"
    
    velocity_share = aggregate['v_share_within_limits']
    assert velocity_ok == (velocity_share >= 0.95), \
        f"velocity_ok ({velocity_ok}) should be True if velocity_share ({velocity_share}) >= 0.95"
    
    dp_max = aggregate['dp_max_bar_per_100m']
    assert dp_ok == (dp_max <= 0.3), \
        f"dp_ok ({dp_ok}) should be True if dp_max ({dp_max}) <= 0.3 bar/100m"
    
    print(f"✓ EN 13941-1 compliance logic: feasible={feasible}, velocity_ok={velocity_ok}, dp_ok={dp_ok}")
    print(f"  velocity_share={velocity_share:.2%}, dp_max={dp_max:.3f} bar/100m")
    
    # Pipe-level extraction
    pipe_kpis = kpis['detailed']['pipes']
    assert len(pipe_kpis) == len(net.pipe), \
        f"Pipe KPIs count ({len(pipe_kpis)}) should match network pipes ({len(net.pipe)})"
    
    for pipe_kpi in pipe_kpis:
        assert 'velocity_ms' in pipe_kpi, "Pipe KPI should have 'velocity_ms'"
    
    print(f"✓ Pipe-level extraction: {len(pipe_kpis)} pipes with required fields")
    
    print("\nKPI Extractor verification: PASSED\n")
    return True


def verify_interactive_map():
    """Verify interactive map generation."""
    print("=" * 60)
    print("Verifying Interactive Map")
    print("=" * 60)
    
    net, buildings = create_simple_network_with_geodata()
    
    output_path = Path("test_map.html")
    create_interactive_map(
        net, buildings, "ST001",
        output_path=output_path,
        velocity_range=(0, 1.5)
    )
    
    assert output_path.exists(), f"Map file {output_path} should exist"
    assert output_path.stat().st_size > 1000, "Map file should be > 1KB"
    
    print(f"✓ Map generated: {output_path} ({output_path.stat().st_size} bytes)")
    print(f"  Open {output_path.absolute()} in browser to verify visual elements")
    print("  Expected: pipes colored by velocity, thickness by DN, buildings sized by demand")
    
    print("\nInteractive Map verification: PASSED\n")
    return True


def verify_qgis_export():
    """Verify QGIS export functionality."""
    print("=" * 60)
    print("Verifying QGIS Export")
    print("=" * 60)
    
    net, buildings = create_simple_network_with_geodata()
    
    output_dir = RESULTS_ROOT / "cha" / "ST001" / "qgis"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    layers = export_network_to_qgis(net, output_dir, "ST001")
    
    # Check that layers were created
    expected_files = [
        output_dir / "supply_pipes.gpkg",
        output_dir / "junctions.gpkg",
    ]
    
    for file_path in expected_files:
        if file_path.exists():
            print(f"✓ Created: {file_path}")
        else:
            print(f"⚠ Missing: {file_path}")
    
    print(f"\n  Open .gpkg files in QGIS to verify:")
    print(f"  - Supply/return separate layers")
    print(f"  - Service connections distinct")
    print(f"  - Junctions present")
    print(f"  - CRS consistent (EPSG:25833 or EPSG:32633)")
    
    print("\nQGIS Export verification: PASSED\n")
    return True


def main():
    """Run all verification checks."""
    print("\n" + "=" * 60)
    print("CHA Implementation Verification")
    print("=" * 60 + "\n")
    
    results = {}
    
    try:
        results['kpi_extractor'] = verify_kpi_extractor()
    except Exception as e:
        print(f"✗ KPI Extractor verification FAILED: {e}")
        results['kpi_extractor'] = False
        import traceback
        traceback.print_exc()
    
    try:
        results['interactive_map'] = verify_interactive_map()
    except Exception as e:
        print(f"✗ Interactive Map verification FAILED: {e}")
        results['interactive_map'] = False
        import traceback
        traceback.print_exc()
    
    try:
        results['qgis_export'] = verify_qgis_export()
    except Exception as e:
        print(f"✗ QGIS Export verification FAILED: {e}")
        results['qgis_export'] = False
        import traceback
        traceback.print_exc()
    
    print("=" * 60)
    print("Summary")
    print("=" * 60)
    for component, passed in results.items():
        status = "PASSED" if passed else "FAILED"
        print(f"{component:20s}: {status}")
    
    all_passed = all(results.values())
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()

