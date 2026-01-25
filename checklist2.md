### Checklist 2 — Topology correctness (graph-level)

Scope: latest converged result for `ST010_HEINRICH_ZILLE_STRASSE` loaded from `results/cha/ST010_HEINRICH_ZILLE_STRASSE/network.pickle`.

#### Trunk is a tree (no cycles)
- **Check**: \(|E_{trunk}| = |V_{trunk}| - 1\) and trunk graph is connected.
- **Result**: **PASS**
  - **V_trunk**: 118  
  - **E_trunk**: 117  
  - **Connected**: True  
  - **Cycle count**: 0

#### Exactly one plant attach node on trunk (single root)
- **Check**: exactly one `pipe_S_plant_to_trunk` and one `pipe_R_plant_to_trunk`, both connecting to the same trunk coordinate (supply/return junction pair at the same location).
- **Result**: **PASS**
  - **Supply attach junction**: `S_456416.7_5734189.1` (junction id 142)
  - **Return attach junction**: `R_456416.7_5734189.1` (junction id 143)
  - **Attach coords match**: True

#### Every building tees into trunk at an edge-split projection node
- **Check (network-level proxy)**:
  - every `service_S_*` pipe starts at a trunk supply junction (`name` starts with `S_`)
  - no `trunk_conn_*` pipes exist
- **Result**: **PASS**
  - **Bad service supply start junctions**: 0
  - **`trunk_conn_*` pipe count**: 0

#### No duplicate trunk edges after splitting/merging
- **Check**: in the trunk-supply graph, no repeated undirected edge \(\{u,v\}\).
- **Result**: **PASS**
  - **Duplicate trunk edges**: 0

#### No zero-length pipes and no NaN/inf lengths
- **Check**: all `net.pipe.length_km` are finite and > 0; and geometric length matches junction geodata distance.
- **Result**: **PASS**
  - **NaN lengths**: 0
  - **Inf lengths**: 0
  - **Lengths <= 0**: 0
  - **Geom length mismatch > 0.05 m**: 0

#### Evidence snapshot (counts)
- **Total pipes**: 378  
- **Trunk supply pipes**: 117  
- **Service supply pipes**: 71  
- **Service return pipes**: 71  

---

### Checklist 2 — Pandapipes element integrity

Scope: latest converged result for `ST010_HEINRICH_ZILLE_STRASSE` loaded from `results/cha/ST010_HEINRICH_ZILLE_STRASSE/network.pickle`.

#### Buildings are not hydraulic mass sinks/sources
- **Check**:
  - no `net.sink` table populated for buildings
  - no `net.source` table populated for buildings
  - no fake consumer pipes like `hx_*` or `substation_dp_*`
- **Result**: **PASS**
  - **has sinks**: False
  - **has sources**: False
  - **`hx_*` pipe count**: 0
  - **`substation_dp_*` pipe count**: 0

#### Exactly one consumer element per building
- **Check**: one `heat_consumer` named `hc_{building_id}` per building.
- **Result**: **PASS**
  - **heat_consumer count**: 71
  - **buildings with count != 1**: 0

#### Each heat_consumer uses exactly two defining parameters
- **Check**: each row has exactly 2 non-null values among:
  - `controlled_mdot_kg_per_s`, `qext_w`, `deltat_k`, `treturn_k`
- **Result**: **PASS**
  - **parameter issues found**: 0

#### Supply/return networks are paired correctly
- **Check**:
  - for each trunk node coordinate suffix, both `S_*` and `R_*` junctions exist
  - `service_S_*` starts at `S_*` and ends at `S_B_*`
  - `service_R_*` starts at `R_B_*` and ends at `R_*`
- **Result**: **PASS**
  - **trunk supply junctions** (names matching `S_<x>_<y>`): 118
  - **trunk return junctions** (names matching `R_<x>_<y>`): 118
  - **unpaired trunk supply (missing return)**: 0
  - **unpaired trunk return (missing supply)**: 0
  - **bad service supply connections**: 0
  - **bad service return connections**: 0

---

### Checklist 2 — Convergence and physics sanity gates (automated checks)

Scope: latest converged result for `ST010_HEINRICH_ZILLE_STRASSE` loaded from `results/cha/ST010_HEINRICH_ZILLE_STRASSE/network.pickle`.

#### Hydraulics convergence
- **Check**: `net.converged == True`
- **Result**: **PASS**

#### Thermal results are finite (no NaNs) + non-trivial temperature field
- **Check**:
  - **FAIL only if**: \((\\dot{m} \\ne 0)\\) AND \((t_{from} \\text{ is NaN} \\;\\text{or}\\; t_{to} \\text{ is NaN})\)
  - **WARN if**: \((\\dot{m} = 0)\\) AND \((t_{from} \\text{ is NaN} \\;\\text{or}\\; t_{to} \\text{ is NaN})\)
  - not “everything has identical temperature” (unless trivial zero-load case)
- **Result**: **PASS**
  - **Non-constant temperatures**: PASS (only 2 unique values across `t_from_k/t_to_k`, not a single constant)
  - **NaN thermal pipes**: 0
  - **Notes**: trunk dead-end stubs were pruned (minimal subtree from plant→all service tees), eliminating zero-flow trunk pipes.

#### Pressure sanity
- **Check**:
  - no negative absolute pressures in `net.res_junction.p_bar`
  - no unrealistically huge \(\Delta p\) per short distance
- **Result**: **PASS**
  - **min pressure (bar)**: 1.5
  - **negative pressure count**: 0
  - **hard gate**: \(\Delta p > 2.0\) bar per 100 m → **0 offenders**

#### Velocity limits (hard fails for sizing)
- **Targets**:
  - trunk \(v_{max} \\le 3.0\) m/s
  - service \(v_{max} \\le 2.0\) m/s
- **Result**: **PASS**
  - **trunk vmax (m/s)**: 1.004
  - **service vmax (m/s)**: 1.182
  - **trunk over-limit pipes**: 0
  - **service over-limit pipes**: 0

#### Direction classification completeness
- **Check**: 0 pipes labeled as direction=unknown (naming/classifier mismatch)
- **Result**: **PASS**
  - **unknown direction pipes**: 0

---

### Checklist 2 — Interactive map correctness

Scope: rendered map at `results/cha/ST010_HEINRICH_ZILLE_STRASSE/interactive_map.html`.

#### Supply/return/service styling is correct and clearly separated
- **Check**:
  - supply is red, return is blue
  - service uses a distinct style (separate layer + dashed lines)
- **Result**: **PASS**
  - **Supply legend label**: “Supply velocity (m/s)” (red color ramp)
  - **Return legend label**: “Return velocity (m/s)” (blue color ramp)
  - **Service styling (evidence)**:
    - service supply polylines: dashed red (`color: "#fb6a4a"`, `dashArray: "8, 4"`, `weight: 3`, `opacity: 0.75`)
    - service return polylines: dashed blue (`color: "#6baed6"`, `dashArray: "8, 4"`, `weight: 3`, `opacity: 0.75`)
    - trunk lines: solid, thicker (`dashArray: null`, `weight: 4`, `opacity: 0.95`)

#### Plant connection rendering is correct (no 3–4 connections)
- **Check**: map contains exactly one plant→trunk supply connection and exactly one trunk→plant return connection.
- **Result**: **PASS**
  - `pipe_S_plant_to_trunk` rendered occurrences: 1
  - `pipe_R_plant_to_trunk` rendered occurrences: 1

#### No legacy connector artifacts are rendered
- **Check**: map does not render any `trunk_conn_*` artifacts.
- **Result**: **PASS**
  - `trunk_conn` string occurrences in HTML: 0


