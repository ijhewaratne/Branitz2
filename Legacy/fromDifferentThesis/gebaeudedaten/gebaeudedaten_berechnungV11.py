import xml.etree.ElementTree as ET
import json
import math
from pyproj import Transformer
from tqdm import tqdm


EXCLUDED_BUILDINGS = {
    "Garage",
    "Schuppen",
    "Stall",
    "Werkstatt",
    "Treibhaus, Gewächshaus",
    "Land- und forstwirtschaftliches Betriebsgebäude",
    "Gebäude zur Freizeitgestaltung",
    "Gebäude zum Parken",
    "Gebäude für soziale Zwecke",
    "Badegebäude",
    "Hallenbad",
    "Umformer",
    "Lagerhalle, Lagerschuppen, Lagerhaus"
}

# Liste der Funktionen die immer Hauptgebäude sein müssen wenn mit Wohnhaus verbunden
MUST_BE_MAIN_BUILDINGS = {
    "Gebäude für soziale Zwecke",
    "Hallenbad",
    "Geschäftsgebäude",
    "Gebäude für Vorratshaltung",
    "Wohngebäude mit Handel und Dienstleistungen",
    "Gebäude zum Parken",
    "Gebäude für Wirtschaft oder Gewerbe",
    "Land- und forstwirtschaftliches Betriebsgebäude",
    "Werkstatt",
    "Hotel, Motel, Pension",
    "Gebäude zur Freizeitgestaltung",
    "Gebäude für Handel und Dienstleistungen",
    "Lagerhalle, Lagerschuppen, Lagerhaus"
}

def extract_coordinates(posList_text, srsDimension):
    """
    Extrahiert Koordinaten aus einem posList Text basierend auf der Dimension
    """
    coords = list(map(float, posList_text.strip().split()))
    if srsDimension == '3':
        coords_xyz = []
        for i in range(0, len(coords), 3):
            x, y, z = coords[i:i + 3]
            coords_xyz.append((x, y, z))
        return coords_xyz
    elif srsDimension == '2':
        coords_xy = []
        for i in range(0, len(coords), 2):
            x, y = coords[i:i + 2]
            coords_xy.append((x, y))
        return coords_xy
    else:
        print(f"Unerwartete srsDimension: {srsDimension}")
        return []


def create_coordinate_transformer():
    """
    Erstellt einen Transformer für die Konvertierung von ETRS89/UTM33 nach WGS84
    """
    return Transformer.from_crs(
        "EPSG:25833",  # ETRS89/UTM zone 33N
        "EPSG:4326",  # WGS84
        always_xy=True
    )


def extract_building_coordinates(building, ns):
    """
    Extrahiert die Koordinaten aus dem lod2TerrainIntersection Element
    """
    coordinates = []
    terrain_intersection = building.find('.//bldg:lod2TerrainIntersection', ns)

    if terrain_intersection is not None:
        for line_string in terrain_intersection.findall('.//gml:LineString', ns):
            pos_list = line_string.find('gml:posList', ns)
            if pos_list is not None:
                coords = list(map(float, pos_list.text.strip().split()))
                for i in range(0, len(coords), 3):
                    coordinates.append((coords[i], coords[i + 1], coords[i + 2]))

    return coordinates


def convert_coordinates_to_wgs84(coordinates, transformer):
    """
    Konvertiert eine Liste von Koordinaten von ETRS89/UTM33 nach WGS84
    """
    wgs84_coords = []
    for x, y, z in coordinates:
        lon, lat = transformer.transform(x, y)
        wgs84_coords.append({
            "latitude": round(lat, 7),
            "longitude": round(lon, 7),
            "height": round(z, 3)
        })
    return wgs84_coords


def should_merge_buildings(current_function, to_merge_function=None, current_id=None, to_merge_id=None,
                           building_to_flurid=None):
    """
    Überprüft, ob zwei Gebäude basierend auf ihren Funktionen und FLURIDs verbunden werden sollen.
    """
    # Wenn keine zu verbindende Funktion angegeben ist (Einzelprüfung)
    if to_merge_function is None:
        return current_function not in EXCLUDED_BUILDINGS

    # Wenn eines der Gebäude ausgeschlossen ist, keine Verbindung erlauben
    if current_function in EXCLUDED_BUILDINGS or to_merge_function in EXCLUDED_BUILDINGS:
        return False

    # Wenn das Hauptgebäude "Nach Quellenlage nicht zu spezifizieren" ist,
    # darf es keine anderen Gebäude als Teile haben
    if current_function == "Nach Quellenlage nicht zu spezifizieren":
        return False

    # "Nach Quellenlage nicht zu spezifizieren" darf als Teil verbunden werden
    if to_merge_function == "Nach Quellenlage nicht zu spezifizieren":
        return True

    # Spezielle Regel für Wohngebäude
    is_current_residential = current_function in ["Wohnhaus", "Wohngebäude"]
    is_to_merge_residential = to_merge_function in ["Wohnhaus", "Wohngebäude"]

    # Wenn beide Wohngebäude sind, prüfe die FLURID
    if is_current_residential and is_to_merge_residential:
        # Wenn keine FLURID-Informationen verfügbar sind, nicht verbinden
        if not building_to_flurid or current_id not in building_to_flurid or to_merge_id not in building_to_flurid:
            return False

        # Nur verbinden wenn sie die gleiche FLURID haben
        return building_to_flurid[current_id] == building_to_flurid[to_merge_id]

    # Wenn das zu verbindende Gebäude ein Wohngebäude ist, prüfe ob das Hauptgebäude
    # ein gemischtes Wohngebäude ist
    if is_to_merge_residential:
        return current_function in [
            "Wohngebäude mit Handel und Dienstleistungen",
            "Wohngebäude mit Gewerbe und Industrie"
        ]

    # Standardfall: Erlaube Verbindung
    return True


def get_building_function(building, ns, gebaeudefunktion_mapping):
    """
    Extrahiert die Gebäudefunktion aus einem Gebäude
    """
    function_elements = building.findall('bldg:function', ns)
    for elem in function_elements:
        function_code = elem.text.split('_')[-1]
        return gebaeudefunktion_mapping.get(function_code, 'Unbekannt')
    return 'Unbekannt'


def calculate_building_volume(building, ns):
    """
    Berechnet das Gesamtvolumen eines Gebäudes
    """
    # Berechne Grundfläche und Höhe
    floor_area = calculate_floor_area(building, ns)
    height_element = building.find('.//bldg:measuredHeight', ns)
    height = float(height_element.text) if height_element is not None else 0

    # Berechne Volumen
    volume = floor_area * height
    return volume


def determine_main_building(building1, building2, building1_id, building2_id, ns, gebaeudefunktion_mapping,
                            building_to_flurid):
    """
    Bestimmt das Hauptgebäude basierend auf den Funktionen und FLURID
    """
    function1 = get_building_function(building1, ns, gebaeudefunktion_mapping)
    function2 = get_building_function(building2, ns, gebaeudefunktion_mapping)

    # "Nach Quellenlage nicht zu spezifizieren" wird immer als Gebäudeteil behandelt
    if function1 == "Nach Quellenlage nicht zu spezifizieren":
        return building2_id, building1_id
    elif function2 == "Nach Quellenlage nicht zu spezifizieren":
        return building1_id, building2_id

    # Definiere erlaubte gemischte Wohngebäude
    MIXED_RESIDENTIAL = {
        "Wohngebäude mit Handel und Dienstleistungen",
        "Wohngebäude mit Gewerbe und Industrie"
    }

    # Prüfe auf Wohngebäude-Kombinationen
    is_function1_residential = function1 in ["Wohnhaus", "Wohngebäude"]
    is_function2_residential = function2 in ["Wohnhaus", "Wohngebäude"]

    # Wenn beide Wohngebäude sind, prüfe die FLURID
    if is_function1_residential and is_function2_residential:
        if not building_to_flurid or building1_id not in building_to_flurid or building2_id not in building_to_flurid:
            raise ValueError(f"FLURID-Information fehlt für Wohngebäude {building1_id} oder {building2_id}")

        if building_to_flurid[building1_id] != building_to_flurid[building2_id]:
            raise ValueError(f"Wohngebäude {building1_id} und {building2_id} haben unterschiedliche FLURIDs")

        # Wenn sie die gleiche FLURID haben, entscheide nach Volumen
        volume1 = calculate_building_volume(building1, ns)
        volume2 = calculate_building_volume(building2, ns)
        return (building1_id, building2_id) if volume1 >= volume2 else (building2_id, building1_id)

    # Wenn eines ein Wohngebäude ist, muss das andere ein gemischtes Wohngebäude sein und wird zum Hauptgebäude
    if is_function1_residential and function2 in MIXED_RESIDENTIAL:
        return building2_id, building1_id
    elif is_function2_residential and function1 in MIXED_RESIDENTIAL:
        return building1_id, building2_id

    # Wenn eines der Gebäude in MUST_BE_MAIN_BUILDINGS ist und das andere ein gemischtes Wohngebäude,
    # wird das MUST_BE_MAIN_BUILDING zum Hauptgebäude
    if function1 in MUST_BE_MAIN_BUILDINGS and function2 in MIXED_RESIDENTIAL:
        return building1_id, building2_id
    elif function2 in MUST_BE_MAIN_BUILDINGS and function1 in MIXED_RESIDENTIAL:
        return building2_id, building1_id

    # Wenn keine der speziellen Regeln greift, entscheide nach Volumen
    volume1 = calculate_building_volume(building1, ns)
    volume2 = calculate_building_volume(building2, ns)

    if volume1 >= volume2:
        return building1_id, building2_id
    else:
        return building2_id, building1_id

def validate_building_connections(buildings_data, gebaeudefunktion_mapping):
    """
    Validiert die Gebäudeverbindungen und gibt fehlerhafte Einträge aus
    """
    print("\nValidiere Gebäudeverbindungen...")
    error_count = 0

    for building_id, building_data in buildings_data.items():
        main_function = building_data['Gebaeudefunktion']

        for part in building_data['Gebaeudeteile']:
            part_id = part['GebaeudeteilID']
            if part_id != building_id:  # Nur verbundene Gebäude prüfen
                if part_id in buildings_data:  # Wenn es als eigenständiges Gebäude existiert
                    orig_function = buildings_data[part_id]['Gebaeudefunktion']
                    if not should_merge_buildings(orig_function):
                        error_count += 1
                        print(f"\nFehlerhafte Verbindung gefunden:")
                        print(f"Hauptgebäude {building_id}: {main_function}")
                        print(f"Verbundenes Gebäude {part_id}: {orig_function}")
                        print("Diese Verbindung sollte nicht existieren!")

    if error_count == 0:
        print("Keine fehlerhaften Verbindungen gefunden.")
    else:
        print(f"\nInsgesamt {error_count} fehlerhafte Verbindungen gefunden.")

    return error_count


def check_building_connection(building1_coords, building2_coords, tolerance=0.1):
    """
    Überprüft, ob zwei Gebäude räumlich verbunden sind.
    tolerance: Toleranz in Metern für die Verbindungsprüfung
    """
    min_distance = float('inf')
    closest_coords = None

    for coord1 in building1_coords:
        for coord2 in building2_coords:
            distance = math.sqrt(
                (coord1[0] - coord2[0]) ** 2 +
                (coord1[1] - coord2[1]) ** 2
            )

            if distance < min_distance:
                min_distance = distance
                closest_coords = (coord1, coord2)

            if distance <= tolerance:
                return True, min_distance, closest_coords

    return False, min_distance, closest_coords


def create_spatial_grid(buildings, ns, building_dict, gebaeudefunktion_mapping, grid_size=10):
    """
    Erstellt ein räumliches Grid für die Gebäude.
    """
    grid = {}

    for building in buildings:
        building_id = building.get('{http://www.opengis.net/gml}id')

        # Prüfe Gebäudefunktion
        function = get_building_function(building, ns, gebaeudefunktion_mapping)

        # Wenn die Gebäudefunktion nicht passt, überspringe dieses Gebäude
        if not should_merge_buildings(function):
            continue

        coords = extract_building_coordinates(building, ns)
        if not coords:
            continue

        min_x = min(c[0] for c in coords)
        max_x = max(c[0] for c in coords)
        min_y = min(c[1] for c in coords)
        max_y = max(c[1] for c in coords)

        start_cell_x = int(min_x / grid_size)
        end_cell_x = int(max_x / grid_size) + 1
        start_cell_y = int(min_y / grid_size)
        end_cell_y = int(max_y / grid_size) + 1

        for x in range(start_cell_x, end_cell_x):
            for y in range(start_cell_y, end_cell_y):
                cell_key = (x, y)
                if cell_key not in grid:
                    grid[cell_key] = set()
                grid[cell_key].add(building_id)

    return grid


def get_potential_neighbors(coords, grid, building_id, processed_buildings, grid_size=10):
    """
    Hilfsfunktion zum Ermitteln potentieller Nachbarn eines Gebäudes
    """
    min_x = min(c[0] for c in coords)
    max_x = max(c[0] for c in coords)
    min_y = min(c[1] for c in coords)
    max_y = max(c[1] for c in coords)

    start_cell_x = int(min_x / grid_size)
    end_cell_x = int(max_x / grid_size) + 1
    start_cell_y = int(min_y / grid_size)
    end_cell_y = int(max_y / grid_size) + 1

    potential_neighbors = set()
    for x in range(start_cell_x - 1, end_cell_x + 1):
        for y in range(start_cell_y - 1, end_cell_y + 1):
            if (x, y) in grid:
                potential_neighbors.update(grid[(x, y)])

    potential_neighbors.discard(building_id)
    potential_neighbors.difference_update(processed_buildings)

    return potential_neighbors

def identify_connected_buildings(root, ns, gebaeudefunktion_mapping, building_to_flurid):
    """
    Identifiziert Gebäude, die räumlich verbunden sind
    """
    buildings = root.findall('.//bldg:Building', ns)
    total_buildings = len(buildings)

    print(f"Erstelle räumlichen Index für {total_buildings} Gebäude...")

    building_dict = {building.get('{http://www.opengis.net/gml}id'): building for building in buildings}
    grid = create_spatial_grid(buildings, ns, building_dict, gebaeudefunktion_mapping)

    # Extrahiere Koordinaten einmalig
    print("Extrahiere Koordinaten...")
    building_coords = {}
    for building in tqdm(buildings, desc="Extrahiere Koordinaten", unit="Gebäude"):
        building_id = building.get('{http://www.opengis.net/gml}id')
        coords = extract_building_coordinates(building, ns)
        building_coords[building_id] = coords

    building_connections = {}
    processed_buildings = set()

    print("Prüfe Gebäudeverbindungen...")
    progress_bar = tqdm(total=total_buildings, desc="Prüfe Verbindungen", unit="Gebäude")
    connection_count = 0

    # Erste Durchlauf: Verarbeite alle Gebäude außer "Nach Quellenlage nicht zu spezifizieren"
    for building_id, coords in building_coords.items():
        building = building_dict[building_id]
        current_function = get_building_function(building, ns, gebaeudefunktion_mapping)

        # Überspringe bereits verarbeitete und "Nach Quellenlage nicht zu spezifizieren" Gebäude
        if building_id in processed_buildings or current_function == "Nach Quellenlage nicht zu spezifizieren":
            progress_bar.update(1)
            continue

        # Wenn das Gebäude eine ausgeschlossene Funktion hat, überspringe es
        if not should_merge_buildings(current_function):
            progress_bar.update(1)
            continue

        potential_neighbors = get_potential_neighbors(coords, grid, building_id, processed_buildings)

        for neighbor_id in potential_neighbors:
            if neighbor_id in processed_buildings:
                continue

            neighbor_building = building_dict[neighbor_id]
            neighbor_function = get_building_function(neighbor_building, ns, gebaeudefunktion_mapping)

            # HIER DIE ERSTE NEUE PRÜFUNG
            # Prüfe ob die Gebäude verbunden werden dürfen (inkl. FLURID-Check)
            if not should_merge_buildings(
                current_function,
                neighbor_function,
                building_id,
                neighbor_id,
                building_to_flurid
            ):
                continue

            # Prüfe räumliche Verbindung
            connected, distance, closest_points = check_building_connection(
                coords, building_coords[neighbor_id]
            )

            if connected:
                main_building, part_building = determine_main_building(
                    building,
                    neighbor_building,
                    building_id,
                    neighbor_id,
                    ns,
                    gebaeudefunktion_mapping,
                    building_to_flurid  # Neuer Parameter
                )

                connection_count += 1

                if main_building not in building_connections:
                    building_connections[main_building] = []
                building_connections[main_building].append(part_building)
                processed_buildings.add(part_building)

        progress_bar.update(1)

    # Zweiter Durchlauf: Verarbeite "Nach Quellenlage nicht zu spezifizieren" Gebäude
    for building_id, coords in building_coords.items():
        building = building_dict[building_id]
        current_function = get_building_function(building, ns, gebaeudefunktion_mapping)

        # Nur "Nach Quellenlage nicht zu spezifizieren" Gebäude verarbeiten
        if current_function != "Nach Quellenlage nicht zu spezifizieren" or building_id in processed_buildings:
            continue

        potential_neighbors = get_potential_neighbors(coords, grid, building_id, processed_buildings)

        for neighbor_id in potential_neighbors:
            if neighbor_id in processed_buildings:
                continue

            neighbor_building = building_dict[neighbor_id]
            neighbor_function = get_building_function(neighbor_building, ns, gebaeudefunktion_mapping)

            # HIER DIE ZWEITE NEUE PRÜFUNG
            # Prüfe ob die Gebäude verbunden werden dürfen (inkl. FLURID-Check)
            if not should_merge_buildings(
                neighbor_function,
                current_function,
                neighbor_id,
                building_id,
                building_to_flurid
            ):
                continue

            # Prüfe räumliche Verbindung
            connected, distance, closest_points = check_building_connection(
                coords, building_coords[neighbor_id]
            )

            if connected:
                # "Nach Quellenlage nicht zu spezifizieren" wird immer als Gebäudeteil hinzugefügt
                main_building = neighbor_id
                part_building = building_id

                connection_count += 1

                if main_building not in building_connections:
                    building_connections[main_building] = []
                building_connections[main_building].append(part_building)
                processed_buildings.add(part_building)

    progress_bar.close()
    print(f"\nGefundene Verbindungen insgesamt: {connection_count}")

    return building_connections

def calculate_polygon_area(coords):
    """
    Berechnet die Fläche eines 3D-Polygons
    """
    n = len(coords)
    if n < 3:
        return 0
    area = 0.0
    normal = [0, 0, 0]
    for i in range(n):
        j = (i + 1) % n
        normal[0] += (coords[i][1] - coords[j][1]) * (coords[i][2] + coords[j][2])
        normal[1] += (coords[i][2] - coords[j][2]) * (coords[i][0] + coords[j][0])
        normal[2] += (coords[i][0] - coords[j][0]) * (coords[i][1] + coords[j][1])
    area = math.sqrt(normal[0] ** 2 + normal[1] ** 2 + normal[2] ** 2) / 2
    return area


def calculate_polygon_area_2d(coords):
    """
    Berechnet die Fläche eines 2D-Polygons
    """
    n = len(coords)
    if n < 3:
        return 0
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += coords[i][0] * coords[j][1]
        area -= coords[j][0] * coords[i][1]
    return abs(area) / 2.0


def calculate_floor_area(building_part, ns):
    """
    Berechnet die Grundfläche eines Gebäudeteils
    """
    ground_surfaces = building_part.findall('.//bldg:GroundSurface', ns)
    total_area = 0.0
    for gs in ground_surfaces:
        multi_surface = gs.find('.//bldg:lod2MultiSurface', ns)
        if multi_surface is not None:
            for surface_member in multi_surface.findall('.//gml:surfaceMember', ns):
                polygon = surface_member.find('.//gml:Polygon', ns)
                if polygon is not None:
                    exterior = polygon.find('.//gml:exterior', ns)
                    if exterior is not None:
                        linear_ring = exterior.find('.//gml:LinearRing', ns)
                        if linear_ring is not None:
                            posList = linear_ring.find('.//gml:posList', ns)
                            if posList is not None:
                                srsDimension = posList.get('srsDimension', '2')
                                coords = extract_coordinates(posList.text, srsDimension)
                                if srsDimension == '2':
                                    area = calculate_polygon_area_2d(coords)
                                else:
                                    area = calculate_polygon_area(coords)
                                total_area += area
    return total_area


def calculate_wall_area(building_part, ns):
    """
    Berechnet die Wandfläche eines Gebäudeteils
    """
    wall_surfaces = building_part.findall('.//bldg:WallSurface', ns)
    total_wall_area = 0.0
    for wall in wall_surfaces:
        multi_surface = wall.find('.//bldg:lod2MultiSurface', ns)
        if multi_surface is not None:
            for surface_member in multi_surface.findall('.//gml:surfaceMember', ns):
                polygon = surface_member.find('.//gml:Polygon', ns)
                if polygon is not None:
                    exterior = polygon.find('.//gml:exterior', ns)
                    if exterior is not None:
                        linear_ring = exterior.find('.//gml:LinearRing', ns)
                        if linear_ring is not None:
                            posList = linear_ring.find('.//gml:posList', ns)
                            if posList is not None:
                                srsDimension = posList.get('srsDimension', '3')
                                coords = extract_coordinates(posList.text, srsDimension)
                                if srsDimension == '2':
                                    area = calculate_polygon_area_2d(coords)
                                else:
                                    area = calculate_polygon_area(coords)
                                total_wall_area += area
    return total_wall_area


def calculate_net_floor_area(floor_area, num_floors, roof_type_code, height, roof_angle):
    """
    Berechnet die Wohnfläche eines Gebäudes unter Berücksichtigung typischer Wohngebäude-Charakteristiken
    """
    USAGE_FACTORS = {
        1: 0.75,  # Eingeschossig: 25% Abzug
        2: 0.80,  # Zweigeschossig: 20% Abzug
        3: 0.65,  # Dreigeschossig: 35% Abzug
        4: 0.60  # Vier und mehr Geschosse: 40% Abzug
    }

    WALL_FACTORS = {
        1: 0.82,  # Eingeschossig: 18% Wandabzug
        2: 0.80,  # Zweigeschossig: 20% Wandabzug
        3: 0.75,  # Dreigeschossig: 25% Wandabzug
        4: 0.75  # Vier und mehr Geschosse: 25% Wandabzug
    }

    usage_factor = USAGE_FACTORS.get(min(num_floors, 4), 0.60)
    wall_factor = WALL_FACTORS.get(min(num_floors, 4), 0.75)

    MIN_USABLE_HEIGHT = 1.0
    FULL_HEIGHT = 2.0
    REAL_FLOOR_HEIGHT = 2.5

    if height is not None:
        calculated_floors = max(1, int(height / REAL_FLOOR_HEIGHT))
        num_floors = min(num_floors, calculated_floors)

    full_floors_area = floor_area * num_floors

    roof_type_factors = {
        '1000': 0.1,  # Flachdach
        '2100': 0.4,  # Pultdach
        '3100': 0.45,  # Satteldach
        '2200': 0.4,  # Versetztes Pultdach
        '3200': 0.45,  # Walmdach
        '3300': 0.4,  # Krüppelwalmdach
        '3400': 0.5,  # Mansardendach
        '3500': 0.35,  # Zeltdach
        '3600': 0.1,  # Kegeldach
        '3700': 0.1,  # Kuppeldach
        '3800': 0.1,  # Sheddach
        '3900': 0.4,  # Bogendach
        '4000': 0.1,  # Turmdach
        '5000': 0.4,  # Mischform
        '9999': 0.4  # Sonstiges
    }

    roof_factor = roof_type_factors.get(roof_type_code, 0.4)
    attic_area = 0

    if roof_type_code != '1000' and height is not None:
        roof_angle_rad = math.radians(roof_angle)
        building_width = math.sqrt(floor_area)
        max_roof_height = math.tan(roof_angle_rad) * (building_width / 2)

        if max_roof_height >= MIN_USABLE_HEIGHT:
            full_height_width = 2 * (max_roof_height - FULL_HEIGHT) / math.tan(roof_angle_rad)
            partial_height_width = 2 * (FULL_HEIGHT - MIN_USABLE_HEIGHT) / math.tan(roof_angle_rad)

            if full_height_width > 0:
                attic_area += full_height_width * building_width
            if partial_height_width > 0:
                attic_area += partial_height_width * building_width * 0.5

            attic_area *= roof_factor

            if num_floors <= 2 and roof_type_code in ['3100', '3200', '3400']:
                attic_area *= 1.2

    total_area = (full_floors_area + attic_area) * wall_factor * usage_factor
    min_area = floor_area * 0.6
    total_area = max(total_area, min_area * num_floors)

    return round(total_area, 2)


def calculate_roof_volume(floor_area, roof_angle, height):
    """
    Berechnet das Dachvolumen
    """
    roof_angle_rad = math.radians(roof_angle)
    roof_height = math.tan(roof_angle_rad) * math.sqrt(floor_area) / 2
    if roof_height > height:
        roof_height = height
    roof_volume = floor_area * roof_height / 2
    return roof_volume


def parse_mapping_file(file_path):
    """
    Liest die Mapping-Datei ein und erstellt ein Dictionary
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    mapping = {}
    if 'containeditems' in data.get('de.adv-online.gid', {}):
        items = data['de.adv-online.gid']['containeditems']
    elif 'containeditems' in data:
        items = data['containeditems']
    else:
        items = []
    for item in items:
        value = item.get('value', {})
        code = value.get('CodeListValue_Local_Id', {}).get('text', None)
        label = value.get('label', {}).get('text', None)
        if code and label:
            mapping[code] = label
    return mapping


def process_building_part(part, ns, transformer, dachform_mapping, flurid=None, addresses=None):
    """
    Verarbeitet einen einzelnen Gebäudeteil und gibt die Daten zurück
    """
    part_coordinates = extract_building_coordinates(part, ns)
    part_wgs84_coords = convert_coordinates_to_wgs84(part_coordinates, transformer)

    # Extrahiere die originale Gebäudefunktion
    function_elements = part.findall('bldg:function', ns)
    orig_function_code = None
    orig_function_name = 'Unbekannt'

    for function_element in function_elements:
        orig_function_code = function_element.text.split('_')[-1]
        orig_function_name = gebaeudefunktion_mapping.get(orig_function_code, 'Unbekannt')
        break

    building_part = part.find('.//bldg:BuildingPart', ns)
    if building_part is not None:
        roof_type_element = building_part.find('bldg:roofType', ns)
        height_element = building_part.find('bldg:measuredHeight', ns)
    else:
        roof_type_element = part.find('bldg:roofType', ns)
        height_element = part.find('bldg:measuredHeight', ns)

    if roof_type_element is not None:
        roof_type_code = roof_type_element.text
        roof_type_label = dachform_mapping.get(roof_type_code, 'Unbekannt')
    else:
        roof_type_code = None
        roof_type_label = 'Unbekannt'

    height = float(height_element.text) if height_element is not None else None

    floor_area = calculate_floor_area(part, ns)
    wall_area = calculate_wall_area(part, ns)

    dachneigung_mapping = {
        '1000': 2,  # Flachdach
        '2100': 20,  # Pultdach
        '2200': 20,  # Versetztes Pultdach
        '3100': 45,  # Satteldach
        '3200': 45,  # Walmdach
        '3300': 24,  # Krüppelwalmdach
        '3400': 60,  # Mansardendach
        '3500': 25,  # Zeltdach
        '3600': 50,  # Kegeldach
        '3700': 45,  # Kuppeldach
        '3800': 45,  # Sheddach
        '3900': 45,  # Bogendach
        '4000': 60,  # Turmdach
        '5000': 45,  # Mischform
        '9999': 60  # Sonstiges
    }

    if height is not None and floor_area > 0:
        roof_angle = dachneigung_mapping.get(roof_type_code, 45)
        roof_volume = calculate_roof_volume(floor_area, roof_angle, height)
        cuboid_volume = floor_area * height
        volume = cuboid_volume - roof_volume
    else:
        volume = 0
        roof_angle = 0

    if height is not None:
        floor_height = 3.2
        num_floors = max(1, int(round(height / floor_height)))
    else:
        num_floors = 1

    net_floor_area = calculate_net_floor_area(
        floor_area,
        num_floors,
        roof_type_code,
        height,
        dachneigung_mapping.get(roof_type_code, 45)
    )

    building_data = {
        'GebaeudeteilID': part.get('{http://www.opengis.net/gml}id'),
        'orig_Gebaeudefunktion': orig_function_name,
        'merg_Gebaeudefunktion': None,
        'Gebaeudehoehe': round(height, 1) if height else None,
        'Grundflaeche': round(floor_area, 1),
        'Etagenzahl': num_floors,
        'Dachart': roof_type_label,
        'Dachwinkel': dachneigung_mapping.get(roof_type_code, 45),
        'Gebaeudevolumen': round(volume, 1),
        'Wandflaeche': round(wall_area, 1),
        'Nettonutzflaeche': round(net_floor_area, 1),
        'Koordinaten': part_wgs84_coords,
        # Neue Felder
        'FLURID': flurid,
        'Adressen': addresses if addresses else []
    }

    return building_data


def process_building_parts(building_parts, building_id, buildings_data, ns, transformer, dachform_mapping,
                           building_dict):
    """
    Verarbeitet alle Gebäudeteile eines Gebäudes
    """
    for building_part_wrapper in building_parts:
        bp = building_part_wrapper.find('bldg:BuildingPart', ns)
        if bp is not None:
            building_part_id = bp.get('{http://www.opengis.net/gml}id')

            part_data = process_building_part(bp, ns, transformer, dachform_mapping)
            part_data['GebaeudeteilID'] = building_part_id
            part_data['merg_Gebaeudefunktion'] = buildings_data[building_id]['Gebaeudefunktion']

            buildings_data[building_id]['Gebaeudeteile'].append(part_data)
            buildings_data[building_id]['Gesamtvolumen'] += part_data['Gebaeudevolumen']
            buildings_data[building_id]['Gesamtgrundflaeche'] += part_data['Grundflaeche']
            buildings_data[building_id]['Gesamtwandflaeche'] += part_data['Wandflaeche']
            buildings_data[building_id]['Gesamtnettonutzflaeche'] += part_data['Nettonutzflaeche']

    # Runde die Gesamtwerte
    buildings_data[building_id]['Gesamtvolumen'] = round(buildings_data[building_id]['Gesamtvolumen'], 1)
    buildings_data[building_id]['Gesamtgrundflaeche'] = round(buildings_data[building_id]['Gesamtgrundflaeche'], 1)
    buildings_data[building_id]['Gesamtwandflaeche'] = round(buildings_data[building_id]['Gesamtwandflaeche'], 1)
    buildings_data[building_id]['Gesamtnettonutzflaeche'] = round(buildings_data[building_id]['Gesamtnettonutzflaeche'],
                                                                  1)


def process_connected_building(connected_building, main_building_id, buildings_data, processed_buildings, ns,
                             transformer, dachform_mapping, building_dict):
    """
    Verarbeitet ein verbundenes Gebäude als Gebäudeteil
    """
    connected_building_id = connected_building.get('{http://www.opengis.net/gml}id')

    # Prüfe die Gebäudefunktion des verbundenen Gebäudes
    function = get_building_function(connected_building, ns, gebaeudefunktion_mapping)

    # Nur verarbeiten, wenn die Funktion passt
    if should_merge_buildings(function):
        part_data = process_building_part(connected_building, ns, transformer, dachform_mapping)
        part_data['GebaeudeteilID'] = connected_building_id
        part_data['merg_Gebaeudefunktion'] = buildings_data[main_building_id]['Gebaeudefunktion']

        buildings_data[main_building_id]['Gebaeudeteile'].append(part_data)
        buildings_data[main_building_id]['Gesamtvolumen'] += part_data['Gebaeudevolumen']
        buildings_data[main_building_id]['Gesamtgrundflaeche'] += part_data['Grundflaeche']
        buildings_data[main_building_id]['Gesamtwandflaeche'] += part_data['Wandflaeche']
        buildings_data[main_building_id]['Gesamtnettonutzflaeche'] += part_data['Nettonutzflaeche']

        # Runde die Gesamtwerte
        buildings_data[main_building_id]['Gesamtvolumen'] = round(buildings_data[main_building_id]['Gesamtvolumen'], 1)
        buildings_data[main_building_id]['Gesamtgrundflaeche'] = round(
            buildings_data[main_building_id]['Gesamtgrundflaeche'], 1)
        buildings_data[main_building_id]['Gesamtwandflaeche'] = round(
            buildings_data[main_building_id]['Gesamtwandflaeche'], 1)
        buildings_data[main_building_id]['Gesamtnettonutzflaeche'] = round(
            buildings_data[main_building_id]['Gesamtnettonutzflaeche'], 1)

        processed_buildings.add(connected_building_id)


def load_geojson_mapping(geojson_file):
    """
    Lädt die GeoJSON-Datei und erstellt Mappings für FLURID und Adressen
    """
    with open(geojson_file, 'r', encoding='utf-8') as f:
        geojson_data = json.load(f)

    # Mapping: Gebäude-ID (oi) -> FLURID
    building_to_flurid = {}
    # Mapping: FLURID -> Adressen
    flurid_to_addresses = {}
    # Mapping: Gebäude-ID -> Grundfläche aus GeoJSON
    building_to_area = {}

    for feature in geojson_data['features']:
        flurid = feature['flurid']

        # Speichere Adressen für diese FLURID
        addresses = []
        for addr in feature.get('adressen', []):
            address = {
                'strasse': addr.get('str'),
                'hausnummer': addr.get('hnr'),
                'adz': addr.get('adz'),
                'plz': addr.get('postplz'),
                'ort': addr.get('postonm')
            }
            addresses.append(address)
        flurid_to_addresses[flurid] = addresses

        # Speichere Gebäude-Informationen
        for building in feature.get('gebaeude', []):
            building_id = building['gebaeude']['oi']
            building_to_flurid[building_id] = flurid
            building_to_area[building_id] = building['gebaeude'].get('grundflaeche')

    return building_to_flurid, flurid_to_addresses, building_to_area

def main():
    """
    Hauptfunktion zur Verarbeitung der Gebäudedaten
    """
    print("\nStarte Gebäudeanalyse...")

    gml_file_path = 'C:\\Users\\e-gue\\Documents\\Bachelorarbeit\\datensatz_gebaeude_cottbus\\3d_branitzer_siedlung\\LoD2_455329-5733295_geb.gml'
    gebaeudefunktion_file_path = 'C:\\Users\\e-gue\\Documents\\Bachelorarbeit\\datensatz_gebaeude_cottbus\\lot2_codeliste\\AX_Gebaeudefunktion.json'
    dachform_file_path = 'C:\\Users\\e-gue\\Documents\\Bachelorarbeit\\datensatz_gebaeude_cottbus\\lot2_codeliste\\AX_Dachform.json'
    geojson_file_path = 'hausumringeV6.geojson'

    print("1/7: Lade Mapping-Dateien...")
    global gebaeudefunktion_mapping
    gebaeudefunktion_mapping = parse_mapping_file(gebaeudefunktion_file_path)
    dachform_mapping = parse_mapping_file(dachform_file_path)

    print("2/7: Erstelle Koordinaten-Transformer...")
    transformer = create_coordinate_transformer()

    print("3/7: Lese GML-Daten...")
    with open(gml_file_path, 'r', encoding='utf-8') as f:
        gml_data = f.read()

    root = ET.fromstring(gml_data)

    ns = {
        'core': 'http://www.opengis.net/citygml/1.0',
        'bldg': 'http://www.opengis.net/citygml/building/1.0',
        'gml': 'http://www.opengis.net/gml',
        'gen': 'http://www.opengis.net/citygml/generics/1.0',
    }

    # Lade GeoJSON-Daten
    building_to_flurid, flurid_to_addresses, building_to_area = load_geojson_mapping(geojson_file_path)

    print("4/7: Identifiziere verbundene Gebäude...")
    buildings = root.findall('.//bldg:Building', ns)
    building_dict = {building.get('{http://www.opengis.net/gml}id'): building for building in buildings}
    building_connections = identify_connected_buildings(
        root,
        ns,
        gebaeudefunktion_mapping,
        building_to_flurid
    )

    print("5/7: Verarbeite Gebäude...")
    total_buildings = len(buildings)
    print(f"Starte Verarbeitung von {total_buildings} Gebäuden...")

    buildings_data = {}
    processed_buildings = set()

    # Erste Durchlauf: Identifiziere alle verbundenen Gebäude
    connected_parts = set()
    for main_building_id, parts in building_connections.items():
        connected_parts.update(parts)

    # Debug-Ausgabe
    print(f"\nGefundene verbundene Gebäudeteile: {len(connected_parts)}")
    for part in connected_parts:
        print(f"Verbundenes Teil: {part}")

    progress_bar = tqdm(
        buildings,
        total=total_buildings,
        desc="Verarbeite Gebäude",
        unit="Gebäude",
        ncols=100
    )

    for building in progress_bar:
        building_id = building.get('{http://www.opengis.net/gml}id')

        # Überspringe Gebäude, die als Teile anderer Gebäude identifiziert wurden
        if building_id in connected_parts:
            progress_bar.set_description(f"Überspringe verbundenes Gebäude {building_id}")
            continue

        if building_id in processed_buildings:
            progress_bar.set_description(f"Überspringe verarbeitetes Gebäude {building_id}")
            continue

        progress_bar.set_description(f"Verarbeite Gebäude {building_id}")

        function_elements = building.findall('bldg:function', ns)
        function_labels = []
        function_code = 'unbekannt'
        for function_element in function_elements:
            function_code_full = function_element.text
            function_code = function_code_full.split('_')[-1] if '_' in function_code_full else function_code_full
            function_label = gebaeudefunktion_mapping.get(function_code, 'Unbekannt')
            function_labels.append(function_label)
        function_name = ', '.join(function_labels)

        # Hole FLURID und Adressen
        flurid = building_to_flurid.get(building_id)
        addresses = flurid_to_addresses.get(flurid, []) if flurid else []

        if building_id not in buildings_data:
            buildings_data[building_id] = {
                'GebaeudeID': building_id,
                'Gebaeudefunktion': function_name,
                'Gebaeudecode': function_code,
                'FLURID': flurid,  # Neue Information
                'Adressen': addresses,  # Neue Information
                'Gebaeudeteile': [],
                'Gesamtvolumen': 0,
                'Gesamtgrundflaeche': 0,
                'Gesamtwandflaeche': 0,
                'Gesamtnettonutzflaeche': 0
            }

            building_parts = building.findall('bldg:consistsOfBuildingPart', ns)

            if building_parts:
                buildings_data[building_id]['Gebaeudeteile'] = []
                buildings_data[building_id]['Gesamtvolumen'] = 0
                buildings_data[building_id]['Gesamtgrundflaeche'] = 0
                buildings_data[building_id]['Gesamtwandflaeche'] = 0
                buildings_data[building_id]['Gesamtnettonutzflaeche'] = 0
            else:
                main_part_data = process_building_part(
                    building,
                    ns,
                    transformer,
                    dachform_mapping,
                    flurid=flurid,  # Neue Parameter
                    addresses=addresses
                )
                main_part_data['GebaeudeteilID'] = building_id
                main_part_data['merg_Gebaeudefunktion'] = function_name
                buildings_data[building_id]['Gebaeudeteile'] = [main_part_data]
                buildings_data[building_id]['Gesamtvolumen'] = main_part_data['Gebaeudevolumen']
                buildings_data[building_id]['Gesamtgrundflaeche'] = main_part_data['Grundflaeche']
                buildings_data[building_id]['Gesamtwandflaeche'] = main_part_data['Wandflaeche']
                buildings_data[building_id]['Gesamtnettonutzflaeche'] = main_part_data['Nettonutzflaeche']

        # Verarbeite verbundene Gebäude nur wenn die Funktion passt
        if building_id in building_connections:
            for connected_building_id in building_connections[building_id]:
                connected_building = root.find(f'.//bldg:Building[@gml:id="{connected_building_id}"]', ns)
                if connected_building is not None:
                    # Prüfe die Funktion des verbundenen Gebäudes
                    connected_function_elements = connected_building.findall('bldg:function', ns)
                    connected_function = None
                    for function_element in connected_function_elements:
                        function_code = function_element.text.split('_')[-1]
                        connected_function = gebaeudefunktion_mapping.get(function_code, 'Unbekannt')
                        break

                    if should_merge_buildings(connected_function):
                        process_connected_building(
                            connected_building,
                            building_id,
                            buildings_data,
                            processed_buildings,
                            ns,
                            transformer,
                            dachform_mapping,
                            building_dict
                        )

        # Verarbeite reguläre Gebäudeteile
        building_parts = building.findall('bldg:consistsOfBuildingPart', ns)
        if building_parts:
            process_building_parts(
                building_parts,
                building_id,
                buildings_data,
                ns,
                transformer,
                dachform_mapping,
                building_dict
            )

    progress_bar.close()

    # Entferne alle verbundenen Gebäude aus buildings_data
    removed_buildings = []
    for connected_id in connected_parts:
        if connected_id in buildings_data:
            removed_buildings.append(connected_id)
            del buildings_data[connected_id]

    # Debug-Ausgabe für entfernte Gebäude
    if removed_buildings:
        print("\nFolgende verbundene Gebäude wurden aus der Hauptliste entfernt:")
        for building_id in removed_buildings:
            print(f"- {building_id}")
    else:
        print("\nKeine verbundenen Gebäude mussten aus der Hauptliste entfernt werden.")

    print("\n6/7: Validiere Gebäudeverbindungen...")
    validate_building_connections(buildings_data, gebaeudefunktion_mapping)

    print("\n7/7: Schreibe Daten in JSON-Datei...")
    output_file = 'output_branitzer_siedlungV11.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(buildings_data, f, ensure_ascii=False, indent=2)

    print(f"\nVerarbeitung erfolgreich abgeschlossen!")
    print(f"Daten wurden in {output_file} gespeichert.")
    print(f"Anzahl der verarbeiteten Gebäude: {len(buildings_data)}")
    print(f"Anzahl der verbundenen Gebäudeteile: {len(connected_parts)}")


if __name__ == "__main__":
    main()