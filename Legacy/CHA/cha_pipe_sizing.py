"""
CHA Pipe Sizing Engine - Intelligent Pipe Sizing for District Heating Networks

This module implements intelligent pipe sizing based on flow rates, engineering standards,
and economic optimization for district heating networks.

Author: Branitz Energy Decision AI
Version: 1.0.0
"""

from __future__ import annotations
import math
import json
from typing import Dict, List, Optional, Tuple, Union
from dataclasses import dataclass
from pathlib import Path
import warnings

warnings.filterwarnings("ignore")


@dataclass
class PipeSizingResult:
    """Result of pipe sizing calculation."""
    diameter_m: float
    diameter_nominal: str
    velocity_ms: float
    pressure_drop_bar: float
    pressure_drop_pa_per_m: float
    reynolds_number: float
    friction_factor: float
    cost_per_m_eur: float
    total_cost_eur: float
    standards_compliance: Dict[str, bool]
    violations: List[str]
    recommendations: List[str]


@dataclass
class PipeCategory:
    """Pipe category definition with constraints."""
    name: str
    diameter_range_m: Tuple[float, float]
    velocity_limit_ms: float
    pressure_drop_limit_pa_per_m: float
    typical_flow_range_kg_s: Tuple[float, float]
    material: str
    insulation_required: bool


class CHAPipeSizingEngine:
    """
    Intelligent Pipe Sizing Engine for District Heating Networks.
    
    Implements flow-based diameter calculation with engineering standards compliance,
    network hierarchy consideration, and economic optimization.
    """
    
    def __init__(self, config: dict):
        """
        Initialize the pipe sizing engine.
        
        Args:
            config: Configuration dictionary with sizing parameters
        """
        self.config = config
        
        # Standard pipe diameters in meters (DN series)
        self.standard_diameters_mm = [25, 32, 40, 50, 63, 80, 100, 125, 150, 200, 250, 300, 400]
        self.standard_diameters_m = [d/1000 for d in self.standard_diameters_mm]
        
        # Default constraints (can be overridden by config)
        self.max_velocity_ms = config.get('max_velocity_ms', 2.0)
        self.min_velocity_ms = config.get('min_velocity_ms', 0.1)
        self.max_pressure_drop_pa_per_m = config.get('max_pressure_drop_pa_per_m', 5000)  # 0.5 bar/100m
        self.min_pressure_drop_pa_per_m = config.get('min_pressure_drop_pa_per_m', 100)   # 0.01 bar/100m
        
        # Auto-resize configuration
        auto_resize_config = config.get('auto_resize', {})
        self.auto_resize_enabled = auto_resize_config.get('enabled', True)
        self.max_resize_iterations = auto_resize_config.get('max_iterations', 3)
        self.sizing_priority = auto_resize_config.get('sizing_priority', ['services', 'distribution', 'mains'])
        self.monotone_sizing = auto_resize_config.get('monotone_sizing', True)
        
        # Standards limits (corrected values from user feedback)
        standards_limits = config.get('standards_limits', {})
        self.standards_limits = {
            'pressure_drop_pa_per_m': standards_limits.get('pressure_drop_pa_per_m', {
                'mains': 300,
                'distribution': 400,
                'services': 500
            }),
            'velocity_ms': standards_limits.get('velocity_ms', {
                'mains': 2.0,
                'distribution': 2.0,
                'services': 1.5
            })
        }
        
        # Water properties at 70°C
        self.water_density_kg_m3 = 977.8
        self.water_dynamic_viscosity_pa_s = 0.000404
        self.water_kinematic_viscosity_m2_s = self.water_dynamic_viscosity_pa_s / self.water_density_kg_m3
        
        # Pipe material properties
        self.pipe_roughness_mm = config.get('pipe_roughness_mm', 0.1)
        self.pipe_roughness_m = self.pipe_roughness_mm / 1000
        
        # Cost factors (EUR per meter)
        self.cost_factors = config.get('cost_factors', {
            'base_cost_per_mm_diameter': 0.5,  # EUR per mm of diameter per meter
            'installation_factor': 1.5,        # Installation cost multiplier
            'insulation_cost_per_m': 15.0,     # Insulation cost per meter
            'material_factor': 1.0             # Material cost factor
        })
        
        # Define pipe categories
        self.pipe_categories = self._define_pipe_categories()
        
        # Standards compliance
        self.standards = self._define_standards()
    
    def _define_pipe_categories(self) -> Dict[str, PipeCategory]:
        """Define pipe categories with their constraints."""
        return {
            'service_connection': PipeCategory(
                name='service_connection',
                diameter_range_m=(0.025, 0.050),
                velocity_limit_ms=self.standards_limits['velocity_ms']['services'],  # 1.5 m/s
                pressure_drop_limit_pa_per_m=self.standards_limits['pressure_drop_pa_per_m']['services'],  # 500 Pa/m
                typical_flow_range_kg_s=(0.1, 2.0),
                material='steel_or_plastic',
                insulation_required=True
            ),
            'distribution_pipe': PipeCategory(
                name='distribution_pipe',
                diameter_range_m=(0.063, 0.150),
                velocity_limit_ms=self.standards_limits['velocity_ms']['distribution'],  # 2.0 m/s
                pressure_drop_limit_pa_per_m=self.standards_limits['pressure_drop_pa_per_m']['distribution'],  # 400 Pa/m
                typical_flow_range_kg_s=(2.0, 20.0),
                material='steel',
                insulation_required=True
            ),
            'main_pipe': PipeCategory(
                name='main_pipe',
                diameter_range_m=(0.200, 0.400),
                velocity_limit_ms=self.standards_limits['velocity_ms']['mains'],  # 2.0 m/s
                pressure_drop_limit_pa_per_m=self.standards_limits['pressure_drop_pa_per_m']['mains'],  # 300 Pa/m
                typical_flow_range_kg_s=(10.0, 100.0),
                material='steel',
                insulation_required=True
            )
        }
    
    def _define_standards(self) -> Dict[str, Dict]:
        """Define engineering standards for compliance checking."""
        return {
            'EN_13941': {
                'max_velocity_ms': 2.0,
                'max_pressure_drop_pa_per_m': 500,  # Corrected: 500 Pa/m (0.05 bar/100m)
                'min_velocity_ms': 0.1,
                'temperature_range_c': (40, 90),
                'pressure_range_bar': (2, 16)
            },
            'DIN_1988': {
                'main_pipes_velocity_ms': self.standards_limits['velocity_ms']['mains'],  # 2.0 m/s
                'distribution_velocity_ms': self.standards_limits['velocity_ms']['distribution'],  # 2.0 m/s
                'service_velocity_ms': self.standards_limits['velocity_ms']['services'],  # 1.5 m/s
                'main_pipes_pressure_drop_pa_per_m': self.standards_limits['pressure_drop_pa_per_m']['mains'],  # 300 Pa/m
                'distribution_pressure_drop_pa_per_m': self.standards_limits['pressure_drop_pa_per_m']['distribution'],  # 400 Pa/m
                'service_pressure_drop_pa_per_m': self.standards_limits['pressure_drop_pa_per_m']['services']  # 500 Pa/m
            }
        }
    
    def calculate_required_diameter(self, flow_rate_kg_s: float, 
                                  pipe_category: str = 'distribution_pipe') -> float:
        """
        Calculate minimum required diameter for given flow rate.
        
        Args:
            flow_rate_kg_s: Mass flow rate in kg/s
            pipe_category: Pipe category ('service_connection', 'distribution_pipe', 'main_pipe')
        
        Returns:
            required_diameter_m: Minimum required diameter in meters
        """
        if flow_rate_kg_s <= 0:
            raise ValueError("Flow rate must be positive")
        
        category = self.pipe_categories[pipe_category]
        
        # Calculate diameter based on velocity constraint
        # v = Q / A = (m_dot / rho) / (π * D² / 4)
        # D = sqrt(4 * m_dot / (rho * π * v))
        max_velocity = category.velocity_limit_ms
        required_diameter_velocity = math.sqrt(
            4 * flow_rate_kg_s / (self.water_density_kg_m3 * math.pi * max_velocity)
        )
        
        # Calculate diameter based on pressure drop constraint
        # Use iterative approach for pressure drop constraint
        required_diameter_pressure = self._calculate_diameter_for_pressure_drop(
            flow_rate_kg_s, category.pressure_drop_limit_pa_per_m
        )
        
        # Take the larger of the two constraints
        required_diameter_m = max(required_diameter_velocity, required_diameter_pressure)
        
        # Ensure within category range
        min_diameter, max_diameter = category.diameter_range_m
        required_diameter_m = max(min_diameter, min(required_diameter_m, max_diameter))
        
        return required_diameter_m
    
    def _calculate_diameter_for_pressure_drop(self, flow_rate_kg_s: float, 
                                            max_pressure_drop_pa_per_m: float) -> float:
        """
        Calculate diameter based on pressure drop constraint using iterative method.
        
        Args:
            flow_rate_kg_s: Mass flow rate in kg/s
            max_pressure_drop_pa_per_m: Maximum allowed pressure drop in Pa/m
        
        Returns:
            diameter_m: Required diameter in meters
        """
        # Initial guess
        diameter_m = 0.1
        
        # Iterative solution
        for _ in range(20):  # Maximum 20 iterations
            velocity_ms = self._calculate_velocity(flow_rate_kg_s, diameter_m)
            reynolds = self._calculate_reynolds_number(velocity_ms, diameter_m)
            friction_factor = self._calculate_friction_factor(reynolds, diameter_m)
            
            # Calculate pressure drop
            pressure_drop_pa_per_m = (
                friction_factor * (1 / diameter_m) * 
                (self.water_density_kg_m3 * velocity_ms**2) / 2
            )
            
            # Check if within tolerance
            if abs(pressure_drop_pa_per_m - max_pressure_drop_pa_per_m) < 10:  # 10 Pa/m tolerance
                break
            
            # Adjust diameter
            if pressure_drop_pa_per_m > max_pressure_drop_pa_per_m:
                # Increase diameter to reduce pressure drop
                diameter_m *= 1.1
            else:
                # Decrease diameter to increase pressure drop
                diameter_m *= 0.95
        
        return diameter_m
    
    def select_standard_diameter(self, required_diameter_m: float, 
                               pipe_category: str = 'distribution_pipe') -> float:
        """
        Select next larger standard diameter.
        
        Args:
            required_diameter_m: Required diameter in meters
            pipe_category: Pipe category for diameter range constraints
        
        Returns:
            standard_diameter_m: Selected standard diameter in meters
        """
        category = self.pipe_categories[pipe_category]
        min_diameter, max_diameter = category.diameter_range_m
        
        # Filter standard diameters within category range
        available_diameters = [
            d for d in self.standard_diameters_m 
            if min_diameter <= d <= max_diameter
        ]
        
        if not available_diameters:
            raise ValueError(f"No standard diameters available for category {pipe_category}")
        
        # Find smallest standard diameter that meets requirement
        for diameter in available_diameters:
            if diameter >= required_diameter_m:
                return diameter
        
        # If no diameter meets requirement, return largest available
        return max(available_diameters)
    
    def validate_hydraulic_constraints(self, pipe_data: dict) -> dict:
        """
        Validate velocity and pressure drop constraints.
        
        Args:
            pipe_data: Dictionary with pipe information
        
        Returns:
            validation_result: Dictionary with validation results
        """
        flow_rate_kg_s = pipe_data['flow_rate_kg_s']
        diameter_m = pipe_data['diameter_m']
        length_m = pipe_data.get('length_m', 100)  # Default 100m
        pipe_category = pipe_data.get('pipe_category', 'distribution_pipe')
        
        # Calculate hydraulic parameters
        velocity_ms = self._calculate_velocity(flow_rate_kg_s, diameter_m)
        reynolds = self._calculate_reynolds_number(velocity_ms, diameter_m)
        friction_factor = self._calculate_friction_factor(reynolds, diameter_m)
        pressure_drop_pa_per_m = self._calculate_pressure_drop_per_meter(
            flow_rate_kg_s, diameter_m, friction_factor
        )
        pressure_drop_bar = (pressure_drop_pa_per_m * length_m) / 100000
        
        # Get category constraints
        category = self.pipe_categories[pipe_category]
        
        # Validate constraints
        violations = []
        recommendations = []
        
        # Velocity validation
        if velocity_ms > category.velocity_limit_ms:
            violations.append(f"Velocity {velocity_ms:.2f} m/s exceeds limit {category.velocity_limit_ms} m/s")
            recommendations.append("Consider increasing pipe diameter")
        elif velocity_ms < self.min_velocity_ms:
            violations.append(f"Velocity {velocity_ms:.2f} m/s below minimum {self.min_velocity_ms} m/s")
            recommendations.append("Consider decreasing pipe diameter")
        
        # Pressure drop validation
        if pressure_drop_pa_per_m > category.pressure_drop_limit_pa_per_m:
            violations.append(f"Pressure drop {pressure_drop_pa_per_m:.0f} Pa/m exceeds limit {category.pressure_drop_limit_pa_per_m} Pa/m")
            recommendations.append("Consider increasing pipe diameter")
        
        # Standards compliance
        standards_compliance = self._check_standards_compliance(
            velocity_ms, pressure_drop_pa_per_m, pipe_category
        )
        
        return {
            'velocity_ms': velocity_ms,
            'pressure_drop_pa_per_m': pressure_drop_pa_per_m,
            'pressure_drop_bar': pressure_drop_bar,
            'reynolds_number': reynolds,
            'friction_factor': friction_factor,
            'violations': violations,
            'recommendations': recommendations,
            'standards_compliance': standards_compliance,
            'compliant': len(violations) == 0
        }
    
    def _check_standards_compliance(self, velocity_ms: float, 
                                  pressure_drop_pa_per_m: float, 
                                  pipe_category: str) -> Dict[str, bool]:
        """Check compliance with engineering standards."""
        compliance = {}
        
        # EN 13941 compliance
        en_13941 = self.standards['EN_13941']
        compliance['EN_13941'] = (
            velocity_ms <= en_13941['max_velocity_ms'] and
            velocity_ms >= en_13941['min_velocity_ms'] and
            pressure_drop_pa_per_m <= en_13941['max_pressure_drop_pa_per_m']
        )
        
        # DIN 1988 compliance
        din_1988 = self.standards['DIN_1988']
        if pipe_category == 'main_pipe':
            compliance['DIN_1988'] = (
                velocity_ms <= din_1988['main_pipes_velocity_ms'] and
                pressure_drop_pa_per_m <= din_1988['main_pipes_pressure_drop_pa_per_m']
            )
        elif pipe_category == 'distribution_pipe':
            compliance['DIN_1988'] = (
                velocity_ms <= din_1988['distribution_velocity_ms'] and
                pressure_drop_pa_per_m <= din_1988['distribution_pressure_drop_pa_per_m']
            )
        elif pipe_category == 'service_connection':
            compliance['DIN_1988'] = (
                velocity_ms <= din_1988['service_velocity_ms'] and
                pressure_drop_pa_per_m <= din_1988['service_pressure_drop_pa_per_m']
            )
        
        return compliance
    
    def calculate_pipe_cost(self, diameter_m: float, length_m: float, 
                          pipe_category: str = 'distribution_pipe') -> float:
        """
        Calculate pipe cost based on diameter and length.
        
        Args:
            diameter_m: Pipe diameter in meters
            length_m: Pipe length in meters
            pipe_category: Pipe category for cost factors
        
        Returns:
            total_cost_eur: Total cost in EUR
        """
        diameter_mm = diameter_m * 1000
        
        # Base material cost
        base_cost_per_m = (
            self.cost_factors['base_cost_per_mm_diameter'] * 
            diameter_mm * 
            self.cost_factors['material_factor']
        )
        
        # Installation cost
        installation_cost_per_m = base_cost_per_m * self.cost_factors['installation_factor']
        
        # Insulation cost (if required)
        category = self.pipe_categories[pipe_category]
        insulation_cost_per_m = (
            self.cost_factors['insulation_cost_per_m'] 
            if category.insulation_required else 0
        )
        
        # Total cost per meter
        total_cost_per_m = base_cost_per_m + installation_cost_per_m + insulation_cost_per_m
        
        # Total cost
        total_cost_eur = total_cost_per_m * length_m
        
        return total_cost_eur
    
    def size_pipe(self, flow_rate_kg_s: float, length_m: float, 
                 pipe_category: str = 'distribution_pipe') -> PipeSizingResult:
        """
        Complete pipe sizing calculation.
        
        Args:
            flow_rate_kg_s: Mass flow rate in kg/s
            length_m: Pipe length in meters
            pipe_category: Pipe category
        
        Returns:
            PipeSizingResult: Complete sizing result
        """
        # Calculate required diameter
        required_diameter_m = self.calculate_required_diameter(flow_rate_kg_s, pipe_category)
        
        # Select standard diameter
        standard_diameter_m = self.select_standard_diameter(required_diameter_m, pipe_category)
        
        # Calculate hydraulic parameters
        velocity_ms = self._calculate_velocity(flow_rate_kg_s, standard_diameter_m)
        reynolds = self._calculate_reynolds_number(velocity_ms, standard_diameter_m)
        friction_factor = self._calculate_friction_factor(reynolds, standard_diameter_m)
        pressure_drop_pa_per_m = self._calculate_pressure_drop_per_meter(
            flow_rate_kg_s, standard_diameter_m, friction_factor
        )
        pressure_drop_bar = (pressure_drop_pa_per_m * length_m) / 100000
        
        # Calculate costs
        cost_per_m_eur = self.calculate_pipe_cost(standard_diameter_m, 1.0, pipe_category)
        total_cost_eur = cost_per_m_eur * length_m
        
        # Validate constraints
        pipe_data = {
            'flow_rate_kg_s': flow_rate_kg_s,
            'diameter_m': standard_diameter_m,
            'length_m': length_m,
            'pipe_category': pipe_category
        }
        validation = self.validate_hydraulic_constraints(pipe_data)
        
        # Get nominal diameter
        diameter_nominal = f"DN {int(standard_diameter_m * 1000)}"
        
        return PipeSizingResult(
            diameter_m=standard_diameter_m,
            diameter_nominal=diameter_nominal,
            velocity_ms=velocity_ms,
            pressure_drop_bar=pressure_drop_bar,
            pressure_drop_pa_per_m=pressure_drop_pa_per_m,
            reynolds_number=reynolds,
            friction_factor=friction_factor,
            cost_per_m_eur=cost_per_m_eur,
            total_cost_eur=total_cost_eur,
            standards_compliance=validation['standards_compliance'],
            violations=validation['violations'],
            recommendations=validation['recommendations']
        )
    
    def _calculate_velocity(self, flow_rate_kg_s: float, diameter_m: float) -> float:
        """Calculate flow velocity in pipe."""
        area_m2 = math.pi * (diameter_m / 2) ** 2
        volume_flow_m3_s = flow_rate_kg_s / self.water_density_kg_m3
        return volume_flow_m3_s / area_m2
    
    def _calculate_reynolds_number(self, velocity_ms: float, diameter_m: float) -> float:
        """Calculate Reynolds number."""
        return (velocity_ms * diameter_m) / self.water_kinematic_viscosity_m2_s
    
    def _calculate_friction_factor(self, reynolds: float, diameter_m: float) -> float:
        """Calculate friction factor using Colebrook-White equation."""
        relative_roughness = self.pipe_roughness_m / diameter_m
        
        # Handle edge cases
        if reynolds <= 0:
            return 0.02  # Default friction factor
        
        # Initial guess
        friction_factor = 0.01
        
        # Iterative solution
        for _ in range(10):
            try:
                # Ensure we don't take sqrt of negative number
                if friction_factor <= 0:
                    friction_factor = 0.01
                
                # Ensure we don't take log of negative or zero
                log_argument = relative_roughness / 3.7 + 2.51 / (reynolds * math.sqrt(friction_factor))
                if log_argument <= 0:
                    friction_factor = 0.02
                    break
                
                friction_factor_new = 1 / (2 * math.log10(log_argument))
                
                if abs(friction_factor_new - friction_factor) < 0.001:
                    break
                friction_factor = friction_factor_new
                
            except (ValueError, ZeroDivisionError):
                friction_factor = 0.02  # Default friction factor
                break
        
        # Ensure reasonable bounds
        return max(0.005, min(0.1, friction_factor))
    
    def _calculate_pressure_drop_per_meter(self, flow_rate_kg_s: float, 
                                         diameter_m: float, 
                                         friction_factor: float) -> float:
        """Calculate pressure drop per meter using Darcy-Weisbach equation."""
        velocity_ms = self._calculate_velocity(flow_rate_kg_s, diameter_m)
        return (
            friction_factor * (1 / diameter_m) * 
            (self.water_density_kg_m3 * velocity_ms**2) / 2
        )
    
    def get_pipe_category_for_flow(self, flow_rate_kg_s: float) -> str:
        """
        Determine appropriate pipe category based on flow rate.
        
        Args:
            flow_rate_kg_s: Mass flow rate in kg/s
        
        Returns:
            pipe_category: Recommended pipe category
        """
        for category_name, category in self.pipe_categories.items():
            min_flow, max_flow = category.typical_flow_range_kg_s
            if min_flow <= flow_rate_kg_s <= max_flow:
                return category_name
        
        # If flow is outside typical ranges, use closest category
        if flow_rate_kg_s < 2.0:
            return 'service_connection'
        elif flow_rate_kg_s < 20.0:
            return 'distribution_pipe'
        else:
            return 'main_pipe'
    
    def export_sizing_results(self, results: List[PipeSizingResult], 
                            output_path: str) -> None:
        """
        Export sizing results to JSON file.
        
        Args:
            results: List of PipeSizingResult objects
            output_path: Output file path
        """
        export_data = []
        for result in results:
            export_data.append({
                'diameter_m': result.diameter_m,
                'diameter_nominal': result.diameter_nominal,
                'velocity_ms': result.velocity_ms,
                'pressure_drop_bar': result.pressure_drop_bar,
                'pressure_drop_pa_per_m': result.pressure_drop_pa_per_m,
                'reynolds_number': result.reynolds_number,
                'friction_factor': result.friction_factor,
                'cost_per_m_eur': result.cost_per_m_eur,
                'total_cost_eur': result.total_cost_eur,
                'standards_compliance': result.standards_compliance,
                'violations': result.violations,
                'recommendations': result.recommendations
            })
        
        with open(output_path, 'w') as f:
            json.dump(export_data, f, indent=2)
        
        print(f"✅ Pipe sizing results exported to {output_path}")
    
    def auto_resize_with_guardrails(self, network_data: Dict) -> Dict:
        """
        Auto-resize pipes with guardrails to prevent oscillation.
        
        Implementation:
        - Max 3 iterations with monotone "size-up only" logic
        - Prioritize sizing: services → distribution → mains
        - Stop when all limits pass OR no diameter increase available
        - Prevent oscillation by only increasing diameters
        
        Args:
            network_data: Dictionary containing pipe network data
            
        Returns:
            Dict with resize results and statistics
        """
        if not self.auto_resize_enabled:
            print("⚠️ Auto-resize disabled, skipping resize loop")
            return {"status": "disabled", "message": "Auto-resize disabled"}
        
        print("🔄 Starting auto-resize loop with guardrails...")
        print(f"   Max iterations: {self.max_resize_iterations}")
        print(f"   Sizing priority: {self.sizing_priority}")
        print(f"   Monotone sizing: {self.monotone_sizing}")
        
        # Initialize tracking
        iteration = 0
        total_violations = 0
        total_resized = 0
        resize_history = []
        
        # Get initial pipe data
        pipes = network_data.get('pipes', [])
        if not pipes:
            return {"status": "error", "message": "No pipe data found"}
        
        # Track original diameters for monotone sizing
        original_diameters = {}
        for pipe in pipes:
            pipe_id = pipe.get('id', pipe.get('name', f"pipe_{len(original_diameters)}"))
            original_diameters[pipe_id] = pipe.get('diameter_m', 0.1)
        
        while iteration < self.max_resize_iterations:
            iteration += 1
            print(f"\n🔄 Iteration {iteration}/{self.max_resize_iterations}")
            
            # Check standards compliance for all pipes
            violations = self.check_standards_compliance(pipes)
            total_violations = len(violations)
            
            if total_violations == 0:
                print("✅ All pipes comply with standards - stopping resize loop")
                break
            
            print(f"   Found {total_violations} violations")
            
            # Prioritize pipe resizing
            prioritized_pipes = self.prioritize_pipe_resizing(violations)
            print(f"   Prioritized pipes for resizing: {len(prioritized_pipes)}")
            
            # Apply monotone sizing
            iteration_resized = 0
            for pipe_id in prioritized_pipes:
                pipe = next((p for p in pipes if p.get('id', p.get('name', '')) == pipe_id), None)
                if not pipe:
                    continue
                
                current_dn = pipe.get('diameter_m', 0.1)
                required_dn = self._calculate_required_diameter_for_pipe(pipe)
                
                if required_dn > current_dn:
                    new_dn = self.apply_monotone_sizing(pipe_id, current_dn, required_dn)
                    if new_dn > current_dn:
                        pipe['diameter_m'] = new_dn
                        pipe['diameter_nominal'] = f"DN {int(new_dn * 1000)}"
                        iteration_resized += 1
                        total_resized += 1
                        print(f"   Resized {pipe_id}: {current_dn*1000:.0f}mm → {new_dn*1000:.0f}mm")
            
            # Record iteration results
            resize_history.append({
                'iteration': iteration,
                'violations_found': total_violations,
                'pipes_resized': iteration_resized,
                'total_resized': total_resized
            })
            
            if iteration_resized == 0:
                print("⚠️ No pipes could be resized - stopping resize loop")
                break
        
        # Final compliance check
        final_violations = self.check_standards_compliance(pipes)
        final_compliance = len(final_violations) == 0
        
        result = {
            'status': 'completed',
            'iterations_completed': iteration,
            'max_iterations': self.max_resize_iterations,
            'total_violations_initial': len(self.check_standards_compliance(network_data.get('pipes', []))),
            'total_violations_final': len(final_violations),
            'total_pipes_resized': total_resized,
            'final_compliance': final_compliance,
            'resize_history': resize_history,
            'violations_remaining': final_violations,
            'monotone_sizing_applied': self.monotone_sizing,
            'sizing_priority_used': self.sizing_priority
        }
        
        print(f"\n✅ Auto-resize completed:")
        print(f"   Iterations: {iteration}/{self.max_resize_iterations}")
        print(f"   Pipes resized: {total_resized}")
        print(f"   Final compliance: {'✅ PASS' if final_compliance else '❌ FAIL'}")
        print(f"   Remaining violations: {len(final_violations)}")
        
        return result
    
    def check_standards_compliance(self, pipe_data: List[Dict]) -> List[str]:
        """
        Check standards compliance for all pipes and return violations.
        
        Args:
            pipe_data: List of pipe dictionaries
            
        Returns:
            List of pipe IDs that violate standards
        """
        violations = []
        
        for pipe in pipe_data:
            pipe_id = pipe.get('id', pipe.get('name', f"pipe_{len(violations)}"))
            pipe_category = pipe.get('pipe_category', 'distribution_pipe')
            
            # Get flow rate and diameter
            flow_rate_kg_s = pipe.get('flow_rate_kg_s', 0.1)
            diameter_m = pipe.get('diameter_m', 0.1)
            
            # Calculate hydraulic parameters
            velocity_ms = self._calculate_velocity(flow_rate_kg_s, diameter_m)
            reynolds = self._calculate_reynolds_number(velocity_ms, diameter_m)
            friction_factor = self._calculate_friction_factor(reynolds, diameter_m)
            pressure_drop_pa_per_m = self._calculate_pressure_drop_per_meter(
                flow_rate_kg_s, diameter_m, friction_factor
            )
            
            # Check against standards limits
            category_limits = self.standards_limits
            
            # Map pipe category to standards category
            if 'service' in pipe_category.lower():
                stds_category = 'services'
            elif 'main' in pipe_category.lower():
                stds_category = 'mains'
            else:
                stds_category = 'distribution'
            
            # Check velocity limit
            velocity_limit = category_limits['velocity_ms'][stds_category]
            if velocity_ms > velocity_limit:
                violations.append(pipe_id)
                continue
            
            # Check pressure drop limit
            pressure_drop_limit = category_limits['pressure_drop_pa_per_m'][stds_category]
            if pressure_drop_pa_per_m > pressure_drop_limit:
                violations.append(pipe_id)
                continue
        
        return violations
    
    def prioritize_pipe_resizing(self, violations: List[str]) -> List[str]:
        """
        Prioritize pipe resizing based on configuration.
        
        Args:
            violations: List of pipe IDs that violate standards
            
        Returns:
            Prioritized list of pipe IDs for resizing
        """
        if not violations:
            return []
        
        # For now, return violations in the order specified by sizing_priority
        # In a real implementation, you would map pipe IDs to their categories
        # and sort according to the priority order
        
        # Simple implementation: return violations in priority order
        # (services first, then distribution, then mains)
        prioritized = []
        
        # Group violations by category (simplified)
        service_violations = [v for v in violations if 'service' in v.lower()]
        distribution_violations = [v for v in violations if 'distribution' in v.lower() or 'dist' in v.lower()]
        main_violations = [v for v in violations if 'main' in v.lower()]
        
        # Apply priority order
        for priority in self.sizing_priority:
            if priority == 'services' and service_violations:
                prioritized.extend(service_violations)
            elif priority == 'distribution' and distribution_violations:
                prioritized.extend(distribution_violations)
            elif priority == 'mains' and main_violations:
                prioritized.extend(main_violations)
        
        # Add any remaining violations not categorized
        remaining = [v for v in violations if v not in prioritized]
        prioritized.extend(remaining)
        
        return prioritized
    
    def apply_monotone_sizing(self, pipe_id: str, current_dn: float, required_dn: float) -> float:
        """
        Apply monotone sizing (size-up only) to prevent oscillation.
        
        Args:
            pipe_id: Pipe identifier
            current_dn: Current diameter in meters
            required_dn: Required diameter in meters
            
        Returns:
            New diameter in meters (always >= current_dn)
        """
        if not self.monotone_sizing:
            return required_dn
        
        # Monotone sizing: only increase diameter, never decrease
        if required_dn <= current_dn:
            return current_dn
        
        # Find next larger standard diameter
        for std_dn in self.standard_diameters_m:
            if std_dn >= required_dn:
                return std_dn
        
        # If no standard diameter meets requirement, return largest available
        return max(self.standard_diameters_m)
    
    def _calculate_required_diameter_for_pipe(self, pipe: Dict) -> float:
        """
        Calculate required diameter for a specific pipe.
        
        Args:
            pipe: Pipe dictionary with flow rate and category
            
        Returns:
            Required diameter in meters
        """
        flow_rate_kg_s = pipe.get('flow_rate_kg_s', 0.1)
        pipe_category = pipe.get('pipe_category', 'distribution_pipe')
        
        return self.calculate_required_diameter(flow_rate_kg_s, pipe_category)


# Example usage and testing
if __name__ == "__main__":
    # Example configuration
    config = {
        'max_velocity_ms': 2.0,
        'min_velocity_ms': 0.1,
        'max_pressure_drop_pa_per_m': 500,
        'pipe_roughness_mm': 0.1,
        'cost_factors': {
            'base_cost_per_mm_diameter': 0.5,
            'installation_factor': 1.5,
            'insulation_cost_per_m': 15.0,
            'material_factor': 1.0
        },
        'auto_resize': {
            'enabled': True,
            'max_iterations': 3,
            'sizing_priority': ['services', 'distribution', 'mains'],
            'monotone_sizing': True
        },
        'standards_limits': {
            'pressure_drop_pa_per_m': {
                'mains': 300,
                'distribution': 400,
                'services': 500
            },
            'velocity_ms': {
                'mains': 2.0,
                'distribution': 2.0,
                'services': 1.5
            }
        }
    }
    
    # Create sizing engine
    sizing_engine = CHAPipeSizingEngine(config)
    
    # Example sizing calculations
    test_cases = [
        {'flow_rate_kg_s': 0.5, 'length_m': 50, 'category': 'service_connection'},
        {'flow_rate_kg_s': 5.0, 'length_m': 200, 'category': 'distribution_pipe'},
        {'flow_rate_kg_s': 25.0, 'length_m': 1000, 'category': 'main_pipe'}
    ]
    
    results = []
    for case in test_cases:
        result = sizing_engine.size_pipe(
            case['flow_rate_kg_s'],
            case['length_m'],
            case['category']
        )
        results.append(result)
        
        print(f"\n📊 Pipe Sizing Result for {case['category']}:")
        print(f"   Flow Rate: {case['flow_rate_kg_s']} kg/s")
        print(f"   Length: {case['length_m']} m")
        print(f"   Diameter: {result.diameter_nominal} ({result.diameter_m:.3f} m)")
        print(f"   Velocity: {result.velocity_ms:.2f} m/s")
        print(f"   Pressure Drop: {result.pressure_drop_bar:.3f} bar")
        print(f"   Cost: €{result.total_cost_eur:.0f}")
        print(f"   Standards Compliance: {result.standards_compliance}")
        if result.violations:
            print(f"   Violations: {result.violations}")
        if result.recommendations:
            print(f"   Recommendations: {result.recommendations}")
    
    # Export results
    sizing_engine.export_sizing_results(results, "test_pipe_sizing_results.json")
    
    # Test auto-resize functionality
    print("\n" + "="*60)
    print("🔄 Testing Auto-Resize with Guardrails")
    print("="*60)
    
    # Create test network data with some violations
    test_network_data = {
        'pipes': [
            {
                'id': 'service_1',
                'flow_rate_kg_s': 2.5,  # High flow for service pipe
                'diameter_m': 0.025,    # Small diameter - will violate
                'pipe_category': 'service_connection',
                'length_m': 50
            },
            {
                'id': 'distribution_1',
                'flow_rate_kg_s': 15.0,  # High flow for distribution pipe
                'diameter_m': 0.080,     # Small diameter - will violate
                'pipe_category': 'distribution_pipe',
                'length_m': 200
            },
            {
                'id': 'main_1',
                'flow_rate_kg_s': 50.0,  # High flow for main pipe
                'diameter_m': 0.200,     # Small diameter - will violate
                'pipe_category': 'main_pipe',
                'length_m': 1000
            }
        ]
    }
    
    # Run auto-resize
    resize_result = sizing_engine.auto_resize_with_guardrails(test_network_data)
    
    print(f"\n📊 Auto-Resize Results:")
    print(f"   Status: {resize_result['status']}")
    print(f"   Iterations: {resize_result['iterations_completed']}/{resize_result['max_iterations']}")
    print(f"   Pipes resized: {resize_result['total_pipes_resized']}")
    print(f"   Final compliance: {'✅ PASS' if resize_result['final_compliance'] else '❌ FAIL'}")
    print(f"   Remaining violations: {len(resize_result['violations_remaining'])}")
    
    # Show final pipe diameters
    print(f"\n📏 Final Pipe Diameters:")
    for pipe in test_network_data['pipes']:
        diameter_nominal = pipe.get('diameter_nominal', f"DN {int(pipe['diameter_m']*1000)}")
        print(f"   {pipe['id']}: {pipe['diameter_m']*1000:.0f}mm ({diameter_nominal})")
