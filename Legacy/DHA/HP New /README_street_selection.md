# Street-Specific Heat Pump Simulation

This enhanced version of the street-level LV grid feasibility analysis includes comprehensive street selection and simulation capabilities.

## New Features

### 🏘️ Interactive Street Selection
- **Interactive Interface**: Choose streets from a numbered list or search by name
- **Street Metadata**: View street type, length, and segment information
- **Partial Matching**: Find streets by typing part of the name

### 🎯 Street-Focused Simulation
- **Configurable Buffer**: Set custom distance (default 40m) around selected street
- **Optimized Network**: Build LV network only for relevant area
- **Building Filtering**: Automatically filter buildings near selected street

### 📊 Enhanced Visualization
- **Street-Specific Maps**: Focused maps centered on selected street
- **Street Information**: Display street name and simulation summary on map
- **Improved Styling**: Better visual representation of results

### 📈 Comprehensive Reporting
- **Street-Specific Files**: Output files named after selected street
- **Summary Statistics**: Detailed analysis of voltage, loading, and violations
- **Comparative Analysis**: Compare multiple streets side-by-side

## Quick Start

### 1. Interactive Street Selection
```python
from street_hp_lv_sim import StreetSimulator

# Create simulator
simulator = StreetSimulator()

# Interactive street selection
street_name = simulator.select_street()  # Launches interactive menu

# Run simulation
results = simulator.run_simulation()
simulator.print_summary()
```

### 2. Direct Street Selection
```python
# Select specific street directly
simulator.select_street("Anton-Bruckner-Straße")

# Run with custom parameters
results = simulator.run_simulation(
    buffer_distance_m=50.0,    # 50m buffer around street
    hp_add_kw_th=8.0,          # 8 kW thermal per building
    hp_cop=2.5,                # Lower COP for worst-case
    v_min_limit_pu=0.92        # Stricter voltage limit
)
```

### 3. List Available Streets
```python
from street_hp_lv_sim import list_available_streets

streets = list_available_streets()
# Shows all 36 available streets with metadata
```

## Available Streets

The system includes 36 streets from the Branitzer Siedlung area:

**Residential Streets:**
- Anton-Bruckner-Straße
- Bleyerstraße  
- Clementinestraße
- Defreggerstraße
- Feuerbachstraße
- Gustav-Hermann-Straße
- Heinrich-Zille-Straße
- Holbeinstraße
- Käthe-Kollwitz-Straße
- Leistikowstraße
- Lenbachstraße
- Liebermannstraße
- Lovis-Corinth-Straße
- Luciestraße
- Menzelstraße
- Petzoldstraße
- Spitzwegstraße
- Wilhelm-Busch-Straße

**Main Roads:**
- Forster Straße
- Damaschkeallee
- Stadtring
- Dissenchener Straße
- Willy-Brandt-Straße
- Werner-von-Siemens-Straße

**Special Areas:**
- Branitzer Siedlung
- Selbsthilfesiedlung
- Vorpark
- Vorparkstraße

## Output Files

For each street simulation, the system generates:

### Results Files
- `{StreetName}_buses_results.geojson` - Bus voltage data
- `{StreetName}_lines_results.geojson` - Line loading data  
- `{StreetName}_violations.csv` - Violations report

### Visualization
- `{StreetName}_hp_lv_map.html` - Interactive street-focused map

## Advanced Usage

### Multiple Street Comparison
```python
def compare_streets():
    simulator = StreetSimulator()
    streets = ["Anton-Bruckner-Straße", "Bleyerstraße", "Clementinestraße"]
    results = {}
    
    for street in streets:
        simulator.select_street(street)
        results[street] = simulator.run_simulation()
    
    # Compare results
    for street, result in results.items():
        summary = result["summary"]
        print(f"{street}: {summary['violations']['total']} violations")
```

### Custom Simulation Parameters
```python
results = simulator.run_simulation(
    selected_scenario="winter_werktag_abendspitze",
    buffer_distance_m=60.0,           # Larger buffer
    hp_add_kw_th=10.0,                # Higher HP load
    hp_cop=2.0,                       # Lower COP
    hp_three_phase=False,             # Single-phase HPs
    load_unit="kW",                   # Force kW units
    v_min_limit_pu=0.95,              # Stricter voltage limit
    line_loading_limit_pct=80.0       # Stricter loading limit
)
```

## StreetSimulator Class Methods

### Core Methods
- `select_street(street_name=None)` - Select street (interactive if None)
- `run_simulation(**params)` - Run complete simulation
- `print_summary()` - Print simulation summary
- `list_available_streets()` - Get all available streets

### Configuration
- `buffer_distance_m` - Distance around street to include buildings
- `hp_add_kw_th` - Thermal kW per building for HP simulation
- `hp_cop` - Coefficient of Performance for HP conversion
- `hp_three_phase` - Whether HPs are 3-phase or single-phase
- `v_min_limit_pu` - Minimum voltage limit for violations
- `line_loading_limit_pct` - Maximum line loading for violations

## Example Workflows

### 1. Quick Street Analysis
```bash
python street_hp_lv_sim.py
# Follow interactive prompts to select street and run simulation
```

### 2. Batch Street Analysis
```python
from street_hp_lv_sim import StreetSimulator

simulator = StreetSimulator()
streets = ["Anton-Bruckner-Straße", "Bleyerstraße", "Clementinestraße"]

for street in streets:
    print(f"\nAnalyzing {street}...")
    simulator.select_street(street)
    results = simulator.run_simulation()
    simulator.print_summary()
```

### 3. Research Study
```python
# Compare different HP scenarios for same street
simulator = StreetSimulator()
simulator.select_street("Anton-Bruckner-Straße")

scenarios = [
    {"hp_add_kw_th": 4.0, "hp_cop": 3.0, "name": "Conservative"},
    {"hp_add_kw_th": 6.0, "hp_cop": 2.8, "name": "Standard"},
    {"hp_add_kw_th": 8.0, "hp_cop": 2.5, "name": "Aggressive"}
]

for scenario in scenarios:
    print(f"\nTesting {scenario['name']} scenario...")
    results = simulator.run_simulation(**scenario)
    print(f"Violations: {results['summary']['violations']['total']}")
```

## Testing

Run the test script to verify functionality:
```bash
python test_street_simulation.py
```

## Backward Compatibility

The original `main()` function still works for area-wide simulations:
```python
from street_hp_lv_sim import main

main(
    selected_scenario="winter_werktag_abendspitze",
    selected_street_name=None,  # Area-wide simulation
    hp_add_kw_th=6.0
)
```

## Requirements

Same as original system:
- pandapower
- pandas
- folium (for visualization)
- shapely (for geometry calculations)

## Troubleshooting

### No Streets Found
- Ensure `Data/branitzer_siedlung.osm` exists
- Check file permissions

### No Buildings Near Street
- Increase `buffer_distance_m` parameter
- Check if street name matches exactly

### Simulation Errors
- Verify all data files are present
- Check conda environment is activated: `conda activate branitz_env`

## Performance Notes

- Street-specific simulations are faster than area-wide simulations
- Interactive selection adds minimal overhead
- File I/O is optimized for street-specific outputs
- Memory usage scales with street area, not entire dataset
