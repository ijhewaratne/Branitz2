# Detailed Cost Breakdown Calculation Guide

This document explains how each value in the "Detailed Cost Breakdown" section is calculated for both District Heating (DH) and Heat Pump (HP) systems.

## Common Parameters

### Capital Recovery Factor (CRF)
**Formula:**
```
CRF = (r × (1 + r)^n) / ((1 + r)^n - 1)
```
Where:
- `r` = discount rate (default: 0.04 = 4%)
- `n` = lifetime in years (default: 20 years)

**Example:**
```
CRF = (0.04 × (1.04)^20) / ((1.04)^20 - 1)
CRF = (0.04 × 2.191) / (2.191 - 1)
CRF = 0.0876 / 1.191
CRF ≈ 0.0736
```

The CRF converts a one-time capital investment into an equivalent annual cost over the system lifetime.

---

## District Heating (DH) Calculations

### 1. CAPEX (Capital Expenditure)

#### `capex_pipes` (EUR)
**Formula:**
```
capex_pipes = Σ(length_m × cost_per_m)
```
- For each pipe diameter (DN), multiply length in meters by cost per meter
- Pipe costs by DN (default):
  - DN20: 50 EUR/m
  - DN25: 60 EUR/m
  - DN32: 75 EUR/m
  - DN40: 90 EUR/m
  - DN50: 110 EUR/m
  - DN65: 140 EUR/m
  - DN80: 170 EUR/m
  - DN100: 220 EUR/m
  - DN125: 280 EUR/m
  - DN150: 350 EUR/m
  - DN200: 500 EUR/m
- **Fallback**: If pipe lengths by DN are not available, uses average cost × total length

**In your example:** `capex_pipes = 0` (no pipes in this calculation, likely using plant cost override)

#### `capex_pump` (EUR)
**Formula:**
```
capex_pump = pump_power_kw × pump_cost_per_kw
```
- `pump_power_kw`: Pump power from CHA simulation (kW)
- `pump_cost_per_kw`: Default = 500 EUR/kW

**In your example:** `capex_pump = 0` (no pump cost, likely using plant cost override)

#### `capex_plant` (EUR)
**Formula:**
```
capex_plant = plant_cost_override OR plant_cost_base_eur
```
- If `plant_cost_override` is provided, uses that value
- Otherwise, uses `plant_cost_base_eur` (default: 1,500,000 EUR)

**In your example:** `capex_plant = 1,500,000 EUR`

#### `capex_total` (EUR)
**Formula:**
```
capex_total = capex_pipes + capex_pump + capex_plant
```

**In your example:** `capex_total = 0 + 0 + 1,500,000 = 1,500,000 EUR`

---

### 2. OPEX (Operational Expenditure)

#### `opex_om` (EUR/year) - Operations & Maintenance
**Formula:**
```
opex_om = capex_total × dh_om_frac_per_year
```
- `dh_om_frac_per_year`: Default = 0.02 (2% of CAPEX per year)

**In your example:** `opex_om = 1,500,000 × 0.02 = 30,000 EUR/year`

#### `opex_energy` (EUR/year) - Fuel/Energy Costs
**Formula depends on generation type:**

**For Biomass:**
```
opex_energy = (annual_heat_mwh / efficiency) × biomass_price_eur_per_mwh
```
- `efficiency`: 0.85 (85% for biomass)
- `biomass_price_eur_per_mwh`: Default = 110 EUR/MWh
- `annual_heat_mwh`: Total annual heat demand (MWh)

**For Gas:**
```
opex_energy = (annual_heat_mwh / efficiency) × gas_price_eur_per_mwh
```
- `efficiency`: 0.90 (90% for gas)
- `gas_price_eur_per_mwh`: Default = 80 EUR/MWh

**For Electric:**
```
opex_energy = (annual_heat_mwh / COP) × electricity_price_eur_per_mwh
```
- `COP`: 3.0 (coefficient of performance)
- `electricity_price_eur_per_mwh`: Default = 250 EUR/MWh

**In your example (Biomass):**
```
opex_energy = (4,403.38 / 0.85) × 110
opex_energy = 5,180.45 × 110
opex_energy = 569,850 EUR/year
```

#### `opex_annual` (EUR/year)
**Formula:**
```
opex_annual = opex_om + opex_energy
```

**In your example:** `opex_annual = 1,000 + 310,827 = 311,827 EUR/year`

---

### 3. LCOH (Levelized Cost of Heat)
**Formula:**
```
LCOH = (capex_total × CRF + opex_annual) / annual_heat_mwh
```

**In your example:**
```
LCOH = (1,500,000 × 0.0736 + 599,850) / 4,403.38
LCOH = (110,400 + 599,850) / 4,403.38
LCOH = 710,250 / 4,403.38
LCOH ≈ 161.3 EUR/MWh
```

---

## Heat Pump (HP) Calculations

### 1. CAPEX (Capital Expenditure)

#### `capex_hp` (EUR)
**Formula:**
```
capex_hp = hp_total_capacity_kw_th × hp_cost_eur_per_kw_th
```
- `hp_total_capacity_kw_th`: Total heat pump thermal capacity (kW)
- `hp_cost_eur_per_kw_th`: Default = 900 EUR/kW_th

**In your example:**
```
capex_hp = 1,503.89 × 900 = 1,353,501 EUR
```
(Assuming `hp_total_capacity_kw_th = 1,503.89 kW`)

#### `capex_lv_upgrade` (EUR) - LV Grid Upgrade Cost
**Formula:**
```
IF max_feeder_loading_pct > loading_threshold_pct:
    overload_factor = (max_feeder_loading_pct - loading_threshold_pct) / 100.0
    hp_el_capacity_kw = hp_total_capacity_kw_th / cop_annual_average
    upgrade_kw_el = overload_factor × hp_el_capacity_kw × 1.5
    capex_lv_upgrade = upgrade_kw_el × lv_upgrade_cost_eur_per_kw_el
ELSE:
    capex_lv_upgrade = 0
```
- `max_feeder_loading_pct`: Maximum feeder loading from DHA (default threshold: 80%)
- `loading_threshold_pct`: Planning limit (default: 80%)
- `lv_upgrade_cost_eur_per_kw_el`: Default = 200 EUR/kW_el
- The `1.5` factor is a safety margin for grid upgrades

**In your example:**
```
max_feeder_loading_pct = 187.29%
loading_threshold_pct = 80%
overload_factor = (187.29 - 80) / 100 = 1.0729
hp_el_capacity_kw = 1,503.89 / 2.8 = 537.10 kW
upgrade_kw_el = 1.0729 × 537.10 × 1.5 = 864.41 kW
capex_lv_upgrade = 864.41 × 200 = 172,882 EUR
```

#### `capex_total` (EUR)
**Formula:**
```
capex_total = capex_hp + capex_lv_upgrade
```

**In your example:** `capex_total = 1,353,501 + 172,882 = 1,526,383 EUR`

---

### 2. OPEX (Operational Expenditure)

#### `opex_om` (EUR/year) - Operations & Maintenance
**Formula:**
```
opex_om = capex_hp × hp_om_frac_per_year
```
- `hp_om_frac_per_year`: Default = 0.02 (2% of HP CAPEX per year)
- **Note**: O&M is calculated only on HP CAPEX, not including LV upgrade

**In your example:**
```
opex_om = 1,353,501 × 0.02 = 27,070 EUR/year
```

#### `opex_energy` (EUR/year) - Electricity Costs
**Formula:**
```
annual_el_mwh = annual_heat_mwh / cop_annual_average
opex_energy = annual_el_mwh × electricity_price_eur_per_mwh
```
- `cop_annual_average`: Annual average COP (default: 2.8)
- `electricity_price_eur_per_mwh`: Default = 250 EUR/MWh

**In your example:**
```
annual_el_mwh = 4,403.38 / 2.8 = 1,572.64 MWh
opex_energy = 1,572.64 × 250 = 393,160 EUR/year
```

#### `opex_annual` (EUR/year)
**Formula:**
```
opex_annual = opex_om + opex_energy
```

**In your example:** `opex_annual = 27,070 + 393,160 = 420,230 EUR/year`

---

### 3. LCOH (Levelized Cost of Heat)
**Formula:**
```
LCOH = (capex_total × CRF + opex_annual) / annual_heat_mwh
```

**In your example:**
```
LCOH = (1,526,383 × 0.0736 + 420,230) / 4,403.38
LCOH = (112,342 + 420,230) / 4,403.38
LCOH = 532,572 / 4,403.38
LCOH ≈ 121.0 EUR/MWh
```

---

## Key Inputs from Other Modules

### From CHA (District Heating Analysis):
- `annual_heat_mwh`: Total annual heat demand (from building profiles)
- `pipe_lengths_by_dn`: Pipe lengths by diameter (from network topology)
- `total_pipe_length_m`: Total pipe length (if DN breakdown not available)
- `pump_power_kw`: Pump power requirement (from hydraulic simulation)

### From DHA (LV Grid Hosting Analysis):
- `max_feeder_loading_pct`: Maximum feeder loading percentage (from powerflow results)
- Used to determine if LV grid upgrade is needed

### From Data Preparation:
- `hp_total_capacity_kw_th`: Total heat pump capacity (sum of individual building HP capacities)
- `cop_annual_average`: Annual average COP (from HP specifications or default)

---

## Summary Equations

### District Heating:
```
CAPEX = Pipes + Pump + Plant
OPEX = (CAPEX × 2%) + (Heat_MWh / Efficiency × Fuel_Price)
LCOH = (CAPEX × CRF + OPEX) / Heat_MWh
```

### Heat Pump:
```
CAPEX = HP_Capacity × HP_Cost + LV_Upgrade (if needed)
OPEX = (HP_CAPEX × 2%) + (Heat_MWh / COP × Electricity_Price)
LCOH = (CAPEX × CRF + OPEX) / Heat_MWh
```

---

## Notes

1. **LV Upgrade Logic**: The LV upgrade cost is only calculated if `max_feeder_loading_pct > loading_threshold_pct` (default 80%). This represents the cost of grid reinforcement needed to host the heat pump loads.

2. **O&M Fraction**: Both systems use 2% of relevant CAPEX per year for operations and maintenance.

3. **Generation Type**: For DH, the efficiency and fuel price depend on the generation type (gas/biomass/electric), which affects the energy OPEX calculation.

4. **CRF**: The same CRF is used for both systems (based on discount rate and lifetime), ensuring fair comparison.

5. **Monte Carlo**: In Monte Carlo simulations, these base values are multiplied by random factors to propagate uncertainty (CAPEX: 0.8-1.2×, prices: 0.7-1.3×, etc.).
