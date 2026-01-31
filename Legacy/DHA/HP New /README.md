### DHA (Electrical) — Heat Pump LV Feasibility (Legacy)

This folder contains the **legacy DHA implementation for electrical distribution feasibility**, focused on assessing **low-voltage (LV) grid impacts** of adding **heat pumps (HPs)** to buildings in the Branitzer Siedlung area.

It builds an LV network from **OSM-derived nodes & ways**, attaches **per-building electrical loads** (by scenario/time-slice), optionally adds an **HP electrical increment**, runs a **power flow** using `pandapower` (single-phase or 3-phase depending on the script), and exports **GeoJSON + CSV + interactive maps**.

> **Terminology in this folder**
> - “DHA” here refers to **Distribution/Decision Heat Analysis** on the *electrical* grid side (HP impact).
> - It is **not** the district heating hydraulic `pandapipes` CHA network model.

---

## What’s in this folder (entry points)

- **Street-level 3‑phase simulation (recommended interactive workflow)**
  - `street_hp_lv_sim.py`
  - Produces **per-street results + map** and supports interactive street selection.

- **Multi-scenario batch simulation (multiprocessing)**
  - `Scripts/simuV6_multiprocessing_ohne_UW.py`
  - Runs many load scenarios for the whole area/network, focuses on **transformer loading** and uses `pp.runpp` (single-phase power flow).

- **OSM → nodes/ways JSON builder**
  - `Scripts/extract_ways_nodes.py`
  - Parses OSM and exports the `nodes`/`ways` JSON used as the electrical network topology.

---

## Methodology (high-level)

### A) Build the electrical network topology from OSM (LV graph)

**Inputs**
- OSM-derived topology JSON (nodes & ways): `branitzer_siedlung_ns_v3_ohne_UW.json`
- (Alternative) Original OSM file: `branitzer_siedlung.osm` (also used for street names and building centroids fallback)

**Steps**
- Create an LV bus for each node (typical: \(V_n = 0.4\) kV).
- Create line segments for each “power way” (e.g. `power=line`, `power=minor_line`, `power=cable`).
- Add a medium-voltage (MV) bus (e.g. 20 kV) and connect it to the LV network via one or more MV/LV transformers.
- Add an **external grid** at MV (slack bus) as the upstream source.

### B) Select a street and filter buildings (street workflow only)

**Inputs**
- `branitzer_siedlung.osm` (street geometries and names)
- `output_branitzer_siedlungV11.json` (building coordinates, preferred)
- Fallback: parse building polygons/centroids from the OSM file

**Steps**
- Extract all streets (`highway` + `name`) from OSM.
- Interactively select a street name.
- Filter buildings within a configurable buffer (default ~40 m) from any street segment.

### C) Attach building loads + add heat pump increment

**Inputs**
- `gebaeude_lastphasenV2.json`: per-building electrical loads for different scenarios (time slices).

**Steps (street 3‑phase workflow)**
- For each building, map it to the nearest electrical node (bus) by geographic distance.
- Get base load \(P_{base}\) for the selected scenario.
- Convert HP thermal power to extra electrical load:
  - \(P_{HP,el} = \frac{Q_{HP,th}}{\mathrm{COP}}\)
- Total building real power:
  - \(P_{tot} = \max(P_{base} + P_{HP,el},\, 0)\)
- Create loads in `pandapower`:
  - If `hp_three_phase=True`: split equally across phases:
    - \(P_a = P_b = P_c = \frac{P_{tot}}{3}\)
  - If `hp_three_phase=False`: assign to one phase (worst-case imbalance):
    - \(P_a = P_{tot},\; P_b = 0,\; P_c = 0\)

**Steps (batch multiprocessing workflow)**
- Uses a fixed **power factor** (default ~0.95) and computes reactive power:
  - \(Q = P \cdot \tan(\arccos(\mathrm{pf}))\)
- Attaches `pp.create_load(...)` at mapped buses.
- Categorizes loads by building codes (residential vs mixed vs others) for reporting.
- Runs many scenarios in parallel.

### D) Run power flow

**Street workflow**
- Runs **3-phase power flow**:
  - `pandapower.runpp_3ph(net, init="auto")`

**Batch workflow**
- Runs standard (single-phase) load flow:
  - `pandapower.runpp(net, algorithm="nr", ...)`

### E) Post-processing + outputs

**Bus voltage**
- From `res_bus_3ph`: `vm_a_pu`, `vm_b_pu`, `vm_c_pu`
- Defines:
  - \(v_{\min} = \min(v_a, v_b, v_c)\)

**Line loading**
- From `res_line_3ph`: `i_a_ka`, `i_b_ka`, `i_c_ka`
- Defines:
  - \(\mathrm{loading}\% = 100 \cdot \frac{\max(i_a, i_b, i_c)}{i_{max}}\)

**Violations**
- Undervoltage if:
  - \(v_{\min} < v_{\min,\mathrm{limit}}\) (default 0.90 pu)
- Line overload if:
  - \(\mathrm{loading}\% > \mathrm{limit}\) (default 100%)

---

## Key equations used (as implemented)

### Distance / geometry
- **Haversine distance** for lat/lon to meters:
  - Used for segment lengths and nearest-node searches.

### Heat pump electrical load model
- \(P_{HP,el} = Q_{HP,th} / \mathrm{COP}\)
- \(P_{tot} = \max(P_{base} + P_{HP,el}, 0)\)

### Reactive power (batch script)
- \(Q = P \cdot \tan(\arccos(\mathrm{pf}))\), with \(\mathrm{pf} \approx 0.95\)

### Line loading
- \(\mathrm{loading}\% = 100 \cdot \frac{\max(i_a, i_b, i_c)}{i_{max}}\)

### Voltage threshold check
- \(v_{\min} = \min(v_a, v_b, v_c)\)

---

## Data inputs (files + expected structure)

All street workflow data is expected under:
- `Legacy/DHA/HP New /Data/`

### 1) Network topology JSON — `branitzer_siedlung_ns_v3_ohne_UW.json`
Produced by `Scripts/extract_ways_nodes.py`.

Expected top-level keys:
- `nodes`: list of objects with `{id, lat, lon, tags}`
- `ways`: list of objects with `{id, nodes: [node_id...], tags, length_km}`

Relevant tags:
- `tags.power` in `{line, cable, minor_line}` used as electrical edges.
- `tags.power == substation` used as MV/LV transformer location in batch script.

### 2) Building loads per scenario — `gebaeude_lastphasenV2.json`
Expected mapping:
- `building_id -> { scenario_name -> value }`

Units:
- Street script auto-detects `MW` vs `kW` by median magnitude; configurable via `load_unit`.

### 3) Building coordinates — `output_branitzer_siedlungV11.json` (optional but preferred)
Parsed very defensively; supports GeoJSON-like formats and German nested building structures.
Fallback is extracting building polygons/centroids from `branitzer_siedlung.osm`.

### 4) OSM file — `branitzer_siedlung.osm` (optional but required for street selection UI)
Used to:
- extract street names (`highway` + `name`)
- compute street segment geometries for building filtering
- fallback building centroid extraction

---

## Running the street-level simulation (recommended)

From inside this folder:

```bash
python street_hp_lv_sim.py
```

Typical parameters (see `StreetSimulator.run_simulation(...)`):
- `selected_scenario`: e.g. `"winter_werktag_abendspitze"`
- `buffer_distance_m`: default ~40 m
- `hp_add_kw_th`: additional thermal kW per building (HP rollout intensity)
- `hp_cop`: COP for thermal→electric conversion
- `hp_three_phase`: True = balanced 3-phase; False = worst-case single-phase
- `v_min_limit_pu`: undervoltage threshold (default 0.90)
- `line_loading_limit_pct`: overload threshold (default 100)

---

## Outputs (street workflow)

Written under `Legacy/DHA/HP New /results/` and `Legacy/DHA/HP New /maps/`:

- `{StreetName}_buses_results.geojson`
  - Bus voltages per phase + `v_min_pu`
- `{StreetName}_lines_results.geojson`
  - Per-line phase currents and `loading_pct`
- `{StreetName}_violations.csv`
  - Undervoltage and overload violations (with severity)
- `{StreetName}_hp_lv_map.html`
  - Folium map (OSM basemap), lines colored by loading and buses colored by voltage class

---

## Assumptions / limitations

- **Minor equipment & protection models are not included** (no fuses, relays, thermal time constants).
- **Cable parameters** in the street workflow are generic constants (R/X/C/max current); replace with DSO standard types for accurate studies.
- **No explicit HP thermal model**: HP is modeled as a **fixed electrical increment** derived from \(Q_{th}\) and COP.
- **Reducer/tee/fitting losses are not applicable** here (this is an electrical model, not hydraulic).

---

## Files to read first (for understanding)

- `street_hp_lv_sim.py` (main street selection + 3‑phase simulation + outputs)
- `README_street_hp_lv_sim.md` (quick usage guide)
- `README_street_selection.md` (street selection UX)
- `Scripts/extract_ways_nodes.py` (how the nodes/ways JSON is built)
- `Scripts/simuV6_multiprocessing_ohne_UW.py` (batch scenario processing + transformer loading)

