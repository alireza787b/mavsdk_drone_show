#!/usr/bin/env python3
"""
================================================================================
DRONE SCHEMATIC DRAWER v4.1
================================================================================
Professional 3-view engineering drawing generator for VTOL aircraft.

Creates top, front, and side views with accurate proportions and dimensions.
Visualizes wing, fuselage, tail fins, propellers, and CG location.

Author: VTOL Analyzer Dev Team
Version: 4.1.0
Date: 2025-01-20
================================================================================
"""

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Circle, Polygon, FancyBboxPatch, Wedge
from matplotlib.figure import Figure


class DroneSchematicDrawer:
    """
    Professional 3-view schematic drawer for VTOL aircraft.

    Generates engineering-style drawings showing:
    - Top view: Wing, fuselage, tail fins (plan view)
    - Front view: Fuselage cross-section, tail fins, motors
    - Side view: Profile with wing, tail fin, fuselage
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
        }

    def draw_3_view(self, figsize=(15, 5)):
        """
        Create professional 3-view drawing.

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

        # Draw each view
        self._draw_top_view(ax_top)
        self._draw_front_view(ax_front)
        self._draw_side_view(ax_side)

        # Overall title
        fig.suptitle('VTOL Aircraft Design Schematic',
                    fontsize=14, fontweight='bold', y=0.98)

        plt.tight_layout(rect=[0, 0, 1, 0.96])

        return fig

    def _draw_top_view(self, ax):
        """Draw top view (plan view)"""
        # Wing (rectangular)
        wing = Rectangle(
            (-self.config.wingspan_m/2, -self.config.wing_chord_m/2),
            self.config.wingspan_m,
            self.config.wing_chord_m,
            linewidth=2.5,
            edgecolor=self.colors['wing_edge'],
            facecolor=self.colors['wing'],
            alpha=0.4,
            zorder=2
        )
        ax.add_patch(wing)

        # Fuselage (cylinder from above - rectangular)
        fuse_length = self.config.fuselage_length_m
        fuse_width = self.config.fuselage_diameter_m

        fuse = Rectangle(
            (-fuse_width/2, -fuse_length/2),
            fuse_width,
            fuse_length,
            linewidth=2.5,
            edgecolor=self.colors['fuselage_edge'],
            facecolor=self.colors['fuselage'],
            alpha=0.5,
            zorder=3
        )
        ax.add_patch(fuse)

        # Tail fins (3 at 120° intervals, radiating from tail)
        self._draw_tail_fins_top(ax)

        # Propellers (4 in quad configuration)
        self._draw_propellers_top(ax)

        # CG marker
        ax.plot(0, 0, '+', color=self.colors['cg'],
               markersize=15, markeredgewidth=3, zorder=10)
        ax.text(0.02, 0.02, 'CG', fontsize=10, color=self.colors['cg'],
               fontweight='bold', zorder=10)

        # Dimension lines
        self._add_dimension_horizontal(ax,
            -self.config.wingspan_m/2, self.config.wingspan_m/2,
            self.config.wing_chord_m/2 + 0.15,
            f"Wingspan: {self.config.wingspan_m:.2f} m"
        )

        # Styling
        ax.set_aspect('equal')
        ax.grid(True, alpha=0.2, linestyle='--', color=self.colors['grid'])
        ax.set_title('TOP VIEW', fontweight='bold', fontsize=12, pad=10)
        ax.set_xlabel('Lateral Distance (m)', fontsize=9)
        ax.set_ylabel('Longitudinal Distance (m)', fontsize=9)

        # Set limits with padding
        max_dim = max(self.config.wingspan_m, fuse_length) * 0.65
        ax.set_xlim(-max_dim, max_dim)
        ax.set_ylim(-max_dim, max_dim)

    def _draw_tail_fins_top(self, ax):
        """Draw tail fins in top view (radiating from tail)"""
        # Fins positioned at tail (aft of CG)
        tail_position = -self.config.tail_fin_position_m

        # 3 or 4 fins evenly spaced
        if self.config.num_tail_fins == 3:
            angles_deg = [0, 120, 240]
        elif self.config.num_tail_fins == 4:
            angles_deg = [0, 90, 180, 270]
        else:
            angles_deg = [0]  # Fallback

        for angle_deg in angles_deg:
            angle_rad = np.radians(angle_deg)

            # Fin center position
            fin_center_x = self.config.fuselage_diameter_m/2 * np.sin(angle_rad)
            fin_center_y = tail_position + self.config.fuselage_diameter_m/2 * np.cos(angle_rad)

            # Fin extends radially
            fin_outer_x = (self.config.fuselage_diameter_m/2 + self.config.tail_fin_span_m) * np.sin(angle_rad)
            fin_outer_y = tail_position + (self.config.fuselage_diameter_m/2 + self.config.tail_fin_span_m) * np.cos(angle_rad)

            # Draw fin as thick line (chord width)
            # Perpendicular to radial direction
            perp_angle = angle_rad + np.pi/2
            dx = self.config.tail_fin_chord_m/2 * np.cos(perp_angle)
            dy = self.config.tail_fin_chord_m/2 * np.sin(perp_angle)

            # Fin polygon (tapered)
            taper = self.config.tail_fin_taper_ratio
            root_chord = self.config.tail_fin_chord_m
            tip_chord = root_chord * taper

            # Root (at fuselage)
            root_x1 = fin_center_x + root_chord/2 * np.cos(perp_angle)
            root_y1 = fin_center_y + root_chord/2 * np.sin(perp_angle)
            root_x2 = fin_center_x - root_chord/2 * np.cos(perp_angle)
            root_y2 = fin_center_y - root_chord/2 * np.sin(perp_angle)

            # Tip (at outer edge)
            tip_x1 = fin_outer_x + tip_chord/2 * np.cos(perp_angle)
            tip_y1 = fin_outer_y + tip_chord/2 * np.sin(perp_angle)
            tip_x2 = fin_outer_x - tip_chord/2 * np.cos(perp_angle)
            tip_y2 = fin_outer_y - tip_chord/2 * np.sin(perp_angle)

            fin_points = [
                [root_x1, root_y1],
                [tip_x1, tip_y1],
                [tip_x2, tip_y2],
                [root_x2, root_y2],
            ]

            fin_polygon = Polygon(fin_points,
                                 linewidth=1.5,
                                 edgecolor=self.colors['tail_edge'],
                                 facecolor=self.colors['tail'],
                                 alpha=0.6,
                                 zorder=4)
            ax.add_patch(fin_polygon)

    def _draw_propellers_top(self, ax):
        """Draw propellers in top view (circles)"""
        # Quad configuration: 4 motors
        # Positioned based on motor_spacing
        spacing = self.config.motor_spacing_m / 2

        prop_radius = self.config.prop_diameter_inch * 0.0254 / 2  # inches to meters

        motor_positions = [
            (spacing, spacing),      # Front right
            (-spacing, spacing),     # Front left
            (-spacing, -spacing),    # Rear left
            (spacing, -spacing),     # Rear right
        ]

        for x, y in motor_positions:
            prop = Circle((x, y), prop_radius,
                         linewidth=1.5,
                         edgecolor=self.colors['prop_edge'],
                         facecolor=self.colors['prop'],
                         alpha=0.3,
                         zorder=5)
            ax.add_patch(prop)

            # Motor center dot
            ax.plot(x, y, 'o', color=self.colors['prop_edge'],
                   markersize=4, zorder=6)

    def _draw_front_view(self, ax):
        """Draw front view (looking at nose)"""
        # Fuselage circle
        fuselage = Circle((0, 0),
                         self.config.fuselage_diameter_m/2,
                         linewidth=2.5,
                         edgecolor=self.colors['fuselage_edge'],
                         facecolor=self.colors['fuselage'],
                         alpha=0.4,
                         zorder=2)
        ax.add_patch(fuselage)

        # Tail fins radiating from fuselage
        self._draw_tail_fins_front(ax)

        # Motors (4 in quad configuration)
        spacing = self.config.motor_spacing_m / 2
        motor_diameter = 0.04  # Approximate motor can diameter

        motor_positions = [
            (spacing, spacing),      # Top right
            (-spacing, spacing),     # Top left
            (-spacing, -spacing),    # Bottom left
            (spacing, -spacing),     # Bottom right
        ]

        for x, y in motor_positions:
            motor = Circle((x, y), motor_diameter/2,
                          linewidth=1.5,
                          edgecolor='#34495E',
                          facecolor='#7F8C8D',
                          alpha=0.6,
                          zorder=5)
            ax.add_patch(motor)

        # CG marker
        ax.plot(0, 0, '+', color=self.colors['cg'],
               markersize=12, markeredgewidth=2.5, zorder=10)

        # Styling
        ax.set_aspect('equal')
        ax.grid(True, alpha=0.2, linestyle='--', color=self.colors['grid'])
        ax.set_title('FRONT VIEW', fontweight='bold', fontsize=12, pad=10)
        ax.set_xlabel('Lateral Distance (m)', fontsize=9)
        ax.set_ylabel('Vertical Distance (m)', fontsize=9)

        # Set limits
        max_dim = max(self.config.motor_spacing_m,
                     self.config.fuselage_diameter_m + 2*self.config.tail_fin_span_m) * 0.65
        ax.set_xlim(-max_dim, max_dim)
        ax.set_ylim(-max_dim, max_dim)

    def _draw_tail_fins_front(self, ax):
        """Draw tail fins in front view (cross-section)"""
        # Fins positioned radially from fuselage
        if self.config.num_tail_fins == 3:
            angles_deg = [0, 120, 240]  # Bottom, upper-right, upper-left
        elif self.config.num_tail_fins == 4:
            angles_deg = [0, 90, 180, 270]  # Bottom, right, top, left
        else:
            angles_deg = [0]

        for angle_deg in angles_deg:
            angle_rad = np.radians(angle_deg - 90)  # Adjust for matplotlib coords

            # Start at fuselage edge
            start_r = self.config.fuselage_diameter_m / 2
            end_r = start_r + self.config.tail_fin_span_m

            start_x = start_r * np.cos(angle_rad)
            start_y = start_r * np.sin(angle_rad)
            end_x = end_r * np.cos(angle_rad)
            end_y = end_r * np.sin(angle_rad)

            # Draw fin as thick line with airfoil cross-section
            ax.plot([start_x, end_x], [start_y, end_y],
                   linewidth=8, color=self.colors['tail'],
                   solid_capstyle='round', zorder=3)

            # Add thickness indication at tip
            perp_angle = angle_rad + np.pi/2
            thickness = self.config.tail_fin_chord_m * self.config.tail_fin_thickness_ratio / 2

            tip_x1 = end_x + thickness * np.cos(perp_angle)
            tip_y1 = end_y + thickness * np.sin(perp_angle)
            tip_x2 = end_x - thickness * np.cos(perp_angle)
            tip_y2 = end_y - thickness * np.sin(perp_angle)

            ax.plot([tip_x1, tip_x2], [tip_y1, tip_y2],
                   linewidth=2, color=self.colors['tail_edge'], zorder=4)

    def _draw_side_view(self, ax):
        """Draw side view (profile)"""
        # Fuselage (cylindrical body)
        fuse_length = self.config.fuselage_length_m
        fuse_diameter = self.config.fuselage_diameter_m

        # Draw as rounded rectangle (cylinder)
        fuse = FancyBboxPatch(
            (-fuse_length/2, -fuse_diameter/2),
            fuse_length,
            fuse_diameter,
            boxstyle="round,pad=0.02",
            linewidth=2.5,
            edgecolor=self.colors['fuselage_edge'],
            facecolor=self.colors['fuselage'],
            alpha=0.4,
            zorder=2
        )
        ax.add_patch(fuse)

        # Wing (airfoil shape simplified as thin line with thickness)
        wing_thickness = self.config.wing_chord_m * 0.12  # 12% thick
        wing = Rectangle(
            (-self.config.wing_chord_m/2, -wing_thickness/2),
            self.config.wing_chord_m,
            wing_thickness,
            linewidth=2,
            edgecolor=self.colors['wing_edge'],
            facecolor=self.colors['wing'],
            alpha=0.5,
            zorder=3
        )
        ax.add_patch(wing)

        # Tail fin (single fin visible from side)
        self._draw_tail_fin_side(ax)

        # CG marker
        ax.plot(0, 0, '+', color=self.colors['cg'],
               markersize=15, markeredgewidth=3, zorder=10)
        ax.text(0.02, -0.08, 'CG', fontsize=10, color=self.colors['cg'],
               fontweight='bold', zorder=10)

        # Dimension line for length
        self._add_dimension_horizontal(ax,
            -fuse_length/2, fuse_length/2,
            -fuse_diameter/2 - 0.15,
            f"Length: {fuse_length:.2f} m"
        )

        # Styling
        ax.set_aspect('equal')
        ax.grid(True, alpha=0.2, linestyle='--', color=self.colors['grid'])
        ax.set_title('SIDE VIEW', fontweight='bold', fontsize=12, pad=10)
        ax.set_xlabel('Longitudinal Distance (m)', fontsize=9)
        ax.set_ylabel('Vertical Distance (m)', fontsize=9)

        # Set limits
        max_dim = max(fuse_length, fuse_diameter + 2*self.config.tail_fin_span_m) * 0.65
        ax.set_xlim(-max_dim, max_dim)
        ax.set_ylim(-max_dim, max_dim)

    def _draw_tail_fin_side(self, ax):
        """Draw tail fin in side view (airfoil profile)"""
        # Fin positioned at tail
        fin_x = -self.config.tail_fin_position_m
        fin_y_base = -self.config.fuselage_diameter_m / 2
        fin_y_top = fin_y_base - self.config.tail_fin_span_m

        # Simplified symmetric airfoil shape
        # Leading edge, top, trailing edge, bottom
        root_chord = self.config.tail_fin_chord_m
        tip_chord = root_chord * self.config.tail_fin_taper_ratio
        max_thickness = root_chord * self.config.tail_fin_thickness_ratio

        # Root airfoil (at fuselage)
        fin_root = Polygon([
            [fin_x - root_chord/2, fin_y_base],  # Leading edge
            [fin_x - root_chord/4, fin_y_base + max_thickness/4],  # Top curve
            [fin_x + root_chord/2, fin_y_base],  # Trailing edge
            [fin_x - root_chord/4, fin_y_base - max_thickness/4],  # Bottom curve
        ],
        linewidth=2,
        edgecolor=self.colors['tail_edge'],
        facecolor=self.colors['tail'],
        alpha=0.6,
        zorder=4)
        ax.add_patch(fin_root)

        # Fin span line
        ax.plot([fin_x, fin_x], [fin_y_base, fin_y_top],
               linewidth=6, color=self.colors['tail'],
               solid_capstyle='round', alpha=0.5, zorder=3)

        # Tip airfoil (smaller)
        fin_tip = Polygon([
            [fin_x - tip_chord/2, fin_y_top],
            [fin_x - tip_chord/4, fin_y_top + max_thickness*0.3],
            [fin_x + tip_chord/2, fin_y_top],
            [fin_x - tip_chord/4, fin_y_top - max_thickness*0.3],
        ],
        linewidth=1.5,
        edgecolor=self.colors['tail_edge'],
        facecolor=self.colors['tail'],
        alpha=0.6,
        zorder=4)
        ax.add_patch(fin_tip)

    def _add_dimension_horizontal(self, ax, x1, x2, y, label):
        """Add horizontal dimension line with arrows and label"""
        # Dimension line
        ax.plot([x1, x2], [y, y],
               color=self.colors['dimension'],
               linewidth=1, linestyle='-', zorder=1)

        # Arrows
        arrow_size = 0.03
        ax.plot(x1, y, '<', color=self.colors['dimension'],
               markersize=6, zorder=1)
        ax.plot(x2, y, '>', color=self.colors['dimension'],
               markersize=6, zorder=1)

        # Label
        ax.text((x1 + x2)/2, y - 0.05, label,
               ha='center', va='top', fontsize=8,
               color=self.colors['dimension'],
               bbox=dict(boxstyle='round,pad=0.3',
                        facecolor='white',
                        edgecolor=self.colors['dimension'],
                        alpha=0.8),
               zorder=1)
