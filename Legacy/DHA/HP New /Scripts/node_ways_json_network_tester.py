import json
import networkx as nx
import matplotlib.pyplot as plt


def plot_network(json_file):
    # Load JSON data
    with open(json_file, 'r') as f:
        data = json.load(f)

    # Create graph
    G = nx.Graph()

    # Add nodes with positions
    for node in data['nodes']:
        G.add_node(node['id'],
                   pos=(node['lon'], node['lat']),
                   tags=node['tags'])

    # Add edges
    for way in data['ways']:
        nodes = way['nodes']
        for i in range(len(nodes) - 1):
            G.add_edge(nodes[i], nodes[i + 1],
                       length=way['length_km'],
                       tags=way['tags'])

    # Analyze connectivity
    components = list(nx.connected_components(G))
    num_components = len(components)
    print(f"\nNetwork Analysis:")
    print(f"Number of nodes: {G.number_of_nodes()}")
    print(f"Number of edges: {G.number_of_edges()}")
    print(f"Number of connected components: {num_components}")

    # Print components details
    for i, component in enumerate(components):
        print(f"\nComponent {i + 1} size: {len(component)} nodes")
        # Count node types in component
        node_types = {}
        for node in component:
            node_tags = G.nodes[node]['tags']
            if 'power' in node_tags:
                node_type = node_tags['power']
                node_types[node_type] = node_types.get(node_type, 0) + 1
        print("Node types in component:")
        for ntype, count in node_types.items():
            print(f"- {ntype}: {count}")

    # Get node positions
    pos = nx.get_node_attributes(G, 'pos')

    # Create figure
    plt.figure(figsize=(15, 10))

    # Draw different components in different colors
    colors = plt.cm.rainbow(np.linspace(0, 1, num_components))

    for component, color in zip(components, colors):
        subgraph = G.subgraph(component)

        # Draw edges
        nx.draw_networkx_edges(subgraph, pos,
                               edge_color=color,
                               width=1.0,
                               alpha=0.7)

        # Draw nodes
        node_colors = []
        for node in subgraph.nodes():
            if 'power' in G.nodes[node]['tags']:
                if G.nodes[node]['tags']['power'] == 'consumer':
                    node_colors.append('cyan')
                elif G.nodes[node]['tags']['power'] == 'substation':
                    node_colors.append('red')
                else:
                    node_colors.append('yellow')
            else:
                node_colors.append('gray')

        nx.draw_networkx_nodes(subgraph, pos,
                               node_size=50,
                               node_color=node_colors,
                               alpha=0.7)

    # Create legend
    legend_elements = [
        plt.Line2D([0], [0], marker='o', color='w',
                   markerfacecolor='cyan', markersize=10, label='Consumer'),
        plt.Line2D([0], [0], marker='o', color='w',
                   markerfacecolor='red', markersize=10, label='Substation'),
        plt.Line2D([0], [0], marker='o', color='w',
                   markerfacecolor='yellow', markersize=10, label='Other Power Node'),
        plt.Line2D([0], [0], marker='o', color='w',
                   markerfacecolor='gray', markersize=10, label='Connection Node')
    ]
    plt.legend(handles=legend_elements, loc='upper right')

    # Set title and adjust layout
    plt.title('Power Network Connectivity Analysis\nDifferent colors represent different connected components')
    plt.axis('equal')
    plt.grid(True)

    # Save plot
    plt.savefig('network_analysis.png', dpi=300, bbox_inches='tight')
    print("\nPlot saved as network_analysis.png")

    # Show plot
    plt.show()


if __name__ == "__main__":
    import numpy as np

    plot_network('branitzer_siedlung_ns_v3_ohne_UW.json')