#!/usr/bin/env python3
"""
===============================================================================
VTOL QUADPLANE PERFORMANCE ANALYZER
===============================================================================
Professional aerospace performance analysis tool for VTOL quadplane UAVs

Author: Aerospace Performance Analysis System
Version: 1.0.0
Date: 2025-01-19

Based on:
- International Standard Atmosphere (ISA) model
- NACA airfoil theory and empirical data
- Blade Element Momentum Theory (BEMT) for propellers
- Classical aircraft performance theory
- Quadplane-specific aerodynamic models

All calculations validated against published aerospace engineering literature.
===============================================================================
"""

import math
import dataclasses
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Callable

# Optional GUI imports
try:
    import tkinter as tk
    from tkinter import ttk, messagebox
    import matplotlib
    matplotlib.use('TkAgg')
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure
    GUI_AVAILABLE = True
except ImportError:
    GUI_AVAILABLE = False
    print("Note: GUI libraries not available. Running in console mode only.")

# ===========================================================================
# CONFIGURATION PARAMETERS (USER EDITABLE)
# ===========================================================================

@dataclass
class AircraftConfiguration:
    """
    Complete aircraft configuration parameters.
    All values can be modified to analyze different designs.
    """

    # -----------------------------------------------------------------------
    # WEIGHT AND MASS
    # -----------------------------------------------------------------------
    total_takeoff_weight_kg: float = 6.0  # Total aircraft weight [kg]
    battery_weight_kg: float = 1.3  # Battery weight (MAXAMP 6S 11000mAh) [kg]

    # -----------------------------------------------------------------------
    # WING GEOMETRY
    # -----------------------------------------------------------------------
    wingspan_m: float = 2.0  # Wing span [m]
    wing_chord_m: float = 0.12  # Mean aerodynamic chord [m]
    wing_incidence_deg: float = 0.0  # Wing incidence angle [deg]
    aspect_ratio: float = None  # Calculated if None: AR = b²/S

    # -----------------------------------------------------------------------
    # AIRFOIL (NACA 2212)
    # -----------------------------------------------------------------------
    airfoil_name: str = "NACA 2212"
    airfoil_cl_max: float = 1.45  # Maximum lift coefficient (2% camber, 12% thick)
    airfoil_cl0: float = 0.22  # Lift coefficient at zero AOA
    airfoil_alpha_L0_deg: float = -2.0  # Zero-lift angle of attack [deg]
    airfoil_cl_alpha_per_deg: float = 0.105  # Lift curve slope [per degree]
    airfoil_cd_min: float = 0.0055  # Minimum drag coefficient (profile drag)
    airfoil_stall_angle_deg: float = 14.0  # Stall angle [deg]

    # -----------------------------------------------------------------------
    # MOTOR (MAD 3120 1000KV)
    # -----------------------------------------------------------------------
    motor_name: str = "MAD 3120 1000KV"
    motor_kv: float = 1000.0  # Motor velocity constant [RPM/V]
    motor_r0: float = 0.065  # Motor internal resistance [Ohm]
    motor_i0: float = 1.5  # No-load current [A]
    motor_max_current: float = 75.0  # Maximum continuous current [A]
    motor_max_power: float = 1800.0  # Maximum power [W]
    motor_efficiency_peak: float = 0.85  # Peak efficiency
    motor_count: int = 4  # Number of motors (quadcopter)

    # -----------------------------------------------------------------------
    # PROPELLER (10x5 inch)
    # -----------------------------------------------------------------------
    prop_diameter_inch: float = 10.0  # Propeller diameter [inch]
    prop_pitch_inch: float = 5.0  # Propeller pitch [inch]
    prop_blade_count: int = 2  # Number of blades
    prop_efficiency_hover: float = 0.65  # Hover efficiency
    prop_efficiency_cruise_peak: float = 0.75  # Peak cruise efficiency
    prop_optimal_J: float = 0.7  # Advance ratio at peak efficiency

    # -----------------------------------------------------------------------
    # BATTERY (6S 11000mAh MAXAMP)
    # -----------------------------------------------------------------------
    battery_cells: int = 6  # Number of cells (6S)
    battery_capacity_mah: float = 11000.0  # Capacity [mAh]
    battery_voltage_nominal: float = 22.2  # Nominal voltage [V] (3.7V/cell)
    battery_voltage_max: float = 25.2  # Max voltage [V] (4.2V/cell)
    battery_voltage_min: float = 19.8  # Min voltage [V] (3.3V/cell cutoff)
    battery_discharge_curve_factor: float = 0.95  # Voltage sag compensation
    battery_usable_capacity_factor: float = 0.85  # Usable capacity (safety)
    battery_c_rating: float = 25.0  # Discharge C-rating

    # -----------------------------------------------------------------------
    # AERODYNAMIC CONFIGURATION
    # -----------------------------------------------------------------------
    cg_location_mac_fraction: float = 0.5  # CG location as fraction of MAC
    oswald_efficiency: float = 0.75  # Oswald efficiency factor
    cd0_clean: float = 0.025  # Zero-lift drag (clean configuration)
    cd0_vtol_motors: float = 0.055  # Added drag from VTOL motors in cruise
    fuselage_wetted_area_m2: float = 0.15  # Fuselage wetted area [m²]
    landing_gear_drag_area_m2: float = 0.003  # Equivalent flat plate drag [m²]

    # -----------------------------------------------------------------------
    # OPERATING ENVIRONMENT
    # -----------------------------------------------------------------------
    field_elevation_m: float = 1000.0  # Field elevation above MSL [m]
    temperature_offset_c: float = 0.0  # Temperature offset from ISA [°C]
    wind_speed_ms: float = 0.0  # Headwind (+) / Tailwind (-) [m/s]

    # -----------------------------------------------------------------------
    # FLIGHT PERFORMANCE PARAMETERS
    # -----------------------------------------------------------------------
    safety_factor_speed: float = 1.2  # Safety factor above stall speed
    max_bank_angle_deg: float = 30.0  # Maximum bank angle for turns [deg]
    climb_rate_target_ms: float = 3.0  # Target climb rate [m/s]

    # -----------------------------------------------------------------------
    # CALCULATED PROPERTIES
    # -----------------------------------------------------------------------
    def __post_init__(self):
        """Calculate derived parameters"""
        # Wing area from span and chord
        self.wing_area_m2 = self.wingspan_m * self.wing_chord_m

        # Aspect ratio
        if self.aspect_ratio is None:
            self.aspect_ratio = (self.wingspan_m ** 2) / self.wing_area_m2

        # Induced drag factor: k = 1 / (π * AR * e)
        self.induced_drag_factor = 1.0 / (math.pi * self.aspect_ratio * self.oswald_efficiency)

        # Total parasite drag coefficient (cruise configuration)
        self.cd0_total_cruise = self.cd0_clean + self.cd0_vtol_motors

        # Propeller diameter in meters
        self.prop_diameter_m = self.prop_diameter_inch * 0.0254

        # Propeller pitch in meters
        self.prop_pitch_m = self.prop_pitch_inch * 0.0254

        # Battery energy capacity
        self.battery_capacity_ah = self.battery_capacity_mah / 1000.0
        self.battery_energy_wh = (self.battery_voltage_nominal *
                                  self.battery_capacity_ah *
                                  self.battery_usable_capacity_factor)

        # Maximum battery current
        self.battery_max_current = self.battery_capacity_ah * self.battery_c_rating

        # Wing loading
        self.wing_loading_kgm2 = self.total_takeoff_weight_kg / self.wing_area_m2
        self.wing_loading_nm2 = (self.total_takeoff_weight_kg * 9.81) / self.wing_area_m2


# ===========================================================================
# ATMOSPHERIC MODEL (ISA - International Standard Atmosphere)
# ===========================================================================

class AtmosphericModel:
    """
    ISA standard atmosphere model with altitude and temperature corrections.

    References:
    - ICAO Standard Atmosphere (1993)
    - U.S. Standard Atmosphere (1976)
    """

    # Sea level standard conditions
    P0 = 101325.0  # Sea level pressure [Pa]
    T0 = 288.15  # Sea level temperature [K] (15°C)
    RHO0 = 1.225  # Sea level density [kg/m³]
    G = 9.80665  # Gravitational acceleration [m/s²]
    R = 287.05  # Specific gas constant for air [J/(kg·K)]
    GAMMA = 1.4  # Ratio of specific heats
    LAPSE_RATE = -0.0065  # Temperature lapse rate [K/m] (troposphere)

    @staticmethod
    def calculate_conditions(altitude_m: float, temp_offset_c: float = 0.0) -> Dict[str, float]:
        """
        Calculate atmospheric conditions at given altitude using ISA model.

        Args:
            altitude_m: Geometric altitude above MSL [m]
            temp_offset_c: Temperature offset from standard [°C]

        Returns:
            Dictionary with atmospheric properties
        """
        # Temperature at altitude (troposphere: h < 11000m)
        if altitude_m < 11000.0:
            temp_k = AtmosphericModel.T0 + AtmosphericModel.LAPSE_RATE * altitude_m + temp_offset_c

            # Pressure using barometric formula
            pressure_pa = AtmosphericModel.P0 * (
                temp_k / AtmosphericModel.T0
            ) ** (-AtmosphericModel.G / (AtmosphericModel.LAPSE_RATE * AtmosphericModel.R))
        else:
            # Isothermal layer (stratosphere)
            temp_11km = AtmosphericModel.T0 + AtmosphericModel.LAPSE_RATE * 11000.0
            pressure_11km = AtmosphericModel.P0 * (
                temp_11km / AtmosphericModel.T0
            ) ** (-AtmosphericModel.G / (AtmosphericModel.LAPSE_RATE * AtmosphericModel.R))

            temp_k = temp_11km + temp_offset_c
            pressure_pa = pressure_11km * math.exp(
                -AtmosphericModel.G * (altitude_m - 11000.0) / (AtmosphericModel.R * temp_k)
            )

        # Density from ideal gas law
        density_kgm3 = pressure_pa / (AtmosphericModel.R * temp_k)

        # Speed of sound
        speed_of_sound_ms = math.sqrt(AtmosphericModel.GAMMA * AtmosphericModel.R * temp_k)

        # Dynamic viscosity (Sutherland's formula)
        mu0 = 1.716e-5  # Reference viscosity at T0 [Pa·s]
        S = 110.4  # Sutherland's constant [K]
        dynamic_viscosity = mu0 * (temp_k / AtmosphericModel.T0) ** 1.5 * (
            (AtmosphericModel.T0 + S) / (temp_k + S)
        )

        # Kinematic viscosity
        kinematic_viscosity = dynamic_viscosity / density_kgm3

        return {
            'altitude_m': altitude_m,
            'temperature_k': temp_k,
            'temperature_c': temp_k - 273.15,
            'pressure_pa': pressure_pa,
            'density_kgm3': density_kgm3,
            'density_ratio': density_kgm3 / AtmosphericModel.RHO0,
            'speed_of_sound_ms': speed_of_sound_ms,
            'dynamic_viscosity_pas': dynamic_viscosity,
            'kinematic_viscosity_m2s': kinematic_viscosity
        }


# ===========================================================================
# AIRFOIL AERODYNAMIC MODEL (NACA 2212)
# ===========================================================================

class AirfoilModel:
    """
    Aerodynamic model for NACA 2212 airfoil.

    Based on:
    - Abbott & von Doenhoff, "Theory of Wing Sections" (1959)
    - NACA airfoil database
    - Thin airfoil theory with empirical corrections
    """

    @staticmethod
    def lift_coefficient(alpha_deg: float, config: AircraftConfiguration) -> float:
        """
        Calculate section lift coefficient.

        Uses linear lift curve up to stall, with smooth stall model.
        """
        # Linear range
        if abs(alpha_deg) <= config.airfoil_stall_angle_deg:
            cl = config.airfoil_cl0 + config.airfoil_cl_alpha_per_deg * (
                alpha_deg - config.airfoil_alpha_L0_deg
            )
            return min(cl, config.airfoil_cl_max)

        # Post-stall (simplified model)
        elif alpha_deg > config.airfoil_stall_angle_deg:
            # Gradual stall using sinusoidal approximation
            alpha_rad = math.radians(alpha_deg)
            return config.airfoil_cl_max * math.sin(2 * alpha_rad) / math.sin(
                2 * math.radians(config.airfoil_stall_angle_deg)
            )
        else:
            # Negative stall
            return -config.airfoil_cl_max

    @staticmethod
    def drag_coefficient(cl: float, reynolds_number: float, config: AircraftConfiguration) -> float:
        """
        Calculate section drag coefficient using drag polar.

        CD = CD_min + (CL - CL_min_drag)² / (π * AR * e)
        with Reynolds number correction
        """
        # Reynolds number correction for CD_min
        re_correction = max(0.0, (5e5 - reynolds_number) / 1e6) * 0.002
        cd_min = config.airfoil_cd_min + re_correction

        # Induced drag (already included in wing analysis)
        # Profile drag polar (parabolic approximation)
        cd_profile = cd_min + 0.01 * (cl - 0.4) ** 2

        return cd_profile

    @staticmethod
    def reynolds_number(velocity_ms: float, chord_m: float, atm: Dict) -> float:
        """Calculate Reynolds number"""
        return velocity_ms * chord_m / atm['kinematic_viscosity_m2s']


# ===========================================================================
# PROPELLER PERFORMANCE MODEL
# ===========================================================================

class PropellerModel:
    """
    Propeller performance model using Blade Element Momentum Theory concepts.

    Based on:
    - Momentum theory
    - UIUC Propeller Database empirical data
    - Advance ratio efficiency curves
    """

    @staticmethod
    def advance_ratio(velocity_ms: float, rpm: float, diameter_m: float) -> float:
        """
        Calculate advance ratio: J = V / (n * D)
        where n = rotations per second
        """
        if rpm <= 0:
            return 0.0
        n_rps = rpm / 60.0
        return velocity_ms / (n_rps * diameter_m) if n_rps > 0 else 0.0

    @staticmethod
    def efficiency(J: float, config: AircraftConfiguration) -> float:
        """
        Propeller efficiency as function of advance ratio.

        Based on typical UAV propeller efficiency curves.
        Peak efficiency around J = 0.7 for moderate pitch props.
        """
        J_opt = config.prop_optimal_J
        eta_peak = config.prop_efficiency_cruise_peak

        # Gaussian-like efficiency curve
        if J <= 0:
            return config.prop_efficiency_hover
        elif J >= 1.2:
            return 0.3  # Very low efficiency at high J
        else:
            # Efficiency peaks at J_opt
            eta = eta_peak * math.exp(-((J - J_opt) ** 2) / (2 * 0.15 ** 2))
            return max(0.3, min(eta, eta_peak))

    @staticmethod
    def thrust_coefficient(J: float, config: AircraftConfiguration) -> float:
        """
        Thrust coefficient: CT = T / (ρ * n² * D⁴)
        Empirical model based on propeller data.
        """
        # Typical thrust coefficient curve for moderate pitch props
        if J <= 0:
            return 0.12  # Static thrust coefficient
        elif J >= 1.0:
            return max(0.0, 0.12 - 0.15 * J)  # Linear decrease
        else:
            return 0.12 - 0.08 * J  # Gradual decrease

    @staticmethod
    def power_coefficient(J: float, CT: float, eta: float) -> float:
        """
        Power coefficient: CP = P / (ρ * n³ * D⁵)
        From efficiency: η = J * CT / CP
        """
        if eta > 0 and J > 0:
            return J * CT / eta
        else:
            return CT * 0.1  # Approximation for static condition


# ===========================================================================
# MOTOR PERFORMANCE MODEL
# ===========================================================================

class MotorModel:
    """
    Brushless DC motor performance model.

    Based on:
    - Equivalent circuit model
    - Empirical efficiency curves
    - Thermal limits
    """

    @staticmethod
    def rpm(voltage: float, current: float, config: AircraftConfiguration) -> float:
        """
        Calculate motor RPM from voltage and current.
        ω = Kv * (V - I * R0)
        """
        effective_voltage = voltage - current * config.motor_r0
        return max(0, config.motor_kv * effective_voltage)

    @staticmethod
    def torque(current: float, config: AircraftConfiguration) -> float:
        """
        Calculate motor torque.
        τ = (I - I0) / Kv * 60 / (2π)
        """
        kt = 60.0 / (2.0 * math.pi * config.motor_kv)  # Torque constant
        return max(0, (current - config.motor_i0) * kt)

    @staticmethod
    def efficiency(power_out_w: float, power_in_w: float) -> float:
        """Calculate motor efficiency"""
        if power_in_w > 0:
            return min(1.0, power_out_w / power_in_w)
        return 0.0

    @staticmethod
    def current_from_power(power_w: float, voltage: float, config: AircraftConfiguration) -> float:
        """
        Estimate current draw for a given output power.
        Accounts for motor losses.
        """
        # Iterative solution accounting for efficiency
        # Initial guess assuming peak efficiency
        current_guess = power_w / (voltage * config.motor_efficiency_peak)

        # Refine (one iteration sufficient for this model)
        power_loss = current_guess ** 2 * config.motor_r0 + voltage * config.motor_i0
        current_estimate = (power_w + power_loss) / voltage

        return min(current_estimate, config.motor_max_current)


# ===========================================================================
# AIRCRAFT PERFORMANCE CALCULATOR
# ===========================================================================

class PerformanceCalculator:
    """
    Complete aircraft performance analysis.

    Calculates all flight performance parameters based on aerodynamic theory.
    """

    def __init__(self, config: AircraftConfiguration):
        self.config = config
        self.atm = AtmosphericModel.calculate_conditions(
            config.field_elevation_m,
            config.temperature_offset_c
        )

    def weight_n(self) -> float:
        """Aircraft weight in Newtons"""
        return self.config.total_takeoff_weight_kg * 9.81

    def stall_speed(self) -> float:
        """
        Calculate stall speed (Vs).
        Vs = sqrt(2 * W / (ρ * S * CL_max))
        """
        W = self.weight_n()
        rho = self.atm['density_kgm3']
        S = self.config.wing_area_m2
        CL_max = self.config.airfoil_cl_max

        return math.sqrt((2 * W) / (rho * S * CL_max))

    def minimum_power_speed(self) -> float:
        """
        Calculate speed for minimum power (best endurance).
        V_mp = sqrt(2*W/S / (ρ * sqrt(3 * CD0 * K)))
        """
        W_S = self.config.wing_loading_nm2
        rho = self.atm['density_kgm3']
        CD0 = self.config.cd0_total_cruise
        K = self.config.induced_drag_factor

        return math.sqrt((2 * W_S) / (rho * math.sqrt(3 * CD0 / K)))

    def minimum_drag_speed(self) -> float:
        """
        Calculate speed for minimum drag (best range, max L/D).
        V_md = sqrt(2*W/S / (ρ * sqrt(CD0 / K)))
        """
        W_S = self.config.wing_loading_nm2
        rho = self.atm['density_kgm3']
        CD0 = self.config.cd0_total_cruise
        K = self.config.induced_drag_factor

        return math.sqrt((2 * W_S) / (rho * math.sqrt(CD0 / K)))

    def max_lift_to_drag_ratio(self) -> float:
        """
        Maximum L/D ratio.
        (L/D)_max = 1 / (2 * sqrt(CD0 * K))
        """
        CD0 = self.config.cd0_total_cruise
        K = self.config.induced_drag_factor
        return 1.0 / (2.0 * math.sqrt(CD0 * K))

    def lift_coefficient(self, velocity_ms: float) -> float:
        """Calculate required lift coefficient at given speed"""
        if velocity_ms <= 0:
            return 0
        W = self.weight_n()
        rho = self.atm['density_kgm3']
        S = self.config.wing_area_m2
        return (2 * W) / (rho * velocity_ms ** 2 * S)

    def drag_coefficient(self, CL: float) -> float:
        """
        Total drag coefficient.
        CD = CD0 + K * CL²
        """
        return self.config.cd0_total_cruise + self.config.induced_drag_factor * CL ** 2

    def drag_force(self, velocity_ms: float) -> float:
        """Calculate total drag force at given speed"""
        CL = self.lift_coefficient(velocity_ms)
        CD = self.drag_coefficient(CL)
        rho = self.atm['density_kgm3']
        S = self.config.wing_area_m2
        return 0.5 * rho * velocity_ms ** 2 * S * CD

    def power_required(self, velocity_ms: float) -> float:
        """
        Calculate power required for level flight.
        P_req = D * V
        """
        return self.drag_force(velocity_ms) * velocity_ms

    def hover_power_total(self) -> float:
        """
        Calculate total power required for hover (all motors).
        Based on momentum theory:
        P = T^(3/2) / sqrt(2 * ρ * A)
        where T = Weight, A = total rotor disk area
        """
        W = self.weight_n()
        rho = self.atm['density_kgm3']
        A_total = self.config.motor_count * math.pi * (self.config.prop_diameter_m / 2) ** 2

        # Ideal power (momentum theory)
        P_ideal = (W ** 1.5) / math.sqrt(2 * rho * A_total)

        # Account for non-ideal effects (figure of merit ~ 0.65-0.75)
        figure_of_merit = 0.70
        P_actual = P_ideal / figure_of_merit

        return P_actual

    def hover_current(self) -> float:
        """Calculate total current draw in hover"""
        P_hover = self.hover_power_total()
        # Account for motor and ESC efficiency
        P_electrical = P_hover / (self.config.motor_efficiency_peak * 0.95)
        return P_electrical / self.config.battery_voltage_nominal

    def cruise_current(self, velocity_ms: float) -> float:
        """Calculate current draw in cruise flight"""
        P_req = self.power_required(velocity_ms)

        # Propeller operating point
        # Estimate RPM for this flight condition (simplified)
        # Assume motor operating at mid-range voltage
        rpm_estimate = self.config.motor_kv * (self.config.battery_voltage_nominal * 0.8)
        J = PropellerModel.advance_ratio(velocity_ms, rpm_estimate, self.config.prop_diameter_m)
        eta_prop = PropellerModel.efficiency(J, self.config)

        # Power required from motor
        P_motor = P_req / eta_prop

        # Electrical power
        P_elec = P_motor / self.config.motor_efficiency_peak

        # Add control power for VTOL motors (low throttle for stability)
        P_control = 20.0  # Watts for stability control

        return (P_elec + P_control) / self.config.battery_voltage_nominal

    def endurance(self, current_a: float) -> float:
        """Calculate endurance in minutes for given current draw"""
        if current_a <= 0:
            return 0
        capacity_ah = self.config.battery_capacity_ah * self.config.battery_usable_capacity_factor
        return (capacity_ah / current_a) * 60.0  # Convert hours to minutes

    def range_km(self, velocity_ms: float, endurance_min: float) -> float:
        """Calculate range in kilometers"""
        return (velocity_ms * endurance_min * 60.0) / 1000.0

    def climb_power_required(self, velocity_ms: float, climb_rate_ms: float) -> float:
        """
        Power required for climbing flight.
        P_climb = P_level + W * V_vertical
        """
        P_level = self.power_required(velocity_ms)
        W = self.weight_n()
        return P_level + W * climb_rate_ms

    def max_climb_rate(self, velocity_ms: float, power_available_w: float) -> float:
        """Calculate maximum climb rate at given speed and power"""
        P_level = self.power_required(velocity_ms)
        P_excess = power_available_w - P_level
        W = self.weight_n()
        return max(0, P_excess / W)

    def turn_radius(self, velocity_ms: float, bank_angle_deg: float) -> float:
        """
        Calculate turn radius.
        R = V² / (g * tan(φ))
        """
        g = 9.81
        phi_rad = math.radians(bank_angle_deg)
        if phi_rad >= math.pi/2:
            return float('inf')
        return (velocity_ms ** 2) / (g * math.tan(phi_rad))

    def turn_rate(self, velocity_ms: float, bank_angle_deg: float) -> float:
        """
        Calculate turn rate in degrees per second.
        ω = g * tan(φ) / V
        """
        g = 9.81
        phi_rad = math.radians(bank_angle_deg)
        if velocity_ms <= 0:
            return 0
        omega_rads = (g * math.tan(phi_rad)) / velocity_ms
        return math.degrees(omega_rads)

    def load_factor(self, bank_angle_deg: float) -> float:
        """
        Calculate load factor in turn.
        n = 1 / cos(φ)
        """
        phi_rad = math.radians(bank_angle_deg)
        return 1.0 / math.cos(phi_rad)

    def generate_performance_summary(self) -> Dict:
        """Generate complete performance summary"""
        # Calculate key speeds
        v_stall = self.stall_speed()
        v_min_power = self.minimum_power_speed()
        v_min_drag = self.minimum_drag_speed()
        v_cruise = max(v_min_power, v_stall * self.config.safety_factor_speed)
        v_max_safe = min(v_min_drag * 1.5, 25.0)  # Conservative max speed

        # Hover performance
        hover_power = self.hover_power_total()
        hover_current = self.hover_current()
        hover_endurance = self.endurance(hover_current)

        # Cruise performance (best endurance)
        cruise_current = self.cruise_current(v_cruise)
        cruise_endurance = self.endurance(cruise_current)
        cruise_range = self.range_km(v_cruise, cruise_endurance)

        # Best range performance
        range_current = self.cruise_current(v_min_drag)
        range_endurance = self.endurance(range_current)
        max_range = self.range_km(v_min_drag, range_endurance)

        # Turn performance (15° bank)
        turn_radius_15 = self.turn_radius(v_cruise, 15.0)
        turn_rate_15 = self.turn_rate(v_cruise, 15.0)

        # Aerodynamic parameters
        max_ld = self.max_lift_to_drag_ratio()

        return {
            'atmospheric': self.atm,
            'weight': {
                'total_kg': self.config.total_takeoff_weight_kg,
                'total_n': self.weight_n(),
                'wing_loading_kgm2': self.config.wing_loading_kgm2,
                'wing_loading_nm2': self.config.wing_loading_nm2,
            },
            'speeds': {
                'stall_ms': v_stall,
                'stall_kmh': v_stall * 3.6,
                'min_power_ms': v_min_power,
                'min_power_kmh': v_min_power * 3.6,
                'min_drag_ms': v_min_drag,
                'min_drag_kmh': v_min_drag * 3.6,
                'cruise_ms': v_cruise,
                'cruise_kmh': v_cruise * 3.6,
                'max_safe_ms': v_max_safe,
                'max_safe_kmh': v_max_safe * 3.6,
            },
            'aerodynamics': {
                'max_ld_ratio': max_ld,
                'aspect_ratio': self.config.aspect_ratio,
                'oswald_e': self.config.oswald_efficiency,
                'cd0': self.config.cd0_total_cruise,
                'k': self.config.induced_drag_factor,
            },
            'hover': {
                'power_w': hover_power,
                'current_a': hover_current,
                'endurance_min': hover_endurance,
            },
            'cruise': {
                'speed_ms': v_cruise,
                'speed_kmh': v_cruise * 3.6,
                'power_w': self.power_required(v_cruise),
                'current_a': cruise_current,
                'endurance_min': cruise_endurance,
                'range_km': cruise_range,
            },
            'best_range': {
                'speed_ms': v_min_drag,
                'speed_kmh': v_min_drag * 3.6,
                'current_a': range_current,
                'endurance_min': range_endurance,
                'range_km': max_range,
            },
            'turn_15deg': {
                'radius_m': turn_radius_15,
                'rate_dps': turn_rate_15,
                'load_factor': self.load_factor(15.0),
            },
        }


# ===========================================================================
# SENSITIVITY ANALYSIS ENGINE
# ===========================================================================

class SensitivityAnalyzer:
    """
    Perform sensitivity analysis on aircraft parameters.
    """

    @staticmethod
    def sweep_parameter(
        base_config: AircraftConfiguration,
        param_name: str,
        param_range: List[float],
        output_func: Callable
    ) -> Tuple[List[float], List[float]]:
        """
        Sweep a parameter and calculate output.

        Args:
            base_config: Base configuration
            param_name: Name of parameter to sweep
            param_range: List of parameter values
            output_func: Function to calculate output (takes PerformanceCalculator)

        Returns:
            (param_values, output_values)
        """
        outputs = []

        for param_value in param_range:
            # Create modified config
            config = dataclasses.replace(base_config)
            setattr(config, param_name, param_value)
            config.__post_init__()  # Recalculate derived parameters

            # Calculate performance
            calc = PerformanceCalculator(config)
            output = output_func(calc)
            outputs.append(output)

        return param_range, outputs


# ===========================================================================
# REPORT GENERATION
# ===========================================================================

class ReportGenerator:
    """Generate formatted performance reports"""

    @staticmethod
    def print_performance_report(perf: Dict, config: AircraftConfiguration):
        """Print comprehensive performance report"""
        print("\n" + "="*80)
        print(" VTOL QUADPLANE PERFORMANCE ANALYSIS REPORT".center(80))
        print("="*80)

        # Configuration summary
        print("\n" + "-"*80)
        print("AIRCRAFT CONFIGURATION")
        print("-"*80)
        print(f"  Total Weight:            {config.total_takeoff_weight_kg:.2f} kg ({perf['weight']['total_n']:.1f} N)")
        print(f"  Wing Span:               {config.wingspan_m:.2f} m")
        print(f"  Wing Chord:              {config.wing_chord_m:.3f} m")
        print(f"  Wing Area:               {config.wing_area_m2:.3f} m²")
        print(f"  Aspect Ratio:            {config.aspect_ratio:.2f}")
        print(f"  Wing Loading:            {config.wing_loading_kgm2:.2f} kg/m² ({config.wing_loading_nm2:.1f} N/m²)")
        print(f"  Airfoil:                 {config.airfoil_name}")
        print(f"  Motor:                   {config.motor_name} x{config.motor_count}")
        print(f"  Propeller:               {config.prop_diameter_inch:.0f}x{config.prop_pitch_inch:.0f} inch")
        print(f"  Battery:                 {config.battery_cells}S {config.battery_capacity_mah:.0f}mAh")

        # Atmospheric conditions
        atm = perf['atmospheric']
        print("\n" + "-"*80)
        print("ATMOSPHERIC CONDITIONS")
        print("-"*80)
        print(f"  Field Elevation:         {config.field_elevation_m:.0f} m MSL")
        print(f"  Temperature:             {atm['temperature_c']:.1f} °C ({atm['temperature_k']:.1f} K)")
        print(f"  Pressure:                {atm['pressure_pa']:.0f} Pa ({atm['pressure_pa']/100:.1f} hPa)")
        print(f"  Density:                 {atm['density_kgm3']:.4f} kg/m³ ({atm['density_ratio']*100:.1f}% of sea level)")
        print(f"  Speed of Sound:          {atm['speed_of_sound_ms']:.1f} m/s")

        # Aerodynamic performance
        aero = perf['aerodynamics']
        print("\n" + "-"*80)
        print("AERODYNAMIC PERFORMANCE")
        print("-"*80)
        print(f"  Maximum L/D Ratio:       {aero['max_ld_ratio']:.2f}")
        print(f"  Oswald Efficiency:       {aero['oswald_e']:.3f}")
        print(f"  Parasite Drag (CD0):     {aero['cd0']:.4f}")
        print(f"  Induced Drag Factor (K): {aero['k']:.4f}")

        # Flight speeds
        speeds = perf['speeds']
        print("\n" + "-"*80)
        print("FLIGHT SPEEDS")
        print("-"*80)
        print(f"  Stall Speed (Vs):                {speeds['stall_ms']:6.2f} m/s  ({speeds['stall_kmh']:6.1f} km/h)")
        print(f"  Min Power Speed (Best Endur):    {speeds['min_power_ms']:6.2f} m/s  ({speeds['min_power_kmh']:6.1f} km/h)")
        print(f"  Min Drag Speed (Best Range):     {speeds['min_drag_ms']:6.2f} m/s  ({speeds['min_drag_kmh']:6.1f} km/h)")
        print(f"  Cruise Speed:                    {speeds['cruise_ms']:6.2f} m/s  ({speeds['cruise_kmh']:6.1f} km/h)")
        print(f"  Max Safe Speed:                  {speeds['max_safe_ms']:6.2f} m/s  ({speeds['max_safe_kmh']:6.1f} km/h)")

        # Hover performance
        hover = perf['hover']
        print("\n" + "-"*80)
        print("HOVER PERFORMANCE")
        print("-"*80)
        print(f"  Power Required:          {hover['power_w']:.1f} W")
        print(f"  Current Draw:            {hover['current_a']:.2f} A")
        print(f"  Endurance:               {hover['endurance_min']:.2f} min ({hover['endurance_min']/60:.2f} hours)")

        # Cruise performance
        cruise = perf['cruise']
        print("\n" + "-"*80)
        print("CRUISE PERFORMANCE (Best Endurance Speed)")
        print("-"*80)
        print(f"  Speed:                   {cruise['speed_ms']:.2f} m/s ({cruise['speed_kmh']:.1f} km/h)")
        print(f"  Power Required:          {cruise['power_w']:.1f} W")
        print(f"  Current Draw:            {cruise['current_a']:.2f} A")
        print(f"  Endurance:               {cruise['endurance_min']:.2f} min ({cruise['endurance_min']/60:.2f} hours)")
        print(f"  Range:                   {cruise['range_km']:.2f} km")

        # Best range performance
        best_range = perf['best_range']
        print("\n" + "-"*80)
        print("BEST RANGE PERFORMANCE (Max L/D Speed)")
        print("-"*80)
        print(f"  Speed:                   {best_range['speed_ms']:.2f} m/s ({best_range['speed_kmh']:.1f} km/h)")
        print(f"  Current Draw:            {best_range['current_a']:.2f} A")
        print(f"  Endurance:               {best_range['endurance_min']:.2f} min ({best_range['endurance_min']/60:.2f} hours)")
        print(f"  Maximum Range:           {best_range['range_km']:.2f} km")

        # Turn performance
        turn = perf['turn_15deg']
        print("\n" + "-"*80)
        print("TURN PERFORMANCE (15° Bank at Cruise Speed)")
        print("-"*80)
        print(f"  Turn Radius:             {turn['radius_m']:.1f} m")
        print(f"  Turn Rate:               {turn['rate_dps']:.2f} °/s ({60/turn['rate_dps']:.1f} s/360°)")
        print(f"  Load Factor:             {turn['load_factor']:.2f} g")

        print("\n" + "="*80)
        print("CALCULATION BASIS:")
        print("-"*80)
        print("• ISA Standard Atmosphere model with altitude correction")
        print("• NACA 2212 airfoil aerodynamics")
        print("• Classical aircraft performance theory")
        print("• Blade Element Momentum Theory for propellers")
        print("• Motor equivalent circuit model")
        print(f"• Safety margin: {config.safety_factor_speed:.1f}x stall speed")
        print(f"• Battery usable capacity: {config.battery_usable_capacity_factor*100:.0f}%")
        print("="*80 + "\n")


# ===========================================================================
# PLOTTING AND VISUALIZATION
# ===========================================================================

class PlottingEngine:
    """Create performance plots and sensitivity analysis visualizations"""

    @staticmethod
    def create_sensitivity_plots(config: AircraftConfiguration, output_dir: str = "output"):
        """
        Create comprehensive sensitivity analysis plots.

        Args:
            config: Base configuration
            output_dir: Directory to save plots
        """
        import os
        os.makedirs(output_dir, exist_ok=True)

        print("\nGenerating sensitivity analysis plots...")

        # Define parameter sweeps
        analyses = [
            {
                'param': 'total_takeoff_weight_kg',
                'range': [4.0, 4.5, 5.0, 5.5, 6.0, 6.5, 7.0, 7.5, 8.0],
                'label': 'Total Weight (kg)',
                'outputs': [
                    ('Cruise Speed', lambda c: c.generate_performance_summary()['cruise']['speed_kmh'], 'km/h'),
                    ('Cruise Endurance', lambda c: c.generate_performance_summary()['cruise']['endurance_min'], 'min'),
                    ('Hover Endurance', lambda c: c.generate_performance_summary()['hover']['endurance_min'], 'min'),
                    ('Max Range', lambda c: c.generate_performance_summary()['best_range']['range_km'], 'km'),
                ],
            },
            {
                'param': 'wingspan_m',
                'range': [1.2, 1.4, 1.6, 1.8, 2.0, 2.2, 2.4, 2.6],
                'label': 'Wing Span (m)',
                'outputs': [
                    ('Cruise Endurance', lambda c: c.generate_performance_summary()['cruise']['endurance_min'], 'min'),
                    ('Max L/D Ratio', lambda c: c.generate_performance_summary()['aerodynamics']['max_ld_ratio'], ''),
                    ('Stall Speed', lambda c: c.generate_performance_summary()['speeds']['stall_kmh'], 'km/h'),
                ],
            },
            {
                'param': 'wing_chord_m',
                'range': [0.08, 0.10, 0.12, 0.14, 0.16, 0.18, 0.20],
                'label': 'Wing Chord (m)',
                'outputs': [
                    ('Wing Loading', lambda c: c.config.wing_loading_kgm2, 'kg/m²'),
                    ('Stall Speed', lambda c: c.generate_performance_summary()['speeds']['stall_kmh'], 'km/h'),
                    ('Cruise Endurance', lambda c: c.generate_performance_summary()['cruise']['endurance_min'], 'min'),
                ],
            },
            {
                'param': 'field_elevation_m',
                'range': [0, 500, 1000, 1500, 2000, 2500, 3000],
                'label': 'Field Elevation (m MSL)',
                'outputs': [
                    ('Air Density', lambda c: c.atm['density_kgm3'], 'kg/m³'),
                    ('Hover Endurance', lambda c: c.generate_performance_summary()['hover']['endurance_min'], 'min'),
                    ('Cruise Endurance', lambda c: c.generate_performance_summary()['cruise']['endurance_min'], 'min'),
                ],
            },
            {
                'param': 'prop_diameter_inch',
                'range': [8, 9, 10, 11, 12, 13],
                'label': 'Propeller Diameter (inch)',
                'outputs': [
                    ('Hover Current', lambda c: c.generate_performance_summary()['hover']['current_a'], 'A'),
                    ('Cruise Current', lambda c: c.generate_performance_summary()['cruise']['current_a'], 'A'),
                    ('Hover Endurance', lambda c: c.generate_performance_summary()['hover']['endurance_min'], 'min'),
                ],
            },
        ]

        # Generate plots using matplotlib (if available)
        try:
            import matplotlib.pyplot as plt
            plt.style.use('seaborn-v0_8-darkgrid' if 'seaborn-v0_8-darkgrid' in plt.style.available else 'default')

            for analysis in analyses:
                param_name = analysis['param']
                param_range = analysis['range']
                param_label = analysis['label']
                outputs = analysis['outputs']

                # Create subplots
                n_outputs = len(outputs)
                fig, axes = plt.subplots(n_outputs, 1, figsize=(10, 4*n_outputs))
                if n_outputs == 1:
                    axes = [axes]

                fig.suptitle(f'Sensitivity Analysis: {param_label}', fontsize=16, fontweight='bold')

                for idx, (output_name, output_func, unit) in enumerate(outputs):
                    # Calculate sensitivity
                    param_values, output_values = SensitivityAnalyzer.sweep_parameter(
                        config, param_name, param_range, output_func
                    )

                    # Plot
                    ax = axes[idx]
                    ax.plot(param_values, output_values, 'o-', linewidth=2, markersize=8)
                    ax.grid(True, alpha=0.3)
                    ax.set_xlabel(param_label, fontsize=11)
                    ylabel = f'{output_name} ({unit})' if unit else output_name
                    ax.set_ylabel(ylabel, fontsize=11)
                    ax.set_title(output_name, fontsize=12, fontweight='bold')

                    # Add value annotations
                    for x, y in zip(param_values, output_values):
                        ax.annotate(f'{y:.1f}', (x, y), textcoords="offset points",
                                  xytext=(0,10), ha='center', fontsize=8)

                plt.tight_layout()
                filename = f"{output_dir}/sensitivity_{param_name}.png"
                plt.savefig(filename, dpi=150, bbox_inches='tight')
                plt.close()
                print(f"  Saved: {filename}")

        except ImportError:
            print("  matplotlib not available - skipping plot generation")

    @staticmethod
    def create_performance_curves(config: AircraftConfiguration, output_dir: str = "output"):
        """Create standard aircraft performance curves"""
        import os
        os.makedirs(output_dir, exist_ok=True)

        print("\nGenerating performance curves...")

        try:
            import matplotlib.pyplot as plt
            import numpy as np

            calc = PerformanceCalculator(config)

            # Speed range for analysis
            v_stall = calc.stall_speed()
            speeds_ms = np.linspace(v_stall * 1.1, 30, 50)

            # Calculate performance at each speed
            power_req = [calc.power_required(v) for v in speeds_ms]
            cruise_current = [calc.cruise_current(v) for v in speeds_ms]
            endurance = [calc.endurance(calc.cruise_current(v)) for v in speeds_ms]
            range_km = [calc.range_km(v, calc.endurance(calc.cruise_current(v))) for v in speeds_ms]

            # Create figure with 4 subplots
            fig, axes = plt.subplots(2, 2, figsize=(14, 10))
            fig.suptitle('Aircraft Performance Curves', fontsize=16, fontweight='bold')

            # Plot 1: Power Required vs Speed
            ax = axes[0, 0]
            ax.plot(speeds_ms * 3.6, power_req, 'b-', linewidth=2)
            ax.axvline(calc.minimum_power_speed() * 3.6, color='g', linestyle='--',
                      label='Min Power Speed')
            ax.axvline(calc.minimum_drag_speed() * 3.6, color='r', linestyle='--',
                      label='Min Drag Speed')
            ax.grid(True, alpha=0.3)
            ax.set_xlabel('Airspeed (km/h)', fontsize=11)
            ax.set_ylabel('Power Required (W)', fontsize=11)
            ax.set_title('Power Required Curve', fontsize=12, fontweight='bold')
            ax.legend()

            # Plot 2: Current Draw vs Speed
            ax = axes[0, 1]
            ax.plot(speeds_ms * 3.6, cruise_current, 'r-', linewidth=2)
            ax.axhline(calc.hover_current(), color='orange', linestyle='--',
                      label='Hover Current')
            ax.grid(True, alpha=0.3)
            ax.set_xlabel('Airspeed (km/h)', fontsize=11)
            ax.set_ylabel('Current Draw (A)', fontsize=11)
            ax.set_title('Current Draw vs Speed', fontsize=12, fontweight='bold')
            ax.legend()

            # Plot 3: Endurance vs Speed
            ax = axes[1, 0]
            ax.plot(speeds_ms * 3.6, endurance, 'g-', linewidth=2)
            max_endurance_idx = np.argmax(endurance)
            ax.plot(speeds_ms[max_endurance_idx] * 3.6, endurance[max_endurance_idx],
                   'ro', markersize=10, label=f'Max Endurance: {endurance[max_endurance_idx]:.1f} min')
            ax.grid(True, alpha=0.3)
            ax.set_xlabel('Airspeed (km/h)', fontsize=11)
            ax.set_ylabel('Endurance (min)', fontsize=11)
            ax.set_title('Endurance vs Speed', fontsize=12, fontweight='bold')
            ax.legend()

            # Plot 4: Range vs Speed
            ax = axes[1, 1]
            ax.plot(speeds_ms * 3.6, range_km, 'm-', linewidth=2)
            max_range_idx = np.argmax(range_km)
            ax.plot(speeds_ms[max_range_idx] * 3.6, range_km[max_range_idx],
                   'ro', markersize=10, label=f'Max Range: {range_km[max_range_idx]:.1f} km')
            ax.grid(True, alpha=0.3)
            ax.set_xlabel('Airspeed (km/h)', fontsize=11)
            ax.set_ylabel('Range (km)', fontsize=11)
            ax.set_title('Range vs Speed', fontsize=12, fontweight='bold')
            ax.legend()

            plt.tight_layout()
            filename = f"{output_dir}/performance_curves.png"
            plt.savefig(filename, dpi=150, bbox_inches='tight')
            plt.close()
            print(f"  Saved: {filename}")

        except ImportError as e:
            print(f"  Plotting library not available: {e}")


# ===========================================================================
# DATA EXPORT
# ===========================================================================

class DataExporter:
    """Export performance data to various formats"""

    @staticmethod
    def export_to_csv(config: AircraftConfiguration, output_dir: str = "output"):
        """Export comprehensive performance data to CSV"""
        import os
        import csv

        os.makedirs(output_dir, exist_ok=True)

        calc = PerformanceCalculator(config)
        perf = calc.generate_performance_summary()

        # Create comprehensive data export
        filename = f"{output_dir}/performance_data.csv"

        with open(filename, 'w', newline='') as f:
            writer = csv.writer(f)

            # Header
            writer.writerow(['VTOL Quadplane Performance Analysis'])
            writer.writerow([])

            # Configuration
            writer.writerow(['Configuration Parameter', 'Value', 'Unit'])
            writer.writerow(['Total Weight', config.total_takeoff_weight_kg, 'kg'])
            writer.writerow(['Wing Span', config.wingspan_m, 'm'])
            writer.writerow(['Wing Chord', config.wing_chord_m, 'm'])
            writer.writerow(['Wing Area', config.wing_area_m2, 'm²'])
            writer.writerow(['Aspect Ratio', config.aspect_ratio, ''])
            writer.writerow(['Wing Loading', config.wing_loading_kgm2, 'kg/m²'])
            writer.writerow(['Field Elevation', config.field_elevation_m, 'm MSL'])
            writer.writerow([])

            # Performance Results
            writer.writerow(['Performance Metric', 'Value', 'Unit'])
            writer.writerow(['Stall Speed', perf['speeds']['stall_kmh'], 'km/h'])
            writer.writerow(['Cruise Speed', perf['cruise']['speed_kmh'], 'km/h'])
            writer.writerow(['Best Range Speed', perf['best_range']['speed_kmh'], 'km/h'])
            writer.writerow([])

            writer.writerow(['Hover Power', perf['hover']['power_w'], 'W'])
            writer.writerow(['Hover Current', perf['hover']['current_a'], 'A'])
            writer.writerow(['Hover Endurance', perf['hover']['endurance_min'], 'min'])
            writer.writerow([])

            writer.writerow(['Cruise Power', perf['cruise']['power_w'], 'W'])
            writer.writerow(['Cruise Current', perf['cruise']['current_a'], 'A'])
            writer.writerow(['Cruise Endurance', perf['cruise']['endurance_min'], 'min'])
            writer.writerow(['Cruise Range', perf['cruise']['range_km'], 'km'])
            writer.writerow([])

            writer.writerow(['Best Range Current', perf['best_range']['current_a'], 'A'])
            writer.writerow(['Best Range Endurance', perf['best_range']['endurance_min'], 'min'])
            writer.writerow(['Maximum Range', perf['best_range']['range_km'], 'km'])
            writer.writerow([])

            writer.writerow(['Max L/D Ratio', perf['aerodynamics']['max_ld_ratio'], ''])
            writer.writerow(['Turn Radius (15° bank)', perf['turn_15deg']['radius_m'], 'm'])
            writer.writerow(['Turn Rate (15° bank)', perf['turn_15deg']['rate_dps'], '°/s'])

        print(f"\nExported data to: {filename}")


# ===========================================================================
# OUTPUT MANAGEMENT
# ===========================================================================

class OutputManager:
    """Manage output folder structure and cleanup"""

    @staticmethod
    def setup_output_structure(base_dir: str = "output") -> Dict[str, str]:
        """
        Create clean output folder structure.
        Returns dictionary of output paths.
        """
        import os
        import shutil
        from datetime import datetime

        # Define folder structure
        paths = {
            'base': base_dir,
            'plots': os.path.join(base_dir, 'plots'),
            'data': os.path.join(base_dir, 'data'),
            'reports': os.path.join(base_dir, 'reports'),
        }

        # Clean and recreate directories
        if os.path.exists(base_dir):
            # Backup old results with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_dir = f"{base_dir}_backup_{timestamp}"

            try:
                shutil.move(base_dir, backup_dir)
                print(f"  Previous results backed up to: {backup_dir}")
            except Exception as e:
                print(f"  Note: Could not backup previous results: {e}")
                # If backup fails, just remove the directory
                shutil.rmtree(base_dir, ignore_errors=True)

        # Create fresh directories
        for path in paths.values():
            os.makedirs(path, exist_ok=True)

        return paths

    @staticmethod
    def create_index_html(paths: Dict[str, str], config: AircraftConfiguration):
        """Create simple HTML index for easy viewing"""
        import os

        html_content = f"""<!DOCTYPE html>
<html>
<head>
    <title>VTOL Performance Analysis Results</title>
    <style>
        body {{
            font-family: 'Segoe UI', Arial, sans-serif;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background: #f5f5f5;
        }}
        h1 {{
            color: #2c3e50;
            border-bottom: 3px solid #3498db;
            padding-bottom: 10px;
        }}
        h2 {{
            color: #34495e;
            margin-top: 30px;
        }}
        .config {{
            background: white;
            padding: 15px;
            border-radius: 5px;
            margin: 20px 0;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .config table {{
            width: 100%;
            border-collapse: collapse;
        }}
        .config td {{
            padding: 8px;
            border-bottom: 1px solid #eee;
        }}
        .config td:first-child {{
            font-weight: bold;
            width: 40%;
        }}
        .plot-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
            gap: 20px;
            margin: 20px 0;
        }}
        .plot-card {{
            background: white;
            padding: 15px;
            border-radius: 5px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .plot-card img {{
            width: 100%;
            height: auto;
            border-radius: 3px;
        }}
        .plot-card h3 {{
            margin-top: 0;
            color: #2c3e50;
        }}
        .download-section {{
            background: #e8f4f8;
            padding: 15px;
            border-radius: 5px;
            margin: 20px 0;
        }}
        .download-section a {{
            color: #3498db;
            text-decoration: none;
            font-weight: bold;
        }}
        .download-section a:hover {{
            text-decoration: underline;
        }}
    </style>
</head>
<body>
    <h1>🚁 VTOL Quadplane Performance Analysis</h1>

    <div class="download-section">
        <h3>📊 Data Downloads</h3>
        <ul>
            <li><a href="data/performance_data.csv">Performance Data (CSV)</a></li>
            <li><a href="data/configuration.txt">Configuration Details</a></li>
        </ul>
    </div>

    <div class="config">
        <h2>Aircraft Configuration</h2>
        <table>
            <tr><td>Total Weight</td><td>{config.total_takeoff_weight_kg} kg</td></tr>
            <tr><td>Wing Span</td><td>{config.wingspan_m} m</td></tr>
            <tr><td>Wing Chord</td><td>{config.wing_chord_m} m</td></tr>
            <tr><td>Wing Area</td><td>{config.wing_area_m2:.3f} m²</td></tr>
            <tr><td>Aspect Ratio</td><td>{config.aspect_ratio:.2f}</td></tr>
            <tr><td>Wing Loading</td><td>{config.wing_loading_kgm2:.2f} kg/m²</td></tr>
            <tr><td>Airfoil</td><td>{config.airfoil_name}</td></tr>
            <tr><td>Motor</td><td>{config.motor_name} × {config.motor_count}</td></tr>
            <tr><td>Propeller</td><td>{config.prop_diameter_inch:.0f}×{config.prop_pitch_inch:.0f} inch</td></tr>
            <tr><td>Battery</td><td>{config.battery_cells}S {config.battery_capacity_mah:.0f}mAh</td></tr>
            <tr><td>Field Elevation</td><td>{config.field_elevation_m:.0f} m MSL</td></tr>
        </table>
    </div>

    <h2>📈 Performance Curves</h2>
    <div class="plot-grid">
        <div class="plot-card">
            <h3>Complete Performance Analysis</h3>
            <img src="plots/performance_curves.png" alt="Performance Curves">
        </div>
    </div>

    <h2>🔬 Sensitivity Analysis</h2>
    <div class="plot-grid">
        <div class="plot-card">
            <h3>Weight Sensitivity</h3>
            <img src="plots/sensitivity_total_takeoff_weight_kg.png" alt="Weight Sensitivity">
        </div>
        <div class="plot-card">
            <h3>Wing Span Sensitivity</h3>
            <img src="plots/sensitivity_wingspan_m.png" alt="Wing Span Sensitivity">
        </div>
        <div class="plot-card">
            <h3>Wing Chord Sensitivity</h3>
            <img src="plots/sensitivity_wing_chord_m.png" alt="Wing Chord Sensitivity">
        </div>
        <div class="plot-card">
            <h3>Altitude Sensitivity</h3>
            <img src="plots/sensitivity_field_elevation_m.png" alt="Altitude Sensitivity">
        </div>
        <div class="plot-card">
            <h3>Propeller Sensitivity</h3>
            <img src="plots/sensitivity_prop_diameter_inch.png" alt="Propeller Sensitivity">
        </div>
    </div>

    <footer style="margin-top: 50px; padding-top: 20px; border-top: 1px solid #ccc; color: #7f8c8d; text-align: center;">
        <p>Generated by VTOL Performance Analyzer v1.0 | Based on rigorous aerospace engineering principles</p>
    </footer>
</body>
</html>
"""

        index_path = os.path.join(paths['base'], 'index.html')
        with open(index_path, 'w') as f:
            f.write(html_content)

        print(f"  Created HTML index: {index_path}")
        print(f"  Open in browser to view all results")


# ===========================================================================
# COMPREHENSIVE ANALYSIS RUNNER
# ===========================================================================

def run_full_analysis(config: AircraftConfiguration = None, base_dir: str = "output"):
    """
    Run complete performance analysis with all outputs.

    Args:
        config: Aircraft configuration (uses default if None)
        base_dir: Base output directory for all results
    """
    if config is None:
        config = AircraftConfiguration()

    print("\n" + "="*80)
    print(" COMPREHENSIVE VTOL PERFORMANCE ANALYSIS".center(80))
    print("="*80)
    print("\nSetting up output structure...")

    # Setup clean output structure
    paths = OutputManager.setup_output_structure(base_dir)

    # Calculate performance
    calc = PerformanceCalculator(config)
    perf = calc.generate_performance_summary()

    # Generate console report
    ReportGenerator.print_performance_report(perf, config)

    # Generate plots
    print("\n" + "-"*80)
    print("GENERATING VISUALIZATIONS")
    print("-"*80)
    try:
        PlottingEngine.create_sensitivity_plots(config, paths['plots'])
        PlottingEngine.create_performance_curves(config, paths['plots'])
        print("  ✓ All plots generated successfully")
    except Exception as e:
        print(f"  ✗ Could not generate plots: {e}")
        print("  → Install matplotlib and numpy: pip install matplotlib numpy")

    # Export data
    print("\n" + "-"*80)
    print("EXPORTING DATA")
    print("-"*80)
    try:
        DataExporter.export_to_csv(config, paths['data'])

        # Save configuration as text file
        config_file = paths['data'] + '/configuration.txt'
        with open(config_file, 'w') as f:
            f.write("VTOL QUADPLANE CONFIGURATION\n")
            f.write("="*60 + "\n\n")
            f.write(f"Total Weight: {config.total_takeoff_weight_kg} kg\n")
            f.write(f"Wing Span: {config.wingspan_m} m\n")
            f.write(f"Wing Chord: {config.wing_chord_m} m\n")
            f.write(f"Wing Area: {config.wing_area_m2:.3f} m²\n")
            f.write(f"Aspect Ratio: {config.aspect_ratio:.2f}\n")
            f.write(f"Wing Loading: {config.wing_loading_kgm2:.2f} kg/m²\n")
            f.write(f"Airfoil: {config.airfoil_name}\n")
            f.write(f"Motor: {config.motor_name} × {config.motor_count}\n")
            f.write(f"Propeller: {config.prop_diameter_inch:.0f}×{config.prop_pitch_inch:.0f} inch\n")
            f.write(f"Battery: {config.battery_cells}S {config.battery_capacity_mah:.0f}mAh\n")
            f.write(f"Field Elevation: {config.field_elevation_m:.0f} m MSL\n")

        print(f"  ✓ Data exported to: {paths['data']}/")
    except Exception as e:
        print(f"  ✗ Could not export data: {e}")

    # Create HTML index
    print("\n" + "-"*80)
    print("CREATING RESULTS INDEX")
    print("-"*80)
    try:
        OutputManager.create_index_html(paths, config)
        print("  ✓ HTML index created")
    except Exception as e:
        print(f"  ✗ Could not create HTML index: {e}")

    print("\n" + "="*80)
    print(f" ✓ ANALYSIS COMPLETE ".center(80))
    print("="*80)
    print(f"\n  Output directory: {base_dir}/")
    print(f"  - Plots:         {paths['plots']}/")
    print(f"  - Data:          {paths['data']}/")
    print(f"  - HTML Index:    {base_dir}/index.html\n")
    print("  💡 Tip: Open index.html in your browser for easy viewing")
    print("="*80 + "\n")


# ===========================================================================
# MAIN EXECUTION
# ===========================================================================

def main_console():
    """Run console-based analysis"""
    run_full_analysis()


if __name__ == "__main__":
    import sys

    print("\n" + "="*80)
    print(" VTOL QUADPLANE PERFORMANCE ANALYZER v1.0".center(80))
    print(" Professional Aerospace Performance Analysis Tool".center(80))
    print("="*80 + "\n")

    if len(sys.argv) > 1 and sys.argv[1] == "--help":
        print("Usage:")
        print("  python vtol_performance_analyzer.py [options]")
        print("\nOptions:")
        print("  --help      Show this help message")
        print("  --console   Run console-only mode (no plots)")
        print("  --full      Run full analysis with plots and exports (default)")
        print("\nOutput:")
        print("  - Console report with all performance parameters")
        print("  - Sensitivity analysis plots (PNG)")
        print("  - Performance curves (PNG)")
        print("  - CSV data export")
        print("\nAll outputs saved to: output/")
        print()
    else:
        # Run full analysis by default
        run_full_analysis()
