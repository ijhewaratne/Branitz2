
import pandas as pd
import pandapower as pp
from branitz_heat_decision.dha.reinforcement_optimizer import plan_grid_reinforcement
from branitz_heat_decision.dha.loadflow import assign_hp_loads
from branitz_heat_decision.dha.config import DHAConfig

def test_reinforcement():
    print(" Creating mock network (Weak)...")
    net = pp.create_empty_network()
    b0 = pp.create_bus(net, vn_kv=20)
    b1 = pp.create_bus(net, vn_kv=0.4)
    b2 = pp.create_bus(net, vn_kv=0.4)
    pp.create_ext_grid(net, b0)
    pp.create_transformer(net, b0, b1, std_type="0.25 MVA 20/0.4 kV") 
    # Weak line
    pp.create_line(net, b1, b2, length_km=0.5, std_type="NAYY 4x50 SE") 
    
    bmap = pd.DataFrame({
        "building_id": [f"b{i}" for i in range(5)],
        "bus_id": [2] * 5,
        "mapped": [True] * 5
    })
    
    # 30kW each * 5 = 150kW. Line 4x50 limit ~140A (~97kVA). >> Overload.
    heat_profiles = pd.DataFrame(
        {f"b{i}": [30.0] for i in range(5)}, index=[0]
    )
    
    cfg = DHAConfig()
    
    loads = assign_hp_loads(
        heat_profiles, bmap, 0, [0], cop=3.0, base_profiles_kw=None
    )
    
    print(" Running Reinforcement Planning...")
    plan = plan_grid_reinforcement(net, loads, cfg, max_iterations=5)
    
    print("\n--- Reinforcement Plan ---")
    print(f"Sufficient: {plan.is_sufficient}")
    print(f"Total Cost: €{plan.total_cost_eur:,.2f}")
    for m in plan.measures:
        print(f" - {m.description} (€{m.cost_eur:,.2f})")
        
    assert len(plan.measures) > 0
    assert plan.is_sufficient
    print("\n✅ Verification SUCCESS")

if __name__ == "__main__":
    test_reinforcement()
