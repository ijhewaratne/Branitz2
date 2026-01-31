from org.openstreetmap.josm.data.osm import Node, Way, DataSet
from org.openstreetmap.josm.gui.layer import OsmDataLayer
from org.openstreetmap.josm.data.coor import LatLon
import math

def copy_node_to_dataset(node, dataset, existingNodes):
    if node.getUniqueId() in existingNodes:
        return existingNodes[node.getUniqueId()]
    else:
        new_node = Node(node.getCoor())
        dataset.addPrimitive(new_node)
        existingNodes[node.getUniqueId()] = new_node
        return new_node

def create_way_with_nodes(way_nodes, dataset, existingNodes, is_power_line=False):
    new_way = Way()
    for node in way_nodes:
        new_node = copy_node_to_dataset(node, dataset, existingNodes)
        new_way.addNode(new_node)
    if is_power_line:
        new_way.put("power", "line")
    dataset.addPrimitive(new_way)
    return new_way

def calculate_closest_building_midpoint(way, streets):
    min_distance = float('inf')
    closest_midpoint = None
    closest_point_on_power_line = None
    for i in range(len(way.getNodes()) - 1):
        node1 = way.getNodes()[i]
        node2 = way.getNodes()[i + 1]
        mid_point = midpoint(node1, node2)
        for street in streets:
            for j in range(len(street.getNodes()) - 1):
                street_node1 = street.getNodes()[j]
                street_node2 = street.getNodes()[j + 1]
                potential_closest_point = closest_point_on_segment(street_node1, street_node2, mid_point)
                if potential_closest_point:
                    dist = distance(mid_point, potential_closest_point)
                    if dist < min_distance:
                        min_distance = dist
                        closest_midpoint = mid_point
                        closest_point_on_power_line = potential_closest_point
    return closest_midpoint, closest_point_on_power_line

def midpoint(node1, node2):
    if not node1 or not node2 or not node1.getCoor() or not node2.getCoor():
        return None
    mid_lat = (node1.getCoor().lat() + node2.getCoor().lat()) / 2
    mid_lon = (node1.getCoor().lon() + node2.getCoor().lon()) / 2
    return Node(LatLon(mid_lat, mid_lon))

def distance(node1, node2):
    if not node1 or not node2 or not node1.getCoor() or not node2.getCoor():
        return float('inf')
    coor1, coor2 = node1.getCoor(), node2.getCoor()
    return math.hypot(coor1.lon() - coor2.lon(), coor1.lat() - coor2.lat())

def closest_point_on_segment(seg_a, seg_b, pt):
    if not seg_a or not seg_b or not pt or not seg_a.getCoor() or not seg_b.getCoor() or not pt.getCoor():
        return None
    ax, ay = seg_a.getCoor().lon(), seg_a.getCoor().lat()
    bx, by = seg_b.getCoor().lon(), seg_b.getCoor().lat()
    px, py = pt.getCoor().lon(), pt.getCoor().lat()
    segment_vector = (bx - ax, by - ay)
    point_vector = (px - ax, py - ay)
    dot_product = sum(a * b for a, b in zip(segment_vector, point_vector))
    segment_length_squared = sum(a * a for a in segment_vector)
    if segment_length_squared == 0:
        return None
    param = dot_product / segment_length_squared
    if param < 0:
        closest_x, closest_y = ax, ay
    elif param > 1:
        closest_x, closest_y = bx, by
    else:
        closest_x = ax + param * segment_vector[0]
        closest_y = ay + param * segment_vector[1]
    return Node(LatLon(closest_y, closest_x))

def find_closest_point_on_streets(point, streets):
    if not point or not point.getCoor():
        return None
    min_distance = float('inf')
    closest_point = None
    for street in streets:
        if not isinstance(street, Way):
            continue
        for i in range(len(street.getNodes()) - 1):
            start = street.getNodes()[i]
            end = street.getNodes()[i + 1]
            potential_closest = closest_point_on_segment(start, end, point)
            if potential_closest:
                dist = distance(point, potential_closest)
                if dist < min_distance:
                    min_distance = dist
                    closest_point = potential_closest
    return closest_point

def visualize_electrical_network():
    from org.openstreetmap.josm.gui import MainApplication
    target_layer = MainApplication.getLayerManager().getActiveLayer()
    dataset = DataSet()
    existingNodes = {}

    streets = [p for p in target_layer.data.allPrimitives() if isinstance(p, Way) and p.get('highway') is not None and p.get('highway') not in ['path', 'footway', 'cycleway', 'platform', 'service', 'track', 'bridleway', 'steps', 'unclassified']]
    address_primitives = [p for p in target_layer.data.allPrimitives() if p.get('addr:housenumber') is not None]
    substations = [p for p in target_layer.data.allPrimitives() if 
                   p.get('power') == 'substation' and 
                   p.get('umspannwerk_110') != 'true' and 
                   p.get('umspannwerk_110_380') != 'true']

    for street in streets:
        create_way_with_nodes(street.getNodes(), dataset, existingNodes, is_power_line=True)

    # Connect substations to the nearest street
    for substation in substations:
        if isinstance(substation, Way):
            substation_center = substation.getBBox().getCenter()
        elif isinstance(substation, Node):
            substation_center = substation.getCoor()
        else:
            continue

        if not substation_center:
            continue
        
        closest_street_point = find_closest_point_on_streets(Node(substation_center), streets)
        
        if closest_street_point:
            substation_node = copy_node_to_dataset(Node(substation_center), dataset, existingNodes)
            street_node = copy_node_to_dataset(closest_street_point, dataset, existingNodes)
            
            connection_way = Way()
            connection_way.addNode(substation_node)
            connection_way.addNode(street_node)
            connection_way.put("power", "line")
            dataset.addPrimitive(connection_way)

    for addr_primitive in address_primitives:
        if isinstance(addr_primitive, Way):
            closest_midpoint, closest_point_on_power_line = calculate_closest_building_midpoint(addr_primitive, streets)
            if closest_midpoint and closest_point_on_power_line:
                closest_midpoint_node = copy_node_to_dataset(closest_midpoint, dataset, existingNodes)
                closest_midpoint_node.put("power", "consumer")
                closest_power_line_node = copy_node_to_dataset(closest_point_on_power_line, dataset, existingNodes)
                
                connection_way = Way()
                connection_way.addNode(closest_midpoint_node)
                connection_way.addNode(closest_power_line_node)
                connection_way.put("power", "minor_line")
                dataset.addPrimitive(connection_way)
        elif isinstance(addr_primitive, Node):
            closest_point_on_power_line = find_closest_point_on_streets(addr_primitive, streets)
            if closest_point_on_power_line:
                addr_node_in_dataset = copy_node_to_dataset(addr_primitive, dataset, existingNodes)
                addr_node_in_dataset.put("power", "consumer")
                closest_power_line_node = copy_node_to_dataset(closest_point_on_power_line, dataset, existingNodes)
                
                connection_way = Way()
                connection_way.addNode(addr_node_in_dataset)
                connection_way.addNode(closest_power_line_node)
                connection_way.put("power", "minor_line")
                dataset.addPrimitive(connection_way)

    visualization_layer = OsmDataLayer(dataset, "Electrical Network Visualization", None)
    MainApplication.getLayerManager().addLayer(visualization_layer)

visualize_electrical_network()

