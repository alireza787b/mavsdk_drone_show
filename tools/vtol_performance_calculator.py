#!/usr/bin/env python3
"""
VTOL Performance Calculator
Calculates detailed flight performance parameters based on aerospace engineering principles
"""

import math
from dataclasses import dataclass
from typing import Dict

@dataclass
class BatterySpec:
    """Battery specifications"""
    cells: int = 6  # 6S
    capacity_mah: float = 11000
    voltage_nominal: float = 22.2  # 6S nominal
    voltage_max: float = 25.2  # 6S fully charged
    voltage_min: float = 18.0  # 6S cutoff
    usable_capacity_factor: float = 0.85  # 85% usable capacity for safety

    @property
    def capacity_ah(self) -> float:
        return self.capacity_mah / 1000.0

    @property
    def energy_wh(self) -> float:
        return self.voltage_nominal * self.capacity_ah * self.usable_capacity_factor

@dataclass
class VTOLSpec:
    """VTOL/Quadplane aircraft specifications - differential thrust control only"""
    wingspan_m: float = 2.0
    wing_area_m2: float = None  # Will be calculated
    aspect_ratio: float = 7.0  # Typical for efficient quadplane
    cd0: float = 0.08  # Parasite drag - exposed motors, moderate design (research: 0.04-0.10)
    oswald_efficiency: float = 0.75  # Oswald efficiency factor (research: 0.75-0.85)
    k: float = None  # Induced drag factor - will be calculated
    cl_max: float = 1.2  # Maximum lift coefficient - conservative
    cl_cruise: float = 0.5  # Cruise lift coefficient
    prop_efficiency_hover: float = 0.65  # Propeller efficiency in hover
    prop_efficiency_cruise: float = 0.55  # Cruise efficiency (hover props in forward flight)
    motor_efficiency: float = 0.85  # Motor efficiency
    control_power_watts: float = 20.0  # Constant power for stability in forward flight
    max_safe_speed_ms: float = 22.0  # Maximum safe cruise speed (structural limit)
    air_density: float = 1.225  # kg/m³ at sea level

    def __post_init__(self):
        if self.wing_area_m2 is None:
            # Calculate wing area from wingspan and aspect ratio
            self.wing_area_m2 = (self.wingspan_m ** 2) / self.aspect_ratio

        if self.k is None:
            # Calculate induced drag factor: K = 1/(π × AR × e)
            self.k = 1.0 / (math.pi * self.aspect_ratio * self.oswald_efficiency)

@dataclass
class CalibrationData:
    """Known calibration data point"""
    weight_kg: float = 5.2
    hover_time_min: float = 12.5  # Average of 12-13 minutes

class VTOLPerformanceCalculator:
    """Calculate VTOL performance parameters"""

    def __init__(self, battery: BatterySpec, vtol: VTOLSpec, calibration: CalibrationData):
        self.battery = battery
        self.vtol = vtol
        self.calibration = calibration

        # Calculate hover current from calibration data
        self.hover_current_per_kg = self._calculate_hover_current_per_kg()

    def _calculate_hover_current_per_kg(self) -> float:
        """
        Calculate hover current per kg from calibration data
        Using: Endurance = (Battery_Capacity * Usable_Factor) / Current
        """
        # Hover time in hours
        hover_time_h = self.calibration.hover_time_min / 60.0

        # Total hover current at calibration weight
        hover_current_total = (self.battery.capacity_ah * self.battery.usable_capacity_factor) / hover_time_h

        # Specific hover current (A per kg)
        return hover_current_total / self.calibration.weight_kg

    def calculate_hover_current(self, weight_kg: float) -> float:
        """Calculate hover current for given weight"""
        # Hover current scales approximately with square root of weight
        # But for conservative estimate, we use linear scaling
        weight_ratio = weight_kg / self.calibration.weight_kg
        base_current = self.hover_current_per_kg * self.calibration.weight_kg
        return base_current * (weight_ratio ** 0.9)  # Slightly better than linear

    def calculate_hover_power(self, weight_kg: float) -> float:
        """Calculate hover power in watts"""
        # Hover power = Weight * g / (prop_efficiency * motor_efficiency)
        g = 9.81
        total_efficiency = self.vtol.prop_efficiency_hover * self.vtol.motor_efficiency
        return (weight_kg * g) / total_efficiency

    def calculate_stall_speed(self, weight_kg: float) -> float:
        """
        Calculate stall speed
        V_stall = sqrt((2 * W) / (rho * S * CL_max))
        """
        W = weight_kg * 9.81  # Weight in Newtons
        rho = self.vtol.air_density
        S = self.vtol.wing_area_m2
        CL_max = self.vtol.cl_max

        v_stall = math.sqrt((2 * W) / (rho * S * CL_max))
        return v_stall

    def calculate_minimum_power_speed(self, weight_kg: float) -> float:
        """
        Calculate speed for minimum power (best endurance)
        This occurs at: V_mp = sqrt((2*W/S) / (rho * sqrt(3*CD0*K)))
        Typically around 1.32 × V_stall
        """
        v_stall = self.calculate_stall_speed(weight_kg)
        # Minimum power speed for best endurance
        v_mp = v_stall * math.sqrt(3.0 * self.vtol.k / self.vtol.cd0)

        # Limit to safe cruise speed
        return min(v_mp, self.vtol.max_safe_speed_ms * 0.85)

    def calculate_cruise_speed(self, weight_kg: float) -> float:
        """
        Calculate optimal cruise speed for best endurance
        This is the minimum power speed
        """
        return self.calculate_minimum_power_speed(weight_kg)

    def calculate_max_cruise_speed(self, weight_kg: float) -> float:
        """Calculate maximum safe cruise speed for quadplane"""
        # Limited by control authority and structural limits
        return self.vtol.max_safe_speed_ms

    def calculate_drag_power(self, weight_kg: float, speed_ms: float) -> float:
        """
        Calculate power required to overcome drag in cruise
        P = D * V where D = 0.5 * rho * V^2 * S * CD
        CD = CD0 + K * CL^2
        """
        W = weight_kg * 9.81
        rho = self.vtol.air_density
        S = self.vtol.wing_area_m2

        # Calculate lift coefficient at this speed
        CL = (2 * W) / (rho * speed_ms**2 * S)

        # Calculate drag coefficient
        CD = self.vtol.cd0 + self.vtol.k * CL**2

        # Calculate drag force
        D = 0.5 * rho * speed_ms**2 * S * CD

        # Power = Drag * Velocity
        drag_power = D * speed_ms

        return drag_power

    def calculate_cruise_power(self, weight_kg: float, speed_ms: float) -> float:
        """
        Calculate total cruise power for quadplane
        Includes drag power + constant control power requirement
        """
        drag_power = self.calculate_drag_power(weight_kg, speed_ms)
        total_efficiency = self.vtol.prop_efficiency_cruise * self.vtol.motor_efficiency
        propulsion_power = drag_power / total_efficiency

        # Add constant control power (motors always running for stability)
        total_power = propulsion_power + self.vtol.control_power_watts

        return total_power

    def calculate_cruise_current(self, weight_kg: float, speed_ms: float) -> float:
        """Calculate cruise current"""
        cruise_power = self.calculate_cruise_power(weight_kg, speed_ms)
        return cruise_power / self.battery.voltage_nominal

    def calculate_endurance(self, current_a: float) -> float:
        """Calculate endurance in minutes given current draw"""
        usable_capacity = self.battery.capacity_ah * self.battery.usable_capacity_factor
        endurance_h = usable_capacity / current_a
        return endurance_h * 60.0  # Convert to minutes

    def calculate_loiter_radius(self, weight_kg: float, bank_angle_deg: float = 15.0) -> float:
        """
        Calculate loiter/orbit radius
        R = V^2 / (g * tan(phi))
        """
        v_cruise = self.calculate_cruise_speed(weight_kg)
        g = 9.81
        phi = math.radians(bank_angle_deg)

        radius = (v_cruise ** 2) / (g * math.tan(phi))
        return radius

    def calculate_orbit_endurance(self, weight_kg: float, bank_angle_deg: float = 15.0) -> float:
        """
        Calculate endurance while orbiting
        Orbiting requires slightly more power than straight cruise due to bank angle
        """
        v_cruise = self.calculate_cruise_speed(weight_kg)

        # In a banked turn, effective weight increases by 1/cos(phi)
        phi = math.radians(bank_angle_deg)
        effective_weight = weight_kg / math.cos(phi)

        # Calculate power for orbiting
        orbit_power = self.calculate_cruise_power(effective_weight, v_cruise)
        orbit_current = orbit_power / self.battery.voltage_nominal

        return self.calculate_endurance(orbit_current)

    def calculate_turn_rate(self, speed_ms: float, bank_angle_deg: float) -> float:
        """Calculate turn rate in degrees per second"""
        g = 9.81
        phi = math.radians(bank_angle_deg)
        omega = (g * math.tan(phi)) / speed_ms
        return math.degrees(omega)

    def get_comprehensive_performance(self, weight_kg: float) -> Dict:
        """Calculate all performance parameters"""

        # Speed parameters
        v_stall = self.calculate_stall_speed(weight_kg)
        v_cruise = self.calculate_cruise_speed(weight_kg)
        v_max_cruise = self.calculate_max_cruise_speed(weight_kg)

        # Hover parameters
        hover_current = self.calculate_hover_current(weight_kg)
        hover_power = self.calculate_hover_power(weight_kg)
        hover_endurance = self.calculate_endurance(hover_current)

        # Cruise parameters
        cruise_current = self.calculate_cruise_current(weight_kg, v_cruise)
        cruise_power = self.calculate_cruise_power(weight_kg, v_cruise)
        cruise_endurance = self.calculate_endurance(cruise_current)

        # Orbit parameters (15 degree bank)
        loiter_radius_15 = self.calculate_loiter_radius(weight_kg, 15.0)
        orbit_endurance_15 = self.calculate_orbit_endurance(weight_kg, 15.0)
        turn_rate_15 = self.calculate_turn_rate(v_cruise, 15.0)

        # Orbit parameters (20 degree bank)
        loiter_radius_20 = self.calculate_loiter_radius(weight_kg, 20.0)
        orbit_endurance_20 = self.calculate_orbit_endurance(weight_kg, 20.0)
        turn_rate_20 = self.calculate_turn_rate(v_cruise, 20.0)

        # Orbit parameters (25 degree bank)
        loiter_radius_25 = self.calculate_loiter_radius(weight_kg, 25.0)
        orbit_endurance_25 = self.calculate_orbit_endurance(weight_kg, 25.0)
        turn_rate_25 = self.calculate_turn_rate(v_cruise, 25.0)

        # Best range cruise (minimum drag speed = maximum L/D)
        # Occurs at: V_md = sqrt((2*W/S) / (rho * sqrt(CD0*K)))
        # Typically 1.32 × minimum power speed or 1.73 × stall speed
        v_best_range = v_stall * math.sqrt(self.vtol.k / self.vtol.cd0)
        v_best_range = min(v_best_range, self.vtol.max_safe_speed_ms)
        best_range_current = self.calculate_cruise_current(weight_kg, v_best_range)
        best_range_endurance = self.calculate_endurance(best_range_current)
        best_range_distance = v_best_range * (best_range_endurance * 60.0) / 1000.0  # km

        # Best endurance distance
        best_endurance_distance = v_cruise * (cruise_endurance * 60.0) / 1000.0  # km

        return {
            # Weight
            'weight_kg': weight_kg,
            'weight_n': weight_kg * 9.81,

            # Speed performance
            'stall_speed_ms': v_stall,
            'stall_speed_kmh': v_stall * 3.6,
            'cruise_speed_ms': v_cruise,
            'cruise_speed_kmh': v_cruise * 3.6,
            'max_cruise_speed_ms': v_max_cruise,
            'max_cruise_speed_kmh': v_max_cruise * 3.6,
            'best_range_speed_ms': v_best_range,
            'best_range_speed_kmh': v_best_range * 3.6,

            # Hover performance
            'hover_current_a': hover_current,
            'hover_power_w': hover_power,
            'hover_endurance_min': hover_endurance,

            # Cruise performance (best endurance)
            'cruise_current_a': cruise_current,
            'cruise_power_w': cruise_power,
            'cruise_endurance_min': cruise_endurance,
            'cruise_range_km': best_endurance_distance,

            # Best range performance
            'best_range_current_a': best_range_current,
            'best_range_endurance_min': best_range_endurance,
            'best_range_km': best_range_distance,

            # Loiter/Orbit performance (15° bank - recommended)
            'loiter_radius_15deg_m': loiter_radius_15,
            'orbit_endurance_15deg_min': orbit_endurance_15,
            'turn_rate_15deg_dps': turn_rate_15,

            # Orbit performance (20° bank - aggressive)
            'loiter_radius_20deg_m': loiter_radius_20,
            'orbit_endurance_20deg_min': orbit_endurance_20,
            'turn_rate_20deg_dps': turn_rate_20,

            # Orbit performance (25° bank - very aggressive)
            'loiter_radius_25deg_m': loiter_radius_25,
            'orbit_endurance_25deg_min': orbit_endurance_25,
            'turn_rate_25deg_dps': turn_rate_25,

            # Aerodynamic parameters
            'wing_loading_kgm2': weight_kg / self.vtol.wing_area_m2,
            'wing_loading_nm2': (weight_kg * 9.81) / self.vtol.wing_area_m2,
            'lift_to_drag_ratio': 1.0 / (self.vtol.cd0 + self.vtol.k * self.vtol.cl_cruise**2),
            'max_ld_ratio': 0.5 / math.sqrt(self.vtol.cd0 * self.vtol.k),  # Maximum L/D at optimal CL
        }

def print_performance_table(perf: Dict, title: str):
    """Print performance data in a formatted table"""
    print(f"\n{'='*80}")
    print(f"{title:^80}")
    print(f"{'='*80}")

    sections = [
        ("BASIC PARAMETERS", [
            ('Total Weight', f"{perf['weight_kg']:.2f} kg"),
            ('Total Weight', f"{perf['weight_n']:.2f} N"),
            ('Wing Loading', f"{perf['wing_loading_kgm2']:.2f} kg/m²"),
            ('Wing Loading', f"{perf['wing_loading_nm2']:.2f} N/m²"),
            ('Lift-to-Drag Ratio (Cruise)', f"{perf['lift_to_drag_ratio']:.2f}"),
            ('Maximum L/D Ratio', f"{perf['max_ld_ratio']:.2f}"),
        ]),

        ("SPEED PERFORMANCE", [
            ('Stall Speed (Vs)', f"{perf['stall_speed_ms']:.2f} m/s ({perf['stall_speed_kmh']:.1f} km/h)"),
            ('Cruise Speed (Best Endurance)', f"{perf['cruise_speed_ms']:.2f} m/s ({perf['cruise_speed_kmh']:.1f} km/h)"),
            ('Best Range Speed', f"{perf['best_range_speed_ms']:.2f} m/s ({perf['best_range_speed_kmh']:.1f} km/h)"),
            ('Max Cruise Speed', f"{perf['max_cruise_speed_ms']:.2f} m/s ({perf['max_cruise_speed_kmh']:.1f} km/h)"),
        ]),

        ("HOVER PERFORMANCE", [
            ('Hover Current', f"{perf['hover_current_a']:.2f} A"),
            ('Hover Power', f"{perf['hover_power_w']:.1f} W"),
            ('Hover Endurance', f"{perf['hover_endurance_min']:.2f} min"),
        ]),

        ("CRUISE PERFORMANCE (Best Endurance Speed)", [
            ('Cruise Current', f"{perf['cruise_current_a']:.2f} A"),
            ('Cruise Power', f"{perf['cruise_power_w']:.1f} W"),
            ('Cruise Endurance', f"{perf['cruise_endurance_min']:.2f} min"),
            ('Cruise Range', f"{perf['cruise_range_km']:.2f} km"),
        ]),

        ("BEST RANGE PERFORMANCE (Higher Speed)", [
            ('Best Range Current', f"{perf['best_range_current_a']:.2f} A"),
            ('Best Range Endurance', f"{perf['best_range_endurance_min']:.2f} min"),
            ('Maximum Range', f"{perf['best_range_km']:.2f} km"),
        ]),

        ("LOITER/ORBIT PERFORMANCE (15° Bank - RECOMMENDED)", [
            ('Loiter Radius', f"{perf['loiter_radius_15deg_m']:.1f} m"),
            ('Orbit Endurance', f"{perf['orbit_endurance_15deg_min']:.2f} min"),
            ('Turn Rate', f"{perf['turn_rate_15deg_dps']:.2f} °/s"),
            ('Orbit Diameter', f"{perf['loiter_radius_15deg_m']*2:.1f} m"),
        ]),

        ("ORBIT PERFORMANCE (20° Bank - Aggressive)", [
            ('Loiter Radius', f"{perf['loiter_radius_20deg_m']:.1f} m"),
            ('Orbit Endurance', f"{perf['orbit_endurance_20deg_min']:.2f} min"),
            ('Turn Rate', f"{perf['turn_rate_20deg_dps']:.2f} °/s"),
            ('Orbit Diameter', f"{perf['loiter_radius_20deg_m']*2:.1f} m"),
        ]),

        ("ORBIT PERFORMANCE (25° Bank - Very Aggressive)", [
            ('Loiter Radius', f"{perf['loiter_radius_25deg_m']:.1f} m"),
            ('Orbit Endurance', f"{perf['orbit_endurance_25deg_min']:.2f} min"),
            ('Turn Rate', f"{perf['turn_rate_25deg_dps']:.2f} °/s"),
            ('Orbit Diameter', f"{perf['loiter_radius_25deg_m']*2:.1f} m"),
        ]),
    ]

    for section_name, items in sections:
        print(f"\n{section_name}")
        print("-" * 80)
        for label, value in items:
            print(f"  {label:.<40} {value:>37}")

def print_comparison_table(perf_6kg: Dict, perf_8kg: Dict):
    """Print comparison table between 6kg and 8kg configurations"""
    print(f"\n{'='*100}")
    print(f"{'COMPARATIVE PERFORMANCE ANALYSIS':^100}")
    print(f"{'='*100}")
    print(f"{'Parameter':<45} {'6.0 kg':>25} {'8.0 kg':>25}")
    print(f"{'-'*100}")

    comparisons = [
        ("WEIGHT & LOADING", [
            ('Total Weight (kg)', 'weight_kg', '{:.2f}'),
            ('Wing Loading (kg/m²)', 'wing_loading_kgm2', '{:.2f}'),
            ('L/D Ratio (Cruise)', 'lift_to_drag_ratio', '{:.2f}'),
            ('Maximum L/D Ratio', 'max_ld_ratio', '{:.2f}'),
        ]),
        ("SPEED (m/s | km/h)", [
            ('Stall Speed', 'stall_speed', '{:.2f} | {:.1f}'),
            ('Cruise Speed (Best Endurance)', 'cruise_speed', '{:.2f} | {:.1f}'),
            ('Best Range Speed', 'best_range_speed', '{:.2f} | {:.1f}'),
            ('Max Cruise Speed', 'max_cruise_speed', '{:.2f} | {:.1f}'),
        ]),
        ("HOVER PERFORMANCE", [
            ('Hover Current (A)', 'hover_current_a', '{:.2f}'),
            ('Hover Power (W)', 'hover_power_w', '{:.1f}'),
            ('Hover Endurance (min)', 'hover_endurance_min', '{:.2f}'),
        ]),
        ("CRUISE PERFORMANCE", [
            ('Cruise Current (A)', 'cruise_current_a', '{:.2f}'),
            ('Cruise Power (W)', 'cruise_power_w', '{:.1f}'),
            ('Cruise Endurance (min)', 'cruise_endurance_min', '{:.2f}'),
            ('Cruise Range (km)', 'cruise_range_km', '{:.2f}'),
        ]),
        ("BEST RANGE PERFORMANCE", [
            ('Best Range Current (A)', 'best_range_current_a', '{:.2f}'),
            ('Best Range Endurance (min)', 'best_range_endurance_min', '{:.2f}'),
            ('Maximum Range (km)', 'best_range_km', '{:.2f}'),
        ]),
        ("LOITER (15° Bank - RECOMMENDED)", [
            ('Loiter Radius (m)', 'loiter_radius_15deg_m', '{:.1f}'),
            ('Orbit Endurance (min)', 'orbit_endurance_15deg_min', '{:.2f}'),
            ('Turn Rate (°/s)', 'turn_rate_15deg_dps', '{:.2f}'),
        ]),
        ("ORBIT (20° Bank)", [
            ('Loiter Radius (m)', 'loiter_radius_20deg_m', '{:.1f}'),
            ('Orbit Endurance (min)', 'orbit_endurance_20deg_min', '{:.2f}'),
            ('Turn Rate (°/s)', 'turn_rate_20deg_dps', '{:.2f}'),
        ]),
        ("ORBIT (25° Bank)", [
            ('Loiter Radius (m)', 'loiter_radius_25deg_m', '{:.1f}'),
            ('Orbit Endurance (min)', 'orbit_endurance_25deg_min', '{:.2f}'),
            ('Turn Rate (°/s)', 'turn_rate_25deg_dps', '{:.2f}'),
        ]),
    ]

    for section_name, items in comparisons:
        print(f"\n{section_name}")
        print(f"{'-'*100}")
        for label, key_base, fmt in items:
            if '|' in fmt:
                # Speed parameters with dual units
                key_ms = key_base + '_ms'
                key_kmh = key_base + '_kmh'
                val_6kg = fmt.format(perf_6kg[key_ms], perf_6kg[key_kmh])
                val_8kg = fmt.format(perf_8kg[key_ms], perf_8kg[key_kmh])
            else:
                val_6kg = fmt.format(perf_6kg[key_base])
                val_8kg = fmt.format(perf_8kg[key_base])

            print(f"  {label:.<43} {val_6kg:>25} {val_8kg:>25}")

def main():
    # Battery specifications
    battery = BatterySpec(
        cells=6,
        capacity_mah=11000,
        voltage_nominal=22.2,
        voltage_max=25.2,
        voltage_min=18.0,
        usable_capacity_factor=0.85
    )

    # VTOL/Quadplane specifications (differential thrust control)
    # Values based on research papers and aerodynamic theory
    vtol = VTOLSpec(
        wingspan_m=2.0,
        aspect_ratio=7.0,
        cd0=0.08,  # Parasite drag (research: 0.04-0.10 for quadplanes)
        oswald_efficiency=0.75,  # Oswald efficiency factor (research: 0.75-0.85)
        cl_max=1.2,  # Conservative maximum lift coefficient
        cl_cruise=0.5,  # Typical cruise lift coefficient
        prop_efficiency_hover=0.65,  # Hover propeller efficiency
        prop_efficiency_cruise=0.55,  # Forward flight efficiency (hover props)
        motor_efficiency=0.85,  # Motor efficiency
        control_power_watts=20.0,  # Constant control power (lower in forward flight)
        max_safe_speed_ms=22.0  # Conservative maximum safe speed
    )

    # Calibration data
    calibration = CalibrationData(
        weight_kg=5.2,
        hover_time_min=12.5
    )

    # Create calculator
    calc = VTOLPerformanceCalculator(battery, vtol, calibration)

    # Calculate performance for both weights
    perf_6kg = calc.get_comprehensive_performance(6.0)
    perf_8kg = calc.get_comprehensive_performance(8.0)

    # Print individual tables
    print_performance_table(perf_6kg, "VTOL PERFORMANCE ANALYSIS - 6.0 KG CONFIGURATION")
    print_performance_table(perf_8kg, "VTOL PERFORMANCE ANALYSIS - 8.0 KG CONFIGURATION")

    # Print comparison table
    print_comparison_table(perf_6kg, perf_8kg)

    print(f"\n{'='*100}")
    print("CALCULATION BASIS:")
    print("-" * 100)
    print("• Aerodynamic theory with validated parameters from research literature")
    print("• CD0 = 0.08 (typical for quadplane with exposed motors, research range: 0.04-0.10)")
    print("• Oswald efficiency e = 0.75 (research validated for simple wings)")
    print("• K = 1/(π×AR×e) = 0.061 (induced drag factor)")
    print("• Hover calibrated from real flight data: 5.2kg @ 12.5min")
    print("• Cruise power: P = (Drag × Velocity) / (η_prop × η_motor) + P_control")
    print("• Minimum power speed: V_mp = V_stall × sqrt(3K/CD0) for best endurance")
    print("• Best range speed: V_md = V_stall × sqrt(K/CD0) for maximum L/D")
    print("• Propeller efficiency in cruise: 55% (hover props in forward flight)")
    print("• Constant 20W control power for stability in forward flight")
    print("• 85% battery usable capacity safety margin")
    print("• Sea level standard atmosphere (ρ = 1.225 kg/m³)")
    print("• NO control surfaces - all control via differential motor thrust")
    print(f"{'='*100}\n")

if __name__ == "__main__":
    main()
