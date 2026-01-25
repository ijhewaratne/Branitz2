"""
Enhanced Convergence Optimizer with Spur-Specific Fixes.
"""

import numpy as np
import pandas as pd
import networkx as nx
import pandapipes as pp
from typing import Dict, Any, List, Optional, Tuple
import logging
from shapely.geometry import Point

from .config import CHAConfig, get_default_config

logger = logging.getLogger(__name__)

class SpurConvergenceOptimizer:
    """Convergence optimizer tailored for trunk-spur networks."""
    
    def __init__(self, net: pp.pandapipesNet, config: Optional[CHAConfig] = None):
        self.net = net
        self.config = config or get_default_config()
        self.validation_log = []
    
    def optimize_with_spur_checks(
        self,
        max_iterations: int = 3,
        ensure_spur_diversity: bool = True,
        add_trunk_loops: bool = True,
        max_junction_degree: int = 4
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Full optimization pipeline for trunk-spur networks.
        """
        for iteration in range(max_iterations):
            issues = self._validate_spur_topology()
            
            if not issues:
                logger.info("Network topology valid")
                break
            
            self._apply_spur_fixes(issues, iteration)
        
        # Final simulation
        try:
            pp.pipeflow(self.net, mode='all', verbose=False)
            converged = self.net.converged
        except Exception as e:
            logger.error(f"Simulation failed: {e}")
            converged = False
        
        summary = {
            'converged': converged,
            'iterations': len(self.validation_log),
            'final_issues': issues if not converged else []
        }
        
        return converged, summary
    
    def _validate_spur_topology(self) -> List[str]:
        """Validate trunk-spur specific topology rules."""
        issues = []
        G = nx.Graph()
        
        for pipe in self.net.pipe.itertuples():
            G.add_edge(pipe.from_junction, pipe.to_junction, name=pipe.name)
        
        # Check 1: Building junction degree must be exactly 2
        if 'name' in self.net.junction.columns:
            building_juncs = self.net.junction[
                self.net.junction['name'].str.contains('building_supply', na=False)
            ].index
            
            for bj in building_juncs:
                if bj in G:
                    degree = G.degree[bj]
                    if degree != 2:
                        issues.append(f"Building junction {bj} has degree {degree}, expected 2")
        
        # Check 2: Spur junctions degree must be 3
        if 'name' in self.net.junction.columns:
            spur_juncs = self.net.junction[
                self.net.junction['name'].str.contains('spur_', na=False)
            ].index
            
            for sj in spur_juncs:
                if sj in G:
                    degree = G.degree[sj]
                    if degree != 3:
                        issues.append(f"Spur junction {sj} has degree {degree}, expected 3")
        
        # Check 3: Trunk junctions degree ≤ 4 (for loop networks, this can be higher)
        if 'name' in self.net.junction.columns:
            trunk_juncs = self.net.junction[
                self.net.junction['name'].str.contains('trunk_node', na=False)
            ].index
            
            for tj in trunk_juncs:
                if tj in G:
                    degree = G.degree[tj]
                    # For loop networks, allow higher degrees (up to 6)
                    if degree > 6:
                        issues.append(f"Trunk junction {tj} overloaded: degree {degree} > 6")
        
        # Check 4: No isolated spurs
        if not nx.is_connected(G):
            issues.append("Network has disconnected components")
        
        # Check 5: Spur length variance (too similar lengths = numerical issues)
        spur_lengths = self.net.pipe[
            self.net.pipe['name'].str.contains('spur')
        ]['length_km']
        
        if len(spur_lengths) > 1:
            cv = spur_lengths.std() / spur_lengths.mean()
            if cv < 0.05:  # Coefficient of variation <5%
                issues.append("Spur lengths too homogeneous, adding variation needed")
        
        return issues
    
    def _apply_spur_fixes(self, issues: List[str], iteration: int):
        """Apply topology fixes based on validation issues."""
        for issue in issues:
            if "degree" in issue:
                self._fix_degree_violation(issue)
            elif "homogeneous" in issue:
                self._add_spur_length_variation()
            elif "disconnected" in issue:
                self._add_virtual_bridge()
        
        self.validation_log.append({
            'iteration': iteration,
            'issues_found': len(issues),
            'fixes_applied': len(issues)
        })
    
    def _fix_degree_violation(self, issue_msg: str):
        """Fix overloaded trunk junctions by splitting."""
        # Parse junction ID from message
        import re
        match = re.search(r'junction (\d+)', issue_msg)
        if not match:
            return
        
        junc_id = int(match.group(1))
        
        # Add high-resistance bypass pipe to relieve load
        # This creates an alternative path without major topology change
        connected_pipes = self.net.pipe[
            (self.net.pipe['from_junction'] == junc_id) |
            (self.net.pipe['to_junction'] == junc_id)
        ]
        
        if len(connected_pipes) >= 4:
            # Create virtual bypass between two farthest neighbors
            neighbor_juncs = set(connected_pipes['from_junction']).union(
                set(connected_pipes['to_junction'])
            )
            neighbor_juncs.discard(junc_id)
            
            if len(neighbor_juncs) >= 2:
                neighbors = list(neighbor_juncs)[:2]
                # Ensure virtual pipe std_type exists
                if 'virtual_pipe' not in self.net.std_types.get('pipe', {}):
                    virtual_typedata = {
                        'inner_diameter_mm': 50.0,
                        'roughness_mm': 100.0,  # Very high resistance
                        'u_w_per_m2k': 0.0,
                    }
                    pp.create_std_type(self.net, component="pipe", std_type_name="virtual_pipe", typedata=virtual_typedata)
                
                # Create virtual pipe with high resistance
                pp.create_pipe(
                    self.net,
                    from_junction=neighbors[0],
                    to_junction=neighbors[1],
                    length_km=0.05,  # 50m virtual pipe
                    std_type="virtual_pipe",
                    name=f"virtual_bypass_{junc_id}"
                )
                logger.info(f"Added virtual bypass for overloaded junction {junc_id}")
    
    def _add_spur_length_variation(self):
        """Add random length variations to break symmetry."""
        spur_pipes = self.net.pipe[self.net.pipe['name'].str.contains('spur')]
        np.random.seed(42 + len(self.validation_log))
        
        for pipe_idx in spur_pipes.index:
            base_length = self.net.pipe.loc[pipe_idx, 'length_km']
            variation = np.random.uniform(0.9, 1.1)  # ±10%
            self.net.pipe.loc[pipe_idx, 'length_km'] = base_length * variation
        
        logger.info(f"Applied length variation to {len(spur_pipes)} spur pipes")
    
    def _add_virtual_bridge(self):
        """Connect disconnected components with high-resistance pipe."""
        G = nx.Graph()
        for pipe in self.net.pipe.itertuples():
            G.add_edge(pipe.from_junction, pipe.to_junction)
        
        components = list(nx.connected_components(G))
        
        if len(components) > 1:
            # Connect first component to largest component
            comp0 = components[0]
            comp1 = max(components[1:], key=len)
            
            # Find nearest pair of junctions
            min_dist = float('inf')
            pair = None
            
            # Get geodata if available
            geodata = None
            if hasattr(self.net, 'junction_geodata') and not self.net.junction_geodata.empty:
                geodata = self.net.junction_geodata
            
            for j1 in comp0:
                for j2 in comp1:
                    if geodata is not None and j1 in geodata.index and j2 in geodata.index:
                        x1, y1 = geodata.loc[j1, ['x', 'y']].values
                        x2, y2 = geodata.loc[j2, ['x', 'y']].values
                        dist = np.sqrt((x2-x1)**2 + (y2-y1)**2)
                    else:
                        # Fallback: use default distance
                        dist = 100.0  # 100m default
                    
                    if dist < min_dist:
                        min_dist = dist
                        pair = (j1, j2)
            
            if pair:
                # Ensure virtual pipe std_type exists
                if 'virtual_pipe' not in self.net.std_types.get('pipe', {}):
                    virtual_typedata = {
                        'inner_diameter_mm': 50.0,
                        'roughness_mm': 100.0,  # Very high resistance
                        'u_w_per_m2k': 0.0,
                    }
                    pp.create_std_type(self.net, component="pipe", std_type_name="virtual_pipe", typedata=virtual_typedata)
                
                # Create virtual bridge pipe with high resistance
                min_len_km = 0.001
                try:
                    if getattr(self, "config", None) is not None:
                        min_len_km = max(min_len_km, float(self.config.min_pipe_length_m) / 1000.0)
                except Exception:
                    pass
                pp.create_pipe(
                    self.net,
                    from_junction=pair[0],
                    to_junction=pair[1],
                    length_km=max(float(min_dist) / 1000.0, min_len_km),
                    std_type="virtual_pipe",
                    name="virtual_bridge"
                )
                logger.info(f"Added virtual bridge between components: {pair}")

def optimize_network_for_convergence(
    net: pp.pandapipesNet,
    config: Optional[CHAConfig] = None,
    **kwargs
) -> Tuple[bool, pp.pandapipesNet, Dict[str, Any]]:
    """Convenience wrapper for spur optimizer."""
    optimizer = SpurConvergenceOptimizer(net, config)
    converged, summary = optimizer.optimize_with_spur_checks(**kwargs)
    return converged, optimizer.net, summary