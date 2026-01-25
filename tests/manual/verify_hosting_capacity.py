
import pandas as pd
import pandapower as pp
from branitz_heat_decision.dha.hosting_capacity import run_monte_carlo_hosting_capacity
from branitz_heat_decision.dha.config import DHAConfig

def test_mc_hosting_capacity():
    print(" Creating mock network...")
    net = pp.create_empty_network()
    b0 = pp.create_bus(net, vn_kv=20)
    b1 = pp.create_bus(net, vn_kv=0.4)
    b2 = pp.create_bus(net, vn_kv=0.4)
    pp.create_ext_grid(net, b0)
    pp.create_transformer(net, b0, b1, std_type="0.4 MVA 20/0.4 kV")
    # Weak line to trigger violations easily
    pp.create_line(net, b1, b2, length_km=0.5, std_type="NAYY 4x50 SE") 
    
    print(" Creating mock data...")
    # Map 10 buildings to bus 2
    bmap = pd.DataFrame({
        "building_id": [f"b{i}" for i in range(10)],
        "bus_id": [2] * 10,
        "mapped": [True] * 10
    })
    
    # Heat profiles (high enough to cause issues if all installed)
    # 20 kW heat -> ~6.6 kW elec @ COP=3
    # 10 buildings * 6.6 = 66 kW. Line limit ~100A ~= 69kW. Close.
    # Try 50kW heat -> 16.6kW elec. 10 * 16.6 = 166kW. Guaranteed overload.
    heat_profiles = pd.DataFrame(
        {f"b{i}": [50.0] * 5 for i in range(10)}, 
        index=[0, 1, 2, 3, 4] # hours
    )
    
    cfg = DHAConfig()
    
    print(" Running Monte Carlo (N=20)...")
    result = run_monte_carlo_hosting_capacity(
        net=net,
        building_bus_map=bmap,
        hourly_heat_profiles=heat_profiles,
        base_load_profiles=None,
        cfg=cfg,
        n_scenarios=20,
        penetration_range=(0.1, 1.0), # 10% to 100%
        design_hour_idx=0,
        top_n_hours=[0, 1]
    )
    
    print("\n--- Results ---")
    print(f"Scenarios Analyzed: {result.scenarios_analyzed}")
    print(f"Safe Scenarios: {result.safe_scenarios}")
    print(f"Violation Scenarios: {result.violation_scenarios}")
    print(f"Safety Score: {result.safety_score:.1%}")
    print(f"Safe Capacity: Median {result.safe_capacity_median_kw:.2f} kW")
    print(f"Median Safe Penetration: {result.safe_penetration_median_pct:.1%}")
    
    if result.violation_scenarios > 0:
        print("\nSample Violation:")
        for r in result.scenario_details:
            if r["has_violation"]:
                print(r)
                break
    
    assert result.scenarios_analyzed == 20
    print("\n✅ Verification SUCCESS")

if __name__ == "__main__":
    test_mc_hosting_capacity()
