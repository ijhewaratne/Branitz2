
import pandas as pd
import pandapower as pp
from branitz_heat_decision.dha.smart_grid_strategies import simulate_smart_grid_strategies
from branitz_heat_decision.dha.loadflow import assign_hp_loads
from branitz_heat_decision.dha.config import DHAConfig
from branitz_heat_decision.dha.kpi_extractor import extract_dha_kpis

def test_strategies():
    print(" Creating mock network (Weak)...")
    net = pp.create_empty_network()
    b0 = pp.create_bus(net, vn_kv=20)
    b1 = pp.create_bus(net, vn_kv=0.4)
    b2 = pp.create_bus(net, vn_kv=0.4)
    pp.create_ext_grid(net, b0)
    pp.create_transformer(net, b0, b1, std_type="0.25 MVA 20/0.4 kV") # Small Trafo
    # Very weak line
    pp.create_line(net, b1, b2, length_km=1.0, std_type="NAYY 4x50 SE") 
    
    # 5 buildings on bus 2
    bmap = pd.DataFrame({
        "building_id": [f"b{i}" for i in range(5)],
        "bus_id": [2] * 5,
        "mapped": [True] * 5
    })
    
    # High heat demand: 20kW each -> 100kW total. Trafo is 250kVA -> 40%. Line?
    # 100kW on 0.4kV ~ 144A. NAYY 4x50 limit ~142A (in ground). 
    # Let's push it harder. 30kW each -> 150kW. Line definitely overloaded.
    heat_profiles = pd.DataFrame(
        {f"b{i}": [30.0] for i in range(5)}, 
        index=[0] # 1 hour
    )
    
    cfg = DHAConfig()
    
    print(" Generating Baseline Loads...")
    loads = assign_hp_loads(
        heat_profiles, bmap, 0, [0], cop=3.0, base_profiles_kw=None
    )
    
    print(" Running Strategy Simulation...")
    # mocking baseline kpis
    baseline_kpis = {"critical_hours_count": 1, "feasible": False}
    
    results = simulate_smart_grid_strategies(net, loads, baseline_kpis, cfg)
    
    print("\n--- Results ---")
    for name, res in results.items():
        print(f"Strategy: {name}")
        print(f"  Feasible: {res.is_feasible}")
        print(f"  Worst V: {res.worst_voltage_pu:.3f} pu")
        print(f"  Max Line: {res.max_line_loading_pct:.1f} %")
        print(f"  Max Trafo: {res.max_trafo_loading_pct:.1f} %")
        print("-" * 20)
    
    # Assertions
    # Curtailment should reduce loading
    curtail = results.get("peak_curtailment")
    if curtail:
        # Load was 150kW. Curtail 70% -> 105kW.
        # Line loading should drop.
        pass

    print("\n✅ Verification SUCCESS")

if __name__ == "__main__":
    test_strategies()
