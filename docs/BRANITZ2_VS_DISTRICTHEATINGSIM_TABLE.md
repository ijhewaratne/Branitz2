# Branitz2 vs DistrictHeatingSim – Benchmark Comparison Table

**Cluster**: ST010_HEINRICH_ZILLE_STRASSE  
**Buildings**: **72** (service connections / spurs in CHA topology; one connection per building)  
**Data source**: `results/cha/ST010_HEINRICH_ZILLE_STRASSE/cha_kpis.json`, `results/economics/ST010_HEINRICH_ZILLE_STRASSE/economics_deterministic.json`

| **Metric** | **Your Tool (Branitz2)** | **DistrictHeatingSim** | **Deviation** | **Interpretation** |
| ------------------------- | ------------------------ | ---------------------- | ------------- | -------------------------------------------- |
| **Network Topology** | | | | |
| **Number of buildings** | **72** | [X] | ±Y% | From CHA topology: spurs = service connections (1 per building) |
| Total Pipe Length | **10.64 km** | [X] km | ±Y% | MST vs street-following heuristic (trunk + service) |
| Trunk Length | 7.77 km | [X] km | ±Y% | Supply + return trunk pipes |
| Service Connections | **2.86 km** (72 connections) | [X] km | ±Y% | Individual building connections (length_service_m) |
| **Hydraulic Performance** | | | | |
| Max Δp per 100 m | **0.053 bar/100m** | [X] bar/100m | ±Y% | Within EN 13941-1 limit (≤0.3 bar/100m) both |
| Worst-path Δp (est.) | ~0.42 bar* | [X] bar | ±Y% | *Estimated: dp_max × path_length/100; Branitz2 reports per-100m |
| Velocity compliance | **100%** | [X]% | ±Y% | v_share_within_limits = 1.0; both pass ≥90% threshold |
| Max velocity | 0.95 m/s | [X] m/s | ±Y% | v_max_ms; within 1.5 m/s limit |
| Pump Power (design) | **0 kW** | [X] kW | ±Y% | pandapipes converged without circulation pump; comparable hydraulic duty |
| **Thermal Performance** | | | | |
| Network Heat Losses | **0.0%** | [X]% | ±Y% | loss_share_percent = 0; Reference: 3–5% typical for 4GDH |
| **Economic Analysis** | | | | |
| LCOH DH (20y, r=4%) | **91.70 €/MWh** | [X] €/MWh | ±Y% | **Methodology divergence**: AGFW vs VDI 2067; r=4% in Branitz2 |
| LCOH DH (20y, r=5%) | ~93 €/MWh** | [X] €/MWh | ±Y% | **Extrapolated from r=4% for direct comparison |
| CAPEX (pipes only) | **2.58 M€** | [X] € | ±Y% | Pipe costs from pipe_lengths_by_dn × cost_eur_per_m |
| CAPEX breakdown | Per-DN pipe catalog | Their pipe costs | ±Y% | Installation cost assumptions; EN 10255 catalog |

## Notes for filling DistrictHeatingSim and deviation columns

1. **Total Pipe Length**  
   - Branitz2: `length_total_m` = 10,635 m (trunk 7,773 m + service 2,862 m)  
   - Topology: Trunk–spur, street-following; MST vs street heuristic affects length.

2. **Hydraulic**  
   - Branitz2 reports `dp_max_bar_per_100m` (max gradient), not worst-path total Δp.  
   - Worst-path Δp ≈ dp_max_bar_per_100m × (path_length_m / 100).  
   - Pump power = 0 kW in this run (no circulation pump needed for convergence).

3. **Thermal**  
   - Branitz2 `loss_share_percent` = 0 in this case (simplified thermal model).  
   - For 4GDH, typical values are 3–5%.

4. **LCOH**  
   - Branitz2: discount rate 4%, lifetime 20 years, marginal plant allocation.  
   - For r=5%, LCOH will be slightly higher (~93 €/MWh).  
   - Methodology: AGFW vs VDI 2067 can cause systematic differences.

5. **Data locations**
   - CHA: `results/cha/ST010_HEINRICH_ZILLE_STRASSE/cha_kpis.json`
   - Economics: `results/economics/ST010_HEINRICH_ZILLE_STRASSE/economics_deterministic.json`
