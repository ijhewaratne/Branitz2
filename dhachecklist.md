### DHA Phase 3 Checklist — LV Grid Hosting (Option 2: MV ext_grid + MV/LV transformer)

This checklist verifies the **current project implementation** of Phase 3 (DHA) in `src/branitz_heat_decision/dha/`.

---

## 1) Data prerequisites (inputs exist + consistent CRS)

- **Cluster + buildings**
  - [ ] `data/processed/buildings.parquet` exists (GeoDataFrame, CRS set; typically EPSG:25833).
  - [ ] `data/processed/building_cluster_map.parquet` exists and contains columns:
    - [ ] `building_id`
    - [ ] `cluster_id` (e.g., `ST010_HEINRICH_ZILLE_STRASSE`)
  - [ ] `data/processed/cluster_design_topn.json` exists and contains:
    - [ ] `clusters[<cluster_id>].design_hour`
    - [ ] `clusters[<cluster_id>].topn_hours` (length ≥ requested TopN, default 10)

- **Heat demand profiles (used as HP thermal input)**
  - [ ] `data/processed/hourly_heat_profiles.parquet` exists (index 0..8759, columns are building_ids).
  - [ ] For the chosen `cluster_id`, at least one building id appears as a column in the profiles parquet.

- **Base electricity demand profiles (normal consumption)**
  - [ ] A base electric dataset exists and is usable for the run:
    - [ ] **JSON scenario-based**: `data/raw/gebaeude_lastphasenV2.json` exists (building_id → scenario → value), OR
    - [ ] **Hourly base parquet**: a processed hourly base-load table exists (index=hour, columns=building_id, values=kW_el).
  - [ ] Base load is aligned to the hours simulated:
    - [ ] Either mapped from scenario → hour set (documented mapping), OR
    - [ ] Provided directly as hourly values for design + TopN hours.
  - [ ] Units are validated and auditable:
    - [ ] Base load values are interpreted as **kW_el** (or converted to kW_el).
    - [ ] If unit auto-detection is used (kW vs MW), the detected unit is logged/stored.

- **Grid source availability**
  - **Legacy grid mode (recommended for Branitz continuity)**
    - [ ] `Legacy/DHA/HP New /Data/branitzer_siedlung_ns_v3_ohne_UW.json` exists (nodes/ways).
  - **Geodata grid mode (optional)**
    - [ ] `data/processed/power_lines.geojson` exists and overlaps the cluster spatially.
    - [ ] `data/processed/power_substations.geojson` exists and overlaps the cluster spatially.
    - [ ] Both geodata files are in a projected CRS (expected: EPSG:25833) for correct lengths/mapping.

---

## 2) Environment prerequisites

- [ ] `pandapower` installed and importable.
- [ ] `geopandas` installed and importable.
- [ ] `numpy`, `pandas`, `shapely` installed.
- [ ] `folium` + `branca` installed (optional; required for `hp_lv_map.html`).

---

## 3) Boundary condition correctness (Option 2)

**Requirement**: Do NOT place `ext_grid` directly on LV. Must be MV slack + transformer(s) to LV.

- [ ] The built `pandapowerNet` contains **exactly one** `ext_grid`.
- [ ] The `ext_grid` is attached to an **MV bus**:
  - [ ] `vn_kv` of ext_grid bus is ~20 kV (>= 5 kV sanity threshold).
- [ ] The network contains **≥ 1 MV/LV transformer** (`net.trafo` not empty).

### 3.1 Transformer modelling details (Option 2 realism knobs)

- [ ] Transformer model is auditable:
  - [ ] Transformer uses a defined std_type or explicit parameter set (Sn, vk%, vkr%, losses).
  - [ ] Tap settings are explicit and documented:
    - [ ] `tap_side` is defined (hv/lv)
    - [ ] `tap_pos` is defined (or taps are locked and documented)
    - [ ] tap range + step are defined (tap_min, tap_max, tap_step_percent)
- [ ] If multiple substations/transformers exist:
  - [ ] It is clear which LV sections are fed by which transformer (topology is connected and auditable).
  - [ ] Any “linking” of transformer LV buses into the LV line graph is logged (if applied).

Implementation references:
- `src/branitz_heat_decision/dha/grid_builder.py::_validate_boundary_option2`

---

## 4) Grid construction (topology + connectivity)

### 4.1 Geodata grid build
- [ ] `build_lv_grid_option2(lines_gdf, substations_gdf, cfg)`:
  - [ ] Deduplicates LV buses at line endpoints using a snap tolerance (to avoid fake parallel lines/islands).
  - [ ] Uses geometry length (CRS meters) to compute `length_km`.
  - [ ] Creates LV lines with reasonable default parameters (R/X/C/max_i).
  - [ ] Creates ≥1 LV substation bus and MV/LV transformer(s).
  - [ ] Fails clearly if unsupplied buses exist (islands).

### 4.2 Legacy nodes/ways adapter
- [ ] `build_lv_grid_from_nodes_ways_json(json_path, cfg)`:
  - [ ] Creates LV buses from nodes (optional dedup).
  - [ ] Creates MV bus + `ext_grid` at MV.
  - [ ] Creates transformers at `tags.power == "substation"`.
  - [ ] Creates LV lines from ways where `tags.power in {line,cable,minor_line}`.
  - [ ] Ensures transformer LV buses are energized (connects to LV line graph if needed).

---

## 5) Building → LV bus mapping

- [ ] `map_buildings_to_lv_buses(buildings_gdf, net, max_dist_m)` produces a DataFrame with columns:
  - [ ] `building_id`
  - [ ] `bus_id`
  - [ ] `distance_m`
  - [ ] `mapped` (boolean)
- [ ] Mapping uses building centroids.
- [ ] Mapping uses projected CRS distances (meters).
- [ ] Unmapped buildings are retained but have `bus_id = NaN` and `mapped == False`.
- [ ] A clear report is available (count mapped/unmapped) in logs or derived from mapping output.

Implementation reference:
- `src/branitz_heat_decision/dha/mapping.py`

---

## 6) Load definition (HP electrical injection) + multi-hour execution

### 6.1 Loads computed from base + HP (required)

- [ ] **Base electricity demand is included** (normal consumption):
  - [ ] A per-building base load \(P_{base}\) (kW_el) exists for the simulated hours/scenario.
  - [ ] DHA load model uses:
    - [ ] \(P_{total}(t) = P_{base}(t) + P_{HP,el}(t)\)
  - [ ] Both components are logged/auditable (at least totals per hour):
    - [ ] `p_base_kw_total`, `p_hp_kw_total`, `p_total_kw_total`
    - [ ] saved to a per-hour CSV (or equivalent artifact)

- [ ] **HP incremental electricity from heat profiles**
  - [ ] `assign_hp_loads(...)` supports design hour + TopN hours.
  - [ ] Equations used:
    - [ ] \(P_{HP,el,kw}(t) = Q_{heat,kw}(t) / COP\)
    - [ ] Reactive power:
      - [ ] Option A (simple): \(Q_{total} = P_{total} * tan(arccos(pf_{total}))\), OR
      - [ ] Option B (split): \(Q_{total} = P_{base}*tan(arccos(pf_{base})) + P_{HP}*tan(arccos(pf_{HP}))\)
  - [ ] Converts to `p_mw`, `q_mvar` for pandapower using \(kW \rightarrow MW\), \(kvar \rightarrow Mvar\).

### 6.2 Loadflow execution
- [ ] `run_loadflow(net, loads_by_hour, ...)`:
  - [ ] Does not recreate loads per hour (updates existing load elements).
  - [ ] Records per-hour `converged` and `solver`.
  - [ ] Produces per-hour snapshots:
    - [ ] `bus_results` with `v_min_pu` (from `vm_pu` or min(vm_a,vm_b,vm_c))
    - [ ] `line_results` with `loading_percent` when possible
- [ ] Single-phase vs three-phase:
  - [ ] If single-phase is requested and `runpp_3ph` is available, uses `asymmetric_load` + `runpp_3ph`.
  - [ ] Otherwise uses balanced loads and documents solver choice.

Implementation references:
- `src/branitz_heat_decision/dha/loadflow.py`

---

## 7) KPIs + violations (auditable across all hours)

- [ ] `extract_dha_kpis(results_by_hour, cfg)` returns:
  - [ ] `feasible` is True only if **no** voltage violations, line overload violations, and no non-convergence across all hours.
  - [ ] `worst_vmin_pu` and its hour
  - [ ] `max_feeder_loading_pct` and its hour
  - [ ] totals: voltage violations, overload violations, planning warnings
- [ ] Violation rules:
  - [ ] Voltage violation if `v_min_pu < cfg.v_min_pu` or `v_min_pu > cfg.v_max_pu`
  - [ ] Overload if `loading_percent > cfg.loading_limit_pct`
  - [ ] Planning warning if `loading_percent > cfg.planning_warning_pct`

Implementation reference:
- `src/branitz_heat_decision/dha/kpi_extractor.py`

---

## 8) Outputs (GeoJSON + CSV + map)

- [ ] Results directory exists:
  - [ ] `results/dha/<cluster_id>/`
- [ ] Output files created:
  - [ ] `dha_kpis.json`
  - [ ] `network.pickle`
  - [ ] `buses_results.geojson`
  - [ ] `lines_results.geojson`
  - [ ] `violations.csv`
  - [ ] `hp_lv_map.html`
- [ ] GeoJSON coordinates are **WGS84** (lon/lat) so they display correctly in GIS/folium even if grid is built in EPSG:25833.
- [ ] Map shows **non-constant** variation:
  - [ ] Lines colored by loading %
  - [ ] Buses colored by voltage class (v_min_pu)
  - [ ] Legends exist and are readable

Implementation reference:
- `src/branitz_heat_decision/dha/export.py`

---

## 9) CLI run (per cluster)

- [ ] CLI exists: `src/scripts/02_run_dha.py`
- [ ] Example command (legacy grid source):

```bash
python src/scripts/02_run_dha.py \
  --cluster-id ST010_HEINRICH_ZILLE_STRASSE \
  --cop 2.8 \
  --hp-three-phase \
  --topn 10 \
  --grid-source legacy_json
```

- [ ] Example command (geodata grid source; only if geodata overlaps cluster):

```bash
python src/scripts/02_run_dha.py \
  --cluster-id ST010_HEINRICH_ZILLE_STRASSE \
  --cop 2.8 \
  --hp-three-phase \
  --topn 10 \
  --grid-source geodata \
  --grid-buffer-m 1500
```

---

## 10) Acceptance criteria (what to verify)

- [ ] Net contains **one MV ext_grid** and **≥1 transformer** to LV.
- [ ] Powerflow converges for **design hour** and preferably all TopN hours.
- [ ] Outputs are generated in `results/dha/<cluster_id>/`.
- [ ] Map and GeoJSON show meaningful variation (not constant fields).

