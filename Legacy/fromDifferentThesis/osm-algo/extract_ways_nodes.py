import xml.etree.ElementTree as ET
from math import radians, sin, cos, sqrt, atan2
import json


def calculate_distance(lat1, lon1, lat2, lon2):
    """
    Calculate distance between two points in kilometers using the Haversine formula
    """
    R = 6371  # Earth's radius in kilometers

    lat1, lon1, lat2, lon2 = map(radians, [float(lat1), float(lon1), float(lat2), float(lon2)])

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))

    return R * c


def parse_osm_file(file_path):
    """
    Parse OSM file and extract nodes and ways with specified format
    """
    tree = ET.parse(file_path)
    root = tree.getroot()

    # Extract nodes
    nodes = []
    for node in root.findall('.//node'):
        node_data = {
            "lon": float(node.get('lon')),
            "lat": float(node.get('lat')),
            "id": int(node.get('id')),
            "tags": {}
        }

        # Extract tags for node
        for tag in node.findall('tag'):
            node_data["tags"][tag.get('k')] = tag.get('v')

        nodes.append(node_data)

    # Extract ways
    ways = []
    for way in root.findall('.//way'):
        way_data = {
            "id": int(way.get('id')),
            "nodes": [],
            "tags": {},
            "length_km": 0
        }

        # Extract nodes references
        node_refs = way.findall('nd')
        for nd in node_refs:
            way_data["nodes"].append(int(nd.get('ref')))

        # Extract tags for way
        for tag in way.findall('tag'):
            way_data["tags"][tag.get('k')] = tag.get('v')

        # Calculate length if there are at least 2 nodes
        if len(way_data["nodes"]) >= 2:
            length = 0
            for i in range(len(way_data["nodes"]) - 1):
                node1 = next(n for n in nodes if n["id"] == way_data["nodes"][i])
                node2 = next(n for n in nodes if n["id"] == way_data["nodes"][i + 1])
                length += calculate_distance(node1["lat"], node1["lon"],
                                             node2["lat"], node2["lon"])
            way_data["length_km"] = length

        ways.append(way_data)

    # Sicherstellen, dass alle Nodes verbunden sind
    ways = ensure_connectivity(nodes, ways)

    return nodes, ways


def export_to_json(nodes, ways, output_file):
    """
    Export nodes and ways to a JSON file
    """
    data = {
        "nodes": nodes,
        "ways": ways
    }

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def ensure_connectivity(nodes, ways):
    # Dictionary, um zu verfolgen, welche Knoten bereits in einem Weg enthalten sind
    connected_nodes = {node_id for way in ways for node_id in way["nodes"]}

    # Für jeden Knoten prüfen, ob er verbunden ist, und eine Verbindung hinzufügen, falls nicht
    for node in nodes:
        if node["id"] not in connected_nodes:
            # Nächstgelegenen verbundenen Knoten finden
            closest_node = None
            min_distance = float('inf')

            for other_node in nodes:
                if other_node["id"] != node["id"] and other_node["id"] in connected_nodes:
                    distance = calculate_distance(node["lat"], node["lon"], other_node["lat"], other_node["lon"])
                    if distance < min_distance:
                        min_distance = distance
                        closest_node = other_node["id"]

            # Wenn ein nächster Knoten gefunden wurde, einen neuen Weg erstellen
            if closest_node:
                new_way = {
                    "id": max(way["id"] for way in ways) + 1,
                    "nodes": [node["id"], closest_node],
                    "tags": {"power": "line"},
                    "length_km": min_distance
                }
                ways.append(new_way)
                print(f"Neue Verbindung erstellt zwischen Knoten {node['id']} und {closest_node}")
            else:
                print(f"Warnung: Kein nächster Knoten gefunden für Knoten {node['id']}")

    return ways


def main():
    input_file = "branitzer_siedlung_ns_v3_ohne_UW.osm"
    output_file = "branitzer_siedlung_ns_v3_ohne_UW.json"

    # Parse OSM file
    nodes, ways = parse_osm_file(input_file)

    # Export to JSON
    export_to_json(nodes, ways, output_file)
    print(f"Data has been exported to {output_file}")


if __name__ == "__main__":
    main()