#!/usr/bin/env python3
"""
================================================================================
DRONE SCHEMATIC DRAWER v4.1.2 - PX4 Tailsitter VTOL (MC Mode)
================================================================================
Professional 3-view engineering drawing generator for PX4 Tailsitter VTOL.

PX4 MULTICOPTER (MC) MODE COORDINATE SYSTEM:
- Uses PX4 FRD body frame (Front-Right-Down)
- X-axis: Forward/Front (nose direction - points UP when hovering in VTOL mode)
- Y-axis: Right (right wing direction)
- Z-axis: Down (towards ground when hovering)

For tailsitter in VTOL/MC (hovering/standing) position:
- Top view: Looking down Z-axis from above → see circular fuselage cross-section, wings span left-right
- Front view: Looking at nose along X-axis → see full wingspan and circular fuselage
- Side view: Looking from right along Y-axis → see vertical fuselage length and wing chord

NOTE: PX4 uses FRD body frame for ALL modes (MC, FW, VTOL). In VTOL/MC mode,
the aircraft stands vertically so X points skyward, but it's still the "forward" body axis.

Author: VTOL Analyzer Dev Team
Version: 4.1.2
Date: 2025-01-21
================================================================================
"""

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Circle, Polygon, FancyBboxPatch, Wedge, FancyArrowPatch
from matplotlib.figure import Figure


class DroneSchematicDrawer:
    """
    Professional 3-view schematic drawer for PX4 Tailsitter VTOL (MC Mode).

    Generates engineering-style drawings with correct PX4 MC (multicopter) mode
    axis orientation using FRD (Front-Right-Down) body frame.
    Tailsitter shown in VTOL/MC (hovering/standing/vertical) configuration.
    """

    def __init__(self, config):
        """
        Initialize drawer with aircraft configuration.

        Args:
            config: AircraftConfiguration object with geometry parameters
        """
        self.config = config

        # Color scheme (professional engineering colors)
        self.colors = {
            'wing': '#4A90E2',           # Medium blue
            'wing_edge': '#2E5C8A',      # Dark blue
            'fuselage': '#E8505B',       # Coral red
            'fuselage_edge': '#B33A44',  # Dark red
            'tail': '#34495E',           # Dark gray-blue
            'tail_edge': '#1F2D3D',      # Very dark blue
            'prop': '#95A5A6',           # Light gray
            'prop_edge': '#34495E',      # Dark gray
            'cg': '#E74C3C',             # Bright red
            'dimension': '#2C3E50',      # Very dark gray
            'grid': '#BDC3C7',           # Light gray
            'nose': '#F39C12',           # Orange for nose indicator
        }

    def draw_3_view(self, figsize=(15, 5)):
        """
        Create professional 3-view drawing with PX4 axis orientation.

        Args:
            figsize: Figure size (width, height) in inches

        Returns:
            matplotlib Figure object
        """
        fig, (ax_top, ax_front, ax_side) = plt.subplots(
            1, 3,
            figsize=figsize,
            facecolor='white'
        )

        # Draw each view with PX4 correct orientation
        self._draw_top_view(ax_top)      # Looking down Z-axis
        self._draw_front_view(ax_front)  # Looking along X-axis (at nose)
        self._draw_side_view(ax_side)    # Looking along Y-axis (from right)

        # Overall title
        fig.suptitle('PX4 Tailsitter VTOL - 3-View Schematic (MC/VTOL Mode)',
                    fontsize=14, fontweight='bold', y=0.98)

        plt.tight_layout(rect=[0, 0, 1, 0.96])

        return fig

    def _draw_top_view(self, ax):
        """
        Draw top view - Looking down Z-axis (from above in VTOL mode)

        See: Circular fuselage cross-section, wings spanning left-right,
        tail fins at aft end, propellers in quad configuration
        """
        # === FUSELAGE (circular cross-section when looking down) ===
        fuselage = Circle(
            (0, 0),
            self.config.fuselage_diameter_m / 2,
            linewidth=2.5,
            edgecolor=self.colors['fuselage_edge'],
            facecolor=self.colors['fuselage'],
            alpha=0.5,
            zorder=3
        )
        ax.add_patch(fuselage)

        # === WING (spans left-right along Y-axis) ===
        # Wing positioned at CG (center of fuselage in top view)
        wing_chord = self.config.wing_chord_m
        wing_span = self.config.wingspan_m

        wing = Rectangle(
            (-wing_span/2, -wing_chord/2),  # Y-axis (left-right), X-axis (fwd-aft)
            wing_span,
            wing_chord,
            linewidth=2.5,
            edgecolor=self.colors['wing_edge'],
            facecolor=self.colors['wing'],
            alpha=0.4,
            zorder=2
        )
        ax.add_patch(wing)

        # Mark leading edge (forward)
        ax.plot([-wing_span/2, wing_span/2], [wing_chord/2, wing_chord/2],
               color=self.colors['wing_edge'], linewidth=3, zorder=4,
               label='Leading Edge')

        # === TAIL FINS (at aft position along X-axis) ===
        self._draw_tail_fins_top(ax)

        # === PROPELLERS (quad configuration around fuselage) ===
        self._draw_propellers_top(ax)

        # === NOSE INDICATOR (shows forward direction) ===
        # Small arrow pointing forward (+X direction in body frame)
        nose_offset = self.config.fuselage_diameter_m / 2 + 0.05
        ax.annotate('', xy=(0, nose_offset + 0.1), xytext=(0, nose_offset),
                   arrowprops=dict(arrowstyle='->', lw=2, color=self.colors['nose']))
        ax.text(0, nose_offset + 0.15, 'NOSE\n(+X)', ha='center', va='bottom',
               fontsize=8, fontweight='bold', color=self.colors['nose'])

        # === CG MARKER ===
        ax.plot(0, 0, 'x', color=self.colors['cg'], markersize=10,
               markeredgewidth=2, zorder=10, label='CG')

        # === DIMENSIONS ===
        # Wing span
        self._add_dimension_horizontal(ax, -wing_span/2, wing_span/2,
                                      -wing_chord/2 - 0.15,
                                      f'{wing_span:.2f}m span')

        # Wing chord
        y_pos = wing_span/2 + 0.15
        ax.annotate('', xy=(y_pos, wing_chord/2), xytext=(y_pos, -wing_chord/2),
                   arrowprops=dict(arrowstyle='<->', lw=1.5, color=self.colors['dimension']))
        ax.text(y_pos + 0.08, 0, f'{wing_chord:.2f}m\nchord',
               ha='left', va='center', fontsize=8, color=self.colors['dimension'])

        # === AXIS CONFIGURATION ===
        ax.set_aspect('equal')
        ax.grid(True, alpha=0.3, linestyle='--', color=self.colors['grid'])
        ax.set_xlabel('Y-axis (Right Wing →)', fontsize=10, fontweight='bold')
        ax.set_ylabel('X-axis (Forward →)', fontsize=10, fontweight='bold')
        ax.set_title('TOP VIEW\n(Looking down -Z axis)', fontsize=11, fontweight='bold')
        ax.legend(loc='upper right', fontsize=8)

        # Set limits with padding
        max_dim = max(wing_span, self.config.fuselage_length_m) * 0.7
        ax.set_xlim(-max_dim, max_dim)
        ax.set_ylim(-max_dim, max_dim)

    def _draw_tail_fins_top(self, ax):
        """Draw tail fins in top view (positioned aft along X-axis)"""
        tail_position = -self.config.tail_fin_position_m  # Aft of CG (negative X)

        # Determine fin angles based on count
        if self.config.num_tail_fins == 3:
            angles_deg = [0, 120, 240]  # Y-shaped
        elif self.config.num_tail_fins == 4:
            angles_deg = [45, 135, 225, 315]  # X-shaped
        else:
            angles_deg = [0, 120, 240]  # Default to 3

        for angle_deg in angles_deg:
            angle_rad = np.radians(angle_deg)

            # Fin parameters
            root_chord = self.config.tail_fin_chord_m
            tip_chord = root_chord * self.config.tail_fin_taper_ratio
            span = self.config.tail_fin_span_m

            # Fin extends radially outward from fuselage
            fuse_radius = self.config.fuselage_diameter_m / 2

            # Calculate fin polygon points (tapered)
            # Fin root at fuselage edge, extends outward
            root_start_x = tail_position - root_chord / 2
            root_end_x = tail_position + root_chord / 2
            tip_start_x = tail_position - tip_chord / 2
            tip_end_x = tail_position + tip_chord / 2

            # Direction perpendicular to fin (radial)
            cos_a = np.cos(angle_rad)
            sin_a = np.sin(angle_rad)

            # Transform to Y-axis (horizontal) coordinate
            fin_points = [
                (fuse_radius * sin_a, fuse_radius * cos_a + root_start_x),  # Root start
                (fuse_radius * sin_a, fuse_radius * cos_a + root_end_x),    # Root end
                ((fuse_radius + span) * sin_a, (fuse_radius + span) * cos_a + tip_end_x),  # Tip end
                ((fuse_radius + span) * sin_a, (fuse_radius + span) * cos_a + tip_start_x),  # Tip start
            ]

            fin_polygon = Polygon(
                fin_points,
                linewidth=1.5,
                edgecolor=self.colors['tail_edge'],
                facecolor=self.colors['tail'],
                alpha=0.6,
                zorder=4
            )
            ax.add_patch(fin_polygon)

    def _draw_propellers_top(self, ax):
        """Draw propellers in top view (quad configuration)"""
        spacing = self.config.motor_spacing_m / 2
        prop_radius = 0.05  # Visual representation

        # Quad motor positions (in Y-X plane for top view)
        motor_positions = [
            (spacing, spacing),      # Front right
            (-spacing, spacing),     # Front left
            (-spacing, -spacing),    # Rear left
            (spacing, -spacing),     # Rear right
        ]

        for y, x in motor_positions:
            # Motor hub
            hub = Circle(
                (y, x),
                prop_radius * 0.3,
                linewidth=1.5,
                edgecolor=self.colors['prop_edge'],
                facecolor=self.colors['prop'],
                alpha=0.7,
                zorder=5
            )
            ax.add_patch(hub)

            # Propeller blades (simple cross)
            ax.plot([y - prop_radius, y + prop_radius], [x, x],
                   color=self.colors['prop'], linewidth=2, alpha=0.5, zorder=4)
            ax.plot([y, y], [x - prop_radius, x + prop_radius],
                   color=self.colors['prop'], linewidth=2, alpha=0.5, zorder=4)

    def _draw_front_view(self, ax):
        """
        Draw front view - Looking at nose (along +X axis)

        See: Full wingspan horizontal, fuselage as circle, tail fins radiating,
        motors at wing tips
        """
        # === FUSELAGE (circular when looking at nose) ===
        fuselage = Circle(
            (0, 0),
            self.config.fuselage_diameter_m / 2,
            linewidth=2.5,
            edgecolor=self.colors['fuselage_edge'],
            facecolor=self.colors['fuselage'],
            alpha=0.5,
            zorder=3
        )
        ax.add_patch(fuselage)

        # === WING (full span visible horizontally) ===
        wing_span = self.config.wingspan_m
        wing_thickness = self.config.wing_chord_m * 0.12  # ~12% airfoil thickness

        # Wing shown as horizontal bar
        wing = Rectangle(
            (-wing_span/2, -wing_thickness/2),
            wing_span,
            wing_thickness,
            linewidth=2.5,
            edgecolor=self.colors['wing_edge'],
            facecolor=self.colors['wing'],
            alpha=0.5,
            zorder=2
        )
        ax.add_patch(wing)

        # === TAIL FINS (radial from fuselage, behind) ===
        self._draw_tail_fins_front(ax)

        # === MOTORS (at wing tips in quad config) ===
        spacing = self.config.motor_spacing_m / 2
        motor_diameter = 0.04

        motor_positions = [
            (spacing, spacing),      # Right upper
            (-spacing, spacing),     # Left upper
            (-spacing, -spacing),    # Left lower
            (spacing, -spacing),     # Right lower
        ]

        for y, z in motor_positions:
            motor = Circle(
                (y, z),
                motor_diameter / 2,
                linewidth=1.5,
                edgecolor='#34495E',
                facecolor='#7F8C8D',
                alpha=0.7,
                zorder=5
            )
            ax.add_patch(motor)

        # === CG MARKER ===
        ax.plot(0, 0, 'x', color=self.colors['cg'], markersize=10,
               markeredgewidth=2, zorder=10)

        # === DIMENSIONS ===
        # Wing span
        self._add_dimension_horizontal(ax, -wing_span/2, wing_span/2,
                                      -wing_thickness/2 - 0.2,
                                      f'{wing_span:.2f}m')

        # === AXIS CONFIGURATION ===
        ax.set_aspect('equal')
        ax.grid(True, alpha=0.3, linestyle='--', color=self.colors['grid'])
        ax.set_xlabel('Y-axis (Right Wing →)', fontsize=10, fontweight='bold')
        ax.set_ylabel('Z-axis (Down ↓)', fontsize=10, fontweight='bold')
        ax.set_title('FRONT VIEW\n(Looking at nose, along +X)', fontsize=11, fontweight='bold')

        # Set limits
        max_dim = wing_span * 0.7
        ax.set_xlim(-max_dim, max_dim)
        ax.set_ylim(-max_dim, max_dim)

    def _draw_tail_fins_front(self, ax):
        """Draw tail fins in front view (radial lines from fuselage)"""
        # Determine fin angles
        if self.config.num_tail_fins == 3:
            angles_deg = [0, 120, 240]
        elif self.config.num_tail_fins == 4:
            angles_deg = [45, 135, 225, 315]
        else:
            angles_deg = [0, 120, 240]

        fuse_radius = self.config.fuselage_diameter_m / 2
        fin_span = self.config.tail_fin_span_m
        fin_thickness = self.config.tail_fin_chord_m * self.config.tail_fin_thickness_ratio

        for angle_deg in angles_deg:
            angle_rad = np.radians(angle_deg)

            # Fin extends radially from fuselage
            start_y = fuse_radius * np.sin(angle_rad)
            start_z = fuse_radius * np.cos(angle_rad)
            end_y = (fuse_radius + fin_span) * np.sin(angle_rad)
            end_z = (fuse_radius + fin_span) * np.cos(angle_rad)

            # Draw fin as thick line
            ax.plot([start_y, end_y], [start_z, end_z],
                   color=self.colors['tail'],
                   linewidth=fin_thickness * 100,  # Scale for visibility
                   alpha=0.6,
                   solid_capstyle='round')

            # Fin edge
            ax.plot([start_y, end_y], [start_z, end_z],
                   color=self.colors['tail_edge'],
                   linewidth=1.5,
                   alpha=0.8)

    def _draw_side_view(self, ax):
        """
        Draw side view - Looking from right side (along +Y axis)

        See: Full fuselage length vertical, wing chord visible, single tail fin profile
        """
        # === FUSELAGE (full length visible vertically in VTOL mode) ===
        fuse_length = self.config.fuselage_length_m
        fuse_diameter = self.config.fuselage_diameter_m

        # Fuselage centered vertically (standing position)
        # X-axis: forward (up in VTOL), Z-axis: down (horizontal in this view)
        fuse = FancyBboxPatch(
            (-fuse_diameter/2, -fuse_length/2),  # Z, X coordinates
            fuse_diameter,
            fuse_length,
            boxstyle="round,pad=0.02",
            linewidth=2.5,
            edgecolor=self.colors['fuselage_edge'],
            facecolor=self.colors['fuselage'],
            alpha=0.5,
            zorder=2
        )
        ax.add_patch(fuse)

        # Nose indicator (top of fuselage in VTOL mode)
        nose_y = fuse_length / 2
        ax.plot(0, nose_y, 'o', color=self.colors['nose'], markersize=8,
               markeredgewidth=2, markerfacecolor='none', zorder=5)
        ax.text(fuse_diameter/2 + 0.1, nose_y, 'NOSE', fontsize=8,
               fontweight='bold', color=self.colors['nose'], va='center')

        # === WING (chord visible as airfoil profile) ===
        wing_chord = self.config.wing_chord_m
        wing_thickness = wing_chord * 0.12  # Airfoil thickness

        # Wing at CG position
        wing = Rectangle(
            (-wing_chord/2, -wing_thickness/2),
            wing_chord,
            wing_thickness,
            linewidth=2,
            edgecolor=self.colors['wing_edge'],
            facecolor=self.colors['wing'],
            alpha=0.6,
            zorder=3
        )
        ax.add_patch(wing)

        # Mark leading edge
        ax.plot([-wing_chord/2, -wing_chord/2], [-wing_thickness/2, wing_thickness/2],
               color=self.colors['wing_edge'], linewidth=3, zorder=4)

        # === TAIL FIN (one fin visible in profile) ===
        self._draw_tail_fin_side(ax)

        # === CG MARKER ===
        ax.plot(0, 0, 'x', color=self.colors['cg'], markersize=10,
               markeredgewidth=2, zorder=10)
        ax.text(0.05, -0.05, 'CG', fontsize=8, color=self.colors['cg'],
               fontweight='bold')

        # === DIMENSIONS ===
        # Fuselage length
        x_pos = fuse_diameter/2 + 0.2
        ax.annotate('', xy=(x_pos, fuse_length/2), xytext=(x_pos, -fuse_length/2),
                   arrowprops=dict(arrowstyle='<->', lw=1.5, color=self.colors['dimension']))
        ax.text(x_pos + 0.08, 0, f'{fuse_length:.2f}m\nlength',
               ha='left', va='center', fontsize=8, color=self.colors['dimension'])

        # Wing chord
        self._add_dimension_horizontal(ax, -wing_chord/2, wing_chord/2,
                                      -wing_thickness/2 - 0.15,
                                      f'{wing_chord:.2f}m chord')

        # === AXIS CONFIGURATION ===
        ax.set_aspect('equal')
        ax.grid(True, alpha=0.3, linestyle='--', color=self.colors['grid'])
        ax.set_xlabel('Z-axis (Down →)', fontsize=10, fontweight='bold')
        ax.set_ylabel('X-axis (Forward ↑)', fontsize=10, fontweight='bold')
        ax.set_title('SIDE VIEW\n(Looking from right, along +Y)', fontsize=11, fontweight='bold')

        # Set limits
        max_dim = max(fuse_length, wing_chord) * 0.7
        ax.set_xlim(-max_dim, max_dim)
        ax.set_ylim(-max_dim, max_dim)

    def _draw_tail_fin_side(self, ax):
        """Draw tail fin profile in side view"""
        tail_position = -self.config.tail_fin_position_m  # Aft (negative X)
        root_chord = self.config.tail_fin_chord_m
        tip_chord = root_chord * self.config.tail_fin_taper_ratio
        span = self.config.tail_fin_span_m
        thickness_ratio = self.config.tail_fin_thickness_ratio

        # Fin extends upward (positive Z direction perpendicular to fuselage)
        fuse_radius = self.config.fuselage_diameter_m / 2

        # Draw tapered fin with airfoil thickness
        root_thick = root_chord * thickness_ratio
        tip_thick = tip_chord * thickness_ratio

        # Fin polygon (one side visible)
        fin_points = [
            # Root airfoil
            (fuse_radius, tail_position - root_chord/2),                    # Root leading edge bottom
            (fuse_radius, tail_position + root_chord/2),                    # Root trailing edge bottom
            # Tip airfoil
            (fuse_radius + span, tail_position + tip_chord/2),              # Tip trailing edge
            (fuse_radius + span, tail_position - tip_chord/2),              # Tip leading edge
        ]

        fin = Polygon(
            fin_points,
            linewidth=2,
            edgecolor=self.colors['tail_edge'],
            facecolor=self.colors['tail'],
            alpha=0.6,
            zorder=4
        )
        ax.add_patch(fin)

    def _add_dimension_horizontal(self, ax, x1, x2, y, label):
        """Add horizontal dimension line with arrows and label"""
        # Dimension line
        ax.annotate('', xy=(x2, y), xytext=(x1, y),
                   arrowprops=dict(arrowstyle='<->', lw=1.5,
                                 color=self.colors['dimension']))

        # Label at midpoint
        mid_x = (x1 + x2) / 2
        ax.text(mid_x, y - 0.05, label, ha='center', va='top',
               fontsize=8, color=self.colors['dimension'],
               bbox=dict(boxstyle='round,pad=0.3', facecolor='white',
                        edgecolor=self.colors['dimension'], alpha=0.8))


def main():
    """Test function for standalone execution"""
    # Example configuration
    from dataclasses import dataclass

    @dataclass
    class TestConfig:
        wingspan_m: float = 2.0
        wing_chord_m: float = 0.20
        fuselage_length_m: float = 1.2
        fuselage_diameter_m: float = 0.10
        num_tail_fins: int = 3
        tail_fin_chord_m: float = 0.05
        tail_fin_span_m: float = 0.15
        tail_fin_position_m: float = 0.50
        tail_fin_thickness_ratio: float = 0.12
        tail_fin_taper_ratio: float = 0.7
        motor_spacing_m: float = 0.50

    config = TestConfig()
    drawer = DroneSchematicDrawer(config)
    fig = drawer.draw_3_view(figsize=(18, 6))

    plt.savefig('px4_tailsitter_schematic.png', dpi=150, bbox_inches='tight')
    print("Schematic saved to: px4_tailsitter_schematic.png")
    plt.show()


if __name__ == "__main__":
    main()
