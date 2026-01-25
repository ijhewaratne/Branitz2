import json
import numpy as np
import pandapower as pp
import pandas as pd
from math import radians, sin, cos, asin, sqrt
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor
import multiprocessing
from functools import partial

# Debug settings
DEBUG = False  # Reduziere Debug-Ausgaben

# Gebäudekategorisierung
RESIDENTIAL_BUILDINGS = {
    "1000",  # Wohngebäude
    "1010",  # Wohnhaus
    "2463",  # Garage
    "1313",  # Gartenhaus
    "3270"   # Gebäude im botanischen Garten
}

MIXED_USE_BUILDINGS = {
    "1120",  # Wohngebäude mit Handel und Dienstleistungen
    "1130"   # Wohngebäude mit Gewerbe und Industrie
}

def debug_print(*args, **kwargs):
    if DEBUG:
        print(*args, **kwargs)

# Load data
with open('branitzer_siedlung_ns_v3_ohne_UW.json', 'r') as f:
    data = json.load(f)

nodes_data = data["nodes"]
ways_data = data["ways"]

# Print initial data summary
debug_print(f"\nInitial Data Summary:")
debug_print(f"Total nodes: {len(nodes_data)}")
debug_print(f"Total ways: {len(ways_data)}")

# Print substation information
debug_print("\nSubstation Information:")
substations = [node for node in nodes_data if node['tags'].get("power") == "substation"]
for sub in substations:
    debug_print(f"Substation ID: {sub['id']}")
    debug_print(f"Position: Lat {sub['lat']}, Lon {sub['lon']}")
    debug_print(f"Tags: {sub['tags']}")
    debug_print("---")

def create_base_network():
    # Create empty network
    net = pp.create_empty_network(name="Branitzer Siedlung", f_hz=50)

    # Dictionary for mapping node IDs to buses
    node_id_to_bus = {}
    bus_geodata_list = []

    # Create LV buses for each node
    for node in nodes_data:
        node_id = str(node['id'])
        bus = pp.create_bus(
            net,
            vn_kv=0.4,
            name=f"Node {node_id}",
            type="b",
            zone="Branitz"
        )
        node_id_to_bus[node_id] = bus
        bus_geodata_list.append({'bus': bus, 'x': node['lon'], 'y': node['lat']})

    # Create MV bus (20 kV) - jetzt direkt für External Grid
    mv_bus = pp.create_bus(
        net,
        vn_kv=20,
        name="MV Grid Connection",
        type="b",
        zone="Branitz"
    )

    # Assign geodata to MV bus
    mv_geodata = {'bus': mv_bus, 'x': bus_geodata_list[0]['x'], 'y': bus_geodata_list[0]['y']}
    bus_geodata_list.append(mv_geodata)
    net.bus_geodata = pd.DataFrame(bus_geodata_list).set_index('bus')

    return net, node_id_to_bus, mv_bus

def create_external_grid(net, mv_bus):
    # Direkte 20kV-Einspeisung
    return pp.create_ext_grid(
        net,
        bus=mv_bus,
        vm_pu=1.02,  # Spannungssollwert
        va_degree=0.0,
        s_sc_max_mva=250,  # Angepasste Kurzschlussleistung für 20kV
        rx_max=0.1,
        name="External Grid 20kV"
    )


def create_transformers(net, mv_bus, node_id_to_bus):
    transformers_created = 0
    trafo_mapping = {}

    # Parameter für verschiedene Transformatorgrößen nach DIN EN 50588-1
    trafo_params = {
        '250': {
            'sn_mva': 0.25,
            'vk_percent': 4.0,
            'vkr_percent': 1.1,
            'pfe_kw': 0.3,
            'i0_percent': 0.2
        },
        '630': {
            'sn_mva': 0.63,
            'vk_percent': 6.0,
            'vkr_percent': 0.8,
            'pfe_kw': 0.6,
            'i0_percent': 0.15
        },
        '1000': {
            'sn_mva': 1.0,
            'vk_percent': 6.0,
            'vkr_percent': 0.7,
            'pfe_kw': 0.75,
            'i0_percent': 0.1
        }
    }

    # Dictionary für Transformatorgrößen
    trafo_sizes = {
        'C': '250',
        'B': '250',
        'J': '250',
        'E': '1000'
    }

    for node in nodes_data:
        tags = node.get('tags', {})
        node_id = str(node['id'])

        if tags.get("power") == "substation":
            trafo_id = tags.get("trafoid", "unknown")

            # Nur noch 20/0,4kV Transformatoren
            if node_id in node_id_to_bus:
                lv_bus = node_id_to_bus[node_id]

                # Transformatorgröße und Parameter bestimmen
                size = trafo_sizes.get(trafo_id, '630')  # Default ist 630 kVA
                params = trafo_params[size]

                debug_print(f"\nCreating MV/LV transformer for substation {node_id}")
                debug_print(f"MV bus: {mv_bus}")
                debug_print(f"LV bus: {lv_bus}")
                debug_print(f"Trafo ID: {trafo_id}")
                debug_print(f"Transformer size: {params['sn_mva'] * 1000} kVA")

                idx = pp.create_transformer_from_parameters(
                    net,
                    hv_bus=mv_bus,
                    lv_bus=lv_bus,
                    sn_mva=params['sn_mva'],
                    vn_hv_kv=20.0,
                    vn_lv_kv=0.4,
                    vk_percent=params['vk_percent'],
                    vkr_percent=params['vkr_percent'],
                    pfe_kw=params['pfe_kw'],
                    i0_percent=params['i0_percent'],
                    shift_degree=150,
                    name=f"MV_Transformer_{trafo_id}",
                    tap_min=-2,
                    tap_max=2,
                    tap_step_percent=2.5,
                    tap_pos=0,
                    tap_neutral=0,
                    tap_side="hv"
                )
                trafo_mapping[idx] = trafo_id
                transformers_created += 1

    debug_print(f"\nTotal transformers created: {transformers_created}")
    debug_print(f"250 kVA transformers: {sum(1 for t in trafo_sizes.values() if t == '250')}")
    debug_print(
        f"630 kVA transformers: {transformers_created - sum(1 for t in trafo_sizes.values() if t == '250') - 1}")
    debug_print(f"1000 kVA transformer: 1")

    return transformers_created, trafo_mapping


def determine_line_parameters(tags):
    """
    Bestimmt die Leitungsparameter basierend auf den OSM-Tags.
    Unterscheidet zwischen verschiedenen Leitungstypen:
    - Hausanschlussleitung (power=minor_line)
    - Hauptleitung (power=line)
    - Verbindung Trafo-Umspannwerk (connection=electrical_highway)
    - Verbindung Trafo-Hauptleitung (connection=electrical)
    """
    power_type = tags.get("power", "")
    connection_type = tags.get("connection", "")

    # Verbindung zwischen Trafo und 110kV Umspannwerk
    if connection_type == "electrical_highway":
        return {
            "r_ohm_per_km": 0.0675,  # NA2XS2Y 3x1x240 mm² Mittelspannung
            "x_ohm_per_km": 0.085,
            "c_nf_per_km": 300,
            "max_i_ka": 0.435,
            "type": "electrical_highway"
        }

    # Verbindung zwischen Trafo und Hauptleitung
    elif connection_type == "electrical":
        return {
            "r_ohm_per_km": 0.089,  # NA2XS2Y 3x1x185 mm² Mittelspannung
            "x_ohm_per_km": 0.087,
            "c_nf_per_km": 280,
            "max_i_ka": 0.385,
            "type": "electrical"
        }

    # Hauptleitung
    elif power_type == "line":
        return {
            "r_ohm_per_km": 0.125,  # NAYY 4x150 mm² Niederspannung
            "x_ohm_per_km": 0.078,
            "c_nf_per_km": 264,
            "max_i_ka": 0.275,
            "type": "main_line"
        }

    # Hausanschlussleitung
    elif power_type == "minor_line":
        return {
            "r_ohm_per_km": 0.375,  # NAYY 4x50 mm² Niederspannung
            "x_ohm_per_km": 0.082,
            "c_nf_per_km": 240,
            "max_i_ka": 0.142,
            "type": "house_connection"
        }

    # Standardwerte falls keine spezifischen Tags vorhanden
    return {
        "r_ohm_per_km": 0.125,
        "x_ohm_per_km": 0.078,
        "c_nf_per_km": 264,
        "max_i_ka": 0.275,
        "type": "default"
    }


def create_lines(net, node_id_to_bus):
    lines_created = 0
    line_types = {
        "electrical_highway": 0,
        "electrical": 0,
        "main_line": 0,
        "house_connection": 0,
        "default": 0
    }

    for way in ways_data:
        way_id = way['id']
        node_ids = [str(node_id) for node_id in way['nodes']]
        tags = way['tags']

        power_type = tags.get("power", "")
        connection_type = tags.get("connection", "")

        if power_type in ["line", "minor_line"] or connection_type in ["electrical", "electrical_highway"]:
            params = determine_line_parameters(tags)

            for i in range(len(node_ids) - 1):
                from_node_id = node_ids[i]
                to_node_id = node_ids[i + 1]
                from_bus = node_id_to_bus.get(from_node_id)
                to_bus = node_id_to_bus.get(to_node_id)

                if from_bus is None or to_bus is None:
                    continue

                from_node = next((node for node in nodes_data if str(node['id']) == from_node_id), None)
                to_node = next((node for node in nodes_data if str(node['id']) == to_node_id), None)
                if from_node is None or to_node is None:
                    continue

                length_km = compute_distance(from_node, to_node)

                pp.create_line_from_parameters(
                    net,
                    from_bus=from_bus,
                    to_bus=to_bus,
                    length_km=length_km,
                    r_ohm_per_km=params["r_ohm_per_km"],
                    x_ohm_per_km=params["x_ohm_per_km"],
                    c_nf_per_km=params["c_nf_per_km"],
                    max_i_ka=params["max_i_ka"],
                    name=f"Line {way_id}_{i}_{params['type']}"
                )
                lines_created += 1
                line_types[params['type']] += 1

    debug_print("\nLine creation summary:")
    debug_print(f"Total lines created: {lines_created}")
    for line_type, count in line_types.items():
        debug_print(f"{line_type}: {count} lines")

    return lines_created

def compute_distance(node1, node2):
    lon1, lat1 = radians(node1['lon']), radians(node1['lat'])
    lon2, lat2 = radians(node2['lon']), radians(node2['lat'])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    c = 2 * asin(sqrt(a))
    radius_earth_km = 6371
    return c * radius_earth_km


def find_consumer_node_by_flurid(building_id, building_data, nodes_data):
    """
    Findet einen consumer node basierend auf der FLURID und Koordinaten.

    Args:
        building_id: ID des zu prüfenden Gebäudes
        building_data: Dictionary mit allen Gebäudedaten
        nodes_data: Liste der Netzwerkknoten

    Returns:
        tuple: (closest_node, distance, method)
        - closest_node: Der gefundene consumer node oder None
        - distance: Distanz zum gefundenen node
        - method: 'flurid' oder 'proximity' oder None
    """
    # FLURID des aktuellen Gebäudes ermitteln
    current_flurid = building_data[building_id].get("FLURID")
    if not current_flurid:
        return None, None, None

    # Koordinaten des aktuellen Gebäudes
    if (not building_data[building_id].get("Gebaeudeteile") or
            not building_data[building_id]["Gebaeudeteile"][0].get("Koordinaten")):
        return None, None, None

    current_coords = (
        building_data[building_id]["Gebaeudeteile"][0]["Koordinaten"][0]["latitude"],
        building_data[building_id]["Gebaeudeteile"][0]["Koordinaten"][0]["longitude"]
    )

    # 1. Suche nach consumer nodes auf demselben Flurstück
    same_flurid_buildings = {
        bid: bdata for bid, bdata in building_data.items()
        if bdata.get("FLURID") == current_flurid
    }

    # Sammle alle Koordinaten von Gebäuden auf demselben Flurstück
    flurid_coordinates = []
    for bid, bdata in same_flurid_buildings.items():
        if (bdata.get("Gebaeudeteile") and
                bdata["Gebaeudeteile"][0].get("Koordinaten")):
            coords = (
                bdata["Gebaeudeteile"][0]["Koordinaten"][0]["latitude"],
                bdata["Gebaeudeteile"][0]["Koordinaten"][0]["longitude"]
            )
            flurid_coordinates.append(coords)

    # Suche nach consumer nodes in der Nähe dieser Koordinaten
    for coords in flurid_coordinates:
        for node in nodes_data:
            if node['tags'].get('power') == 'consumer':
                distance = sqrt(
                    (coords[1] - node['lon']) ** 2 +
                    (coords[0] - node['lat']) ** 2
                )
                # Wenn der consumer node sehr nah an einem Gebäude auf demselben
                # Flurstück ist (Schwellwert: 0.0001 ≈ 11m)
                if distance < 0.0001:
                    return node, distance, 'flurid'

    # 2. Fallback: Suche nach nächstgelegenem consumer node
    min_distance = float('inf')
    closest_consumer = None

    consumer_nodes = [node for node in nodes_data if node['tags'].get('power') == 'consumer']
    for node in consumer_nodes:
        distance = sqrt(
            (current_coords[1] - node['lon']) ** 2 +
            (current_coords[0] - node['lat']) ** 2
        )
        if distance < min_distance:
            min_distance = distance
            closest_consumer = node

    if closest_consumer:
        return closest_consumer, min_distance, 'proximity'

    return None, None, None


def create_loads(net, node_id_to_bus, building_data, load_data, scenario):
    loads_created = 0
    skipped_buildings = 0
    total_power_mw = 0
    residential_power_mw = 0
    commercial_power_mw = 0
    non_consumer_nodes = 0

    # Statistik für Zuordnungsmethoden
    assignment_stats = {
        'flurid': 0,
        'proximity': 0,
        'failed': 0
    }

    for building_id, building in building_data.items():
        try:
            if building_id not in load_data:
                continue

            if scenario not in load_data[building_id]:
                debug_print(f"Skipping building {building_id}: No load data for scenario {scenario}")
                skipped_buildings += 1
                continue

            p_mw = load_data[building_id][scenario] / 1000.0
            power_factor = 0.95
            q_mvar = p_mw * np.tan(np.arccos(power_factor))

            # Gebäudefunktion auswerten
            building_type = building.get('Gebaeudefunktion', '')

            # Last kategorisieren
            if building_type in RESIDENTIAL_BUILDINGS:
                residential_power_mw += p_mw
            elif building_type in MIXED_USE_BUILDINGS:
                residential_power_mw += p_mw * 0.5
                commercial_power_mw += p_mw * 0.5
            else:
                commercial_power_mw += p_mw

            # Neue Methode zum Finden des consumer node
            closest_node, distance, method = find_consumer_node_by_flurid(
                building_id, building_data, nodes_data
            )

            if closest_node is None:
                debug_print(f"No suitable consumer node found for building {building_id}")
                assignment_stats['failed'] += 1
                skipped_buildings += 1
                continue

            # Statistik aktualisieren
            if method:
                assignment_stats[method] += 1

            # Debug-Ausgabe mit zusätzlichen Informationen
            debug_print(f"Processing building {building_id}:")
            debug_print(f"  Building type: {building.get('Gebaeudefunktion')}")
            debug_print(f"  FLURID: {building.get('FLURID')}")
            debug_print(f"  Assignment method: {method}")
            debug_print(f"  Distance to consumer node: {distance * 111320:.2f}m")  # Umrechnung in Meter

            node_id = str(closest_node['id'])
            if node_id in node_id_to_bus:
                bus = node_id_to_bus[node_id]
                pp.create_load(
                    net,
                    bus=bus,
                    p_mw=p_mw,
                    q_mvar=q_mvar,
                    name=f"Load {building_id}",
                    scaling=1.0
                )
                loads_created += 1
                total_power_mw += p_mw

        except Exception as e:
            debug_print(f"Error processing building {building_id}: {str(e)}")
            debug_print(f"Building data: {building}")
            skipped_buildings += 1
            assignment_stats['failed'] += 1
            continue

    # Erweiterte Debug-Ausgabe
    debug_print(f"\nLoad Creation Summary:")
    debug_print(f"Loads created: {loads_created}")
    debug_print(f"Buildings skipped: {skipped_buildings}")
    debug_print(f"\nAssignment Statistics:")
    debug_print(f"FLURID assignments: {assignment_stats['flurid']}")
    debug_print(f"Proximity assignments: {assignment_stats['proximity']}")
    debug_print(f"Failed assignments: {assignment_stats['failed']}")
    debug_print(f"Total power: {total_power_mw:.3f} MW")

    return loads_created, total_power_mw, residential_power_mw, commercial_power_mw


def run_single_scenario(scenario_data, net, node_id_to_bus, building_data, load_data, trafo_mapping):
    """
    Einzelnes Szenario ausführen - für Multiprocessing optimiert
    """
    POWER_FACTOR = 0.95

    # Gebäudekategorisierung
    RESIDENTIAL_BUILDINGS = {
        "1000",  # Wohngebäude
        "1010",  # Wohnhaus
        "2463",  # Garage
        "1313",  # Gartenhaus
        "3270"  # Gebäude im botanischen Garten
    }

    MIXED_USE_BUILDINGS = {
        "1120",  # Wohngebäude mit Handel und Dienstleistungen
        "1130"  # Wohngebäude mit Gewerbe und Industrie
    }

    scenario = scenario_data
    net_copy = pp.copy.deepcopy(net)

    loads_created = 0
    total_power_mw = 0
    residential_power_mw = 0
    commercial_power_mw = 0
    load_data_list = []

    # Lasten sammeln
    for building_id, building in building_data.items():
        if building_id not in load_data or scenario not in load_data[building_id]:
            continue

        p_mw = load_data[building_id][scenario] / 1000.0
        q_mvar = p_mw * np.tan(np.arccos(POWER_FACTOR))

        # Gebäudecode aus der JSON-Struktur
        building_code = building.get('Gebaeudecode')

        # Last kategorisieren basierend auf dem Code
        if building_code in RESIDENTIAL_BUILDINGS:
            residential_power_mw += p_mw
        elif building_code in MIXED_USE_BUILDINGS:
            residential_power_mw += p_mw * 0.5
            commercial_power_mw += p_mw * 0.5
        else:
            commercial_power_mw += p_mw

        closest_node, _, _ = find_consumer_node_by_flurid(building_id, building_data, nodes_data)
        if closest_node is None:
            continue

        node_id = str(closest_node['id'])
        if node_id in node_id_to_bus:
            bus = node_id_to_bus[node_id]
            # Einzelne Last direkt erstellen
            pp.create_load(
                net_copy,
                bus=bus,
                p_mw=p_mw,
                q_mvar=q_mvar,
                name=f"Load {building_id}",
                scaling=1.0
            )
            loads_created += 1
            total_power_mw += p_mw

    scenario_results = {
        "scenario": scenario,
        "loads_created": loads_created,
        "total_power_mw": total_power_mw,
        "residential_power_mw": residential_power_mw,
        "commercial_power_mw": commercial_power_mw,
        "transformer_loading": [],
        "success": False
    }

    try:
        # Optimierte Power Flow Berechnung
        pp.runpp(
            net_copy,
            algorithm='nr',
            max_iteration=40,
            tolerance_mva=1e-3,
            enforce_q_lims=False,
            init='dc',
            calculate_voltage_angles=True,
            trafo_model='t',
            consider_line_temperature=False,
            run_control=False,
            distributed_slack=True
        )

        # Transformator-Ergebnisse verarbeiten
        trafo_results = []
        for idx, trafo in net_copy.res_trafo.iterrows():
            trafo_results.append({
                "trafo_id": trafo_mapping.get(idx, f"unknown_{idx}"),
                "p_hv_mw": float(trafo['p_hv_mw']),
                "q_hv_mvar": float(trafo['q_hv_mvar']),
                "loading_percent": float(trafo['loading_percent'])
            })

        scenario_results["transformer_loading"] = trafo_results
        scenario_results["success"] = True

    except pp.LoadflowNotConverged as e:
        scenario_results["error"] = f"Power flow did not converge: {str(e)}"
        scenario_results["success"] = False
    except Exception as e:
        scenario_results["error"] = f"Error in scenario calculation: {str(e)}"
        scenario_results["success"] = False
    finally:
        # Speicher freigeben
        del net_copy

    return scenario_results


def main():
    # Daten laden - mit Caching
    try:
        with open('output_branitzer_siedlungV11.json', 'r') as f:
            building_data = json.load(f)
        print("Building data loaded successfully")

        with open('gebaeude_lastphasenV2.json', 'r') as f:
            load_data = json.load(f)
        print("Load data loaded successfully")
    except Exception as e:
        print(f"Error loading data: {e}")
        return

    if not building_data or not load_data:
        print("Error: Building data or load data is empty")
        return

    try:
        # Basis-Netzwerk erstellen
        net, node_id_to_bus, mv_bus = create_base_network()
        create_external_grid(net, mv_bus)
        _, trafo_mapping = create_transformers(net, mv_bus, node_id_to_bus)
        create_lines(net, node_id_to_bus)

        # Szenarien vorbereiten
        sample_building = next(iter(load_data.values()))
        scenarios = list(sample_building.keys())

        results = {
            "metadata": {
                "datum": datetime.now().isoformat(),
                "number_of_scenarios": len(scenarios),
                "network_info": {
                    "number_of_buses": len(net.bus),
                    "number_of_lines": len(net.line),
                    "number_of_transformers": len(net.trafo)
                }
            },
            "scenarios": {}
        }

        print(f"Processing {len(scenarios)} scenarios...")

        # Multiprocessing Setup
        num_processes = max(1, multiprocessing.cpu_count() - 1)
        print(f"Using {num_processes} processes for parallel computation")

        # Partial function für Pool
        run_scenario_partial = partial(
            run_single_scenario,
            net=net,
            node_id_to_bus=node_id_to_bus,
            building_data=building_data,  # Jetzt wird building_data verwendet
            load_data=load_data,  # Jetzt wird load_data verwendet
            trafo_mapping=trafo_mapping
        )

        # Parallel Processing der Szenarien
        with ProcessPoolExecutor(max_workers=num_processes) as executor:
            scenario_results = list(executor.map(run_scenario_partial, scenarios))

        # Ergebnisse zusammenführen
        successful_scenarios = 0
        for result in scenario_results:
            if result and "scenario" in result:
                results["scenarios"][result["scenario"]] = result
                if result.get("success", False):
                    successful_scenarios += 1

        # Statistiken hinzufügen
        results["metadata"]["successful_scenarios"] = successful_scenarios
        results["metadata"]["failed_scenarios"] = len(scenarios) - successful_scenarios

        # Ergebnisse speichern
        with open('network_resultsV6_ohne_UW_houesehold_comm_data.json', 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

        print(f"Simulation completed:")
        print(f"- Total scenarios: {len(scenarios)}")
        print(f"- Successful: {successful_scenarios}")
        print(f"- Failed: {len(scenarios) - successful_scenarios}")
        print("Results saved to network_resultsV6_ohne_UW_houesehold_comm_data.json")

    except Exception as e:
        print(f"Error in main execution: {str(e)}")
        raise


if __name__ == "__main__":
    main()