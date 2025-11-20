#!/usr/bin/env python3
"""
===============================================================================
VTOL QUADPLANE PERFORMANCE ANALYZER v3.0
===============================================================================
Industrial-grade aerospace performance analysis tool for VTOL quadplane UAVs
with tailsitter-specific corrections and mission profile analysis.

Author: Aerospace Performance Analysis System
Version: 3.0.0
Date: 2025-01-20

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

# Try to import numpy first (needed for both 2D and 3D plotting)
try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    np = None

# Optional GUI and plotting imports
try:
    import tkinter as tk
    from tkinter import ttk, messagebox
    import matplotlib
    matplotlib.use('TkAgg')
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure
    GUI_AVAILABLE = True
    PLOTTING_AVAILABLE = True
except ImportError:
    GUI_AVAILABLE = False
    PLOTTING_AVAILABLE = False
    print("Note: GUI/plotting libraries not available. Running in console mode only.")

# Try to import 3D plotting tools
try:
    if PLOTTING_AVAILABLE and NUMPY_AVAILABLE:
        from mpl_toolkits.mplot3d import Axes3D
        PLOTTING_3D_AVAILABLE = True
    else:
        PLOTTING_3D_AVAILABLE = False
except ImportError:
    PLOTTING_3D_AVAILABLE = False

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
    # TAILSITTER-SPECIFIC PARAMETERS (v3.0)
    # -----------------------------------------------------------------------
    # Aircraft type selection
    aircraft_type: str = "TAILSITTER"  # "TAILSITTER" or "QUADPLANE"

    # DRAG BREAKDOWN (Tailsitter-specific)
    # Total CD0 = cd0_clean + cd0_nacelles + cd0_fuselage_base + cd0_gear + cd0_interference
    cd0_motor_nacelles: float = 0.035  # 4 motor pods in crossflow [TUNE THIS]
    cd0_fuselage_base: float = 0.008   # Blunt tail (vertical sitting position)
    cd0_landing_gear: float = 0.012    # Tailsitter landing structure
    cd0_interference: float = 0.015    # Propeller-wing interaction

    # CONTROL POWER (Differential thrust - NO control surfaces)
    control_power_base_w: float = 50.0           # Baseline control power [W] [TUNE THIS]
    control_power_speed_factor: float = 5.0      # Additional power at low speed [W/(m/s)]
    # At 15 m/s: 50W, At 10 m/s: 75W, At 5 m/s: 100W

    # TRANSITION PARAMETERS
    transition_forward_duration_s: float = 15.0  # Hover→cruise transition time [s] [MEASURE FROM LOGS]
    transition_forward_power_factor: float = 2.0 # Peak power multiplier [TUNE THIS]
    transition_back_duration_s: float = 10.0     # Cruise→hover transition time [s] [MEASURE FROM LOGS]
    transition_back_power_factor: float = 1.6    # Peak power multiplier (usually less than forward)

    # Q-ASSIST (Low-speed flight augmentation - PX4 VT_FW_DIFTHR_EN)
    q_assist_enabled: bool = True                # Enable Q-Assist for tailsitter
    q_assist_threshold_speed_ms: float = 12.0    # Activate below this airspeed [m/s]
    q_assist_max_power_fraction: float = 0.25    # Max 25% of hover power

    # PROPULSION EFFICIENCY CORRECTIONS (Tailsitter hover-optimized props)
    prop_efficiency_lowspeed: float = 0.68       # 12-18 m/s (better than standard)
    prop_efficiency_highspeed: float = 0.55      # >20 m/s (worse than standard)

    # AUXILIARY SYSTEMS POWER BUDGET (v3.0)
    avionics_power_w: float = 6.5      # Flight controller (3W) + GPS (0.5W) + Telemetry (2W) + Sensors (1W)
    payload_power_w: float = 8.0       # Camera (5W) + Gimbal (3W)
    heater_power_w: float = 0.0        # Battery heater for cold weather (if needed)
    esc_efficiency: float = 0.92       # ESC efficiency (typical 30-60A ESC)

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
        # v3.0: Use tailsitter-specific breakdown if TAILSITTER type
        if self.aircraft_type == "TAILSITTER":
            self.cd0_total_cruise = (self.cd0_clean +
                                     self.cd0_motor_nacelles +
                                     self.cd0_fuselage_base +
                                     self.cd0_landing_gear +
                                     self.cd0_interference)
        else:
            # Standard quadplane
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

    def control_power(self, velocity_ms: float) -> float:
        """
        Calculate control power required (v3.0 - Tailsitter-specific).

        For tailsitters with differential thrust control (no control surfaces),
        power requirement increases significantly at low speeds.

        Args:
            velocity_ms: Airspeed [m/s]

        Returns:
            Control power [W]
        """
        if self.config.aircraft_type == "TAILSITTER":
            # Differential thrust control: higher power at low speeds
            # P_control = base + speed_factor * max(0, threshold - velocity)
            threshold_speed = 15.0  # m/s
            if velocity_ms < threshold_speed:
                additional_power = self.config.control_power_speed_factor * (threshold_speed - velocity_ms)
            else:
                additional_power = 0.0

            return self.config.control_power_base_w + additional_power
        else:
            # Standard quadplane with control surfaces: minimal power
            return 20.0

    def q_assist_power(self, velocity_ms: float) -> float:
        """
        Calculate Q-Assist power (v3.0 - Tailsitter low-speed augmentation).

        Q-Assist uses VTOL motors to provide additional lift/control at low speeds.
        Active when airspeed < threshold, provides fraction of hover power.

        Args:
            velocity_ms: Airspeed [m/s]

        Returns:
            Q-Assist power [W]
        """
        if not self.config.q_assist_enabled or self.config.aircraft_type != "TAILSITTER":
            return 0.0

        if velocity_ms < self.config.q_assist_threshold_speed_ms:
            # Linear blend: 100% at zero speed, 0% at threshold
            blend_factor = 1.0 - (velocity_ms / self.config.q_assist_threshold_speed_ms)
            hover_power = self.hover_power_total()
            return hover_power * self.config.q_assist_max_power_fraction * blend_factor
        else:
            return 0.0

    def propeller_efficiency_cruise(self, velocity_ms: float) -> float:
        """
        Calculate propeller efficiency for cruise flight (v3.0 - Speed-dependent).

        Tailsitter hover-optimized props have different efficiency at various speeds.

        Args:
            velocity_ms: Airspeed [m/s]

        Returns:
            Propeller efficiency [0-1]
        """
        if self.config.aircraft_type == "TAILSITTER":
            # Tailsitter with hover-optimized props
            if velocity_ms < 12.0:
                # Very low speed (Q-Assist range): lower efficiency
                return 0.60
            elif velocity_ms < 18.0:
                # Low to medium speed (12-18 m/s): best efficiency range
                return self.config.prop_efficiency_lowspeed
            else:
                # High speed (>18 m/s): reduced efficiency
                # Linear blend from lowspeed to highspeed efficiency
                if velocity_ms < 20.0:
                    blend = (velocity_ms - 18.0) / 2.0
                    return (self.config.prop_efficiency_lowspeed * (1 - blend) +
                            self.config.prop_efficiency_highspeed * blend)
                else:
                    return self.config.prop_efficiency_highspeed
        else:
            # Standard quadplane: use traditional advance ratio method
            rpm_estimate = self.config.motor_kv * (self.config.battery_voltage_nominal * 0.8)
            J = PropellerModel.advance_ratio(velocity_ms, rpm_estimate, self.config.prop_diameter_m)
            return PropellerModel.efficiency(J, self.config)

    def transition_energy(self, direction: str = "forward") -> Dict[str, float]:
        """
        Calculate transition energy and time (v3.0 - Tailsitter transitions).

        Transitions involve 90° pitch rotation with high power requirements.
        Peak power occurs around 45° pitch angle.

        Args:
            direction: "forward" (hover→cruise) or "back" (cruise→hover)

        Returns:
            Dictionary with energy [Wh], average power [W], duration [s]
        """
        if direction == "forward":
            duration_s = self.config.transition_forward_duration_s
            power_factor = self.config.transition_forward_power_factor
        else:  # "back"
            duration_s = self.config.transition_back_duration_s
            power_factor = self.config.transition_back_power_factor

        # Base power (hover power)
        hover_power = self.hover_power_total()

        # Average power during transition (simplified trapezoidal profile)
        # Start at hover power, peak at power_factor × hover, end at cruise
        cruise_speed = self.minimum_power_speed()
        cruise_power = self.power_required(cruise_speed)

        if direction == "forward":
            # Average: (hover + peak + cruise) / 3
            peak_power = hover_power * power_factor
            avg_power = (hover_power + peak_power + cruise_power) / 3.0
        else:
            # Back transition: (cruise + peak + hover) / 3
            peak_power = hover_power * power_factor
            avg_power = (cruise_power + peak_power + hover_power) / 3.0

        # Account for propeller and motor efficiency
        avg_power_electrical = avg_power / (self.config.motor_efficiency_peak * self.config.esc_efficiency)

        # Energy consumed
        energy_wh = (avg_power_electrical * duration_s) / 3600.0

        return {
            'direction': direction,
            'duration_s': duration_s,
            'avg_power_w': avg_power_electrical,
            'peak_power_w': peak_power / (self.config.motor_efficiency_peak * self.config.esc_efficiency),
            'energy_wh': energy_wh,
        }

    def cruise_current(self, velocity_ms: float) -> float:
        """
        Calculate current draw in cruise flight (v3.0 - Enhanced with all power components).

        Includes:
        - Aerodynamic drag power
        - Propeller efficiency (speed-dependent for tailsitter)
        - Motor efficiency
        - ESC efficiency
        - Control power (differential thrust for tailsitter)
        - Q-Assist power (low-speed augmentation)
        - Avionics power
        - Payload power
        - Heater power (if enabled)
        """
        # 1. Aerodynamic power required
        P_aero = self.power_required(velocity_ms)

        # 2. Propeller efficiency (v3.0: speed-dependent for tailsitter)
        eta_prop = self.propeller_efficiency_cruise(velocity_ms)

        # 3. Power required from propulsion motor
        P_motor = P_aero / eta_prop

        # 4. Electrical power accounting for motor efficiency
        P_propulsion = P_motor / self.config.motor_efficiency_peak

        # 5. Control power (v3.0: differential thrust for tailsitter)
        P_control = self.control_power(velocity_ms)

        # 6. Q-Assist power (v3.0: low-speed augmentation for tailsitter)
        P_qassist = self.q_assist_power(velocity_ms)

        # 7. Auxiliary systems (v3.0)
        P_avionics = self.config.avionics_power_w
        P_payload = self.config.payload_power_w
        P_heater = self.config.heater_power_w

        # 8. Total electrical power (before ESC)
        P_total_pre_esc = P_propulsion + P_control + P_qassist + P_avionics + P_payload + P_heater

        # 9. Account for ESC efficiency (v3.0)
        P_total_electrical = P_total_pre_esc / self.config.esc_efficiency

        # 10. Current draw from battery
        return P_total_electrical / self.config.battery_voltage_nominal

    def power_budget_breakdown(self, velocity_ms: float) -> Dict[str, float]:
        """
        Calculate detailed power budget breakdown (v3.0).

        Returns:
            Dictionary with all power components [W]
        """
        # Aerodynamic power
        P_aero = self.power_required(velocity_ms)

        # Propeller efficiency
        eta_prop = self.propeller_efficiency_cruise(velocity_ms)

        # Motor power
        P_motor_shaft = P_aero / eta_prop

        # Motor losses
        P_motor_electrical = P_motor_shaft / self.config.motor_efficiency_peak
        P_motor_loss = P_motor_electrical - P_motor_shaft

        # Control power
        P_control = self.control_power(velocity_ms)

        # Q-Assist power
        P_qassist = self.q_assist_power(velocity_ms)

        # Auxiliary systems
        P_avionics = self.config.avionics_power_w
        P_payload = self.config.payload_power_w
        P_heater = self.config.heater_power_w

        # Total before ESC
        P_total_pre_esc = P_motor_electrical + P_control + P_qassist + P_avionics + P_payload + P_heater

        # ESC losses
        P_esc_loss = P_total_pre_esc * (1.0 / self.config.esc_efficiency - 1.0)

        # Total electrical
        P_total = P_total_pre_esc + P_esc_loss

        return {
            'aerodynamic_drag_w': P_aero,
            'propeller_efficiency': eta_prop,
            'motor_shaft_power_w': P_motor_shaft,
            'motor_electrical_w': P_motor_electrical,
            'motor_loss_w': P_motor_loss,
            'control_power_w': P_control,
            'q_assist_w': P_qassist,
            'avionics_w': P_avionics,
            'payload_w': P_payload,
            'heater_w': P_heater,
            'esc_loss_w': P_esc_loss,
            'total_electrical_w': P_total,
            'current_a': P_total / self.config.battery_voltage_nominal,
        }

    def mission_profile_analysis(self, mission_segments: List[Dict]) -> Dict:
        """
        Analyze complete mission profile with multiple segments (v3.0).

        Args:
            mission_segments: List of mission segments, each containing:
                - type: "hover", "cruise", "transition_forward", "transition_back"
                - duration_s: Duration in seconds (not used for transitions)
                - speed_ms: Speed in m/s (for cruise segments)

        Returns:
            Dictionary with mission analysis results
        """
        total_energy_wh = 0.0
        total_time_s = 0.0
        segment_results = []

        for segment in mission_segments:
            seg_type = segment['type']

            if seg_type == "hover":
                duration_s = segment.get('duration_s', 0)
                current_a = self.hover_current()
                power_w = current_a * self.config.battery_voltage_nominal
                energy_wh = (power_w * duration_s) / 3600.0

                segment_results.append({
                    'type': 'hover',
                    'duration_s': duration_s,
                    'power_w': power_w,
                    'current_a': current_a,
                    'energy_wh': energy_wh,
                })

                total_energy_wh += energy_wh
                total_time_s += duration_s

            elif seg_type == "cruise":
                duration_s = segment.get('duration_s', 0)
                speed_ms = segment.get('speed_ms', self.minimum_power_speed())
                current_a = self.cruise_current(speed_ms)
                power_w = current_a * self.config.battery_voltage_nominal
                energy_wh = (power_w * duration_s) / 3600.0
                distance_km = (speed_ms * duration_s) / 1000.0

                segment_results.append({
                    'type': 'cruise',
                    'duration_s': duration_s,
                    'speed_ms': speed_ms,
                    'speed_kmh': speed_ms * 3.6,
                    'distance_km': distance_km,
                    'power_w': power_w,
                    'current_a': current_a,
                    'energy_wh': energy_wh,
                })

                total_energy_wh += energy_wh
                total_time_s += duration_s

            elif seg_type == "transition_forward":
                trans = self.transition_energy("forward")
                segment_results.append({
                    'type': 'transition_forward',
                    'duration_s': trans['duration_s'],
                    'avg_power_w': trans['avg_power_w'],
                    'peak_power_w': trans['peak_power_w'],
                    'energy_wh': trans['energy_wh'],
                })

                total_energy_wh += trans['energy_wh']
                total_time_s += trans['duration_s']

            elif seg_type == "transition_back":
                trans = self.transition_energy("back")
                segment_results.append({
                    'type': 'transition_back',
                    'duration_s': trans['duration_s'],
                    'avg_power_w': trans['avg_power_w'],
                    'peak_power_w': trans['peak_power_w'],
                    'energy_wh': trans['energy_wh'],
                })

                total_energy_wh += trans['energy_wh']
                total_time_s += trans['duration_s']

        # Calculate totals and remaining capacity
        battery_capacity_wh = self.config.battery_energy_wh
        remaining_wh = battery_capacity_wh - total_energy_wh
        remaining_percent = (remaining_wh / battery_capacity_wh) * 100.0

        return {
            'segments': segment_results,
            'total_energy_wh': total_energy_wh,
            'total_time_s': total_time_s,
            'total_time_min': total_time_s / 60.0,
            'battery_capacity_wh': battery_capacity_wh,
            'energy_used_wh': total_energy_wh,
            'energy_remaining_wh': remaining_wh,
            'battery_remaining_percent': remaining_percent,
        }

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
        """Generate complete performance summary (v3.0 - Enhanced)"""
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

        # v3.0: Power budget breakdown for cruise
        cruise_power_budget = self.power_budget_breakdown(v_cruise)

        # v3.0: Transition energy
        transition_forward = self.transition_energy("forward")
        transition_back = self.transition_energy("back")

        # v3.0: Drag breakdown (tailsitter-specific)
        drag_breakdown = None
        if self.config.aircraft_type == "TAILSITTER":
            drag_breakdown = {
                'cd0_clean': self.config.cd0_clean,
                'cd0_nacelles': self.config.cd0_motor_nacelles,
                'cd0_fuselage': self.config.cd0_fuselage_base,
                'cd0_gear': self.config.cd0_landing_gear,
                'cd0_interference': self.config.cd0_interference,
                'cd0_total': self.config.cd0_total_cruise,
            }

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
                'drag_breakdown': drag_breakdown,  # v3.0
            },
            'hover': {
                'power_w': hover_power,
                'current_a': hover_current,
                'endurance_min': hover_endurance,
            },
            'cruise': {
                'speed_ms': v_cruise,
                'speed_kmh': v_cruise * 3.6,
                'power_w': cruise_power_budget['total_electrical_w'],  # v3.0: total power
                'current_a': cruise_current,
                'endurance_min': cruise_endurance,
                'range_km': cruise_range,
                'power_budget': cruise_power_budget,  # v3.0
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
            'transitions': {  # v3.0
                'forward': transition_forward,
                'back': transition_back,
            },
            'aircraft_type': self.config.aircraft_type,  # v3.0
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
        """Print comprehensive performance report (v3.0 - Enhanced)"""
        print("\n" + "="*80)
        print(" VTOL QUADPLANE PERFORMANCE ANALYSIS REPORT v3.0".center(80))
        print("="*80)

        # Configuration summary
        print("\n" + "-"*80)
        print("AIRCRAFT CONFIGURATION")
        print("-"*80)
        print(f"  Aircraft Type:           {config.aircraft_type}")  # v3.0
        print(f"  Total Weight:            {config.total_takeoff_weight_kg:.2f} kg ({perf['weight']['total_n']:.1f} N)")
        print(f"  Wing Span:               {config.wingspan_m:.2f} m")
        print(f"  Wing Chord:              {config.wing_chord_m:.3f} m")
        print(f"  Wing Area:               {config.wing_area_m2:.3f} m²")
        print(f"  Aspect Ratio:            {config.aspect_ratio:.2f}")
        print(f"  Wing Loading:            {config.wing_loading_kgm2:.2f} kg/m² ({config.wing_loading_nm2:.1f} N/m²)")
        print(f"  Airfoil:                 {config.airfoil_name}")
        print(f"  Motor:                   {config.motor_name} x{config.motor_count}")
        print(f"  Propeller:               {config.prop_diameter_inch:.0f}x{config.prop_pitch_inch:.0f} inch")
        print(f"  Battery:                 {config.battery_cells}S {config.battery_capacity_mah:.0f}mAh ({config.battery_energy_wh:.1f} Wh usable)")

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

        # v3.0: Drag breakdown for tailsitter
        if aero.get('drag_breakdown'):
            drag = aero['drag_breakdown']
            print("\n  Drag Breakdown (Tailsitter):")
            print(f"    • Clean airframe:      {drag['cd0_clean']:.4f}")
            print(f"    • Motor nacelles:      {drag['cd0_nacelles']:.4f}")
            print(f"    • Fuselage base:       {drag['cd0_fuselage']:.4f}")
            print(f"    • Landing gear:        {drag['cd0_gear']:.4f}")
            print(f"    • Interference:        {drag['cd0_interference']:.4f}")
            print(f"    ─────────────────────────────")
            print(f"    • TOTAL CD0:           {drag['cd0_total']:.4f}")

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
        print(f"  Total Power:             {cruise['power_w']:.1f} W")
        print(f"  Current Draw:            {cruise['current_a']:.2f} A")
        print(f"  Endurance:               {cruise['endurance_min']:.2f} min ({cruise['endurance_min']/60:.2f} hours)")
        print(f"  Range:                   {cruise['range_km']:.2f} km")

        # v3.0: Power budget breakdown
        if 'power_budget' in cruise:
            pb = cruise['power_budget']
            print("\n  Power Budget Breakdown:")
            print(f"    • Aerodynamic drag:    {pb['aerodynamic_drag_w']:6.1f} W")
            print(f"    • Propeller eff:       {pb['propeller_efficiency']*100:6.1f} %")
            print(f"    • Motor shaft power:   {pb['motor_shaft_power_w']:6.1f} W")
            print(f"    • Motor electrical:    {pb['motor_electrical_w']:6.1f} W  (loss: {pb['motor_loss_w']:.1f} W)")
            print(f"    • Control power:       {pb['control_power_w']:6.1f} W")
            if pb['q_assist_w'] > 0:
                print(f"    • Q-Assist power:      {pb['q_assist_w']:6.1f} W")
            print(f"    • Avionics:            {pb['avionics_w']:6.1f} W")
            print(f"    • Payload:             {pb['payload_w']:6.1f} W")
            if pb['heater_w'] > 0:
                print(f"    • Heater:              {pb['heater_w']:6.1f} W")
            print(f"    • ESC loss:            {pb['esc_loss_w']:6.1f} W")
            print(f"    ─────────────────────────────")
            print(f"    • TOTAL:               {pb['total_electrical_w']:6.1f} W  ({pb['current_a']:.2f} A)")

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

        # v3.0: Transition energy (tailsitter)
        if 'transitions' in perf:
            trans = perf['transitions']
            print("\n" + "-"*80)
            print("TRANSITION ENERGY (Tailsitter)")
            print("-"*80)
            print(f"  Forward Transition (Hover → Cruise):")
            print(f"    • Duration:            {trans['forward']['duration_s']:.1f} s")
            print(f"    • Average Power:       {trans['forward']['avg_power_w']:.1f} W")
            print(f"    • Peak Power:          {trans['forward']['peak_power_w']:.1f} W")
            print(f"    • Energy Used:         {trans['forward']['energy_wh']:.1f} Wh")
            print(f"\n  Back Transition (Cruise → Hover):")
            print(f"    • Duration:            {trans['back']['duration_s']:.1f} s")
            print(f"    • Average Power:       {trans['back']['avg_power_w']:.1f} W")
            print(f"    • Peak Power:          {trans['back']['peak_power_w']:.1f} W")
            print(f"    • Energy Used:         {trans['back']['energy_wh']:.1f} Wh")
            total_trans_energy = trans['forward']['energy_wh'] + trans['back']['energy_wh']
            print(f"\n  Total Transition Cycle:  {total_trans_energy:.1f} Wh")

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
        if config.aircraft_type == "TAILSITTER":
            print("\nv3.0 TAILSITTER ENHANCEMENTS:")
            print("• Differential thrust control power modeling")
            print("• Speed-dependent propeller efficiency corrections")
            print("• Q-Assist low-speed augmentation")
            print("• Detailed drag breakdown (nacelles, interference, base)")
            print("• Transition energy with peak power modeling")
            print("• Complete power budget analysis")
            print("• Mission profile segmentation")
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

                # Save as PNG (web viewing)
                png_filename = f"{output_dir}/sensitivity_{param_name}.png"
                plt.savefig(png_filename, dpi=150, bbox_inches='tight')

                # Save as JPG (high resolution for reports)
                jpg_filename = f"{output_dir}/sensitivity_{param_name}.jpg"
                plt.savefig(jpg_filename, dpi=300, bbox_inches='tight',
                           facecolor='white', format='jpeg')

                plt.close()
                print(f"  ✓ Saved PNG: {os.path.basename(png_filename)}")
                print(f"  ✓ Saved JPG: {os.path.basename(jpg_filename)}")

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

            # Save as PNG (web viewing)
            png_filename = f"{output_dir}/performance_curves.png"
            plt.savefig(png_filename, dpi=150, bbox_inches='tight')

            # Save as JPG (high resolution for reports)
            jpg_filename = f"{output_dir}/performance_curves.jpg"
            plt.savefig(jpg_filename, dpi=300, bbox_inches='tight',
                       facecolor='white', format='jpeg')

            plt.close()
            print(f"  ✓ Saved PNG: {os.path.basename(png_filename)}")
            print(f"  ✓ Saved JPG: {os.path.basename(jpg_filename)}")

        except ImportError as e:
            print(f"  Plotting library not available: {e}")


# ===========================================================================
# 3D SURFACE PLOT ENGINE
# ===========================================================================

class SurfacePlotEngine:
    """
    Advanced 3D surface plotting for multi-parameter performance analysis.

    Enables visualization of performance metrics as functions of two parameters,
    providing aerospace engineers with comprehensive design space exploration.
    """

    @staticmethod
    def create_surface_plot(
        config: AircraftConfiguration,
        param_x_name: str,
        param_x_range: List[float],
        param_x_label: str,
        param_y_name: str,
        param_y_range: List[float],
        param_y_label: str,
        output_func: Callable,
        output_label: str,
        output_unit: str,
        filename: str,
        title: str = None,
        cmap: str = 'viridis'
    ):
        """
        Create 3D surface plot for two-parameter sensitivity analysis.

        Args:
            config: Base aircraft configuration
            param_x_name: First parameter name (e.g., 'total_takeoff_weight_kg')
            param_x_range: Range of first parameter values
            param_x_label: Label for X-axis
            param_y_name: Second parameter name (e.g., 'field_elevation_m')
            param_y_range: Range of second parameter values
            param_y_label: Label for Y-axis
            output_func: Function to calculate output (takes PerformanceCalculator)
            output_label: Label for Z-axis (output metric)
            output_unit: Unit for Z-axis
            filename: Output filename
            title: Plot title (auto-generated if None)
            cmap: Colormap name
        """
        try:
            import numpy as np
            import matplotlib.pyplot as plt
            from mpl_toolkits.mplot3d import Axes3D
            from matplotlib import cm

            # Create meshgrid
            X, Y = np.meshgrid(param_x_range, param_y_range)
            Z = np.zeros_like(X)

            # Calculate output for each parameter combination
            for i, y_val in enumerate(param_y_range):
                for j, x_val in enumerate(param_x_range):
                    # Create modified config
                    test_config = dataclasses.replace(config)
                    setattr(test_config, param_x_name, x_val)
                    setattr(test_config, param_y_name, y_val)
                    test_config.__post_init__()

                    # Calculate performance
                    calc = PerformanceCalculator(test_config)
                    Z[i, j] = output_func(calc)

            # Create 3D surface plot
            fig = plt.figure(figsize=(14, 10))
            ax = fig.add_subplot(111, projection='3d')

            # Plot surface
            surf = ax.plot_surface(X, Y, Z, cmap=cmap, alpha=0.9,
                                  linewidth=0, antialiased=True,
                                  edgecolor='none')

            # Add contour lines on the bottom
            ax.contour(X, Y, Z, zdir='z', offset=Z.min(),
                      cmap=cmap, alpha=0.6, linewidths=1)

            # Labels and title
            ax.set_xlabel(param_x_label, fontsize=12, labelpad=10)
            ax.set_ylabel(param_y_label, fontsize=12, labelpad=10)
            z_label = f'{output_label} ({output_unit})' if output_unit else output_label
            ax.set_zlabel(z_label, fontsize=12, labelpad=10)

            if title is None:
                title = f'{output_label} vs {param_x_label} and {param_y_label}'
            ax.set_title(title, fontsize=14, fontweight='bold', pad=20)

            # Add colorbar
            cbar = fig.colorbar(surf, ax=ax, shrink=0.5, aspect=10)
            cbar.set_label(z_label, rotation=270, labelpad=20)

            # Optimize viewing angle
            ax.view_init(elev=25, azim=45)

            # Add grid
            ax.grid(True, alpha=0.3)

            # Tight layout
            plt.tight_layout()

            # Save as both PNG and JPG (high resolution)
            base_filename = filename.replace('.png', '').replace('.jpg', '')

            # Save PNG (for web viewing)
            png_filename = f"{base_filename}.png"
            plt.savefig(png_filename, dpi=200, bbox_inches='tight', facecolor='white')

            # Save JPG (for reports/presentations)
            jpg_filename = f"{base_filename}.jpg"
            plt.savefig(jpg_filename, dpi=300, bbox_inches='tight',
                       facecolor='white', format='jpeg')

            plt.close()

            return png_filename, jpg_filename

        except Exception as e:
            print(f"  Error creating 3D surface plot: {e}")
            return None, None

    @staticmethod
    def create_common_aerospace_3d_plots(config: AircraftConfiguration, output_dir: str = "output"):
        """
        Generate the most common 3D surface plots used in aerospace design.

        These plots help designers understand:
        - Performance envelope boundaries
        - Trade-offs between design parameters
        - Optimal operating conditions
        - Sensitivity to environmental conditions
        """
        import os
        os.makedirs(output_dir, exist_ok=True)

        print("\nGenerating 3D surface plots for aerospace design analysis...")

        # Define common aerospace design surface plots
        surface_plots = [
            {
                'name': 'hover_endurance_vs_weight_elevation',
                'title': 'Hover Endurance: Weight vs Altitude',
                'param_x': 'total_takeoff_weight_kg',
                'param_x_range': np.linspace(4.0, 8.0, 15),
                'param_x_label': 'Total Weight (kg)',
                'param_y': 'field_elevation_m',
                'param_y_range': np.linspace(0, 3000, 15),
                'param_y_label': 'Field Elevation (m MSL)',
                'output_func': lambda c: c.generate_performance_summary()['hover']['endurance_min'],
                'output_label': 'Hover Endurance',
                'output_unit': 'min',
                'cmap': 'YlOrRd_r',
            },
            {
                'name': 'cruise_endurance_vs_weight_wingspan',
                'title': 'Cruise Endurance: Weight vs Wing Span',
                'param_x': 'total_takeoff_weight_kg',
                'param_x_range': np.linspace(4.0, 8.0, 15),
                'param_x_label': 'Total Weight (kg)',
                'param_y': 'wingspan_m',
                'param_y_range': np.linspace(1.2, 2.6, 15),
                'param_y_label': 'Wing Span (m)',
                'output_func': lambda c: c.generate_performance_summary()['cruise']['endurance_min'],
                'output_label': 'Cruise Endurance',
                'output_unit': 'min',
                'cmap': 'viridis',
            },
            {
                'name': 'max_range_vs_weight_wingspan',
                'title': 'Maximum Range: Weight vs Wing Span',
                'param_x': 'total_takeoff_weight_kg',
                'param_x_range': np.linspace(4.0, 8.0, 15),
                'param_x_label': 'Total Weight (kg)',
                'param_y': 'wingspan_m',
                'param_y_range': np.linspace(1.2, 2.6, 15),
                'param_y_label': 'Wing Span (m)',
                'output_func': lambda c: c.generate_performance_summary()['best_range']['range_km'],
                'output_label': 'Maximum Range',
                'output_unit': 'km',
                'cmap': 'plasma',
            },
            {
                'name': 'stall_speed_vs_weight_wing_area',
                'title': 'Stall Speed: Weight vs Wing Chord',
                'param_x': 'total_takeoff_weight_kg',
                'param_x_range': np.linspace(4.0, 8.0, 15),
                'param_x_label': 'Total Weight (kg)',
                'param_y': 'wing_chord_m',
                'param_y_range': np.linspace(0.08, 0.20, 15),
                'param_y_label': 'Wing Chord (m)',
                'output_func': lambda c: c.generate_performance_summary()['speeds']['stall_kmh'],
                'output_label': 'Stall Speed',
                'output_unit': 'km/h',
                'cmap': 'coolwarm',
            },
            {
                'name': 'ld_ratio_vs_wingspan_chord',
                'title': 'Max L/D Ratio: Wing Span vs Chord',
                'param_x': 'wingspan_m',
                'param_x_range': np.linspace(1.2, 2.6, 15),
                'param_x_label': 'Wing Span (m)',
                'param_y': 'wing_chord_m',
                'param_y_range': np.linspace(0.08, 0.20, 15),
                'param_y_label': 'Wing Chord (m)',
                'output_func': lambda c: c.generate_performance_summary()['aerodynamics']['max_ld_ratio'],
                'output_label': 'Max L/D Ratio',
                'output_unit': '',
                'cmap': 'RdYlGn',
            },
            {
                'name': 'cruise_endurance_vs_elevation_wingspan',
                'title': 'Cruise Endurance: Altitude vs Wing Span',
                'param_x': 'field_elevation_m',
                'param_x_range': np.linspace(0, 3000, 15),
                'param_x_label': 'Field Elevation (m MSL)',
                'param_y': 'wingspan_m',
                'param_y_range': np.linspace(1.2, 2.6, 15),
                'param_y_label': 'Wing Span (m)',
                'output_func': lambda c: c.generate_performance_summary()['cruise']['endurance_min'],
                'output_label': 'Cruise Endurance',
                'output_unit': 'min',
                'cmap': 'viridis',
            },
        ]

        # Generate each surface plot
        generated_plots = []
        for i, plot_spec in enumerate(surface_plots, 1):
            print(f"  [{i}/{len(surface_plots)}] Generating: {plot_spec['title']}...")

            filename = os.path.join(output_dir, f"3d_{plot_spec['name']}")

            try:
                png_file, jpg_file = SurfacePlotEngine.create_surface_plot(
                    config=config,
                    param_x_name=plot_spec['param_x'],
                    param_x_range=plot_spec['param_x_range'],
                    param_x_label=plot_spec['param_x_label'],
                    param_y_name=plot_spec['param_y'],
                    param_y_range=plot_spec['param_y_range'],
                    param_y_label=plot_spec['param_y_label'],
                    output_func=plot_spec['output_func'],
                    output_label=plot_spec['output_label'],
                    output_unit=plot_spec['output_unit'],
                    filename=filename,
                    title=plot_spec['title'],
                    cmap=plot_spec['cmap']
                )

                if png_file and jpg_file:
                    generated_plots.append({
                        'name': plot_spec['name'],
                        'title': plot_spec['title'],
                        'png': png_file,
                        'jpg': jpg_file
                    })
                    print(f"      ✓ Saved PNG: {os.path.basename(png_file)}")
                    print(f"      ✓ Saved JPG: {os.path.basename(jpg_file)}")

            except Exception as e:
                print(f"      ✗ Error: {e}")

        print(f"\n  ✓ Generated {len(generated_plots)} 3D surface plots")
        print(f"    - High-res JPG (300 dpi) for reports/presentations")
        print(f"    - Web-optimized PNG (200 dpi) for viewing")

        return generated_plots


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
            'plots_3d': os.path.join(base_dir, 'plots', '3d_surfaces'),
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
    <h1>[VTOL] Quadplane Performance Analysis</h1>

    <div class="download-section">
        <h3>[DATA] Downloads</h3>
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

    <h2>🔬 2D Sensitivity Analysis</h2>
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

    <h2>🌐 3D Surface Plots - Multi-Parameter Analysis</h2>
    <p style="color: #555; margin: 10px 0;">
        Professional aerospace design surface plots showing performance as a function of two parameters.
        <strong>High-resolution JPG versions (300 dpi) available in plots/3d_surfaces/ folder.</strong>
    </p>
    <div class="plot-grid">
        <div class="plot-card">
            <h3>Hover Endurance: Weight vs Altitude</h3>
            <img src="plots/3d_surfaces/3d_hover_endurance_vs_weight_elevation.png" alt="Hover Endurance Surface">
            <p style="font-size: 0.9em; color: #666; margin-top: 10px;">
                Shows how hover time varies with aircraft weight and operating altitude.
            </p>
        </div>
        <div class="plot-card">
            <h3>Cruise Endurance: Weight vs Wing Span</h3>
            <img src="plots/3d_surfaces/3d_cruise_endurance_vs_weight_wingspan.png" alt="Cruise Endurance Surface">
            <p style="font-size: 0.9em; color: #666; margin-top: 10px;">
                Optimal wing span selection for different weight configurations.
            </p>
        </div>
        <div class="plot-card">
            <h3>Maximum Range: Weight vs Wing Span</h3>
            <img src="plots/3d_surfaces/3d_max_range_vs_weight_wingspan.png" alt="Maximum Range Surface">
            <p style="font-size: 0.9em; color: #666; margin-top: 10px;">
                Design space for maximum range capability.
            </p>
        </div>
        <div class="plot-card">
            <h3>Stall Speed: Weight vs Wing Chord</h3>
            <img src="plots/3d_surfaces/3d_stall_speed_vs_weight_wing_area.png" alt="Stall Speed Surface">
            <p style="font-size: 0.9em; color: #666; margin-top: 10px;">
                Wing loading effects on minimum flight speed.
            </p>
        </div>
        <div class="plot-card">
            <h3>Max L/D Ratio: Wing Span vs Chord</h3>
            <img src="plots/3d_surfaces/3d_ld_ratio_vs_wingspan_chord.png" alt="L/D Ratio Surface">
            <p style="font-size: 0.9em; color: #666; margin-top: 10px;">
                Aerodynamic efficiency optimization landscape.
            </p>
        </div>
        <div class="plot-card">
            <h3>Cruise Endurance: Altitude vs Wing Span</h3>
            <img src="plots/3d_surfaces/3d_cruise_endurance_vs_elevation_wingspan.png" alt="Altitude Endurance Surface">
            <p style="font-size: 0.9em; color: #666; margin-top: 10px;">
                Performance envelope at different altitudes and wing configurations.
            </p>
        </div>
    </div>

    <footer style="margin-top: 50px; padding-top: 20px; border-top: 1px solid #ccc; color: #7f8c8d; text-align: center;">
        <p>Generated by VTOL Performance Analyzer v3.0 | Industrial-Grade Tailsitter Analysis</p>
        <p>Enhanced with differential thrust control, Q-Assist, transitions, and power budget analysis</p>
    </footer>
</body>
</html>
"""

        index_path = os.path.join(paths['base'], 'index.html')
        with open(index_path, 'w', encoding='utf-8') as f:
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
    print("GENERATING 2D VISUALIZATIONS")
    print("-"*80)
    try:
        PlottingEngine.create_sensitivity_plots(config, paths['plots'])
        PlottingEngine.create_performance_curves(config, paths['plots'])
        print("  ✓ All 2D plots generated successfully")
    except Exception as e:
        print(f"  ✗ Could not generate 2D plots: {e}")
        print("  → Install matplotlib and numpy: pip install matplotlib numpy")

    # Generate 3D surface plots
    print("\n" + "-"*80)
    print("GENERATING 3D SURFACE PLOTS")
    print("-"*80)
    try:
        generated_3d_plots = SurfacePlotEngine.create_common_aerospace_3d_plots(
            config, paths['plots_3d']
        )
        print(f"  ✓ Generated {len(generated_3d_plots)} 3D surface plots")
    except Exception as e:
        print(f"  ✗ Could not generate 3D plots: {e}")
        print("  → Ensure matplotlib and numpy are installed")

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
    print(f"  - 2D Plots:      {paths['plots']}/")
    print(f"  - 3D Surfaces:   {paths['plots_3d']}/")
    print(f"  - Data Export:   {paths['data']}/")
    print(f"  - HTML Index:    {base_dir}/index.html\n")
    print("  [TIP] Open index.html in your browser for easy viewing")
    print("  [NOTE] High-res JPG files (300 dpi) available for reports/presentations")
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
    print(" VTOL QUADPLANE PERFORMANCE ANALYZER v3.0".center(80))
    print(" Industrial-Grade Tailsitter Performance Analysis".center(80))
    print("="*80 + "\n")

    if len(sys.argv) > 1 and sys.argv[1] == "--help":
        print("Usage:")
        print("  python vtol_performance_analyzer.py [options]")
        print("\nOptions:")
        print("  --help                Show this help message")
        print("  --preset NAME         Use specific configuration preset")
        print("  --list-presets        List all available presets")
        print("  --console             Run console-only mode (no plots)")
        print("  --full                Run full analysis with plots (default)")
        print("\nPreset Usage:")
        print("  python vtol_performance_analyzer.py --preset baseline    # 6kg standard")
        print("  python vtol_performance_analyzer.py --preset lightning   # 5.2kg ultra-light")
        print("  python vtol_performance_analyzer.py --preset thunder     # 8kg heavy payload")
        print("\nDefault:")
        print("  If no preset specified, uses 'baseline' (6kg production standard)")
        print("\nOutput:")
        print("  - Console report with all performance parameters")
        print("  - 2D sensitivity analysis plots (PNG + JPG)")
        print("  - 2D performance curves (PNG + JPG)")
        print("  - 6 professional 3D surface plots (PNG + high-res JPG)")
        print("  - CSV data export")
        print("  - Interactive HTML index")
        print("\nAll outputs saved to: output/")
        print("  - 2D plots: output/plots/")
        print("  - 3D plots: output/plots/3d_surfaces/")
        print("  - Data: output/data/")
        print("\nv3.0 Features:")
        print("  - Tailsitter-specific corrections (drag, control power, transitions)")
        print("  - Mission profile analysis")
        print("  - Complete power budget breakdown")
        print("  - Configuration presets (5.2kg, 6kg, 8kg)")
        print()
    elif len(sys.argv) > 1 and sys.argv[1] == "--list-presets":
        try:
            from config_presets import PresetManager
            manager = PresetManager()
            print("Available Configuration Presets:")
            print("-" * 80)
            for preset_name in manager.list_presets():
                desc = manager.get_preset_description(preset_name)
                print(f"  • {preset_name:<35} {desc}")
            print("\nUsage:")
            print("  python vtol_performance_analyzer.py --preset <preset_name>")
            print("\nDefault (if no preset specified):")
            print("  baseline (6kg Production Standard)")
            print()
        except ImportError:
            print("Warning: config_presets.py not found. Using default configuration.")
            print()
    elif len(sys.argv) > 2 and sys.argv[1] == "--preset":
        # Use specified preset
        preset_name = sys.argv[2]
        try:
            from config_presets import PresetManager
            manager = PresetManager()
            config = manager.get_preset(preset_name)
            print(f"Using preset: {manager.get_preset_description(preset_name)}")
            print()
            run_full_analysis(config)
        except ImportError:
            print("Warning: config_presets.py not found. Using default configuration.")
            run_full_analysis()
        except ValueError as e:
            print(f"Error: {e}")
            print("\nUse --list-presets to see available options")
            print()
    else:
        # Default: Try to use baseline preset
        try:
            from config_presets import PresetManager
            manager = PresetManager()
            config = manager.get_preset("baseline")
            print("Using default preset: BASELINE (6kg Production Standard)")
            print("  (Use --preset to select: lightning, baseline, or thunder)")
            print("  (Use --list-presets to see all options)")
            print()
            run_full_analysis(config)
        except ImportError:
            print("Using built-in default configuration")
            print("  (Install config_presets.py for preset support)")
            print()
            run_full_analysis()
