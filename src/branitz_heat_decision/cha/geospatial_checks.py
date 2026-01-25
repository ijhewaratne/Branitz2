"""
Geospatial validation for DH network design.

Checks:
1. Pipes follow streets and rights-of-way
2. All buildings are connected
3. No unrealistic pipe routing
"""

import logging
from typing import Dict, List, Tuple
from dataclasses import dataclass
import numpy as np
import geopandas as gpd
from shapely.geometry import LineString, Point
import pandapipes as pp

logger = logging.getLogger(__name__)


@dataclass
class GeospatialResult:
    """Result of geospatial validation"""
    passed: bool
    issues: List[str]
    warnings: List[str]
    metrics: Dict[str, float]


class GeospatialValidator:
    """Validates geospatial aspects of DH network design"""
    
    def __init__(self, config):
        self.config = config.geospatial
    
    def validate(
        self,
        net: pp.pandapipesNet,
        streets_gdf: gpd.GeoDataFrame,
        buildings_gdf: gpd.GeoDataFrame
    ) -> GeospatialResult:
        """
        Complete geospatial validation.
        
        Args:
            net: Pandapipes network
            streets_gdf: Street network geometries
            buildings_gdf: Building footprints with demand
        
        Returns:
            GeospatialResult with validation outcome
        """
        
        issues = []
        warnings = []
        metrics = {}
        
        logger.info("Running geospatial validation...")
        
        # 1. Street alignment check
        street_check = self._check_street_alignment(net, streets_gdf)
        issues.extend(street_check["issues"])
        warnings.extend(street_check["warnings"])
        metrics.update(street_check["metrics"])
        
        # 2. Building connectivity check
        building_check = self._check_building_connectivity(net, buildings_gdf)
        issues.extend(building_check["issues"])
        warnings.extend(building_check["warnings"])
        metrics.update(building_check["metrics"])
        
        # 3. Topology sanity checks
        topology_check = self._check_topology_sanity(net)
        issues.extend(topology_check["issues"])
        warnings.extend(topology_check["warnings"])
        metrics.update(topology_check["metrics"])
        
        passed = len(issues) == 0
        
        logger.info(f"Geospatial validation: {'PASSED' if passed else 'FAILED'}")
        logger.info(f"  Issues: {len(issues)}, Warnings: {len(warnings)}")
        
        return GeospatialResult(
            passed=passed,
            issues=issues,
            warnings=warnings,
            metrics=metrics
        )
    
    def _get_xy(self, net, junction_idx) -> Tuple[float, float]:
        """Safely get x,y coordinates for a junction"""
        # Try junction_geodata first (standard location)
        if junction_idx in net.junction_geodata.index:
            return (
                net.junction_geodata.loc[junction_idx, "x"],
                net.junction_geodata.loc[junction_idx, "y"]
            )
        # Fallback to junction table if merged
        elif "x" in net.junction.columns:
            return (
                net.junction.loc[junction_idx, "x"],
                net.junction.loc[junction_idx, "y"]
            )
        elif "geo_x" in net.junction.columns:
            return (
                net.junction.loc[junction_idx, "geo_x"],
                net.junction.loc[junction_idx, "geo_y"]
            )
        return (0.0, 0.0)  # Default/Error fallback
    
    def _check_street_alignment(
        self,
        net: pp.pandapipesNet,
        streets_gdf: gpd.GeoDataFrame
    ) -> Dict:
        """Check if pipes follow streets"""
        
        issues = []
        warnings = []
        
        # Create street buffer
        street_buffer = streets_gdf.geometry.buffer(self.config.street_buffer_m)
        street_union = street_buffer.unary_union
        
        pipes_off_street = []
        max_deviation = 0.0
        
        for idx, pipe in net.pipe.iterrows():
            # Get pipe geometry
            from_xy = self._get_xy(net, pipe["from_junction"])
            to_xy = self._get_xy(net, pipe["to_junction"])
            
            # Create pipe line
            pipe_line = LineString([from_xy, to_xy])
            
            # Check if pipe is within street buffer
            if not pipe_line.within(street_union):
                # Calculate deviation
                distance = pipe_line.distance(street_union)
                max_deviation = max(max_deviation, distance)
                
                if distance > self.config.street_buffer_m:
                    if self.config.allow_private_property:
                        warnings.append(
                            f"Pipe {idx} deviates {distance:.1f}m from street (may cross private property)"
                        )
                    else:
                        issues.append(
                            f"Pipe {idx} is {distance:.1f}m from nearest street (exceeds {self.config.street_buffer_m}m tolerance)"
                        )
                        pipes_off_street.append(idx)
        
        # Calculate compliance percentage
        compliance_pct = 100 * (1 - len(pipes_off_street) / len(net.pipe)) if len(net.pipe) > 0 else 100
        
        return {
            "issues": issues,
            "warnings": warnings,
            "metrics": {
                "street_alignment_pct": compliance_pct,
                "pipes_off_street_count": len(pipes_off_street),
                "max_street_deviation_m": max_deviation
            }
        }
    
    def _check_building_connectivity(
        self,
        net: pp.pandapipesNet,
        buildings_gdf: gpd.GeoDataFrame
    ) -> Dict:
        """Check if all buildings are properly connected"""
        
        issues = []
        warnings = []
        
        # Get buildings with heat demand
        # Column is annual_heat_demand_kwh_a
        demand_col = "annual_heat_demand_kwh_a"
        buildings_with_demand = buildings_gdf[buildings_gdf[demand_col] > 0]
        
        # Get connected buildings from heat exchangers AND sinks
        connected_buildings = set()
        connection_distances = []
        
        # Collect all consumer locations (junction indices)
        consumer_junctions = []
        
        # Check heat exchangers
        if "heat_exchanger" in dir(net) and len(net.heat_exchanger) > 0:
            if "bus" in net.heat_exchanger.columns:
                consumer_junctions.extend([(idx, row["bus"], "heat_exchanger") for idx, row in net.heat_exchanger.iterrows()])
            elif "from_junction" in net.heat_exchanger.columns:
                consumer_junctions.extend([(idx, row["from_junction"], "heat_exchanger") for idx, row in net.heat_exchanger.iterrows()])
                
        # Check sinks
        if "sink" in dir(net) and len(net.sink) > 0:
            consumer_junctions.extend([(idx, row["junction"], "sink") for idx, row in net.sink.iterrows()])
            
        for comp_idx, junc_idx, comp_type in consumer_junctions:
            # Use helper for coordinates
            junc_xy = self._get_xy(net, junc_idx)
            junction_point = Point(junc_xy)
            
            distances = buildings_with_demand.geometry.distance(junction_point)
            if len(distances) == 0:
                continue
                
            nearest_building_idx = distances.idxmin()
            nearest_distance = distances.min()
            
            connection_distances.append(nearest_distance)
            
            if nearest_distance < self.config.max_connection_distance_m:
                connected_buildings.add(nearest_building_idx)
            else:
                warnings.append(
                    f"{comp_type} {comp_idx} is {nearest_distance:.1f}m from nearest building (excessive service pipe)"
                )
        
        # Check for unconnected buildings
        required_buildings = set(buildings_with_demand.index)
        unconnected = required_buildings - connected_buildings
        
        if unconnected:
            total_unconnected_kwh = buildings_with_demand.loc[sorted(list(unconnected)), demand_col].sum()
            total_kwh = buildings_with_demand[demand_col].sum()
            
            total_unconnected_demand = total_unconnected_kwh / 1000.0
            total_demand = total_kwh / 1000.0
            
            issues.append(
                f"{len(unconnected)} buildings ({total_unconnected_demand:.1f} MWh/a, "
                f"{100*total_unconnected_demand/total_demand:.1f}% of demand) not connected to network"
            )
        
        # Check connection distance statistics
        if connection_distances:
            avg_connection_dist = np.mean(connection_distances)
            max_connection_dist = np.max(connection_distances)
            
            if max_connection_dist > self.config.max_connection_distance_m:
                warnings.append(
                    f"Maximum service pipe length {max_connection_dist:.1f}m exceeds "
                    f"recommended {self.config.max_connection_distance_m}m"
                )
        else:
            avg_connection_dist = 0
            max_connection_dist = 0
        
        connectivity_pct = 100 * len(connected_buildings) / len(required_buildings) if len(required_buildings) > 0 else 100
        
        return {
            "issues": issues,
            "warnings": warnings,
            "metrics": {
                "building_connectivity_pct": connectivity_pct,
                "connected_buildings_count": len(connected_buildings),
                "unconnected_buildings_count": len(unconnected),
                "avg_service_pipe_length_m": avg_connection_dist,
                "max_service_pipe_length_m": max_connection_dist
            }
        }
    
    def _check_topology_sanity(self, net: pp.pandapipesNet) -> Dict:
        """Check for topology issues"""
        
        issues = []
        warnings = []
        
        # Check for isolated junctions
        connected_junctions = set()
        for idx, pipe in net.pipe.iterrows():
            connected_junctions.add(pipe["from_junction"])
            connected_junctions.add(pipe["to_junction"])
        
        all_junctions = set(net.junction.index)
        isolated_junctions = all_junctions - connected_junctions
        
        if isolated_junctions:
            warnings.append(
                f"{len(isolated_junctions)} isolated junctions found (not connected to any pipe)"
            )
        
        # Check for excessively long pipe segments
        long_segments = []
        for idx, pipe in net.pipe.iterrows():
            length_m = pipe["length_km"] * 1000
            if length_m > self.config.max_segment_length_m:
                long_segments.append((idx, length_m))
        
        if long_segments:
            warnings.append(
                f"{len(long_segments)} pipe segments exceed {self.config.max_segment_length_m}m "
                f"(max: {max(seg[1] for seg in long_segments):.0f}m)"
            )
        
        # Check for disconnected network components
        import networkx as nx
        
        G = nx.Graph()
        for idx, pipe in net.pipe.iterrows():
            G.add_edge(pipe["from_junction"], pipe["to_junction"])
        
        n_components = nx.number_connected_components(G)
        
        if n_components > 1:
            issues.append(
                f"Network has {n_components} disconnected components (must be connected)"
            )
        
        return {
            "issues": issues,
            "warnings": warnings,
            "metrics": {
                "network_components": n_components,
                "isolated_junctions": len(isolated_junctions),
                "long_segments_count": len(long_segments)
            }
        }
