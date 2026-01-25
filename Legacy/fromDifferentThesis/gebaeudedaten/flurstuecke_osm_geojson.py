import xml.etree.ElementTree as ET
import json
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union
import numpy as np


def parse_osm_to_polygons(osm_file):
    """
    Parst OSM-Datei und erstellt Dictionary mit Flurstückspolygonen
    """
    tree = ET.parse(osm_file)
    root = tree.getroot()

    # Sammle alle Nodes
    nodes = {}
    for node in root.findall('node'):
        node_id = node.get('id')
        lat = float(node.get('lat'))
        lon = float(node.get('lon'))
        nodes[node_id] = (lon, lat)  # Lon, Lat Format für GeoJSON Kompatibilität

    # Erstelle Polygone aus Ways
    flurstueck_polygons = {}
    invalid_ways = 0
    for i, way in enumerate(root.findall('way')):
        way_id = way.get('id')
        node_refs = []

        for nd in way.findall('nd'):
            ref = nd.get('ref')
            if ref in nodes:
                node_refs.append(nodes[ref])
            else:
                print(f"Warnung: Node {ref} nicht gefunden für Way {way_id}")

        # Schließe das Polygon, falls nötig
        if node_refs and node_refs[0] != node_refs[-1]:
            node_refs.append(node_refs[0])

        if len(node_refs) >= 3:  # Ein valides Polygon braucht mindestens 3 Punkte
            try:
                poly = Polygon(node_refs)
                if poly.is_valid:
                    flurstueck_polygons[f"FLUR_{i + 1}"] = poly
                else:
                    print(f"Warnung: Ungültiges Polygon für Way {way_id}")
                    invalid_ways += 1
            except Exception as e:
                print(f"Fehler beim Erstellen des Polygons für Way {way_id}: {str(e)}")
                invalid_ways += 1
        else:
            print(f"Warnung: Zu wenige Punkte für Way {way_id}: {len(node_refs)} Punkte")
            invalid_ways += 1

    print(f"Statistik Flurstücke:")
    print(f"- Gültige Polygone erstellt: {len(flurstueck_polygons)}")
    print(f"- Ungültige/Übersprungene Ways: {invalid_ways}")

    return flurstueck_polygons


def point_in_polygon(point, polygon):
    """
    Prüft, ob ein Punkt in einem Polygon liegt
    """
    try:
        return polygon.contains(Point(point))
    except Exception as e:
        print(f"Fehler bei Point-in-Polygon Test: {str(e)}")
        return False


def find_containing_flurstueck(hausumring_coords, flurstueck_polygons, hausumring_id):
    """
    Findet das Flurstück, das den Hausumring enthält
    """
    try:
        # Berechne den Centroid des Hausumrings
        points = np.array(hausumring_coords[0])  # Nimm die äußere Ring-Koordinaten
        centroid = Point(np.mean(points[:, 0]), np.mean(points[:, 1]))

        # Debug: Zeige Centroid-Koordinaten
        print(f"\nDebug für Hausumring {hausumring_id}:")
        print(f"- Centroid: {centroid.x}, {centroid.y}")

        # Erstelle auch ein Polygon aus dem Hausumring für Überlappungsprüfung
        hausumring_poly = Polygon(points)

        found_flurstuecke = []
        for flur_id, polygon in flurstueck_polygons.items():
            if polygon.contains(centroid):
                # Berechne Überlappungsprozent
                intersection_area = polygon.intersection(hausumring_poly).area
                hausumring_area = hausumring_poly.area
                overlap_percent = (intersection_area / hausumring_area) * 100

                found_flurstuecke.append((flur_id, overlap_percent))
                print(f"- Gefundenes Flurstück: {flur_id}")
                print(f"- Überlappung: {overlap_percent:.2f}%")

        if not found_flurstuecke:
            print("- Kein enthaltendes Flurstück gefunden!")
            print("- Prüfe Abstände zu allen Flurstücken...")

            # Finde das nächstgelegene Flurstück
            min_distance = float('inf')
            nearest_flur = None
            for flur_id, polygon in flurstueck_polygons.items():
                distance = polygon.distance(centroid)
                if distance < min_distance:
                    min_distance = distance
                    nearest_flur = flur_id

            print(f"- Nächstes Flurstück: {nearest_flur} (Abstand: {min_distance:.2f} Einheiten)")
            return None

        # Bei mehreren Treffern, nimm das mit der größten Überlappung
        if found_flurstuecke:
            best_match = max(found_flurstuecke, key=lambda x: x[1])
            return best_match[0]

        return None

    except Exception as e:
        print(f"Fehler bei der Flurstückszuordnung für Hausumring {hausumring_id}: {str(e)}")
        print(f"Koordinaten des Hausumrings: {hausumring_coords}")
        return None


def process_hausumringe(hausumringe_file, flurstueck_polygons, output_file):
    """
    Verarbeitet Hausumringe und ordnet sie Flurstücken zu
    """
    # Lese Hausumringe
    with open(hausumringe_file, 'r', encoding='utf-8') as f:
        hausumringe = json.load(f)

    total_hausumringe = len(hausumringe['features'])
    assigned_hausumringe = 0
    unassigned_hausumringe = 0

    print(f"\nStarte Verarbeitung von {total_hausumringe} Hausumringen...")

    # Verarbeite jeden Hausumring
    for feature in hausumringe['features']:
        hausumring_id = feature['properties'].get('oi', 'Unbekannt')
        coords = feature['geometry']['coordinates']

        flur_id = find_containing_flurstueck(coords, flurstueck_polygons, hausumring_id)

        if flur_id:
            feature['properties']['flurid'] = flur_id
            assigned_hausumringe += 1
        else:
            feature['properties']['flurid'] = None
            unassigned_hausumringe += 1

    print(f"\nStatistik Zuordnung:")
    print(f"- Gesamt Hausumringe: {total_hausumringe}")
    print(f"- Erfolgreich zugeordnet: {assigned_hausumringe}")
    print(f"- Nicht zugeordnet: {unassigned_hausumringe}")
    print(f"- Zuordnungsrate: {(assigned_hausumringe / total_hausumringe * 100):.2f}%")

    # Schreibe erweiterte GeoJSON
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(hausumringe, f, ensure_ascii=False, indent=2)


def validate_polygons(flurstueck_polygons):
    """
    Überprüft die Gültigkeit der Flurstückspolygone
    """
    print("\nValidiere Flurstückspolygone:")
    valid_count = 0
    invalid_count = 0
    total_area = 0

    for flur_id, polygon in flurstueck_polygons.items():
        if polygon.is_valid:
            valid_count += 1
            total_area += polygon.area
        else:
            invalid_count += 1
            print(f"Ungültiges Polygon: {flur_id}")

    print(f"- Gültige Polygone: {valid_count}")
    print(f"- Ungültige Polygone: {invalid_count}")
    print(f"- Gesamtfläche: {total_area:.2f} Quadrateinheiten")


def main():
    # Dateipfade
    osm_file = 'flurstueckeV2.osm'
    hausumringe_file = 'hausumringe_branitzer_siedlung.json'
    output_file = 'hausumringe_mit_flurid.geojson'

    print("Verarbeite Flurstücke aus OSM...")
    flurstueck_polygons = parse_osm_to_polygons(osm_file)

    # Validiere die erstellten Polygone
    validate_polygons(flurstueck_polygons)

    print("\nOrdne Hausumringe den Flurstücken zu...")
    process_hausumringe(hausumringe_file, flurstueck_polygons, output_file)

    print(f"\nFertig! Ergebnis wurde in {output_file} gespeichert.")


if __name__ == "__main__":
    main()