### CHA Implementation Checklist (no code changes)

Use this checklist to confirm the CHA (Community Heat Analysis) workflow is fully implemented and behaving as intended.

---

## Step 2.1 — Build street-following topology (`network_builder_trunk_spur.py`)

- **Data load + CRS**
  - Buildings + streets are loaded and **reprojected to a metric CRS** (e.g., EPSG:25833) before distance-based logic (lengths, nearest points, buffering).

- **Trunk mode supported**
  - Trunk topology is built from a **street graph** (NetworkX) using a street-following method.
  - At least one trunk mode exists that produces a **connected trunk** to serve all attach targets (radial/tree accepted).
  - If multiple trunk modes are supported, they are selectable via config/CLI and documented.

- **Nearest points / attach points**
  - For every building, compute a **nearest attach point** on the street graph (projection onto a street edge).
  - Persist per-building attach metadata (at minimum: building_id, street edge id or (u,v), attach point coords, nearest nodes).

- **Split edges (tee-on-main)**
  - When `attach_mode == split_edge_per_building`, trunk edges that host attach points are **split at attach points** into a chain.
  - Each building gets a **true trunk tee node** created by the split.
  - Service pipes connect **directly** to the trunk tee node.
  - No legacy connector artifacts are used (e.g., no `trunk_conn_*`, no `S_T_*`/`R_T_*` connector pipes).

- **Trunk edge construction**
  - Trunk edges are derived from shortest paths from **plant/root** to all attach targets.
  - Trunk is **one connected network** (component check passes).
  - Trunk is **radial / acyclic** when tree mode is intended (cycle check passes).

- **Return / topology info**
  - Builder returns trunk edges, spur/service assignments, and a topology info dict that includes plant location used and trunk stats.

---

## Step 2.2 — Pipe sizing & catalog (`sizing_catalog.py`)

- **Catalog parsing**
  - Technical catalog (DN series + inner diameters) is loaded.
  - Fallback catalog exists if the Excel file is missing/unavailable.

- **Design flow basis**
  - Uses \( \dot{m} = Q / (c_p \Delta T) \) with consistent units (W, J/kgK, K → kg/s).

- **Trunk sizing (downstream demand accumulation)**
  - Trunk is sized by **downstream aggregated load** on the trunk tree rooted at the plant attach node.
  - Trunk **tapers** (larger near plant, smaller downstream), subject to constraints.

- **Service sizing (per building)**
  - Service pipes are sized per building based on that building’s design load.

- **Constraints enforced (not just flagged)**
  - **Role-based velocity targets** enforced for trunk/service.
  - **Absolute velocity hard cap** flagged if exceeded even after maximum DN.
  - **dp/m constraint enforced**: if dp/m estimate exceeds limit, DN is increased until dp/m is within limit (or max DN reached).

- **Sizing rationale CSV**
  - `pipe_sizing_rationale.csv` includes for each pipe/edge:
    - Q_down (trunk) or Q_building (service)
    - mdot_design
    - chosen DN + diameter
    - v_calc
    - dp_per_m estimate + dp_per_m_max
    - status flags (ok / dp_per_m_exceeded / v_abs_max_exceeded / fallback)
  - If post-simulation dp/m is available, it is merged into the rationale output.

---

## Step 2.3 — Convergence optimization (`convergence_optimizer_spur.py`)

- **Connectivity validation**
  - Detects disconnected components and either fixes or fails with a clear error.

- **Symmetry breaking / stabilization**
  - Applies at least one stabilization strategy (e.g., roughness perturbation, virtual bridges with non-zero lengths).

- **Initial conditions**
  - Provides distance-based or topology-based initial pressure guidance to help convergence.

- **Fallback integration**
  - Network builder attempts direct `pp.pipeflow` first.
  - If it fails, the spur convergence optimizer is used as a fallback and returns `(converged, net, log)`.

- **Output**
  - Optimizer produces a concise optimization log with applied actions and final convergence status.

---

## Step 2.4 — KPI extraction (EN 13941-1 style) (`kpi_extractor.py`)

- **Hydraulic KPIs**
  - Max/mean velocity and share within limits.
  - dp metrics (e.g., dp per 100m) computed safely (no divide-by-zero).
  - Pressure sanity values reported (min/max) if available.

- **Thermal KPIs**
  - Thermal results handled robustly:
    - No fake temperatures when thermal columns are missing.
    - Finite checks and “thermal not solved” behavior when needed.
  - Thermal loss metrics computed from `res_pipe.qext_w` if available.

- **Pump KPIs**
  - Pump power extracted from `res_circ_pump_const_pressure` when available.

- **Heat consumer compatibility**
  - Heat delivered and mass flow are derived from:
    - `heat_consumer` / `res_heat_consumer` (not sinks/sources for buildings).

- **Feasibility criteria**
  - A `feasible` flag exists and is based on documented limits (velocity, dp, pressure sanity, etc.).

---

## Step 2.5 — Interactive map generation (`qgis_export.py`)

- **Dual network separation**
  - Supply and return pipes are clearly separated into distinct layers.

- **Cascading colors (value-based gradients)**
  - **Velocity map**: supply = red shades, return = blue shades (true gradient, not fixed colors).
  - **Temperature map**: supply = red shades, return = blue shades.
  - **Pressure map**: supply = red shades, return = blue shades.

- **Scaling between min/max**
  - Colormap scaling uses **actual data min/max** (or documented percentile scaling) to ensure visible gradients.
  - Legends reflect the actual scaling bounds used.

- **Pipe thickness by diameter**
  - Line thickness uses a role-based scaling (`trunk` vs `service`) and is clamped for readability.
  - Thickness legend exists and explains DN/diameter encoding.

- **Service styling**
  - Service pipes are dashed and visually distinct from trunk pipes.

- **Plant + pump markers**
  - Plant marker is shown at the plant location used.
  - Pump marker is shown at plant (or derived from pump element table).

- **Flow-aligned pressure drop**
  - Any displayed/exported Δp uses **flow-aligned dp** (uses mdot sign to align dp with real flow direction).
  - Orientation-only dp is either hidden or clearly labeled as “oriented”.

---

## CLI & deliverables (`src/scripts/01_run_cha.py`)

- **CLI supports**
  - `--cluster-id`
  - `--use-trunk-spur`
  - `--attach-mode`, `--trunk-mode` (as applicable)
  - Optional fixed plant location:
    - `--plant-wgs84-lat`, `--plant-wgs84-lon`
    - `--disable-auto-plant-siting`

- **Outputs created per cluster**
  - `results/cha/<cluster>/cha_kpis.json`
  - `results/cha/<cluster>/network.pickle`
  - `results/cha/<cluster>/interactive_map.html` (velocity)
  - `results/cha/<cluster>/interactive_map_temperature.html`
  - `results/cha/<cluster>/interactive_map_pressure.html`
  - CSV exports:
    - `pipe_velocities_supply_return.csv`
    - `pipe_velocities_supply_return_with_temp.csv`
    - `pipe_velocities_plant_to_plant_main_path.csv`
    - `pipe_pressures_supply_return.csv`

