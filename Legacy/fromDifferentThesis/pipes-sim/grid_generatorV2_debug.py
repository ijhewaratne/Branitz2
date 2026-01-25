import sys
import numpy as np
import osmnx as ox
import geopandas as gpd
import networkx as nx
import matplotlib.pyplot as plt
from shapely.geometry import Point, LineString
import pandapipes as pp
import json
from geopy.distance import geodesic
from shapely.geometry import MultiLineString

def get_pipe_length(coord1, coord2):
    """Berechnet die Distanz zwischen zwei Koordinaten in Metern"""
    return geodesic(coord1, coord2).meters

def get_max_heating_load(building_data):
    """Ermittelt die maximale Heizleistung aus allen Szenarien"""
    if building_data['Sanierungszustand'] == 'unbeheizt':
        return 0

    if 'Szenarien' not in building_data or building_data['Szenarien'] == 0:
        return 0

    max_load = 0
    for jahrestyp in building_data['Szenarien'].values():
        if isinstance(jahrestyp, list):
            for szenario in jahrestyp:
                load = szenario['Durchschnitt']['Momentane_Heizleistung_W']
                max_load = max(max_load, load)

    return max_load


def load_and_filter_data(osm_file, buildings_json, heating_json):
    # Straßen und Einspeisepunkt aus OSM laden
    streets = ox.features_from_xml(osm_file, tags={'highway': True})
    feeding_point = ox.features_from_xml(osm_file, tags={'gas': 'feeding_point'})

    # Straßen filtern
    relevant_types = ['residential', 'secondary', 'primary', 'tertiary',
                      'unclassified', 'service', 'living_street', 'track']
    filtered_streets = streets[streets['highway'].isin(relevant_types)]

    # Heizlastdaten laden
    with open(heating_json, 'r', encoding='utf-8') as f:
        heating_data = json.load(f)

    # Gebäude aus JSON laden
    with open(buildings_json, 'r', encoding='utf-8') as f:
        buildings_data = json.load(f)

    # GeoDataFrame für Gebäude erstellen
    building_list = []
    for building_id, building in buildings_data.items():
        # Heizlast aus heating_data ermitteln
        heating_info = heating_data['ergebnisse'].get(building_id, {})
        if heating_info.get('Sanierungszustand') != 'unbeheizt':
            coords = building['Gebaeudeteile'][0]['Koordinaten'][0]
            point = Point(coords['longitude'], coords['latitude'])
            max_heating_load = get_max_heating_load(heating_info)

            building_info = {
                'geometry': point,
                'building_id': building_id,
                'max_heating_load': max_heating_load,
                'connection_point': point
            }
            building_list.append(building_info)

    buildings = gpd.GeoDataFrame(building_list)
    buildings.set_crs("EPSG:4326", inplace=True)

    return filtered_streets, buildings, feeding_point


def find_connection_point(building, streets):
    """
    Findet den optimalen Anschlusspunkt für ein Gebäude auf der nächsten Straße.

    Args:
        building: GeoSeries mit Gebäudeinformationen
        streets: GeoDataFrame mit Straßeninformationen

    Returns:
        Point: Optimaler Anschlusspunkt auf der Straße
    """
    building_point = Point(building.geometry.x, building.geometry.y)

    min_distance = float('inf')
    best_point = None
    best_street = None

    for _, street in streets.iterrows():
        if isinstance(street.geometry, LineString):
            point = street.geometry.interpolate(
                street.geometry.project(building_point)
            )
            dist = building_point.distance(point)
            if dist < min_distance:
                min_distance = dist
                best_point = point
                best_street = street.geometry

    if best_point is None:
        print(f"Warnung: Kein Anschlusspunkt für Gebäude gefunden")
        return None

    return best_point


def create_street_graph(filtered_streets, connection_points):
    """
    Erstellt einen Graphen aus Straßen und Anschlusspunkten.

    Args:
        filtered_streets: GeoDataFrame mit Straßeninformationen
        connection_points: Liste von Point-Objekten für Hausanschlüsse

    Returns:
        networkx.Graph: Graph mit allen Straßen und Anschlusspunkten
    """
    G = nx.Graph()

    # Straßen-Dictionary für schnellen Zugriff
    street_lines = {}

    # Erst normale Straßen hinzufügen
    for idx, row in filtered_streets.iterrows():
        if isinstance(row.geometry, LineString):
            coords = list(row.geometry.coords)
            for i in range(len(coords) - 1):
                start_coord = coords[i]
                end_coord = coords[i + 1]
                line = LineString([Point(start_coord), Point(end_coord)])

                G.add_edge(start_coord, end_coord)
                # Speichere die Liniengeometrie im Dictionary
                street_lines[(start_coord, end_coord)] = line
                street_lines[(end_coord, start_coord)] = line  # Beide Richtungen

    # Anschlusspunkte zum Graph hinzufügen
    for point in connection_points:
        if point is not None:
            point_coord = (point.x, point.y)

            # Finde nächste Straßenkante
            min_dist = float('inf')
            nearest_edge = None

            for edge in G.edges():
                if edge in street_lines:
                    line = street_lines[edge]
                    dist = point.distance(line)
                    if dist < min_dist:
                        min_dist = dist
                        nearest_edge = edge

            if nearest_edge is not None:
                # Füge Verbindungen zum Anschlusspunkt hinzu
                G.add_edge(nearest_edge[0], point_coord)
                G.add_edge(point_coord, nearest_edge[1])

    print(f"Debug: Graph erstellt mit {G.number_of_nodes()} Knoten und {G.number_of_edges()} Kanten")
    return G


def find_shortest_paths(graph, filtered_streets, buildings, feeding_point):
    feeding_point_coords = (feeding_point.geometry.iloc[0].x, feeding_point.geometry.iloc[0].y)
    start_node = min(graph.nodes(), key=lambda n: Point(n).distance(Point(feeding_point_coords)))

    paths = []
    for idx, building in buildings.iterrows():
        end_point = (building.connection_point.x, building.connection_point.y)
        end_node = min(graph.nodes(), key=lambda n: Point(n).distance(Point(end_point)))

        try:
            path = nx.shortest_path(graph, start_node, end_node, weight='length')
            paths.append(path)
        except nx.NetworkXNoPath:
            print(f"Kein Weg gefunden für Gebäude {building.building_id}")

    return paths


def create_main_network(graph, paths):
    main_network = nx.Graph()
    edge_usage = {}

    for path in paths:
        for i in range(len(path) - 1):
            edge = tuple(sorted([path[i], path[i + 1]]))
            edge_usage[edge] = edge_usage.get(edge, 0) + 1

    for edge, count in edge_usage.items():
        main_network.add_edge(edge[0], edge[1], weight=count)

    return main_network, edge_usage


def calculate_pipe_loads(main_network, paths, buildings):
    """Berechnet die Gesamtlast für jede Leitung basierend auf nachgelagerten Gebäuden"""
    pipe_loads = {}

    # Für jede Kante im Netz
    for edge in main_network.edges():
        total_load = 0
        edge_sorted = tuple(sorted(edge))

        # Für jeden Pfad prüfen
        for idx, path in enumerate(paths):
            # Wenn die Kante in diesem Pfad vorkommt
            for i in range(len(path) - 1):
                current_edge = tuple(sorted([path[i], path[i + 1]]))
                if current_edge == edge_sorted:
                    # Heizlast des Gebäudes am Ende dieses Pfades addieren
                    building_load = buildings.iloc[idx]['max_heating_load']
                    total_load += building_load
                    break

        pipe_loads[edge_sorted] = total_load

    return pipe_loads


def determine_pipe_diameter(load):
    """
    Bestimmt den Rohrdurchmesser basierend auf der Wärmelast in Watt.

    Orientiert an DVGW-Normen:
    - Hausanschlüsse: DN25-DN50
    - Versorgungsleitungen: DN50-DN150
    - Hauptleitungen: DN100-DN300
    """
    if load == 0:
        return 0
    elif load < 2000:  # Kleine Hausanschlüsse
        return 25
    elif load < 5000:  # Mittlere Hausanschlüsse
        return 32
    elif load < 10000:  # Große Hausanschlüsse
        return 40
    elif load < 20000:  # Kleine Versorgungsleitungen
        return 65
    elif load < 50000:  # Mittlere Versorgungsleitungen
        return 100
    elif load < 100000:  # Große Versorgungsleitungen
        return 150
    elif load < 200000:  # Kleine Hauptleitungen
        return 200
    elif load < 400000:  # Mittlere Hauptleitungen
        return 250
    else:  # Große Hauptleitungen
        return 300


def identify_critical_paths(main_network, pipe_loads):
    """Identifiziert kritische Leitungen basierend auf der durchgeleiteten Last"""
    critical_edges = []

    # Sortiere Leitungen nach Last
    sorted_loads = sorted(pipe_loads.items(), key=lambda x: x[1], reverse=True)

    # Die top 20% der Leitungen mit höchster Last werden als kritisch eingestuft
    num_critical = max(1, int(len(sorted_loads) * 0.2))
    critical_edges = [edge for edge, load in sorted_loads[:num_critical]]

    return critical_edges


def identify_critical_endpoints(main_network, pipe_loads, buildings):
    # Debug: Prüfe Duplikate
    print("\nDebug - Buildings DataFrame:")
    print(f"Anzahl Einträge gesamt: {len(buildings)}")
    print(f"Anzahl unique building_ids: {buildings['building_id'].nunique()}")
    print(f"Anzahl unique Koordinaten: {buildings.geometry.nunique()}")

    # Entferne Duplikate und erstelle Kopie
    buildings_unique = buildings.drop_duplicates(subset=['building_id']).copy()
    print(f"Anzahl Einträge nach Duplikat-Entfernung: {len(buildings_unique)}")

    critical_points = []
    endpoints = [node for node, degree in main_network.degree() if degree == 1]

    print(f"\nDebug - Anzahl Endpunkte: {len(endpoints)}")

    for endpoint in endpoints:
        nearby_buildings = set()  # Set um Duplikate zu vermeiden
        total_load = 0

        print(f"\nAnalysiere Endpunkt {endpoint}:")

        for _, building in buildings_unique.iterrows():
            building_coord = (building.geometry.x, building.geometry.y)
            distance = Point(endpoint).distance(Point(building_coord))

            if distance < 100:  # 100m Radius
                if building.building_id not in nearby_buildings:
                    nearby_buildings.add(building.building_id)
                    total_load += building.max_heating_load
                    print(f"- Gebäude {building.building_id}:")
                    print(f"  Koordinaten: {building_coord}")
                    print(f"  Distanz: {distance:.2f}m")
                    print(f"  Last: {building.max_heating_load:.0f}W")

        print(f"\nEndpunkt Zusammenfassung:")
        print(f"- Anzahl unique Gebäude: {len(nearby_buildings)}")
        print(f"- Gesamtlast: {total_load:.0f}W")

        if len(nearby_buildings) >= 5 or total_load > 20000:
            critical_points.append({
                'point': endpoint,
                'buildings': len(nearby_buildings),
                'load': total_load
            })
            print("=> Als kritisch eingestuft")

    # Sortiere nach Last und nimm die Top 10
    critical_points = sorted(critical_points, key=lambda x: x['load'], reverse=True)[:10]

    print("\nDebug - Kritische Punkte:")
    for idx, cp in enumerate(critical_points, 1):
        print(f"\nKritischer Punkt {idx}:")
        print(f"- Koordinaten: {cp['point']}")
        print(f"- Anzahl Gebäude: {cp['buildings']}")
        print(f"- Gesamtlast: {cp['load']:.0f}W")

    return critical_points


def find_potential_loops(main_network, critical_points, filtered_streets, pipe_loads):
    potential_loops = []

    # Erstelle MultiLineString aus Hauptleitungen für schnellere Abfragen
    main_lines = []
    for edge in main_network.edges():
        if pipe_loads.get(tuple(sorted(edge)), 0) > 20000:  # Nur echte Hauptleitungen
            main_lines.append(LineString([Point(edge[0]), Point(edge[1])]))
    main_network_geometry = MultiLineString(main_lines)

    for critical in critical_points:
        endpoint = critical['point']
        endpoint_point = Point(endpoint)

        # Finde nächsten Punkt auf der Hauptleitung
        nearest_point = None
        min_distance = float('inf')

        for line in main_lines:
            proj_point = line.interpolate(line.project(endpoint_point))
            dist = endpoint_point.distance(proj_point)

            if dist < min_distance:
                # Prüfe ob Verbindung entlang einer Straße möglich
                for _, street in filtered_streets.iterrows():
                    if (street.geometry.distance(endpoint_point) < 1 and
                            street.geometry.distance(proj_point) < 1):
                        min_distance = dist
                        nearest_point = proj_point
                        break

        if nearest_point and min_distance < 150:  # Max 150m
            potential_loops.append({
                'points': (endpoint, (nearest_point.x, nearest_point.y)),
                'distance': min_distance,
                'buildings_secured': critical['buildings'],
                'load': critical['load']
            })

    return sorted(potential_loops, key=lambda x: x['buildings_secured'], reverse=True)[:3]


def add_loops_to_network(main_network, potential_loops, pipe_loads):
    """Fügt ausgewählte Ringleitungen zum Netz hinzu"""
    loops_added = set()

    for loop in potential_loops:
        points = loop['points']

        # Prüfe ob diese Verbindung bereits existiert
        if points not in loops_added and (points[1], points[0]) not in loops_added:
            # Füge neue Verbindung hinzu
            main_network.add_edge(points[0], points[1])

            # Dimensioniere neue Leitung basierend auf der Hälfte der kritischen Last
            pipe_loads[tuple(sorted(points))] = loop['load'] * 0.5

            loops_added.add(points)

            # Begrenze die Anzahl der Schleifen
            if len(loops_added) >= 3:  # Maximal 3 neue Schleifen
                break

    return main_network, pipe_loads


def verify_network_connectivity(main_network, buildings):
    if not nx.is_connected(main_network):
        components = list(nx.connected_components(main_network))
        print(f"Network has {len(components)} disconnected components")
        return False

    # Check if all buildings are connected
    for idx, building in buildings.iterrows():
        building_coords = (building.geometry.x, building.geometry.y)
        nearest_node = min(main_network.nodes(),
                           key=lambda n: Point(n).distance(Point(building_coords)))
        if not nx.has_path(main_network, nearest_node, min(main_network.nodes())):
            print(f"Building {building.building_id} is disconnected")
            return False
    return True


def project_point_to_line(point_coords, line_coords):
    """
    Projiziert einen Punkt auf eine Linie und gibt den nächstgelegenen Punkt zurück.
    Behandelt Koordinatenformate und Rundungsfehler robust.
    """
    try:
        # Stelle sicher, dass wir mit validen Geometrien arbeiten
        point = Point(point_coords)
        line = LineString(line_coords)

        # Prüfe ob die Geometrien valid sind
        if not point.is_valid or not line.is_valid:
            return None

        # Finde den nächsten Punkt auf der Linie
        projected_point = line.interpolate(line.project(point))

        # Prüfe ob das Ergebnis valid ist
        if not projected_point.is_valid:
            return None

        return projected_point

    except (ValueError, AttributeError) as e:
        print(f"Fehler bei der Punktprojektion: {e}")
        return None


def create_pandapipes_network(main_network, pipe_loads, buildings, feeding_point, building_json):
    net = pp.create_empty_network(fluid="lgas")
    pp.create_fluid_from_lib(net, "lgas", overwrite=True)

    node_mapping = {}
    feed_height = 71.9

    # Hauptnetzknoten
    for node in main_network.nodes():
        junction_idx = pp.create_junction(
            net,
            pn_bar=0.05,
            tfluid_k=288.15,
            height_m=feed_height,
            geodata=(node[0], node[1])
        )
        node_mapping[node] = junction_idx

    # Einspeisepunkt
    feed_coords = (feeding_point.geometry.iloc[0].x, feeding_point.geometry.iloc[0].y)
    feed_node = min(node_mapping.keys(),
                    key=lambda n: Point(n).distance(Point(feed_coords)))
    feed_idx = node_mapping[feed_node]

    pp.create_ext_grid(
        net,
        junction=feed_idx,
        p_bar=0.1,
        t_k=288.15,
        mdot_kg_per_s=0.228
    )

    # Hauptleitungen
    min_diameter = 0.080
    min_length = 1.0

    for edge, load in pipe_loads.items():
        from_node = node_mapping[edge[0]]
        to_node = node_mapping[edge[1]]

        path_length = get_pipe_length(
            (edge[0][1], edge[0][0]),
            (edge[1][1], edge[1][0])
        )
        length = max(path_length, min_length)
        diameter = max(determine_pipe_diameter(load) / 1000, min_diameter)

        pp.create_pipe_from_parameters(
            net,
            from_junction=from_node,
            to_junction=to_node,
            length_km=length / 1000,
            diameter_m=diameter,
            k_mm=0.1,
            sections=1
        )

    # Hausanschlüsse
    min_mass_flow = 1e-4

    for idx, building in buildings.iterrows():
        building_id = building.building_id
        building_data = building_json[building_id]
        building_height = building_data['Gebaeudeteile'][0]['Koordinaten'][0]['height']

        building_junction = pp.create_junction(
            net,
            pn_bar=0.023,
            tfluid_k=288.15,
            height_m=building_height,
            geodata=(building.geometry.x, building.geometry.y)
        )

        # Finde nächsten Hauptnetzknoten
        nearest_node = min(node_mapping.keys(),
                           key=lambda n: Point(n).distance(Point(building.geometry.x, building.geometry.y)))

        if isinstance(nearest_node, tuple):
            main_junction = node_mapping[nearest_node]
        else:
            main_junction = node_mapping[Point(nearest_node)]

        # Berechne Hausanschlusslänge
        connection_length = get_pipe_length(
            (building.geometry.y, building.geometry.x),
            (nearest_node[1], nearest_node[0])
        )
        connection_length = max(connection_length, min_length)

        mass_flow = max(building.max_heating_load / (40000 * 1000), min_mass_flow)

        # Dimensioniere Hausanschluss
        if connection_length > 80:
            house_connection_diameter = 0.040
        elif connection_length > 50 or mass_flow > 0.0005:
            house_connection_diameter = 0.032
        else:
            house_connection_diameter = 0.025

        # Direkte Verbindung: Hauptnetz zu Gebäude
        pp.create_pipe_from_parameters(
            net,
            from_junction=main_junction,
            to_junction=building_junction,
            length_km=connection_length / 1000,
            diameter_m=house_connection_diameter,
            k_mm=0.1,
            sections=1
        )

        # Verbraucher
        pp.create_sink(
            net,
            junction=building_junction,
            mdot_kg_per_s=mass_flow,
            name=f"Building_{building_id}"
        )

    return net


def run_pandapipes_calculation(net):
    try:
        pp.pipeflow(
            net,
            stop_condition="tol",
            iter=1000,
            tol=1e-4,
            friction_model="nikuradse",
            mode="hydraulics",
            nonlinear_method="automatic",
            init_option="flat",
            alpha=0.5,
            reload_lookups=True
        )

        velocities = abs(net.res_pipe.v_mean_m_per_s)
        pressure_drops = abs(net.res_pipe.p_from_bar - net.res_pipe.p_to_bar)
        reynolds = abs(net.res_pipe.reynolds)

        # Basic network statistics
        total_consumption = net.sink['mdot_kg_per_s'].sum()
        total_feed = net.res_ext_grid['mdot_kg_per_s'].sum()

        print("\nEingangsdaten:")
        print("Anzahl Knoten:", len(net.junction))
        print("Anzahl Rohre:", len(net.pipe))
        print("Anzahl Verbraucher:", len(net.sink))
        print("Einspeisedruck:", net.ext_grid.p_bar.values[0], "bar")

        print("\nNetzwerkanalyse:")
        print(f"Minimale Fließgeschwindigkeit: {velocities.min():.2f} m/s")
        print(f"Maximale Fließgeschwindigkeit: {velocities.max():.2f} m/s")
        print(f"Durchschnittliche Fließgeschwindigkeit: {velocities.mean():.2f} m/s")
        print(f"Minimaler Druck: {net.res_junction.p_bar.min():.2f} bar")
        print(f"Maximaler Druck: {net.res_junction.p_bar.max():.2f} bar")
        print(f"Maximaler Druckverlust: {pressure_drops.max():.2f} bar")
        print(f"Durchschnittlicher Druckverlust: {pressure_drops.mean():.2f} bar")
        print(f"Maximale Reynolds-Zahl: {reynolds.max():.0f}")

        print("\nKritische Rohre (Ausgangsdruck < 0.018 bar):")
        critical_pipes = net.res_pipe[net.res_pipe.p_to_bar < 0.018]
        for idx, pipe in critical_pipes.iterrows():
            print(f"\nRohr {idx}:")
            print(f"Durchmesser: DN{net.pipe.diameter_m[idx] * 1000:.0f}")
            print(f"Länge: {net.pipe.length_km[idx] * 1000:.1f}m")
            print(f"Eingangsdruck: {pipe.p_from_bar:.3f} bar")
            print(f"Ausgangsdruck: {pipe.p_to_bar:.3f} bar")
            print(f"Fließgeschwindigkeit: {pipe.v_mean_m_per_s:.2f} m/s")

        print(f"\nGasflüsse:")
        print(f"Gesamteinspeisung: {total_feed:.3f} kg/s")
        print(f"Gesamtverbrauch: {total_consumption:.3f} kg/s")
        # Debug Rohrdurchmesser
        diameters = net.pipe.diameter_m.values * 1000  # Umrechnung in mm
        unique_diameters = np.unique(diameters)
        print("\nRohrdurchmesser-Verteilung:")
        for d in sorted(unique_diameters):
            count = len(diameters[diameters == d])
            print(f"DN {d:.0f}mm: {count} Rohre")

        print("\nRohrlängen:")
        lengths = net.pipe.length_km.values * 1000  # Umrechnung in Meter
        print(f"Minimale Länge: {lengths.min():.1f}m")
        print(f"Maximale Länge: {lengths.max():.1f}m")
        print(f"Durchschnittliche Länge: {lengths.mean():.1f}m")

        # Verteilung der Längen nach Durchmesser
        print("\nDurchschnittliche Längen nach Durchmesser:")
        for d in sorted(np.unique(net.pipe.diameter_m.values * 1000)):
            mask = net.pipe.diameter_m.values * 1000 == d
            avg_length = lengths[mask].mean()
            print(f"DN {d:.0f}mm: {avg_length:.1f}m")
        """
        print("\nDetaillierte Netzanalyse:")
        print("\nDrücke an Rohren:")
        for idx, row in net.res_pipe.iterrows():
            print(f"Rohr {idx}: Eingang {row.p_from_bar:.3f} bar, Ausgang {row.p_to_bar:.3f} bar")
        """
        """
        print("\n=== BASIC NETWORK CONDITIONS ===")
        print(f"Feed pressure: {net.ext_grid.p_bar.values[0]:.3f} bar")
        print(f"Feed mass flow: {net.ext_grid.mdot_kg_per_s.values[0]:.3f} kg/s")
        print(f"Node pressure setpoints: {sorted(net.junction.pn_bar.unique())} bar")

        # Analyze main network flow patterns by diameter
        print("\n=== MAIN NETWORK FLOW ANALYSIS BY DIAMETER ===")
        diameter_stats = {}
        for d in sorted(set(net.pipe.diameter_m)):
            if d >= 0.080:  # Only main pipes
                pipes = net.pipe[net.pipe.diameter_m == d]
                flows = net.res_pipe.loc[pipes.index, 'v_mean_m_per_s']
                diameter_stats[d] = {
                    'count': len(pipes),
                    'positive_flows': sum(flows > 0),
                    'negative_flows': sum(flows < 0),
                    'zero_flows': sum(abs(flows) < 0.01),
                    'min_velocity': flows.min(),
                    'max_velocity': flows.max(),
                    'mean_velocity': flows.mean(),
                    'pipes_with_negative_flow': pipes.index[flows < 0].tolist()
                }

                print(f"\nDN{int(d * 1000)} Statistics:")
                print(f"Total pipes: {diameter_stats[d]['count']}")
                print(f"Positive flows: {diameter_stats[d]['positive_flows']}")
                print(f"Negative flows: {diameter_stats[d]['negative_flows']}")
                print(f"Near-zero flows: {diameter_stats[d]['zero_flows']}")
                print(
                    f"Velocity range: {diameter_stats[d]['min_velocity']:.3f} to {diameter_stats[d]['max_velocity']:.3f} m/s")
                print(f"Mean velocity: {diameter_stats[d]['mean_velocity']:.3f} m/s")
        
        # Detailed ring structure analysis
        print("\n=== RING STRUCTURE ANALYSIS ===")
        # Identify potential rings by finding pipes that form closed loops
        G = nx.Graph()
        for idx, pipe in net.pipe.iterrows():
            if pipe.diameter_m >= 0.080:  # Only main pipes
                G.add_edge(pipe.from_junction, pipe.to_junction,
                           pipe_idx=idx,
                           diameter=pipe.diameter_m)

        # Find cycles in the graph
        cycles = nx.cycle_basis(G)
        print(f"\nFound {len(cycles)} potential ring structures")

        # Analyze each ring
        for i, cycle in enumerate(cycles):
            print(f"\nRing {i + 1} Analysis:")
            # Get all pipes in this ring
            ring_pipes = []
            for j in range(len(cycle)):
                from_node = cycle[j]
                to_node = cycle[(j + 1) % len(cycle)]
                edge_data = G.get_edge_data(from_node, to_node)
                if edge_data:
                    ring_pipes.append(edge_data['pipe_idx'])

            print(f"Number of pipes in ring: {len(ring_pipes)}")

            # Analyze flow patterns in the ring
            flow_patterns = []
            pressures = []
            for pipe_idx in ring_pipes:
                flow = net.res_pipe.loc[pipe_idx, 'v_mean_m_per_s']
                p_from = net.res_pipe.loc[pipe_idx, 'p_from_bar']
                p_to = net.res_pipe.loc[pipe_idx, 'p_to_bar']
                dp = p_from - p_to
                diameter = net.pipe.loc[pipe_idx, 'diameter_m']

                flow_patterns.append({
                    'pipe_idx': pipe_idx,
                    'diameter': f"DN{int(diameter * 1000)}",
                    'flow': flow,
                    'pressure_drop': dp
                })
                pressures.extend([p_from, p_to])

            # Print detailed ring analysis
            print("\nFlow patterns in ring:")
            for pattern in flow_patterns:
                print(f"Pipe {pattern['pipe_idx']} ({pattern['diameter']}):")
                print(f"  Flow velocity: {pattern['flow']:.3f} m/s")
                print(f"  Pressure drop: {pattern['pressure_drop']:.6f} bar")

            print(f"\nRing pressure characteristics:")
            print(f"  Maximum pressure: {max(pressures):.3f} bar")
            print(f"  Minimum pressure: {min(pressures):.3f} bar")
            print(f"  Pressure difference: {max(pressures) - min(pressures):.3f} bar")
            print(f"  Number of flow reversals: {sum(1 for p in flow_patterns if p['flow'] < 0)}")

        # Overall pressure distribution
        print("\n=== OVERALL PRESSURE DISTRIBUTION ===")
        print(f"Network minimum pressure: {net.res_junction.p_bar.min():.3f} bar")
        print(f"Network maximum pressure: {net.res_junction.p_bar.max():.3f} bar")
        print(f"Network pressure range: {net.res_junction.p_bar.max() - net.res_junction.p_bar.min():.3f} bar")

        # Mass balance verification
        print("\n=== MASS BALANCE VERIFICATION ===")
        print(f"Total feed in: {abs(net.res_ext_grid.mdot_kg_per_s.sum()):.6f} kg/s")
        print(f"Total consumption: {abs(net.sink.mdot_kg_per_s.sum()):.6f} kg/s")
        print(
            f"Balance difference: {abs(net.res_ext_grid.mdot_kg_per_s.sum()) - abs(net.sink.mdot_kg_per_s.sum()):.6f} kg/s")
        """

        return True, net

    except Exception as e:
        print(f"Calculation error: {e}")
        return False, net


def analyze_house_connections(net):
    print("\nHausanschluss-Analyse:")

    # Zähle Verbindungen pro Gebäude
    building_connections = {}
    for idx, sink in net.sink.iterrows():
        building_id = sink['name'].split('_')[1]  # Building_ID -> ID

        # Finde alle Rohre die zum Sink führen
        connected_pipes = net.pipe[
            (net.pipe.to_junction == sink.junction) |
            (net.pipe.from_junction == sink.junction)
            ]

        # Speichere Anzahl und Details der Verbindungen
        building_connections[building_id] = {
            'pipe_count': len(connected_pipes),
            'pipe_details': []
        }

        for _, pipe in connected_pipes.iterrows():
            building_connections[building_id]['pipe_details'].append({
                'diameter': pipe.diameter_m * 1000,
                'length': pipe.length_km * 1000
            })

    # Statistik
    connections_per_building = {}
    for building_id, data in building_connections.items():
        count = data['pipe_count']
        connections_per_building[count] = connections_per_building.get(count, 0) + 1

        if count > 1:
            print(f"\nGebäude {building_id} hat {count} Verbindungen:")
            for pipe in data['pipe_details']:
                print(f"- DN{int(pipe['diameter'])} mit Länge {pipe['length']:.1f}m")

    print("\nVerbindungsstatistik:")
    for count, num_buildings in sorted(connections_per_building.items()):
        print(f"{num_buildings} Gebäude haben {count} Verbindung(en)")


def analyze_pipe_topology(net):
    print("\nDetaillierte Rohranalyse:")

    # DN25 Rohre analysieren
    dn25_pipes = net.pipe[net.pipe.diameter_m == 0.025]

    # Verbindungstypen kategorisieren
    connection_types = {
        'building_to_main': 0,  # Verbindung Gebäude zu Hauptleitung
        'building_to_connection': 0,  # Verbindung Gebäude zu Anschlusspunkt
        'connection_to_main': 0  # Verbindung Anschlusspunkt zu Hauptleitung
    }

    # Knoten nach Typ kategorisieren
    sink_junctions = set(net.sink.junction.values)
    main_junctions = set()
    connection_junctions = set()

    for idx, pipe in net.pipe.iterrows():
        if pipe.diameter_m >= 0.080:  # Hauptleitungen
            main_junctions.add(pipe.from_junction)
            main_junctions.add(pipe.to_junction)

    # DN25 Verbindungen analysieren
    for idx, pipe in dn25_pipes.iterrows():
        from_j = pipe.from_junction
        to_j = pipe.to_junction

        if to_j in sink_junctions:
            if from_j in main_junctions:
                connection_types['building_to_main'] += 1
            else:
                connection_types['building_to_connection'] += 1
                connection_junctions.add(from_j)
        elif from_j in sink_junctions:
            if to_j in main_junctions:
                connection_types['building_to_main'] += 1
            else:
                connection_types['building_to_connection'] += 1
                connection_junctions.add(to_j)
        elif from_j in connection_junctions or to_j in connection_junctions:
            connection_types['connection_to_main'] += 1

    print("\nDN25 Rohrverbindungen:")
    for type_name, count in connection_types.items():
        print(f"{type_name}: {count}")

    print(f"\nGesamtzahl DN25 Rohre: {len(dn25_pipes)}")
    print(f"Anzahl Anschlussknoten: {len(connection_junctions)}")

def visualize_main_network(filtered_streets, buildings, feeding_point, main_network, edge_usage):
    fig, ax = plt.subplots(figsize=(12, 8))

    filtered_streets.plot(ax=ax, color='lightgray', linewidth=1, label='Straßen')
    buildings.plot(ax=ax, color='blue', alpha=0.3, label='Gebäude')
    feeding_point.plot(ax=ax, color='red', markersize=100, marker='*', label='Einspeisepunkt')

    max_usage = max(edge_usage.values())
    for edge, count in edge_usage.items():
        linewidth = 1 + (count / max_usage) * 4
        plt.plot([edge[0][0], edge[1][0]],
                 [edge[0][1], edge[1][1]],
                 'red',
                 linewidth=linewidth,
                 alpha=0.7)

    plt.title('Gasnetz Hauptverteilung')
    plt.legend(loc='center left', bbox_to_anchor=(1, 0.5))
    plt.savefig('gasnetz_hauptverteilung.png', bbox_inches='tight', dpi=300)
    plt.close()


def visualize_dimensioned_network(net, filtered_streets, buildings, feeding_point, pipe_loads, potential_loops=None):
    fig, ax = plt.subplots(figsize=(12, 8))

    # Straßen und Gebäude als Hintergrund
    filtered_streets.plot(ax=ax, color='lightgray', linewidth=1, label='Straßen')
    buildings.plot(ax=ax, color='blue', alpha=0.3, label='Gebäude')
    feeding_point.plot(ax=ax, color='red', markersize=100, marker='*', label='Einspeisepunkt')

    # Blaue Farbabstufungen für verschiedene Durchmesser - weniger starke Abstufung
    diameter_colors = {
        25: '#1565C0',  # Dunkelblau für alle mit leichten Abstufungen
        32: '#1666C0',
        40: '#1767C0',
        65: '#1868C0',
        80: '#1969C0',
        100: '#1A6AC0',
        150: '#1B6BC0',
        200: '#1C6CC0',
        250: '#1D6DC0',
        300: '#1E6EC0'
    }

    # Basis-Linienbreite und deutlicherer Unterschied
    base_width = 0.5
    max_width_diff = 3.0  # erhöht für deutlichere Unterschiede

    unique_diameters = set()

    # Hauptleitungen zeichnen
    for edge, load in pipe_loads.items():
        diameter_mm = determine_pipe_diameter(load)

        # Deutlichere Breitenunterschiede
        width_factor = (diameter_mm - 25) / (300 - 25)  # Normalisiert auf 0-1
        linewidth = base_width + (width_factor * max_width_diff)

        color = diameter_colors.get(diameter_mm, '#1E6EC0')

        plt.plot([edge[0][0], edge[1][0]],
                 [edge[0][1], edge[1][1]],
                 color=color,
                 linewidth=linewidth,
                 alpha=0.8)  # Erhöhte Sichtbarkeit

        unique_diameters.add(diameter_mm)

    # Ringleitungen in Grün zeichnen
    if potential_loops:
        for loop in potential_loops:
            points = loop['points']
            plt.plot([points[0][0], points[1][0]],
                     [points[0][1], points[1][1]],
                     color='green',
                     linewidth=2,
                     linestyle='-',
                     alpha=0.8,
                     zorder=3)  # Über den normalen Leitungen

    # Hausanschlüsse zeichnen - aus dem pandapipes Netzwerk
    if net is not None:
        for idx, sink in net.sink.iterrows():
            sink_junction = sink.junction
            connected_pipes = net.pipe[
                (net.pipe.to_junction == sink_junction) |
                (net.pipe.from_junction == sink_junction)
                ]

            for _, pipe in connected_pipes.iterrows():
                if pipe.from_junction == sink_junction:
                    from_coords = net.junction_geodata.loc[pipe.from_junction]
                    to_coords = net.junction_geodata.loc[pipe.to_junction]
                else:
                    from_coords = net.junction_geodata.loc[pipe.to_junction]
                    to_coords = net.junction_geodata.loc[pipe.from_junction]

                diameter_mm = int(pipe.diameter_m * 1000)
                width_factor = (diameter_mm - 25) / (300 - 25)
                linewidth = base_width + (width_factor * max_width_diff)

                plt.plot([from_coords.x, to_coords.x],
                         [from_coords.y, to_coords.y],
                         color=diameter_colors.get(diameter_mm, '#1E6EC0'),
                         linewidth=linewidth,
                         alpha=0.8)

    # Legende mit Durchmessern und Ringleitungen
    handles = []

    # Durchmesser-Legende
    for d in sorted(unique_diameters):
        width_factor = (d - 25) / (300 - 25)
        linewidth = base_width + (width_factor * max_width_diff)
        handles.append(plt.Line2D([], [],
                                  color=diameter_colors.get(d, '#1E6EC0'),
                                  linewidth=linewidth,
                                  alpha=0.8,
                                  label=f'DN {d}'))

    # Ringleitungen-Legende
    if potential_loops:
        handles.append(plt.Line2D([], [],
                                  color='green',
                                  linewidth=2,
                                  alpha=0.8,
                                  label='Ringleitung'))

    # Straßen und Gebäude Legende
    handles.append(plt.Line2D([], [], color='lightgray', linewidth=1, label='Straßen'))
    handles.append(plt.Line2D([], [], color='blue', marker='o', alpha=0.3, label='Gebäude'))
    handles.append(plt.Line2D([], [], color='red', marker='*', markersize=10, label='Einspeisepunkt'))

    plt.legend(handles=handles, loc='center left', bbox_to_anchor=(1, 0.5))
    plt.title('Gasnetz mit dimensionierten Leitungen')
    plt.savefig('gasnetz_komplett.png', bbox_inches='tight', dpi=300)
    plt.close()


def export_for_godot(net, pipe_loads, potential_loops=None, output_file="network_data.json"):
    """
    Exportiert das Netzwerk in einem godot-optimierten Format.

    Struktur:
    - Koordinaten werden für direkte Verwendung in Godot normalisiert
    - Separate Arrays für effizientes Rendering
    - Minimaler Speicherbedarf durch Fokus auf Visualisierungsdaten
    """
    # Koordinaten normalisieren
    coords = net.junction_geodata[['x', 'y']].values
    x_min, y_min = coords.min(axis=0)
    x_max, y_max = coords.max(axis=0)

    # Normalisierungsfunktion für Koordinaten
    def normalize_coords(x, y):
        return {
            "x": float((x - x_min) / (x_max - x_min)),
            "y": float((y - y_min) / (y_max - y_min))
        }

    # Basisdaten für die Visualisierung
    network_data = {
        "metadata": {
            "original_bounds": {
                "x_min": float(x_min),
                "x_max": float(x_max),
                "y_min": float(y_min),
                "y_max": float(y_max)
            }
        },
        "pipes": [],
        "feed_points": [],
        "rings": []
    }

    # Rohre exportieren
    for idx, pipe in net.pipe.iterrows():
        from_coords = net.junction_geodata.loc[pipe.from_junction]
        to_coords = net.junction_geodata.loc[pipe.to_junction]

        # Finde zugehörige Last
        pipe_key = tuple(sorted([
            (from_coords.x, from_coords.y),
            (to_coords.x, to_coords.y)
        ]))
        load = pipe_loads.get(pipe_key, 0)

        pipe_data = {
            "from": normalize_coords(from_coords.x, from_coords.y),
            "to": normalize_coords(to_coords.x, to_coords.y),
            "diameter": float(pipe.diameter_m),
            "load": float(load)
        }

        # Füge Simulationsergebnisse hinzu, falls vorhanden
        if hasattr(net, 'res_pipe'):
            pipe_data.update({
                "pressure_from": float(net.res_pipe.p_from_bar[idx]),
                "pressure_to": float(net.res_pipe.p_to_bar[idx]),
                "velocity": float(net.res_pipe.v_mean_m_per_s[idx])
            })

        network_data["pipes"].append(pipe_data)

    # Einspeisepunkte
    for idx, grid in net.ext_grid.iterrows():
        junction_coords = net.junction_geodata.loc[grid.junction]
        feed_point = {
            "position": normalize_coords(junction_coords.x, junction_coords.y),
            "pressure": float(grid.p_bar)
        }
        network_data["feed_points"].append(feed_point)

    # Ringleitungen (falls vorhanden)
    if potential_loops:
        for loop in potential_loops:
            ring_data = {
                "from": normalize_coords(loop['points'][0][0], loop['points'][0][1]),
                "to": normalize_coords(loop['points'][1][0], loop['points'][1][1]),
                "load": float(loop['load'])
            }
            network_data["rings"].append(ring_data)

    # Speichere als JSON
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(network_data, f, indent=2)

    print(f"Netzwerk erfolgreich für Godot exportiert nach: {output_file}")
    print(f"Anzahl Rohre: {len(network_data['pipes'])}")
    print(f"Anzahl Einspeisepunkte: {len(network_data['feed_points'])}")
    print(f"Anzahl Ringleitungen: {len(network_data['rings'])}")

if __name__ == "__main__":
    # 1. Daten laden
    filtered_streets, buildings, feeding_point = load_and_filter_data(
        'branitzer_siedlung.osm',
        'output_branitzer_siedlungV11.json',
        'ergebnis_momentane_heizleistungV3.json'
    )

    # Lade Gebäudedaten für Höheninformationen
    with open('output_branitzer_siedlungV11.json', 'r', encoding='utf-8') as f:
        building_json = json.load(f)

    # 2. Anschlusspunkte für alle Gebäude bestimmen
    print("Bestimme Hausanschlusspunkte...")
    connection_points = []
    for _, building in buildings.iterrows():
        connection_point = find_connection_point(building, filtered_streets)
        connection_points.append(connection_point)
    print(f"- {len([p for p in connection_points if p is not None])} Anschlusspunkte gefunden")
    print(f"- {len([p for p in connection_points if p is None])} Gebäude ohne Anschlusspunkt")

    # 3. Erweiterten Straßengraph erstellen (mit Anschlusspunkten)
    print("Erstelle erweiterten Straßengraph...")
    street_graph = create_street_graph(filtered_streets, connection_points)
    print(f"- Graph enthält {street_graph.number_of_nodes()} Knoten und {street_graph.number_of_edges()} Kanten")

    # 4. Pfade zum Einspeisepunkt finden
    print("Berechne kürzeste Pfade...")
    paths = find_shortest_paths(street_graph, filtered_streets, buildings, feeding_point)
    print(f"- {len(paths)} Pfade gefunden")

    # 5. Hauptnetz erstellen
    print("Erstelle Hauptnetz...")
    main_network, edge_usage = create_main_network(street_graph, paths)
    print(f"- Hauptnetz enthält {main_network.number_of_nodes()} Knoten und {main_network.number_of_edges()} Kanten")

    # 6. Dimensionierung
    print("Berechne Leitungslasten...")
    pipe_loads = calculate_pipe_loads(main_network, paths, buildings)
    print(f"- {len(pipe_loads)} Leitungen dimensioniert")

    # 7. Erste Visualisierung des Grundnetzes
    visualize_dimensioned_network(None, filtered_streets, buildings, feeding_point, pipe_loads)
    #"""
    # 8. Ringe hinzufügen
    critical_points = identify_critical_endpoints(main_network, pipe_loads, buildings)
    potential_loops = find_potential_loops(main_network, critical_points, filtered_streets, pipe_loads)

    print(f"\nKritische Endpunkte gefunden: {len(critical_points)}")
    print("Details der wichtigsten Endpunkte:")
    for cp in critical_points[:5]:
        print(f"- {cp['buildings']} Gebäude, Last: {cp['load']:.0f}")

    print(f"\nMögliche Ringe gefunden: {len(potential_loops)}")
    print("Details der Ringverbindungen:")
    for loop in potential_loops:
        print(f"- Sichert {loop['buildings_secured']} Gebäude, Länge: {loop['distance']:.1f}m")

    print("Füge Ringleitungen hinzu...")
    main_network, pipe_loads = add_loops_to_network(main_network, potential_loops, pipe_loads)
    #"""
    # 9. Aktualisierte Visualisierung mit Ringen
    visualize_dimensioned_network(None, filtered_streets, buildings, feeding_point, pipe_loads, potential_loops)

    # 10. Netzwerk-Konnektivität prüfen
    print("Prüfe Netzwerk-Konnektivität...")
    if not verify_network_connectivity(main_network, buildings):
        print("Fehler: Netzwerk ist nicht vollständig verbunden!")
        sys.exit(1)
    print("- Netzwerk ist vollständig verbunden")

    # 11. pandapipes Netzwerk erstellen
    print("Erstelle pandapipes Netzwerk...")
    # Übergebe building_json an create_pandapipes_network
    pp_network = create_pandapipes_network(main_network, pipe_loads, buildings, feeding_point, building_json)

    # 12. Simulation durchführen
    print("Führe Netzberechnung durch...")
    success, pp_network = run_pandapipes_calculation(pp_network)

    if success:
        print("Netzwerkberechnung erfolgreich durchgeführt!")
        # Finale Visualisierung des berechneten Netzes
        visualize_dimensioned_network(pp_network, filtered_streets, buildings, feeding_point, pipe_loads, potential_loops)
        # Zusätzliche ANalyse
        analyze_house_connections(pp_network)
        analyze_pipe_topology(pp_network)
        export_for_godot(pp_network, pipe_loads, potential_loops)
    else:
        print("Fehler bei der Netzwerkberechnung!")