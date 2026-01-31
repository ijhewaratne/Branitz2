# Street HP LV Feasibility (Branitz-Siedlung)

This builds a **three-phase LV grid** from your OSM-derived *nodes & ways* JSON and attaches **per-building loads + heat pumps**. It then runs `pandapower` (`runpp_3ph`) and exports:

- `results/lines_results.geojson` – LV segments with **loading %** (max of A/B/C phase currents)
- `results/buses_results.geojson` – LV buses with **per-phase voltages** and **v_min_pu**
- `results/violations.csv` – flags buses with v_min_pu < 0.90 and lines with loading_pct > 100
- `maps/street_hp_lv_map.html` – interactive map (OSM basemap) with **color gradients**:
  - Lines: green→red by **loading %**
  - Buses: red→green by **min voltage (pu)**

## Requirements
```bash
pip install pandapower folium branca shapely pandas
```

## Inputs (place in `data/`)

* `branitzer_siedlung_ns_v3_ohne_UW.json`  ✅
* `gebaeude_lastphasenV2.json` ✅ (values often in **MW**; set `load_unit` accordingly)
* *(optional)* `output_branitzer_siedlungV11.json` (building coords)
* *(fallback)* `branitzer_siedlung.osm` (we'll extract building centroids)

## Run

```bash
python street_hp_lv_sim.py
```

Tune the defaults at the bottom of the file:

```python
main(
  selected_scenario="winter_werktag_abendspitze",  # which load slice to simulate
  selected_street_name="An der Bahn",              # only buildings near this street (≈40 m buffer)
  load_unit="MW",                                  # set "kW" if your JSON values are already kW
  hp_add_kw_th=6.0,                                # EXTRA thermal kW PER BUILDING to model new HPs
  hp_cop=2.8,                                      # COP used to convert thermal→electric (P_el = kW_th / COP)
  hp_three_phase=True,                             # False = put HP on one phase (show imbalance)
  limit_to_bbox=None,                              # or (minlat, minlon, maxlat, maxlon) if no street name
  v_min_limit_pu=0.90,                             # undervoltage threshold for violations.csv
  line_loading_limit_pct=100.0                     # line overload threshold for violations.csv
)
```

## Notes

* If you don't have a building catalog, the script **parses building polygons from `branitzer_siedlung.osm`** and maps centroids to the nearest LV node.
* Cable parameters are **generic LV** (Cu 4×150 mm²). Replace in `build_lv_net()` with your DSO std-types for accurate ampacities.
* The MV/LV transformer is a placeholder (`sn_mva=0.63`, `vector_group="Dyn"`). Adjust to your station.
* **Note**: pandapower 3-phase only supports transformer vector groups: `'YNyn'`, `'Dyn'`, `'Yzn'`.
* Use `hp_three_phase=False` to see **phase imbalance** from single-phase HPs.
* If no street name is found, pass a `limit_to_bbox=(minlat, minlon, maxlat, maxlon)`.

## Interpreting the results

### Map visualization
* **Red lines** ⇒ overloaded segments. **Amber** ⇒ nearing limit.
* **Red nodes** ⇒ voltage drops (e.g., < 0.90 pu).

### Violations.csv
* **undervoltage**: buses with v_min_pu below threshold
* **overload**: lines with loading_pct above threshold
* **severity**: "critical" for severe violations, "warning" for moderate ones

### Interpretation tips
* If you only want to test the existing electrical demand: set `hp_add_kw_th = 0`
* To test a rollout of new HPs: keep `hp_add_kw_th > 0` (e.g., 6–10 kW_th per house) and pick a COP (e.g., 2.5–3.0 for cold design)
* Use `hp_three_phase=False` once to see worst-case single-phase effects (imbalance)
* If lines go red or nodes go red → consider cable upsizing, parallel feeder, feeder split, or trafo uprate

### Iterate on:
* `hp_add_kw_th` / `hp_cop` (HP sizing, COP)
* Cable R/X/C + `max_i_ka` (std-types)
* Trafo rating/impedance
* 3-phase vs single-phase allocation
