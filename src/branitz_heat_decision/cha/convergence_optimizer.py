import pandapipes as pp
import networkx as nx
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
import logging

from branitz_heat_decision.cha.config import CHAConfig, get_default_config

logger = logging.getLogger(__name__)

class ConvergenceOptimizer:
    """
    Optimizes pandapipes network topology for numerical convergence.
    
    Key insight: Newton-Raphson requires at least one loop to avoid singular matrix.
    For tree networks, we add a minimal high-resistance loop that doesn't affect flow distribution.
    """
    
    def __init__(self, net: pp.pandapipesNet, config: Optional[CHAConfig] = None):
        """
        Initialize optimizer with network.
        
        Args:
            net: pandapipesNet to optimize
            config: CHAConfig with physical parameters
        """
        self.net = net
        self.config = config or get_default_config()
        self.validation_results: Dict[str, Any] = {}
        self.optimization_log: List[Dict[str, Any]] = []
        self.fixes_applied: int = 0
        
        # Build NetworkX graphs for topology analysis
        self.supply_graph = self._build_supply_graph()
        self.return_graph = self._build_return_graph()
        
        # Identify plant node
        self.plant_junction = self._identify_plant_node()
        if self.plant_junction is None:
            raise ValueError("Cannot identify plant junction in network")
        
        logger.info(f"Initialized ConvergenceOptimizer with {len(self.net.junction)} junctions, "
                    f"{len(self.net.pipe)} pipes, plant={self.plant_junction}")
    
    def optimize_for_convergence(
        self,
        max_iterations: int = 3,
        fix_parallel: bool = True,
        fix_loops: bool = True,
        fix_connectivity: bool = True,
        fix_pressures: bool = True,
        fix_short_pipes_flag: bool = True,
        min_length_m: float = 1.0,
        parallel_variation_pct: float = 0.01,
        loop_method: str = "high_resistance",
        virtual_pipe_resistance: float = 100.0,
        plant_pressure_bar: Optional[float] = None,
        pressure_drop_per_m: float = 0.001
    ) -> bool:
        """
        Main optimization loop.
        
        Args:
            max_iterations: Max optimization iterations
            fix_parallel: Fix parallel paths
            fix_loops: Break loops if needed
            fix_connectivity: Ensure all nodes reachable
            fix_pressures: Improve initial pressure distribution
            fix_short_pipes_flag: Fix very short pipes
            min_length_m: Minimum pipe length
            parallel_variation_pct: Roughness variation for parallel paths
            loop_method: "high_resistance" or "remove_pipe"
            virtual_pipe_resistance: mm roughness for virtual pipes
            plant_pressure_bar: Plant pressure (auto-detect if None)
            pressure_drop_per_m: Expected Δp per meter
            
        Returns:
            bool: True if network passes all validation checks
        """
        logger.info("Starting convergence optimization...")
        
        kwargs = {
            'fix_parallel': fix_parallel,
            'fix_loops': fix_loops,
            'fix_connectivity': fix_connectivity,
            'fix_pressures': fix_pressures,
            'fix_short_pipes_flag': fix_short_pipes_flag,
            'min_length_m': min_length_m,
            'parallel_variation_pct': parallel_variation_pct,
            'loop_method': loop_method,
            'virtual_pipe_resistance': virtual_pipe_resistance,
            'plant_pressure_bar': plant_pressure_bar,
            'pressure_drop_per_m': pressure_drop_per_m
        }
        
        for iteration in range(max_iterations):
            logger.info(f"--- Optimization Iteration {iteration + 1}/{max_iterations} ---")
            
            # Run validation
            self.validation_results = self._validate_all()
            
            # If valid, we can stop
            if self.validation_results['is_valid']:
                logger.info("Network passed validation, optimization complete")
                break
            
            # Apply fixes based on validation issues
            fixes_applied_this_iter = self._apply_fixes(
                self.validation_results,
                iteration=iteration,
                **kwargs
            )
            
            if fixes_applied_this_iter == 0:
                logger.warning("No fixes applied this iteration, stopping")
                break
            
            self.fixes_applied += fixes_applied_this_iter
        else:
            logger.warning("Reached max iterations without full validation")
        
        # Final validation
        final_validation = self._validate_all()
        self.optimization_log.append({
            'iteration': iteration,
            'fixes_applied': self.fixes_applied,
            'validation': final_validation
        })
        
        return final_validation['is_valid']
    
    def _build_supply_graph(self) -> nx.Graph:
        """
        Build NetworkX graph from supply network.
        
        Returns:
            Graph where nodes are junction indices, edges are pipes
        """
        G = nx.Graph()
        
        # Add nodes
        for idx in self.net.junction.index:
            geometry = self.net.junction_geodata
            if not geometry.empty and idx in geometry.index:
                coords = (geometry.loc[idx, 'x'], geometry.loc[idx, 'y'])
            else:
                coords = (0, 0)  # Fallback if no geodata
            G.add_node(idx, coords=coords)
        
        # Add edges for supply pipes (from_junction, to_junction)
        for pipe_idx, pipe in self.net.pipe.iterrows():
            G.add_edge(
                pipe['from_junction'],
                pipe['to_junction'],
                pipe_idx=pipe_idx,
                length_km=pipe['length_km'],
                diameter_m=pipe['diameter_m']
            )
        
        return G
    
    def _build_return_graph(self) -> nx.Graph:
        """
        Build NetworkX graph from return network.
        
        Returns:
            Graph for return pipes (same structure as supply for now)
        """
        # For now, return same as supply (can be extended for separate return network)
        return self._build_supply_graph()
    
    def _validate_all(self) -> Dict[str, Any]:
        """
        Run all validation checks.
        
        Returns:
            Dict with:
                is_valid: bool
                issues: List[str]
                warnings: List[str]
                metrics: Dict[str, Any]
        """
        issues = []
        warnings = []
        
        # 1. Check for parallel paths (multiple routes from plant to same sink)
        parallel_score = self._check_parallel_paths()
        if parallel_score > 0.1:  # Threshold: >10% of nodes have parallel paths
            issues.append(f"High parallel path score: {parallel_score:.2f}")
        
        # 2. Check for loops (cycles in graph)
        loop_score = self._check_loops()
        if loop_score > 0:
            warnings.append(f"Network has {loop_score} loops")
        
        # 3. Check connectivity (all nodes reachable from plant)
        disconnected = self._check_connectivity()
        if disconnected:
            issues.append(f"Disconnected components: {len(disconnected)} nodes")
        
        # 4. Check for very short pipes (< 1m)
        short_pipes = self._check_short_pipes()
        if short_pipes:
            warnings.append(f"Short pipes found: {len(short_pipes)}")
        
        # 5. Check pressure consistency
        pressure_ok = self._check_pressure_consistency()
        if not pressure_ok:
            issues.append("Pressure consistency check failed")
        
        is_valid = len(issues) == 0
        
        return {
            'is_valid': is_valid,
            'issues': issues,
            'warnings': warnings,
            'metrics': {
                'parallel_score': parallel_score,
                'loop_score': loop_score,
                'disconnected_count': len(disconnected),
                'short_pipe_count': len(short_pipes)
            }
        }
    
    def _check_parallel_paths(self) -> float:
        """
        Detect parallel flow paths (multiple routes from plant to same sink).
        
        Returns:
            float: Score 0-1 (0=no parallel paths, 1=all nodes have parallel paths)
        """
        # Get all sink nodes (buildings)
        if 'sink' not in self.net or self.net.sink.empty:
            return 0.0
        
        sinks = self.net.sink['junction'].values
        
        parallel_nodes = 0
        
        for sink in sinks:
            # Find all simple paths from plant to sink
            try:
                paths = list(nx.all_simple_paths(self.supply_graph, self.plant_junction, sink))
                if len(paths) > 1:
                    parallel_nodes += 1
            except nx.NetworkXNoPath:
                # Disconnected - will be caught by connectivity check
                continue
        
        return parallel_nodes / len(sinks) if len(sinks) > 0 else 0.0
    
    def _check_loops(self) -> int:
        """
        Count number of cycles (loops) in the network.
        
        Returns:
            int: Number of cycles
        """
        try:
            cycles = list(nx.cycle_basis(self.supply_graph))
            return len(cycles)
        except Exception:
            return 0
    
    def _check_short_pipes(self) -> List[int]:
        """
        Find pipes shorter than minimum length.
        
        Returns:
            List of pipe indices that are too short
        """
        min_length_km = self.config.min_pipe_length_m / 1000.0
        short_pipes = self.net.pipe[self.net.pipe['length_km'] < min_length_km].index.tolist()
        return short_pipes
    
    def _check_pressure_consistency(self) -> bool:
        """
        Check that pressure values are consistent.
        
        Returns:
            bool: True if pressures are valid
        """
        if self.net.junction.empty:
            return False
        
        # Check that all pressures are positive
        if 'pn_bar' in self.net.junction.columns:
            pressures = self.net.junction['pn_bar']
            if (pressures <= 0).any():
                return False
        
        return True
    
    def _apply_fixes(self, validation_results: Dict[str, Any], iteration: int, **kwargs) -> int:
        """
        Apply fixes based on validation issues.
        
        Returns:
            int: Number of fixes applied
        """
        fixes_applied = 0
        
        # Fix 1: Add minimal loop for tree networks
        if validation_results['metrics']['loop_score'] == 0 and iteration == 0:
            logger.info("Network is tree (no loops), adding minimal loop for stability")
            self._add_minimal_loop()
            fixes_applied += 1
        
        # Fix 2: Add roughness variations to break symmetry
        if kwargs.get('fix_parallel') and validation_results['metrics']['parallel_score'] > 0:
            logger.info("Adding roughness variations to break symmetry")
            self._add_roughness_variations(kwargs.get('parallel_variation_pct', 0.01))
            fixes_applied += 1
        
        # Fix 3: Improve initial pressures
        if kwargs.get('fix_pressures'):
            logger.info("Improving initial pressure distribution")
            self._improve_initial_pressures(
                plant_pressure_bar=kwargs.get('plant_pressure_bar'),
                pressure_drop_per_m=kwargs.get('pressure_drop_per_m', 0.001)
            )
            fixes_applied += 1
        
        # Fix 4: Fix short pipes
        if kwargs.get('fix_short_pipes_flag'):
            short_pipes = self._check_short_pipes()
            if short_pipes:
                logger.info(f"Fixing {len(short_pipes)} short pipes")
                self._fix_short_pipes(kwargs.get('min_length_m', 1.0))
                fixes_applied += 1
        
        # Fix 5: Ensure connectivity (add virtual pipes if needed)
        if kwargs.get('fix_connectivity'):
            disconnected = self._check_connectivity()
            if disconnected:
                logger.info(f"Fixing connectivity for {len(disconnected)} nodes")
                self._add_virtual_pipes(disconnected, kwargs.get('virtual_pipe_resistance', 100.0))
                fixes_applied += 1
        
        return fixes_applied
    
    def _add_minimal_loop(self):
        """
        Add a minimal high-resistance loop to tree network.
        
        Strategy:
        - Find the two farthest sink junctions
        - Connect them with a short pipe (10m)
        - Use very high roughness (100mm) so loop carries negligible flow
        - This satisfies solver's mathematical requirement without affecting flow distribution
        """
        # Find farthest sinks from plant
        if 'sink' not in self.net or self.net.sink.empty:
            logger.warning("No sinks found, cannot create loop")
            return
        
        sinks = self.net.sink['junction'].values
        if len(sinks) < 2:
            logger.warning("Not enough sinks to create loop")
            return
        
        # Compute distances from plant (shortest path lengths)
        try:
            distances = nx.single_source_shortest_path_length(self.supply_graph, self.plant_junction)
        except Exception:
            logger.warning("Could not compute distances from plant")
            return
        
        # Get two farthest sinks
        sink_distances = {sink: distances.get(sink, 0) for sink in sinks}
        farthest_sinks = sorted(sink_distances.items(), key=lambda x: x[1], reverse=True)[:2]
        
        if len(farthest_sinks) < 2:
            logger.warning("Could not find two farthest sinks")
            return
        
        sink1, dist1 = farthest_sinks[0]
        sink2, dist2 = farthest_sinks[1]
        
        logger.info(f"Creating minimal loop between sinks {sink1} (dist={dist1:.1f}) and {sink2} (dist={dist2:.1f})")
        
        # Get coordinates
        geom = self.net.junction_geodata
        if not geom.empty and sink1 in geom.index and sink2 in geom.index:
            x1, y1 = geom.loc[sink1, ['x', 'y']].values
            x2, y2 = geom.loc[sink2, ['x', 'y']].values
        else:
            # Fallback: use plant coordinates
            x1, y1 = 0, 0
            x2, y2 = 10, 0
        
        # Add junctions for loop connection
        loop_junction_1 = pp.create_junction(
            self.net,
            pn_bar=self.config.system_pressure_bar,
            tfluid_k=self.config.supply_temp_k,
            name=f"loop_junc_{sink1}",
            geodata=(x1, y1)
        )
        
        loop_junction_2 = pp.create_junction(
            self.net,
            pn_bar=self.config.system_pressure_bar,
            tfluid_k=self.config.supply_temp_k,
            name=f"loop_junc_{sink2}",
            geodata=(x2, y2)
        )
        
        # Connect sinks to loop junctions (very short pipes)
        pp.create_pipe(
            self.net,
            from_junction=sink1,
            to_junction=loop_junction_1,
            length_km=0.001,  # 1m
            diameter_m=0.05,  # DN50
            k_mm=100.0,       # Very high roughness → negligible flow
            name=f"loop_connect_{sink1}"
        )
        
        pp.create_pipe(
            self.net,
            from_junction=sink2,
            to_junction=loop_junction_2,
            length_km=0.001,  # 1m
            diameter_m=0.05,  # DN50
            k_mm=100.0,       # Very high roughness → negligible flow
            name=f"loop_connect_{sink2}"
        )
        
        # Add the loop pipe (10m, very high resistance)
        loop_pipe = pp.create_pipe(
            self.net,
            from_junction=loop_junction_1,
            to_junction=loop_junction_2,
            length_km=0.01,   # 10m
            diameter_m=0.05,  # DN50
            k_mm=100.0,       # Very high roughness
            name="minimal_loop"
        )
        
        logger.info(f"Added minimal loop (pipe index: {loop_pipe})")
    
    def _add_roughness_variations(self, variation_pct: float = 0.01):
        """
        Add small random variations to pipe roughness to prevent numerical singularity.
        
        Args:
            variation_pct: Percentage variation (e.g., 0.01 = 1%)
        """
        np.random.seed(42)  # For reproducibility
        
        for pipe_idx, pipe in self.net.pipe.iterrows():
            # Skip pipes that already have high roughness (like our loop)
            if pipe['k_mm'] > 10.0:
                continue
            
            # Add small random variation
            variation = np.random.uniform(-variation_pct, variation_pct)
            new_roughness = pipe['k_mm'] * (1 + variation)
            
            self.net.pipe.loc[pipe_idx, 'k_mm'] = new_roughness
        
        logger.info(f"Applied {variation_pct*100:.2f}% roughness variations to {len(self.net.pipe)} pipes")
    
    def _improve_initial_pressures(
        self,
        plant_pressure_bar: Optional[float] = None,
        pressure_drop_per_m: float = 0.001
    ):
        """
        Set better initial pressures based on distance from plant.
        
        Args:
            plant_pressure_bar: Plant pressure (detect if None)
            pressure_drop_per_m: Expected pressure drop per meter (bar/m)
        """
        if plant_pressure_bar is None:
            # Detect from plant junction
            if 'source' in self.net and not self.net.source.empty:
                plant_junction_idx = self.net.source['junction'].iloc[0]
            else:
                plant_junction_idx = self.plant_junction
            plant_pressure_bar = self.net.junction.loc[plant_junction_idx, 'pn_bar']
        
        # Compute distances from plant
        try:
            distances = nx.single_source_shortest_path_length(self.supply_graph, self.plant_junction)
        except Exception:
            logger.warning("Could not compute distances for pressure initialization")
            return
        
        # Set initial pressures (decrease with distance)
        for junction_idx in self.net.junction.index:
            if junction_idx == self.plant_junction:
                if 'pinit' in self.net.junction.columns:
                    self.net.junction.loc[junction_idx, 'pinit'] = plant_pressure_bar
            elif junction_idx in distances:
                distance_m = distances[junction_idx]
                pressure_drop = distance_m * pressure_drop_per_m
                initial_pressure = max(1.0, plant_pressure_bar - pressure_drop)
                if 'pinit' in self.net.junction.columns:
                    self.net.junction.loc[junction_idx, 'pinit'] = initial_pressure
        
        logger.info(f"Improved initial pressures for {len(distances)} junctions")
    
    def _check_connectivity(self) -> List[int]:
        """
        Check that all junctions are reachable from plant.
        
        Returns:
            List of disconnected junction indices
        """
        try:
            reachable = set(nx.descendants(self.supply_graph, self.plant_junction))
            reachable.add(self.plant_junction)  # Include plant itself
            all_junctions = set(self.net.junction.index)
            disconnected = list(all_junctions - reachable)
            
            if disconnected:
                logger.warning(f"Found {len(disconnected)} disconnected junctions: {disconnected[:10]}...")
            
            return disconnected
        except Exception:
            # If graph is empty or plant not in graph, all are disconnected
            return list(self.net.junction.index)
    
    def _fix_short_pipes(self, min_length_m: float = 1.0):
        """
        Fix pipes shorter than minimum length by lengthening them.
        
        Args:
            min_length_m: Minimum allowed pipe length in meters
        """
        min_length_km = min_length_m / 1000.0
        short_pipes = self.net.pipe[self.net.pipe['length_km'] < min_length_km].index
        
        for pipe_idx in short_pipes:
            current_length_m = self.net.pipe.loc[pipe_idx, 'length_km'] * 1000
            new_length_km = min_length_m / 1000
            
            self.net.pipe.loc[pipe_idx, 'length_km'] = new_length_km
            
            logger.debug(f"Extended pipe {pipe_idx} from {current_length_m:.2f}m to {min_length_m}m")
        
        if len(short_pipes):
            logger.info(f"Fixed {len(short_pipes)} short pipes (< {min_length_m}m)")
    
    def _add_virtual_pipes(self, disconnected: List[int], resistance: float = 100.0):
        """
        Add virtual high-resistance pipes to connect disconnected nodes to plant.
        
        Args:
            disconnected: List of disconnected junction indices
            resistance: Roughness (mm) for virtual pipes
        """
        for junction_idx in disconnected:
            # Connect to nearest reachable junction
            try:
                # Find nearest junction that is reachable
                reachable = set(nx.descendants(self.supply_graph, self.plant_junction))
                reachable.add(self.plant_junction)
                
                if not reachable:
                    # Connect directly to plant
                    target = self.plant_junction
                else:
                    # Find nearest reachable junction (simplified: use plant)
                    target = self.plant_junction
                
                # Get coordinates
                geom = self.net.junction_geodata
                if not geom.empty and junction_idx in geom.index and target in geom.index:
                    x1, y1 = geom.loc[junction_idx, ['x', 'y']].values
                    x2, y2 = geom.loc[target, ['x', 'y']].values
                    length_m = np.sqrt((x2-x1)**2 + (y2-y1)**2)
                else:
                    length_m = 10.0  # Default
                
                # Add virtual pipe
                pp.create_pipe(
                    self.net,
                    from_junction=target,
                    to_junction=junction_idx,
                    length_km=length_m / 1000.0,
                    diameter_m=0.05,
                    k_mm=resistance,
                    name=f"virtual_connect_{junction_idx}"
                )
                
                logger.debug(f"Added virtual pipe connecting {junction_idx} to {target}")
            except Exception as e:
                logger.warning(f"Could not add virtual pipe for {junction_idx}: {e}")
    
    def _identify_plant_node(self) -> Optional[int]:
        """
        Identify plant/source junction in network.
        
        Returns:
            Junction index of plant, or None if not found
        """
        # Try to find from source component
        if 'source' in self.net and not self.net.source.empty:
            return self.net.source['junction'].iloc[0]
        
        # Try to find junction with 'is_plant' flag
        if 'is_plant' in self.net.junction.columns:
            plant_junctions = self.net.junction[self.net.junction['is_plant']].index
            if len(plant_junctions) == 1:
                return plant_junctions[0]
        
        # Fallback: junction with highest pressure
        if not self.net.junction.empty and 'pn_bar' in self.net.junction.columns:
            return self.net.junction.loc[self.net.junction['pn_bar'].idxmax()].name
        
        return None
    
    def get_optimized_network(self) -> pp.pandapipesNet:
        """Return the optimized network."""
        return self.net
    
    def get_optimization_summary(self) -> Dict[str, Any]:
        """
        Get summary of optimization actions.
        
        Returns:
            Dict with:
                - iterations: int
                - fixes_applied: int
                - fixes_by_type: Dict[str, int]
                - final_validation: Dict[str, bool]
        """
        return {
            'iterations': len(self.optimization_log),
            'fixes_applied': self.fixes_applied,
            'optimization_log': self.optimization_log,
            'final_validation': self.validation_results
        }


def optimize_network_for_convergence(
    net: pp.pandapipesNet,
    config: Optional[CHAConfig] = None,
    max_iterations: int = 3,
    **kwargs
) -> Tuple[bool, pp.pandapipesNet, Dict[str, Any]]:
    """
    Convenience function: optimize network and return results.
    
    Args:
        net: pandapipesNet to optimize
        config: CHAConfig
        max_iterations: Max optimization loops
        
    Returns:
        Tuple of (converged: bool, optimized_net: pandapipesNet, summary: dict)
    """
    optimizer = ConvergenceOptimizer(net, config)
    converged = optimizer.optimize_for_convergence(max_iterations=max_iterations, **kwargs)
    
    return (
        converged,
        optimizer.get_optimized_network(),
        optimizer.get_optimization_summary()
    )
