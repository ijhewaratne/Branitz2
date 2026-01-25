"""
Integration tests for KPI Extractor.
Tests EN 13941-1 compliance logic and pipe-level extraction.
"""
import pytest
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from tests.fixtures import create_converged_network
from branitz_heat_decision.cha.kpi_extractor import extract_kpis


@pytest.mark.cha
def test_kpi_extraction_basic():
    """Test basic KPI extraction."""
    net = create_converged_network()
    kpis = extract_kpis(net, "ST001", design_hour=1234)
    
    # Check structure
    assert 'feasible' in kpis['en13941_compliance']
    assert isinstance(kpis['en13941_compliance']['feasible'], bool)
    assert 'v_max_ms' in kpis['aggregate']
    assert 'en13941_compliance' in kpis
    assert 'detailed' in kpis


@pytest.mark.cha
def test_en13941_compliance_logic():
    """Test EN 13941-1 compliance logic."""
    net = create_converged_network()
    kpis = extract_kpis(net, "ST001", design_hour=1234)
    
    compliance = kpis['en13941_compliance']
    aggregate = kpis['aggregate']
    
    # Check compliance structure
    assert 'feasible' in compliance
    assert 'velocity_ok' in compliance
    assert 'dp_ok' in compliance
    assert 'reasons' in compliance
    
    # Feasible = True only if velocity_share >= 95% AND dp <= 0.3 bar/100m
    velocity_ok = compliance['velocity_ok']
    dp_ok = compliance['dp_ok']
    feasible = compliance['feasible']
    
    # Logic check: feasible should be True only if both are True
    assert feasible == (velocity_ok and dp_ok), \
        "feasible should be True only if both velocity_ok and dp_ok are True"
    
    # Check velocity share threshold (95%)
    velocity_share = aggregate['v_share_within_limits']
    assert velocity_ok == (velocity_share >= 0.95), \
        "velocity_ok should be True if velocity_share >= 0.95"
    
    # Check pressure drop threshold (0.3 bar/100m)
    dp_max = aggregate['dp_max_bar_per_100m']
    assert dp_ok == (dp_max <= 0.3), \
        "dp_ok should be True if dp_max <= 0.3 bar/100m"
    
    # Check reason codes
    reasons = compliance['reasons']
    if feasible:
        assert 'DH_OK' in reasons, "Feasible networks should have DH_OK reason"
    else:
        if not velocity_ok:
            assert 'DH_VELOCITY_VIOLATION' in reasons, \
                "Velocity violations should have DH_VELOCITY_VIOLATION reason"
        if not dp_ok:
            assert 'DH_DP_VIOLATION' in reasons, \
                "DP violations should have DH_DP_VIOLATION reason"


@pytest.mark.cha
def test_pipe_level_extraction():
    """Test pipe-level KPI extraction."""
    net = create_converged_network()
    kpis = extract_kpis(net, "ST001", design_hour=1234, detailed=True)
    
    pipe_kpis = kpis['detailed']['pipes']
    assert len(pipe_kpis) == len(net.pipe), \
        f"Pipe KPIs count ({len(pipe_kpis)}) should match network pipes ({len(net.pipe)})"
    
    # Check required fields in pipe KPIs
    required_fields = ['velocity_ms', 'pressure_drop_bar', 'pressure_drop_per_100m_bar']
    for pipe_kpi in pipe_kpis:
        for field in required_fields:
            assert field in pipe_kpi, f"Pipe KPI should have '{field}' field"


@pytest.mark.cha
def test_aggregate_structure():
    """Test aggregate KPI structure."""
    net = create_converged_network()
    kpis = extract_kpis(net, "ST001", design_hour=1234)
    
    aggregate = kpis['aggregate']
    
    # Check required aggregate fields
    required_fields = [
        'v_max_ms', 'v_mean_ms', 'v_min_ms',
        'dp_max_bar_per_100m', 'dp_mean_bar_per_100m',
        't_supply_c', 't_return_c', 'delta_t_k',
        'length_total_m', 'length_supply_m', 'length_service_m'
    ]
    
    for field in required_fields:
        assert field in aggregate, f"Aggregate KPIs should have '{field}' field"

